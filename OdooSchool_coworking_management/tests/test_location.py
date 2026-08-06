from psycopg2.errors import UniqueViolation

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestOSCoworkingLocation(TransactionCase):
    """Test coworking location data and business constraints."""

    def test_location_code_is_generated(self):
        """Verify that a new location receives a sequence-generated code."""
        location = self.env['os.coworking.location'].create(
            {
                'name': 'Sequence Test Location',
            }
        )

        self.assertRegex(location.code, r'^LOC/\d{5}$')
        self.assertNotEqual(location.code, self.env._('New'))

    def test_location_code_is_unique_per_company(self):
        """Verify that a location code is unique within one company."""
        location_model = self.env['os.coworking.location']
        location_model.create(
            {
                'name': 'First Unique Code Location',
                'code': 'LOC/TEST',
            }
        )

        with (
            mute_logger('odoo.sql_db'),
            self.assertRaises(UniqueViolation),
            self.cr.savepoint(),
        ):
            location_model.create(
                {
                    'name': 'Duplicate Code Location',
                    'code': 'LOC/TEST',
                }
            )

        other_company = self.env['res.company'].create(
            {
                'name': 'Other Test Company',
            }
        )
        location = location_model.create(
            {
                'name': 'Other Company Location',
                'code': 'LOC/TEST',
                'company_id': other_company.id,
            }
        )

        self.assertEqual(location.code, 'LOC/TEST')

    def test_location_working_hours_constraints(self):
        """Verify valid hours and reject invalid daily working ranges."""
        location = self.env['os.coworking.location'].create(
            {
                'name': 'Full Day Test Location',
                'working_hour_from': 0.0,
                'working_hour_to': 24.0,
            }
        )

        self.assertEqual(location.working_hour_from, 0.0)
        self.assertEqual(location.working_hour_to, 24.0)

        invalid_ranges = [
            (-1.0, 18.0),
            (8.0, 8.0),
            (18.0, 8.0),
            (8.0, 25.0),
        ]
        for opening_hour, closing_hour in invalid_ranges:
            with self.subTest(
                opening_hour=opening_hour,
                closing_hour=closing_hour,
            ):
                with self.assertRaises(ValidationError), self.cr.savepoint():
                    self.env['os.coworking.location'].create(
                        {
                            'name': 'Invalid Working Hours Location',
                            'working_hour_from': opening_hour,
                            'working_hour_to': closing_hour,
                        }
                    )

    def test_archived_location_is_hidden_by_default(self):
        """Verify that archived locations require disabled active filtering."""
        location_model = self.env['os.coworking.location']
        archived_location = location_model.create(
            {
                'name': 'Archived Test Location',
                'active': False,
            }
        )

        self.assertNotIn(archived_location, location_model.search([]))
        self.assertIn(
            archived_location,
            location_model.with_context(active_test=False).search([]),
        )
