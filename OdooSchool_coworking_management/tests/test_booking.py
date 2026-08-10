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
        cls.unlimited_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Unlimited Booking Test Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
            }
        )
        cls.hours_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Hourly Booking Test Plan',
                'usage_type': 'hours',
                'duration_days': 30,
                'included_hours': 10.0,
            }
        )
        cls.env['product.template'].create(
            [
                {
                    'name': 'Unlimited Booking Test Product',
                    'type': 'service',
                    'list_price': 100.0,
                    'is_coworking_service': True,
                    'coworking_service_type': 'membership',
                    'coworking_plan_id': cls.unlimited_plan.id,
                },
                {
                    'name': 'Hourly Booking Test Product',
                    'type': 'service',
                    'list_price': 80.0,
                    'is_coworking_service': True,
                    'coworking_service_type': 'membership',
                    'coworking_plan_id': cls.hours_plan.id,
                },
            ]
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

    def test_booking_sequence_and_report(self):
        """Verify booking basics and PDF confirmation rendering."""
        booking = self._create_booking(note='Prepare the requested equipment.')
        report = self.env.ref('OdooSchool_coworking_management.os_coworking_booking_report_action')

        self.assertRegex(booking.name, r'^BKG/\d{5}$')
        self.assertEqual(booking.duration_hours, 2.0)

        html_content, html_type = self.env['ir.actions.report']._render_qweb_html(
            report.id,
            booking.ids,
        )
        self.assertEqual(html_type, 'html')
        self.assertIn(b'Booking Confirmation', html_content)
        self.assertIn(b'Draft', html_content)
        self.assertIn(b'Product Price', html_content)
        self.assertIn(b'General Coworking Rules', html_content)

        with self.allow_pdf_render():
            pdf_content, pdf_type = (
                self.env['ir.actions.report']
                .with_context(force_report_rendering=True)
                ._render_qweb_pdf(report.id, booking.ids)
            )
        self.assertEqual(pdf_type, 'pdf')
        self.assertTrue(pdf_content.startswith(b'%PDF'))

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

    def test_booking_confirmation_constraints(self):
        """Verify unavailable, outside-hours, and overlapping bookings fail."""
        booking = self._create_booking(resource_id=self.maintenance_resource.id)
        with self.assertRaises(ValidationError):
            booking.action_confirm()

        outside_hours_booking = self._create_booking(
            start_datetime=datetime.combine(self.booking_date, time(7)),
            end_datetime=datetime.combine(self.booking_date, time(8)),
        )
        with self.assertRaises(ValidationError):
            outside_hours_booking.action_confirm()

        first_booking = self._create_booking()
        first_booking.action_confirm()
        overlapping_booking = self._create_booking(
            start_datetime=datetime.combine(self.booking_date, time(11)),
            end_datetime=datetime.combine(self.booking_date, time(13)),
        )
        with self.assertRaises(ValidationError):
            overlapping_booking.action_confirm()

    def test_booking_requires_visit_and_revalidates_check_in(self):
        """Verify completion and check-in lifecycle protections."""
        booking = self._create_booking()
        booking.action_confirm()
        with self.assertRaises(UserError):
            booking.action_done()
        with self.assertRaises(UserError):
            self.unlimited_membership.action_freeze()

        self.resource.state = 'maintenance'
        with self.assertRaises(ValidationError):
            booking.action_check_in()

        self.resource.state = 'available'
        booking.action_check_in()
        with self.assertRaises(UserError):
            booking.action_done()
        booking.visit_ids.action_check_out()
        self.assertEqual(booking.state, 'done')

    def test_user_access_is_limited_to_assigned_locations(self):
        """Verify User ACL and record rules for location-based booking access."""
        coworking_user = (
            self.env['res.users']
            .with_context(no_reset_password=True)
            .create(
                {
                    'name': 'Booking Access Test User',
                    'login': 'booking_access_test_user',
                }
            )
        )
        self.env.ref('OdooSchool_coworking_management.group_coworking_user').write(
            {'user_ids': [Command.link(coworking_user.id)]}
        )
        self.location.write({'staff_user_ids': [Command.link(coworking_user.id)]})
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
