from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase


class TestOSCoworkingLocation(TransactionCase):
    """Test coworking location data and business constraints."""

    def test_location_sequence_and_working_hours(self):
        """Verify location sequence and the main working-hours constraint."""
        location = self.env['os.coworking.location'].create(
            {
                'name': 'Sequence Test Location',
            }
        )

        self.assertRegex(location.code, r'^LOC/\d{5}$')
        self.assertNotEqual(location.code, self.env._('New'))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['os.coworking.location'].create(
                {
                    'name': 'Invalid Working Hours Location',
                    'working_hour_from': 18.0,
                    'working_hour_to': 8.0,
                }
            )
