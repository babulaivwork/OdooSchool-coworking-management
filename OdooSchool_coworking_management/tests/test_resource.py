from psycopg2.errors import CheckViolation, UniqueViolation

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
        cls.other_location = cls.env['os.coworking.location'].create(
            {
                'name': 'Secondary Resource Test Location',
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

    def test_resource_code_is_generated(self):
        """Verify that a new resource receives a sequence-generated code."""
        resource = self._create_resource(name='Sequence Test Resource')

        self.assertRegex(resource.code, r'^RES/\d{5}$')
        self.assertNotEqual(resource.code, self.env._('New'))

    def test_resource_code_is_unique_per_location(self):
        """Verify that a resource code is unique within one location."""
        self._create_resource(
            name='First Unique Code Resource',
            code='RES/TEST',
        )

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(UniqueViolation),
            self.cr.savepoint(),
        ):
            self._create_resource(
                name='Duplicate Code Resource',
                code='RES/TEST',
            )

        resource = self._create_resource(
            name='Other Location Resource',
            code='RES/TEST',
            location_id=self.other_location.id,
        )

        self.assertEqual(resource.code, 'RES/TEST')

    def test_resource_capacity_constraint(self):
        """Verify that resource capacity must be greater than zero."""
        for capacity in (0, -1):
            with self.subTest(capacity=capacity):
                with (
                    mute_logger('odoo.sql_db'),
                    self.assertRaises(CheckViolation),
                    self.cr.savepoint(),
                ):
                    self._create_resource(
                        name='Invalid Capacity Resource',
                        capacity=capacity,
                    )

    def test_resource_hourly_rate_constraint(self):
        """Verify that a resource hourly rate cannot be negative."""
        resource = self._create_resource(
            name='Free Resource',
            hourly_rate=0.0,
        )

        self.assertEqual(resource.hourly_rate, 0.0)

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(CheckViolation),
            self.cr.savepoint(),
        ):
            self._create_resource(
                name='Negative Rate Resource',
                hourly_rate=-1.0,
            )

    def test_resource_types_and_states(self):
        """Verify all supported resource types and operational states."""
        variants = [
            ('desk', 'available'),
            ('meeting_room', 'maintenance'),
            ('private_office', 'inactive'),
            ('event_space', 'available'),
        ]
        resources = self.resource_model
        for resource_type, state in variants:
            resources |= self._create_resource(
                name=f'{resource_type} {state}',
                resource_type=resource_type,
                state=state,
            )

        self.assertEqual(set(resources.mapped('resource_type')), {item[0] for item in variants})
        self.assertEqual(set(resources.mapped('state')), {item[1] for item in variants})

    def test_archived_resource_is_hidden_by_default(self):
        """Verify that archived resources require disabled active filtering."""
        archived_resource = self._create_resource(
            name='Archived Test Resource',
            active=False,
            state='inactive',
        )

        self.assertNotIn(archived_resource, self.resource_model.search([]))
        self.assertIn(
            archived_resource,
            self.resource_model.with_context(active_test=False).search([]),
        )

    def test_location_resource_smart_button_action(self):
        """Verify the resource count and location-filtered smart button action."""
        first_resource = self._create_resource(name='First Location Resource')
        second_resource = self._create_resource(name='Second Location Resource')
        self._create_resource(
            name='Unrelated Location Resource',
            location_id=self.other_location.id,
        )

        self.assertEqual(self.location.resource_count, 2)

        action = self.location.action_view_resources()
        self.assertEqual(action['domain'], [('location_id', '=', self.location.id)])
        self.assertEqual(action['context'], {'default_location_id': self.location.id})
        action_resources = self.resource_model.search(action['domain'])
        self.assertEqual(set(action_resources.ids), {first_resource.id, second_resource.id})
