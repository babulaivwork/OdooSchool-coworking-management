from datetime import datetime, time, timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
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
        cls.other_location = cls.env['os.coworking.location'].create(
            {
                'name': 'Other Availability Test Location',
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
            name='Available Desk',
            resource_type='desk',
            capacity=1,
        )
        cls._create_resource(
            name='Maintenance Meeting Room',
            capacity=8,
            state='maintenance',
        )
        cls._create_resource(
            name='Inactive Meeting Room',
            capacity=8,
            state='inactive',
        )
        cls._create_resource(
            name='Archived Meeting Room',
            capacity=8,
            active=False,
        )
        cls._create_resource(
            name='Meeting Room at Other Location',
            location_id=cls.other_location.id,
            capacity=8,
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

    def test_search_returns_only_matching_operational_resources(self):
        """Verify location, type, capacity, active, and state filtering."""
        wizard = self._create_wizard()

        action = wizard.action_search_resources()

        self.assertEqual(
            set(wizard.available_resource_ids.ids),
            {self.available_room.id, self.large_room.id},
        )
        self.assertEqual(action['res_model'], wizard._name)
        self.assertEqual(action['res_id'], wizard.id)
        self.assertEqual(action['target'], 'new')
        self.assertTrue(wizard.search_performed)

    def test_search_marks_empty_result_and_criteria_change_resets_it(self):
        """Verify an empty search is distinguishable from a new wizard."""
        wizard = self._create_wizard(capacity=100)

        wizard.action_search_resources()

        self.assertTrue(wizard.search_performed)
        self.assertFalse(wizard.available_resource_ids)

        wizard._onchange_search_criteria()

        self.assertFalse(wizard.search_performed)
        self.assertFalse(wizard.available_resource_ids)

    def test_search_excludes_overlap_and_allows_adjacent_booking(self):
        """Verify only overlapping confirmed bookings block a resource."""
        blocking_booking = self._create_booking(self.available_room)
        blocking_booking.action_confirm()
        self._create_booking(self.large_room)

        overlapping_wizard = self._create_wizard(
            start_datetime=datetime.combine(self.search_date, time(11)),
            end_datetime=datetime.combine(self.search_date, time(13)),
        )
        overlapping_wizard.action_search_resources()

        self.assertNotIn(
            self.available_room,
            overlapping_wizard.available_resource_ids,
        )
        self.assertIn(self.large_room, overlapping_wizard.available_resource_ids)

        adjacent_wizard = self._create_wizard(
            start_datetime=datetime.combine(self.search_date, time(12)),
            end_datetime=datetime.combine(self.search_date, time(13)),
        )
        adjacent_wizard.action_search_resources()

        self.assertIn(self.available_room, adjacent_wizard.available_resource_ids)
        self.assertIn(self.large_room, adjacent_wizard.available_resource_ids)

    def test_wizard_validates_capacity_and_period(self):
        """Verify positive capacity, full hours, chronology, and working time."""
        with self.assertRaises(ValidationError):
            self._create_wizard(capacity=0)

        with self.assertRaises(ValidationError):
            self._create_wizard(
                end_datetime=datetime.combine(self.search_date, time(9)),
            )

        with self.assertRaises(ValidationError):
            self._create_wizard(
                start_datetime=datetime.combine(self.search_date, time(10, 30)),
            )

        with self.assertRaises(ValidationError):
            self._create_wizard(
                start_datetime=datetime.combine(self.search_date, time(7)),
                end_datetime=datetime.combine(self.search_date, time(8)),
            )

    def test_create_booking_opens_prefilled_unsaved_form(self):
        """Verify booking form defaults without creating a database record."""
        wizard = self._create_wizard(partner_id=self.client.id)
        wizard.action_search_resources()
        wizard.selected_resource_id = self.available_room
        booking_count = self.booking_model.search_count([])

        action = wizard.action_create_booking()

        self.assertEqual(self.booking_model.search_count([]), booking_count)
        self.assertEqual(action['res_model'], 'os.coworking.booking')
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'current')
        self.assertFalse(action['res_id'])
        self.assertEqual(
            action['context'],
            {
                'default_resource_id': self.available_room.id,
                'default_start_datetime': fields.Datetime.to_string(
                    self.start_datetime
                ),
                'default_end_datetime': fields.Datetime.to_string(self.end_datetime),
                'default_partner_id': self.client.id,
            },
        )
        self.assertNotIn('default_membership_id', action['context'])

    def test_create_booking_rechecks_selected_resource(self):
        """Verify stale availability results cannot prepare a booking."""
        wizard = self._create_wizard()
        wizard.action_search_resources()

        with self.assertRaises(UserError):
            wizard.action_create_booking()

        wizard.selected_resource_id = self.available_room
        blocking_booking = self._create_booking(self.available_room)
        blocking_booking.action_confirm()

        with self.assertRaises(ValidationError):
            wizard.action_create_booking()

    def test_wizard_action_is_available_from_menu_and_booking_views(self):
        """Verify menu and binding action configuration for the wizard."""
        action = self.env.ref(
            'OdooSchool_coworking_management.os_coworking_action_availability_wizard'
        )
        menu = self.env.ref(
            'OdooSchool_coworking_management.os_coworking_menu_availability_wizard'
        )

        self.assertEqual(action.res_model, self.wizard_model._name)
        self.assertEqual(action.target, 'new')
        self.assertEqual(action.binding_model_id.model, 'os.coworking.booking')
        self.assertEqual(action.binding_view_types, 'list,form')
        self.assertEqual(menu.action, action)

    def test_user_acl_allows_complete_wizard_flow(self):
        """Verify Coworking User can create, search, update, and delete a wizard."""
        coworking_user = self.env['res.users'].with_context(no_reset_password=True).create(
            {
                'name': 'Availability Wizard Test User',
                'login': 'availability_wizard_test_user',
            }
        )
        self.env.ref(
            'OdooSchool_coworking_management.group_coworking_user'
        ).write({'user_ids': [Command.link(coworking_user.id)]})
        self.location.write(
            {'staff_user_ids': [Command.link(coworking_user.id)]}
        )
        wizard = self.wizard_model.with_user(coworking_user).create(
            {
                'location_id': self.location.id,
                'resource_type': 'meeting_room',
                'capacity': 4,
                'start_datetime': self.start_datetime,
                'end_datetime': self.end_datetime,
            }
        )

        wizard.action_search_resources()

        self.assertIn(self.available_room, wizard.available_resource_ids)
        wizard.write({'capacity': 5})
        wizard.unlink()
        self.assertFalse(wizard.exists())
