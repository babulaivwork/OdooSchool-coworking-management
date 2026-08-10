from psycopg2.errors import CheckViolation

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
        }
        plan_values.update(values)
        return self.env['os.coworking.membership.plan'].create(plan_values)

    def _create_product(self, plan, list_price=100.0):
        """Create a valid membership product linked to a test plan."""
        return self.env['product.template'].create(
            {
                'name': 'Test Membership Product',
                'type': 'service',
                'list_price': list_price,
                'is_coworking_service': True,
                'coworking_service_type': 'membership',
                'coworking_plan_id': plan.id,
            }
        )

    def test_membership_plan_sequence_price_and_constraints(self):
        """Verify plan sequence, product price, and main constraints."""
        plan = self._create_plan(name='Product Price Plan')
        product = self._create_product(plan, list_price=125.0)

        self.assertRegex(plan.code, r'^PLN/\d{5}$')
        self.assertEqual(plan.product_id, product)
        self.assertEqual(plan.price, 125.0)
        self.assertEqual(plan.currency_id, product.currency_id)
        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(CheckViolation),
            self.cr.savepoint(),
        ):
            self._create_plan(duration_days=0)

        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._create_plan(usage_type='hours', included_hours=0.0)
