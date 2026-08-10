from psycopg2.errors import CheckViolation

from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestOSCoworkingResource(TransactionCase):
    """Test coworking resource data, actions, and business constraints."""

    @classmethod
    def setUpClass(cls):
        """Create reusable locations for resource tests."""
        super().setUpClass()
        cls.resource_model = cls.env['os.coworking.resource']
        cls.location = cls.env['os.coworking.location'].create(
            {
                'name': 'Primary Resource Test Location',
            }
        )

    def _create_resource(self, **values):
        """Create a resource with valid default test values."""
        resource_values = {
            'name': 'Test Resource',
            'location_id': self.location.id,
            'resource_type': 'desk',
            'capacity': 1,
            'hourly_rate': 10.0,
        }
        resource_values.update(values)
        return self.resource_model.create(resource_values)

    def test_resource_sequence_and_constraints(self):
        """Verify resource sequence and its main numeric constraints."""
        resource = self._create_resource(name='Sequence Test Resource')

        self.assertRegex(resource.code, r'^RES/\d{5}$')
        self.assertNotEqual(resource.code, self.env._('New'))
        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(CheckViolation),
            self.cr.savepoint(),
        ):
            self._create_resource(capacity=0)

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(CheckViolation),
            self.cr.savepoint(),
        ):
            self._create_resource(hourly_rate=-1.0)
