from psycopg2.errors import UniqueViolation

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestCoworkingStandardModelExtensions(TransactionCase):
    """Test coworking fields added to standard Odoo models."""

    def test_partner_coworking_client_flag(self):
        """Verify the coworking client flag and its default value."""
        regular_partner = self.env['res.partner'].create({'name': 'Regular Contact'})
        coworking_client = self.env['res.partner'].create(
            {
                'name': 'Coworking Client',
                'is_coworking_client': True,
            }
        )

        self.assertFalse(regular_partner.is_coworking_client)
        self.assertTrue(coworking_client.is_coworking_client)

    def test_product_coworking_service_fields_and_plan_link(self):
        """Verify coworking service types and membership plan linking."""
        expected_service_types = {
            'membership',
            'additional_service',
        }
        service_type_field = self.env['product.template']._fields['coworking_service_type']
        available_service_types = {value for value, _label in service_type_field.selection}
        plan = self.env['os.coworking.membership.plan'].create(
            {
                'name': 'Linked Test Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
            }
        )
        product = self.env['product.template'].create(
            {
                'name': 'Linked Membership Service',
                'type': 'service',
                'list_price': 100.0,
                'is_coworking_service': True,
                'coworking_service_type': 'membership',
                'coworking_plan_id': plan.id,
            }
        )

        self.assertEqual(available_service_types, expected_service_types)
        self.assertTrue(product.is_coworking_service)
        self.assertEqual(product.coworking_service_type, 'membership')
        self.assertEqual(product.coworking_plan_id, plan)
        self.assertEqual(plan.product_id, product)
        self.assertEqual(plan.price, product.list_price)

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(UniqueViolation),
            self.cr.savepoint(),
        ):
            self.env['product.template'].create(
                {
                    'name': 'Duplicate Plan Membership Service',
                    'type': 'service',
                    'is_coworking_service': True,
                    'coworking_service_type': 'membership',
                    'coworking_plan_id': plan.id,
                }
            )
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['product.template'].create(
                {
                    'name': 'Non-Service Coworking Product',
                    'type': 'consu',
                    'is_coworking_service': True,
                    'coworking_service_type': 'additional_service',
                }
            )
