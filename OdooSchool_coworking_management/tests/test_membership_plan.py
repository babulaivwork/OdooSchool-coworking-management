from psycopg2.errors import CheckViolation, UniqueViolation

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestOSCoworkingMembershipPlan(TransactionCase):
    """Test membership plan data and business constraints."""

    def _create_plan(self, **values):
        """Create a membership plan with valid default test values."""
        plan_values = {
            'name': 'Test Membership Plan',
            'usage_type': 'unlimited',
            'duration_days': 30,
            'price': 100.0,
        }
        plan_values.update(values)
        return self.env['os.coworking.membership.plan'].create(plan_values)

    def test_membership_plan_code_is_generated(self):
        """Verify that a new plan receives a sequence-generated code."""
        plan = self._create_plan(name='Sequence Test Plan')

        self.assertRegex(plan.code, r'^PLN/\d{5}$')
        self.assertNotEqual(plan.code, self.env._('New'))

    def test_membership_plan_code_is_unique(self):
        """Verify that a membership plan code is globally unique."""
        self._create_plan(name='First Unique Code Plan', code='PLN/TEST')

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(UniqueViolation),
            self.cr.savepoint(),
        ):
            self._create_plan(name='Duplicate Code Plan', code='PLN/TEST')

    def test_membership_plan_duration_constraint(self):
        """Verify that membership plan duration must be positive."""
        for duration_days in (0, -1):
            with self.subTest(duration_days=duration_days):
                with (
                    mute_logger('odoo.sql_db'),
                    self.assertRaises(CheckViolation),
                    self.cr.savepoint(),
                ):
                    self._create_plan(
                        name='Invalid Duration Plan',
                        duration_days=duration_days,
                    )

    def test_membership_plan_price_constraint(self):
        """Verify that zero is valid and negative plan prices are rejected."""
        free_plan = self._create_plan(name='Free Plan', price=0.0)

        self.assertEqual(free_plan.price, 0.0)

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(CheckViolation),
            self.cr.savepoint(),
        ):
            self._create_plan(name='Negative Price Plan', price=-1.0)

    def test_membership_plan_valid_usage_limits(self):
        """Verify valid limits for unlimited, hourly, and visit plans."""
        unlimited_plan = self._create_plan(name='Unlimited Plan')
        hourly_plan = self._create_plan(
            name='Hourly Plan',
            usage_type='hours',
            included_hours=10.0,
        )
        visit_plan = self._create_plan(
            name='Visit Plan',
            usage_type='visits',
            included_visits=5,
        )

        self.assertEqual(unlimited_plan.usage_type, 'unlimited')
        self.assertEqual(hourly_plan.included_hours, 10.0)
        self.assertEqual(visit_plan.included_visits, 5)

    def test_membership_plan_invalid_usage_limits(self):
        """Verify that missing and incompatible usage limits are rejected."""
        invalid_values = [
            {'usage_type': 'unlimited', 'included_hours': 1.0},
            {'usage_type': 'unlimited', 'included_visits': 1},
            {'usage_type': 'hours', 'included_hours': 0.0},
            {'usage_type': 'hours', 'included_hours': 10.0, 'included_visits': 1},
            {'usage_type': 'visits', 'included_visits': 0},
            {'usage_type': 'visits', 'included_visits': 5, 'included_hours': 1.0},
        ]
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError), self.cr.savepoint():
                    self._create_plan(
                        name='Invalid Usage Limits Plan',
                        **values,
                    )

    def test_membership_plan_usage_type_onchange(self):
        """Verify that changing the usage type clears incompatible limits."""
        plan = self.env['os.coworking.membership.plan'].new(
            {
                'usage_type': 'hours',
                'included_hours': 10.0,
                'included_visits': 5,
            }
        )

        plan._onchange_usage_type()

        self.assertEqual(plan.included_hours, 10.0)
        self.assertEqual(plan.included_visits, 0)

        plan.usage_type = 'unlimited'
        plan._onchange_usage_type()

        self.assertEqual(plan.included_hours, 0.0)
        self.assertEqual(plan.included_visits, 0)

    def test_archived_membership_plan_is_hidden_by_default(self):
        """Verify that archived plans require disabled active filtering."""
        plan_model = self.env['os.coworking.membership.plan']
        archived_plan = self._create_plan(
            name='Archived Membership Plan',
            active=False,
        )

        self.assertNotIn(archived_plan, plan_model.search([]))
        self.assertIn(
            archived_plan,
            plan_model.with_context(active_test=False).search([]),
        )

    def test_membership_plan_options_and_currency(self):
        """Verify location, renewal, and company currency defaults."""
        plan = self._create_plan(
            name='Location Renewal Plan',
            all_locations=False,
            allow_auto_renew=True,
        )

        self.assertFalse(plan.all_locations)
        self.assertTrue(plan.allow_auto_renew)
        self.assertEqual(plan.currency_id, self.env.company.currency_id)
