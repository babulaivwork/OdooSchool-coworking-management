from datetime import datetime, time, timedelta

from odoo import fields
from odoo.tests import TransactionCase


class TestOSCoworkingAvailabilityWizard(TransactionCase):
    """Test resource availability search and draft booking preparation."""

    @classmethod
    def setUpClass(cls):
        """Create reusable locations, resources, and membership data."""
        super().setUpClass()
        cls.wizard_model = cls.env['os.coworking.availability.wizard']
        cls.booking_model = cls.env['os.coworking.booking']
        cls.env.company.partner_id.tz = 'UTC'

        cls.location = cls.env['os.coworking.location'].create(
            {
                'name': 'Availability Test Location',
                'working_hour_from': 8.0,
                'working_hour_to': 18.0,
            }
        )
        cls.available_room = cls._create_resource(
            name='Available Six-Person Room',
            capacity=6,
        )
        cls.large_room = cls._create_resource(
            name='Available Ten-Person Room',
            capacity=10,
        )
        cls._create_resource(
            name='Small Meeting Room',
            capacity=2,
        )
        cls._create_resource(
            name='Maintenance Meeting Room',
            capacity=8,
            state='maintenance',
        )

        cls.client = cls.env['res.partner'].create(
            {
                'name': 'Availability Test Client',
                'is_coworking_client': True,
            }
        )
        cls.plan = cls.env['os.coworking.membership.plan'].create(
            {
                'name': 'Availability Test Unlimited Plan',
                'usage_type': 'unlimited',
                'duration_days': 30,
            }
        )
        today = fields.Date.today()
        cls.membership = cls.env['os.coworking.membership'].create(
            {
                'partner_id': cls.client.id,
                'plan_id': cls.plan.id,
                'date_start': today,
                'date_end': today + timedelta(days=29),
                'state': 'active',
            }
        )
        cls.search_date = today + timedelta(days=1)
        cls.start_datetime = datetime.combine(cls.search_date, time(10))
        cls.end_datetime = datetime.combine(cls.search_date, time(12))

    @classmethod
    def _create_resource(cls, **values):
        """Create a meeting room with valid reusable default values."""
        resource_values = {
            'name': 'Availability Test Resource',
            'location_id': cls.location.id,
            'resource_type': 'meeting_room',
            'capacity': 4,
            'hourly_rate': 20.0,
        }
        resource_values.update(values)
        return cls.env['os.coworking.resource'].create(resource_values)

    def _create_wizard(self, **values):
        """Create an availability wizard with valid default criteria."""
        wizard_values = {
            'location_id': self.location.id,
            'resource_type': 'meeting_room',
            'capacity': 4,
            'start_datetime': self.start_datetime,
            'end_datetime': self.end_datetime,
        }
        wizard_values.update(values)
        return self.wizard_model.create(wizard_values)

    def _create_booking(self, resource, start_datetime=None, end_datetime=None):
        """Create a draft booking for a resource and the test membership."""
        return self.booking_model.create(
            {
                'partner_id': self.client.id,
                'resource_id': resource.id,
                'membership_id': self.membership.id,
                'start_datetime': start_datetime or self.start_datetime,
                'end_datetime': end_datetime or self.end_datetime,
            }
        )

    def test_search_returns_available_resources_and_excludes_overlap(self):
        """Verify the main resource filters and confirmed-booking overlap."""
        wizard = self._create_wizard()
        wizard.action_search_resources()

        self.assertEqual(
            set(wizard.available_resource_ids.ids),
            {self.available_room.id, self.large_room.id},
        )
        blocking_booking = self._create_booking(self.available_room)
        blocking_booking.action_confirm()
        wizard.action_search_resources()
        self.assertEqual(wizard.available_resource_ids, self.large_room)

        empty_wizard = self._create_wizard(capacity=100)
        empty_wizard.action_search_resources()
        self.assertTrue(empty_wizard.search_performed)
        self.assertFalse(empty_wizard.available_resource_ids)

    def test_create_booking_opens_prefilled_unsaved_form(self):
        """Verify booking form defaults without creating a database record."""
        wizard = self._create_wizard(partner_id=self.client.id)
        wizard.action_search_resources()
        wizard.selected_resource_id = self.available_room
        booking_count = self.booking_model.search_count([])

        action = wizard.action_create_booking()

        self.assertEqual(self.booking_model.search_count([]), booking_count)
        self.assertEqual(action['res_model'], 'os.coworking.booking')
        self.assertFalse(action['res_id'])
        self.assertEqual(
            action['context']['default_resource_id'],
            self.available_room.id,
        )
        self.assertEqual(action['context']['default_partner_id'], self.client.id)
