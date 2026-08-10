from datetime import datetime, time, timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase


class TestOSCoworkingBooking(TransactionCase):
    """Test coworking booking data, security, actions, and constraints."""

    @classmethod
    def setUpClass(cls):
        """Create reusable booking, resource, membership, and client data."""
        super().setUpClass()
        cls.booking_model = cls.env['os.coworking.booking']
        cls.env.company.partner_id.tz = 'UTC'

        cls.location = cls.env['os.coworking.location'].create(
            {
                'name': 'Primary Booking Test Location',
                'working_hour_from': 8.0,
                'working_hour_to': 18.0,
            }
        )
        cls.other_location = cls.env['os.coworking.location'].create(
            {
                'name': 'Secondary Booking Test Location',
                'working_hour_from': 8.0,
                'working_hour_to': 18.0,
            }
        )
        cls.resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Available Booking Test Desk',
                'location_id': cls.location.id,
                'resource_type': 'desk',
                'capacity': 1,
                'hourly_rate': 10.0,
            }
        )
        cls.other_resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Secondary Booking Test Room',
                'location_id': cls.other_location.id,
                'resource_type': 'meeting_room',
                'capacity': 6,
                'hourly_rate': 25.0,
            }
        )
        cls.maintenance_resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Maintenance Booking Test Office',
                'location_id': cls.location.id,
                'resource_type': 'private_office',
                'capacity': 4,
                'hourly_rate': 40.0,
                'state': 'maintenance',
            }
        )

        cls.client = cls.env['res.partner'].create(
            {
                'name': 'Primary Booking Test Client',
                'is_coworking_client': True,
            }
        )
        cls.other_client = cls.env['res.partner'].create(
            {
                'name': 'Secondary Booking Test Client',
                'is_coworking_client': True,
            }
        )

        cls.unlimited_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Unlimited Booking Test Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
                'price': 100.0,
            }
        )
        cls.hours_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Hourly Booking Test Plan',
                'usage_type': 'hours',
                'duration_days': 30,
                'included_hours': 10.0,
                'price': 80.0,
            }
        )
        cls.visits_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Visit Booking Test Plan',
                'usage_type': 'visits',
                'duration_days': 30,
                'included_visits': 4,
                'price': 60.0,
            }
        )

        today = fields.Date.today()
        cls.booking_date = today + timedelta(days=1)
        membership_values = {
            'partner_id': cls.client.id,
            'date_start': today,
            'date_end': today + timedelta(days=29),
            'state': 'active',
        }
        cls.unlimited_membership = cls.env['os.coworking.membership'].create(
            {
                **membership_values,
                'plan_id': cls.unlimited_plan.id,
            }
        )
        cls.hours_membership = cls.env['os.coworking.membership'].create(
            {
                **membership_values,
                'plan_id': cls.hours_plan.id,
                'remaining_hours': 10.0,
            }
        )
        cls.visits_membership = cls.env['os.coworking.membership'].create(
            {
                **membership_values,
                'plan_id': cls.visits_plan.id,
                'remaining_visits': 4,
            }
        )

    def _create_booking(self, **values):
        """Create a draft booking with valid reusable default values."""
        booking_values = {
            'partner_id': self.client.id,
            'resource_id': self.resource.id,
            'membership_id': self.unlimited_membership.id,
            'start_datetime': datetime.combine(self.booking_date, time(10)),
            'end_datetime': datetime.combine(self.booking_date, time(12)),
        }
        booking_values.update(values)
        return self.booking_model.create(booking_values)

    def test_booking_sequence_and_duration(self):
        """Verify the generated number, duration, location, and notes."""
        booking = self._create_booking(note='A booking test note.')

        self.assertRegex(booking.name, r'^BKG/\d{5}$')
        self.assertEqual(booking.duration_hours, 2.0)
        self.assertEqual(booking.location_id, self.location)
        self.assertEqual(booking.note, 'A booking test note.')

    def test_hourly_membership_reservation_is_restored_on_cancel(self):
        """Verify hourly limit reservation and restoration on cancellation."""
        booking = self._create_booking(membership_id=self.hours_membership.id)

        booking.action_confirm()

        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.reserved_hours, 2.0)
        self.assertEqual(self.hours_membership.remaining_hours, 8.0)

        booking.action_cancel()

        self.assertEqual(booking.state, 'cancelled')
        self.assertEqual(booking.reserved_hours, 0.0)
        self.assertEqual(self.hours_membership.remaining_hours, 10.0)

    def test_visit_reservation_is_retained_on_completion(self):
        """Verify a visit is reserved and retained when a booking is done."""
        booking = self._create_booking(membership_id=self.visits_membership.id)

        booking.action_confirm()
        booking.action_done()

        self.assertEqual(booking.state, 'done')
        self.assertEqual(booking.reserved_visits, 1)
        self.assertEqual(self.visits_membership.remaining_visits, 3)

    def test_unlimited_membership_has_no_numeric_reservation(self):
        """Verify unlimited bookings do not change numeric membership limits."""
        booking = self._create_booking()

        booking.action_confirm()

        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.reserved_hours, 0.0)
        self.assertEqual(booking.reserved_visits, 0)

    def test_booking_rejects_unavailable_resource(self):
        """Verify a resource under maintenance cannot be confirmed."""
        booking = self._create_booking(resource_id=self.maintenance_resource.id)

        with self.assertRaises(ValidationError):
            booking.action_confirm()

    def test_booking_rejects_invalid_time_boundaries(self):
        """Verify full-hour and location working-hour restrictions."""
        with self.assertRaises(ValidationError):
            self._create_booking(
                start_datetime=datetime.combine(self.booking_date, time(10, 30)),
            )

        outside_hours_booking = self._create_booking(
            start_datetime=datetime.combine(self.booking_date, time(7)),
            end_datetime=datetime.combine(self.booking_date, time(8)),
        )
        with self.assertRaises(ValidationError):
            outside_hours_booking.action_confirm()

    def test_booking_rejects_overlap_and_accepts_adjacent_interval(self):
        """Verify confirmed intervals cannot overlap but may be adjacent."""
        first_booking = self._create_booking()
        first_booking.action_confirm()

        overlapping_booking = self._create_booking(
            start_datetime=datetime.combine(self.booking_date, time(11)),
            end_datetime=datetime.combine(self.booking_date, time(13)),
        )
        with self.assertRaises(ValidationError):
            overlapping_booking.action_confirm()

        adjacent_booking = self._create_booking(
            start_datetime=datetime.combine(self.booking_date, time(12)),
            end_datetime=datetime.combine(self.booking_date, time(13)),
        )
        adjacent_booking.action_confirm()

        self.assertEqual(adjacent_booking.state, 'confirmed')

    def test_booking_rejects_ineligible_membership(self):
        """Verify membership owner, status, date, and location eligibility."""
        wrong_owner_membership = self.env['os.coworking.membership'].create(
            {
                'partner_id': self.other_client.id,
                'plan_id': self.unlimited_plan.id,
                'date_start': self.booking_date,
                'date_end': self.booking_date + timedelta(days=29),
                'state': 'active',
            }
        )
        wrong_owner_booking = self._create_booking(
            membership_id=wrong_owner_membership.id,
        )
        with self.assertRaises(ValidationError):
            wrong_owner_booking.action_confirm()

        draft_membership = self.env['os.coworking.membership'].create(
            {
                'partner_id': self.client.id,
                'plan_id': self.unlimited_plan.id,
                'date_start': self.booking_date,
                'date_end': self.booking_date + timedelta(days=29),
            }
        )
        inactive_membership_booking = self._create_booking(
            membership_id=draft_membership.id,
        )
        with self.assertRaises(ValidationError):
            inactive_membership_booking.action_confirm()

        location_plan = self.env['os.coworking.membership.plan'].create(
            {
                'name': 'Location Booking Test Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
                'price': 90.0,
                'all_locations': False,
            }
        )
        location_membership = self.env['os.coworking.membership'].create(
            {
                'partner_id': self.client.id,
                'plan_id': location_plan.id,
                'location_id': self.location.id,
                'date_start': self.booking_date,
                'date_end': self.booking_date + timedelta(days=29),
                'state': 'active',
            }
        )
        wrong_location_booking = self._create_booking(
            resource_id=self.other_resource.id,
            membership_id=location_membership.id,
        )
        with self.assertRaises(ValidationError):
            wrong_location_booking.action_confirm()

    def test_booking_state_actions_reject_invalid_transitions(self):
        """Verify lifecycle actions enforce the agreed booking states."""
        booking = self._create_booking()

        with self.assertRaises(UserError):
            booking.action_cancel()
        with self.assertRaises(UserError):
            booking.action_done()

        booking.action_confirm()
        with self.assertRaises(UserError):
            booking.action_confirm()

    def test_location_and_partner_booking_smart_buttons(self):
        """Verify smart button counts, domains, and partner default values."""
        first_booking = self._create_booking()
        second_booking = self._create_booking(
            start_datetime=datetime.combine(self.booking_date, time(13)),
            end_datetime=datetime.combine(self.booking_date, time(14)),
        )
        self._create_booking(
            resource_id=self.other_resource.id,
            start_datetime=datetime.combine(self.booking_date, time(14)),
            end_datetime=datetime.combine(self.booking_date, time(15)),
        )

        self.assertEqual(self.location.booking_count, 2)
        self.assertEqual(self.client.coworking_booking_count, 3)

        location_action = self.location.action_view_bookings()
        self.assertEqual(location_action['domain'], [('location_id', '=', self.location.id)])
        location_bookings = self.booking_model.search(location_action['domain'])
        self.assertEqual(set(location_bookings.ids), {first_booking.id, second_booking.id})

        partner_action = self.client.action_view_coworking_bookings()
        self.assertEqual(partner_action['domain'], [('partner_id', '=', self.client.id)])
        self.assertEqual(partner_action['context'], {'default_partner_id': self.client.id})

    def test_user_access_is_limited_to_assigned_locations(self):
        """Verify User ACL and record rules for location-based booking access."""
        coworking_user = self.env['res.users'].with_context(no_reset_password=True).create(
            {
                'name': 'Booking Access Test User',
                'login': 'booking_access_test_user',
            }
        )
        self.env.ref(
            'OdooSchool_coworking_management.group_coworking_user'
        ).write({'user_ids': [Command.link(coworking_user.id)]})
        self.location.write(
            {'staff_user_ids': [Command.link(coworking_user.id)]}
        )
        allowed_booking = self._create_booking()
        denied_booking = self._create_booking(
            resource_id=self.other_resource.id,
            start_datetime=datetime.combine(self.booking_date, time(14)),
            end_datetime=datetime.combine(self.booking_date, time(15)),
        )

        visible_bookings = self.booking_model.with_user(coworking_user).search(
            [('id', 'in', [allowed_booking.id, denied_booking.id])]
        )

        self.assertIn(allowed_booking, visible_bookings)
        self.assertNotIn(denied_booking, visible_bookings)
        with self.assertRaises(AccessError):
            allowed_booking.with_user(coworking_user).unlink()
