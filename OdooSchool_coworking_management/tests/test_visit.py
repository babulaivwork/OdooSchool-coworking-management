from datetime import datetime, time, timedelta

from psycopg2.errors import CheckViolation, UniqueViolation

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestOSCoworkingVisit(TransactionCase):
    """Test coworking visit lifecycle, constraints, links, and security."""

    @classmethod
    def setUpClass(cls):
        """Create reusable clients, locations, resources, and memberships."""
        super().setUpClass()
        cls.visit_model = cls.env['os.coworking.visit']
        cls.booking_model = cls.env['os.coworking.booking']
        cls.env.company.partner_id.tz = 'UTC'

        cls.location = cls.env['os.coworking.location'].create(
            {
                'name': 'Primary Visit Test Location',
                'working_hour_from': 8.0,
                'working_hour_to': 18.0,
            }
        )
        cls.other_location = cls.env['os.coworking.location'].create(
            {
                'name': 'Secondary Visit Test Location',
                'working_hour_from': 8.0,
                'working_hour_to': 18.0,
            }
        )
        cls.resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Primary Visit Test Desk',
                'location_id': cls.location.id,
                'resource_type': 'desk',
                'capacity': 1,
                'hourly_rate': 10.0,
            }
        )
        cls.second_resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Secondary Visit Test Desk',
                'location_id': cls.location.id,
                'resource_type': 'desk',
                'capacity': 1,
                'hourly_rate': 12.0,
            }
        )
        cls.other_resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Other Location Visit Test Room',
                'location_id': cls.other_location.id,
                'resource_type': 'meeting_room',
                'capacity': 6,
                'hourly_rate': 25.0,
            }
        )

        cls.client = cls.env['res.partner'].create(
            {
                'name': 'Primary Visit Test Client',
                'is_coworking_client': True,
            }
        )
        cls.other_client = cls.env['res.partner'].create(
            {
                'name': 'Secondary Visit Test Client',
                'is_coworking_client': True,
            }
        )
        cls.plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Unlimited Visit Test Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
                'price': 100.0,
            }
        )

        today = fields.Date.today()
        cls.booking_date = today + timedelta(days=1)
        membership_values = {
            'plan_id': cls.plan.id,
            'date_start': today,
            'date_end': today + timedelta(days=29),
            'state': 'active',
        }
        cls.membership = cls.env['os.coworking.membership'].create(
            {
                **membership_values,
                'partner_id': cls.client.id,
            }
        )
        cls.other_membership = cls.env['os.coworking.membership'].create(
            {
                **membership_values,
                'partner_id': cls.other_client.id,
            }
        )

    def _create_booking(
        self,
        *,
        client=None,
        membership=None,
        resource=None,
        start_hour=10,
    ):
        """Create a valid draft booking for a visit test scenario."""
        return self.booking_model.create(
            {
                'partner_id': (client or self.client).id,
                'resource_id': (resource or self.resource).id,
                'membership_id': (membership or self.membership).id,
                'start_datetime': datetime.combine(
                    self.booking_date,
                    time(start_hour),
                ),
                'end_datetime': datetime.combine(
                    self.booking_date,
                    time(start_hour + 1),
                ),
            }
        )

    def _create_confirmed_booking(self, **values):
        """Create and confirm a valid booking for a visit test scenario."""
        booking = self._create_booking(**values)
        booking.action_confirm()
        return booking

    def test_check_in_and_check_out_lifecycle(self):
        """Verify visit links, sequence, duration, and booking completion."""
        booking = self._create_confirmed_booking()

        booking.action_check_in()
        visit = booking.visit_ids

        self.assertRegex(visit.name, r'^VIS/\d{5}$')
        self.assertNotEqual(visit.name, self.env._('New'))
        self.assertEqual(visit.state, 'checked_in')
        self.assertEqual(visit.partner_id, booking.partner_id)
        self.assertEqual(visit.location_id, booking.location_id)
        self.assertEqual(visit.resource_id, booking.resource_id)
        self.assertEqual(visit.membership_id, booking.membership_id)
        self.assertEqual(visit.company_id, booking.company_id)
        self.assertEqual(booking.state, 'confirmed')

        visit.check_in = fields.Datetime.now() - timedelta(hours=2)
        visit.action_check_out()

        self.assertEqual(visit.state, 'checked_out')
        self.assertTrue(visit.check_out)
        self.assertAlmostEqual(visit.duration_hours, 2.0, delta=0.01)
        self.assertEqual(booking.state, 'done')

    def test_visit_requires_confirmed_booking_and_valid_initial_state(self):
        """Verify visits can start only from confirmed bookings."""
        draft_booking = self._create_booking()

        with self.assertRaises(ValidationError):
            self.visit_model.create({'booking_id': draft_booking.id})

        confirmed_booking = self._create_confirmed_booking(start_hour=12)
        with self.assertRaises(ValidationError):
            self.visit_model.create(
                {
                    'booking_id': confirmed_booking.id,
                    'state': 'checked_out',
                }
            )

    def test_booking_accepts_only_one_visit(self):
        """Verify action and SQL constraint reject a duplicate visit."""
        booking = self._create_confirmed_booking()
        booking.action_check_in()

        with self.assertRaises(UserError):
            booking.action_check_in()

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(UniqueViolation),
            self.cr.savepoint(),
        ):
            self.visit_model.create({'booking_id': booking.id})

    def test_client_cannot_have_two_open_visits(self):
        """Verify one client cannot be checked in to two resources."""
        first_booking = self._create_confirmed_booking()
        second_booking = self._create_confirmed_booking(
            resource=self.second_resource,
        )
        first_booking.action_check_in()

        with self.assertRaises(ValidationError), self.cr.savepoint():
            second_booking.action_check_in()

        self.assertFalse(second_booking.visit_ids)

    def test_visit_time_and_checkout_constraints(self):
        """Verify check-out chronology and invalid repeated action handling."""
        booking = self._create_confirmed_booking()
        booking.action_check_in()
        visit = booking.visit_ids

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(CheckViolation),
            self.cr.savepoint(),
        ):
            visit.write({'check_out': visit.check_in - timedelta(minutes=1)})

        visit.action_check_out()
        with self.assertRaises(UserError):
            visit.action_check_out()

    def test_partner_visit_smart_button_action(self):
        """Verify the contact visit count and smart button domain."""
        booking = self._create_confirmed_booking()
        booking.action_check_in()
        visit = booking.visit_ids

        self.assertEqual(self.client.coworking_visit_count, 1)

        action = self.client.action_view_coworking_visits()
        self.assertEqual(action['domain'], [('partner_id', '=', self.client.id)])
        self.assertEqual(self.visit_model.search(action['domain']), visit)

    def test_user_access_is_limited_to_assigned_locations(self):
        """Verify User and Admin access to visits follows location rules."""
        allowed_booking = self._create_confirmed_booking()
        denied_booking = self._create_confirmed_booking(
            client=self.other_client,
            membership=self.other_membership,
            resource=self.other_resource,
        )
        allowed_booking.action_check_in()
        denied_booking.action_check_in()
        allowed_visit = allowed_booking.visit_ids
        denied_visit = denied_booking.visit_ids

        coworking_user = self.env['res.users'].with_context(
            no_reset_password=True
        ).create(
            {
                'name': 'Visit Access Test User',
                'login': 'visit_access_test_user',
            }
        )
        self.env.ref(
            'OdooSchool_coworking_management.group_coworking_user'
        ).write({'user_ids': [Command.link(coworking_user.id)]})
        self.location.write(
            {'staff_user_ids': [Command.link(coworking_user.id)]}
        )

        visible_visits = self.visit_model.with_user(coworking_user).search(
            [('id', 'in', [allowed_visit.id, denied_visit.id])]
        )

        self.assertIn(allowed_visit, visible_visits)
        self.assertNotIn(denied_visit, visible_visits)
        allowed_visit.with_user(coworking_user).write({'note': 'Updated by User'})
        with self.assertRaises(AccessError):
            allowed_visit.with_user(coworking_user).unlink()

        admin = self.env.ref('base.user_admin')
        admin_visits = self.visit_model.with_user(admin).search(
            [('id', 'in', [allowed_visit.id, denied_visit.id])]
        )
        self.assertEqual(set(admin_visits.ids), {allowed_visit.id, denied_visit.id})
        denied_visit.with_user(admin).unlink()
