from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from psycopg2.errors import CheckViolation

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestOSCoworkingMembership(TransactionCase):
    """Test membership payment, lifecycle, limits, renewal, and constraints."""

    @classmethod
    def setUpClass(cls):
        """Create reusable client, location, and plans for membership tests."""
        super().setUpClass()
        cls.membership_model = cls.env['os.coworking.membership']
        cls.today = fields.Date.context_today(cls.membership_model)
        cls.env.company.partner_id.tz = 'UTC'
        cls.client = cls.env['res.partner'].create(
            {
                'name': 'Membership Test Client',
                'is_coworking_client': True,
            }
        )
        cls.location = cls.env['os.coworking.location'].create(
            {
                'name': 'Membership Test Location',
            }
        )
        cls.resource = cls.env['os.coworking.resource'].create(
            {
                'name': 'Membership Test Desk',
                'location_id': cls.location.id,
                'resource_type': 'desk',
                'capacity': 1,
                'hourly_rate': 10.0,
            }
        )
        cls.unlimited_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Test Unlimited Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
                'allow_auto_renew': True,
            }
        )
        cls.hours_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Test Hours Plan',
                'usage_type': 'hours',
                'duration_days': 30,
                'included_hours': 10.0,
                'allow_auto_renew': True,
            }
        )
        cls.visits_plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Test Visits Plan',
                'usage_type': 'visits',
                'duration_days': 30,
                'included_visits': 5,
                'allow_auto_renew': True,
            }
        )
        cls.products = cls.env['product.template'].create(
            [
                {
                    'name': 'Test Unlimited Membership Product',
                    'type': 'service',
                    'purchase_ok': False,
                    'list_price': 100.0,
                    'is_coworking_service': True,
                    'coworking_service_type': 'membership',
                    'coworking_plan_id': cls.unlimited_plan.id,
                },
                {
                    'name': 'Test Hours Membership Product',
                    'type': 'service',
                    'purchase_ok': False,
                    'list_price': 80.0,
                    'is_coworking_service': True,
                    'coworking_service_type': 'membership',
                    'coworking_plan_id': cls.hours_plan.id,
                },
                {
                    'name': 'Test Visits Membership Product',
                    'type': 'service',
                    'purchase_ok': False,
                    'list_price': 45.0,
                    'is_coworking_service': True,
                    'coworking_service_type': 'membership',
                    'coworking_plan_id': cls.visits_plan.id,
                },
            ]
        )

    def _create_membership(self, plan=None, **values):
        """Create a membership with valid default test values."""
        membership_values = {
            'partner_id': self.client.id,
            'plan_id': (plan or self.unlimited_plan).id,
            'date_start': self.today,
        }
        membership_values.update(values)
        return self.membership_model.create(membership_values)

    def test_membership_sequence_and_automatic_dates(self):
        """Verify the generated number and inclusive automatic end date."""
        membership = self._create_membership()

        self.assertRegex(membership.name, r'^MEM/\d{5}$')
        self.assertNotEqual(membership.name, self.env._('New'))
        self.assertEqual(
            membership.date_end,
            self.today + relativedelta(days=self.unlimited_plan.duration_days - 1),
        )

    def test_activation_initializes_all_plan_types(self):
        """Verify activation limits for unlimited, hourly, and visit plans."""
        cases = [
            (self.unlimited_plan, 0.0, 0),
            (self.hours_plan, 10.0, 0),
            (self.visits_plan, 0.0, 5),
        ]
        for plan, expected_hours, expected_visits in cases:
            with self.subTest(usage_type=plan.usage_type):
                membership = self._create_membership(plan=plan)

                membership.action_mark_as_paid()
                membership.action_activate()

                self.assertEqual(membership.state, 'active')
                self.assertEqual(membership.remaining_hours, expected_hours)
                self.assertEqual(membership.remaining_visits, expected_visits)

    def test_location_limited_plan_requires_location(self):
        """Verify that activation requires a location for a limited plan."""
        plan = self.env['os.coworking.membership.plan'].create(
            {
                'name': 'Test Location-Limited Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
                'all_locations': False,
            }
        )
        self.env['product.template'].create(
            {
                'name': 'Test Location-Limited Membership Product',
                'type': 'service',
                'purchase_ok': False,
                'list_price': 100.0,
                'is_coworking_service': True,
                'coworking_service_type': 'membership',
                'coworking_plan_id': plan.id,
            }
        )
        membership = self._create_membership(plan=plan)

        with self.assertRaises(UserError):
            membership.action_mark_as_paid()

        membership.location_id = self.location
        membership.action_mark_as_paid()
        membership.action_activate()

        self.assertEqual(membership.state, 'active')

    def test_freeze_and_unfreeze_extend_end_date(self):
        """Verify full frozen days extend the membership end date."""
        membership = self._create_membership(plan=self.hours_plan)
        membership.action_mark_as_paid()
        membership.action_activate()
        original_end_date = membership.date_end

        membership.action_freeze()
        membership.freeze_date = self.today - relativedelta(days=3)
        membership.action_unfreeze()

        self.assertEqual(membership.state, 'active')
        self.assertFalse(membership.freeze_date)
        self.assertEqual(membership.total_frozen_days, 3)
        self.assertEqual(membership.date_end, original_end_date + relativedelta(days=3))

    def test_early_termination_and_invalid_transition(self):
        """Verify early termination and rejection of invalid draft actions."""
        membership = self._create_membership()

        with self.assertRaises(UserError):
            membership.action_cancel()

        membership.action_mark_as_paid()
        membership.action_activate()
        membership.action_cancel()

        self.assertEqual(membership.state, 'cancelled')

    def test_cron_expires_and_creates_one_renewal(self):
        """Verify expiry and idempotent automatic renewal draft creation."""
        expired_end_date = self.today - relativedelta(days=1)
        membership = self._create_membership(
            date_start=self.today - relativedelta(days=30),
            date_end=expired_end_date,
            state='active',
            auto_renew=True,
            payment_status='paid',
            payment_date=self.today - relativedelta(days=30),
        )

        self.membership_model._cron_expire_memberships()

        renewal = membership.renewed_membership_id
        self.assertEqual(membership.state, 'expired')
        self.assertTrue(renewal)
        self.assertEqual(renewal.state, 'draft')
        self.assertEqual(renewal.previous_membership_id, membership)
        self.assertEqual(renewal.date_start, expired_end_date + relativedelta(days=1))
        self.assertEqual(
            renewal.date_end,
            renewal.date_start + relativedelta(days=self.unlimited_plan.duration_days - 1),
        )

        self.membership_model._cron_expire_memberships()

        renewal_count = self.membership_model.search_count(
            [('previous_membership_id', '=', membership.id)]
        )
        self.assertEqual(renewal_count, 1)

    def test_cron_ignores_frozen_membership(self):
        """Verify that the scheduled action does not expire frozen records."""
        membership = self._create_membership(
            date_start=self.today - relativedelta(days=30),
            date_end=self.today - relativedelta(days=1),
            state='frozen',
            freeze_date=self.today - relativedelta(days=5),
            payment_status='paid',
            payment_date=self.today - relativedelta(days=30),
        )

        self.membership_model._cron_expire_memberships()

        self.assertEqual(membership.state, 'frozen')
        self.assertFalse(membership.renewed_membership_id)

    def test_auto_renew_requires_supported_plan(self):
        """Verify automatic renewal cannot use an unsupported plan."""
        plan = self.env['os.coworking.membership.plan'].create(
            {
                'name': 'Test Non-Renewable Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
                'allow_auto_renew': False,
            }
        )

        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._create_membership(plan=plan, auto_renew=True)

    def test_date_and_remaining_limit_constraints(self):
        """Verify invalid dates and negative remaining limits are rejected."""
        invalid_values = [
            {
                'date_start': self.today,
                'date_end': self.today - relativedelta(days=1),
            },
            {'remaining_hours': -1.0},
            {'remaining_visits': -1},
        ]
        for values in invalid_values:
            with self.subTest(values=values):
                with (
                    mute_logger('odoo.sql_db'),
                    self.assertRaises(CheckViolation),
                    self.cr.savepoint(),
                ):
                    self._create_membership(**values)

    def test_payment_is_required_before_activation(self):
        """Verify payment confirmation and the paid-only activation rule."""
        membership = self._create_membership(plan=self.hours_plan)

        self.assertEqual(membership.payment_status, 'unpaid')
        self.assertFalse(membership.payment_date)
        with self.assertRaises(UserError):
            membership.action_activate()

        membership.action_mark_as_paid()

        self.assertEqual(membership.payment_status, 'paid')
        self.assertEqual(membership.payment_date, self.today)
        with self.assertRaises(UserError):
            membership.action_mark_as_paid()
        with self.assertRaises(UserError):
            membership.write({'payment_status': 'unpaid', 'payment_date': False})

        membership.action_activate()
        self.assertEqual(membership.state, 'active')

    def test_paid_membership_commercial_fields_are_locked(self):
        """Verify paid membership commercial details cannot be changed."""
        membership = self._create_membership(plan=self.hours_plan)
        membership.action_mark_as_paid()

        locked_values = [
            {'partner_id': self.env['res.partner'].create({'name': 'Other Client'}).id},
            {'plan_id': self.visits_plan.id},
            {'location_id': self.location.id},
            {'date_start': self.today + relativedelta(days=1)},
        ]
        for values in locked_values:
            with self.subTest(values=values):
                with self.assertRaises(UserError), self.cr.savepoint():
                    membership.write(values)

        membership.write({'note': 'Non-commercial details remain editable.'})
        self.assertEqual(membership.note, 'Non-commercial details remain editable.')

    def test_confirmed_booking_blocks_freeze_and_termination(self):
        """Verify confirmed bookings block disruptive membership actions."""
        membership = self._create_membership(plan=self.hours_plan)
        membership.action_mark_as_paid()
        membership.action_activate()
        booking_date = self.today + timedelta(days=1)
        booking = self.env['os.coworking.booking'].create(
            {
                'partner_id': self.client.id,
                'membership_id': membership.id,
                'resource_id': self.resource.id,
                'start_datetime': datetime.combine(booking_date, time(10)),
                'end_datetime': datetime.combine(booking_date, time(12)),
            }
        )
        booking.action_confirm()

        with self.assertRaises(UserError):
            membership.action_freeze()
        with self.assertRaises(UserError):
            membership.action_cancel()

        booking.action_cancel()
        membership.action_freeze()
        self.assertEqual(membership.state, 'frozen')

    def test_payment_requires_linked_product(self):
        """Verify payment cannot be confirmed without a plan product."""
        plan = self.env['os.coworking.membership.plan'].create(
            {
                'name': 'Test Plan Without Product',
                'usage_type': 'unlimited',
                'duration_days': 30,
            }
        )
        membership = self._create_membership(plan=plan)

        with self.assertRaises(UserError):
            membership.action_mark_as_paid()
        with self.assertRaises(UserError):
            membership._get_coworking_product()

        self.assertEqual(membership.payment_status, 'unpaid')
        self.assertFalse(membership.payment_date)

    def test_membership_invoice_report_renders_pdf(self):
        """Verify membership invoice data and PDF rendering."""
        membership = self._create_membership(plan=self.hours_plan)
        membership.action_mark_as_paid()
        product = membership._get_coworking_product()
        report = self.env.ref(
            'OdooSchool_coworking_management.os_coworking_membership_invoice_report_action'
        )

        html_content, html_type = self.env['ir.actions.report']._render_qweb_html(
            report.id,
            membership.ids,
        )
        self.assertEqual(html_type, 'html')
        self.assertIn(b'Membership Invoice', html_content)
        self.assertIn(product.name.encode(), html_content)
        self.assertIn(b'Paid', html_content)
        self.assertIn(b'80.00', html_content)

        with self.allow_pdf_render():
            pdf_content, pdf_type = (
                self.env['ir.actions.report']
                .with_context(force_report_rendering=True)
                ._render_qweb_pdf(report.id, membership.ids)
            )
        self.assertEqual(pdf_type, 'pdf')
        self.assertTrue(pdf_content.startswith(b'%PDF'))

    def test_partner_membership_smart_button_action(self):
        """Verify the contact count and membership smart button action."""
        membership = self._create_membership()

        self.assertEqual(self.client.coworking_membership_count, 1)

        action = self.client.action_view_coworking_memberships()
        self.assertEqual(action['domain'], [('partner_id', '=', self.client.id)])
        self.assertEqual(action['context'], {'default_partner_id': self.client.id})
        action_memberships = self.membership_model.search(action['domain'])
        self.assertEqual(action_memberships, membership)

    def test_membership_booking_and_visit_smart_buttons(self):
        """Verify membership operation counts and smart button actions."""
        membership = self._create_membership(plan=self.unlimited_plan)
        membership.action_mark_as_paid()
        membership.action_activate()
        booking_date = self.today + timedelta(days=1)
        booking = self.env['os.coworking.booking'].create(
            {
                'partner_id': self.client.id,
                'membership_id': membership.id,
                'resource_id': self.resource.id,
                'start_datetime': datetime.combine(booking_date, time(14)),
                'end_datetime': datetime.combine(booking_date, time(15)),
            }
        )
        booking.action_confirm()
        booking.action_check_in()

        self.assertEqual(membership.booking_count, 1)
        self.assertEqual(membership.visit_count, 1)

        booking_action = membership.action_view_bookings()
        self.assertEqual(booking_action['domain'], [('membership_id', '=', membership.id)])
        self.assertEqual(
            booking_action['context'],
            {
                'default_partner_id': self.client.id,
                'default_membership_id': membership.id,
            },
        )
        visit_action = membership.action_view_visits()
        self.assertEqual(visit_action['domain'], [('membership_id', '=', membership.id)])
