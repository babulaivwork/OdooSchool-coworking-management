from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestOSCoworkingMembership(TransactionCase):
    """Test membership payment, lifecycle, limits, renewal, and constraints."""

    @classmethod
    def setUpClass(cls):
        """Create reusable client, location, and plans for membership tests."""
        super().setUpClass()
        cls.membership_model = cls.env['os.coworking.membership']
        cls.today = fields.Date.context_today(cls.membership_model)
        cls.client = cls.env['res.partner'].create(
            {
                'name': 'Membership Test Client',
                'is_coworking_client': True,
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
        cls.env['product.template'].create(
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

    def test_membership_payment_activation_and_limits(self):
        """Verify sequence, payment, activation, and all three plan limits."""
        cases = [
            (self.unlimited_plan, 0.0, 0),
            (self.hours_plan, 10.0, 0),
            (self.visits_plan, 0.0, 5),
        ]
        for plan, expected_hours, expected_visits in cases:
            with self.subTest(usage_type=plan.usage_type):
                membership = self._create_membership(plan=plan)

                with self.assertRaises(UserError):
                    membership.action_activate()
                membership.action_mark_as_paid()
                if plan == self.hours_plan:
                    with self.assertRaises(UserError):
                        membership.write({'payment_status': 'unpaid'})
                    with self.assertRaises(UserError):
                        membership.write({'plan_id': self.visits_plan.id})
                membership.action_activate()

                self.assertRegex(membership.name, r'^MEM/\d{5}$')
                self.assertEqual(membership.state, 'active')
                self.assertEqual(membership.remaining_hours, expected_hours)
                self.assertEqual(membership.remaining_visits, expected_visits)
                self.assertEqual(
                    membership.date_end,
                    self.today + relativedelta(days=plan.duration_days - 1),
                )

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
