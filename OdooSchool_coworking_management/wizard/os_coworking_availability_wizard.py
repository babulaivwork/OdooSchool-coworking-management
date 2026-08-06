from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError


class OSCoworkingAvailabilityWizard(models.TransientModel):
    """Search for coworking resources available during a selected period."""

    _name = 'os.coworking.availability.wizard'
    _description = 'Coworking Resource Availability'

    location_id = fields.Many2one(
        comodel_name='os.coworking.location',
        string='Location',
        required=True,
        domain=[('active', '=', True)],
    )
    resource_type = fields.Selection(
        selection=[
            ('desk', 'Desk'),
            ('meeting_room', 'Meeting Room'),
            ('private_office', 'Private Office'),
            ('event_space', 'Event Space'),
        ],
        string='Resource Type',
        required=True,
        default='desk',
    )
    capacity = fields.Integer(
        string='Minimum Capacity',
        required=True,
        default=1,
    )
    start_datetime = fields.Datetime(
        string='Start',
        required=True,
    )
    end_datetime = fields.Datetime(
        string='End',
        required=True,
    )
    available_resource_ids = fields.Many2many(
        comodel_name='os.coworking.resource',
        relation='os_coworking_availability_resource_rel',
        column1='wizard_id',
        column2='resource_id',
        string='Available Resources',
        readonly=True,
    )
    selected_resource_id = fields.Many2one(
        comodel_name='os.coworking.resource',
        string='Selected Resource',
        domain="[('id', 'in', available_resource_ids)]",
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Client',
        domain=[('is_coworking_client', '=', True)],
    )

    @api.constrains('capacity')
    def _check_capacity(self):
        """Ensure that the requested minimum capacity is positive.

        :raises ValidationError: If capacity is zero or negative.
        """
        for wizard in self:
            if wizard.capacity <= 0:
                raise ValidationError(
                    self.env._('Minimum capacity must be greater than zero.')
                )

    @api.constrains('location_id', 'start_datetime', 'end_datetime')
    def _check_search_period(self):
        """Validate the selected period when wizard criteria are saved."""
        for wizard in self:
            if wizard.location_id and wizard.start_datetime and wizard.end_datetime:
                wizard._validate_search_period()

    @api.onchange(
        'location_id',
        'resource_type',
        'capacity',
        'start_datetime',
        'end_datetime',
    )
    def _onchange_search_criteria(self):
        """Clear stale search results after availability criteria change."""
        self.available_resource_ids = [Command.clear()]
        self.selected_resource_id = False

    def _get_timezone_name(self):
        """Return the common timezone used for coworking operations.

        :return: Company timezone, with user timezone and UTC as fallbacks.
        :rtype: str
        """
        self.ensure_one()
        return self.location_id.company_id.partner_id.tz or self.env.user.tz or 'UTC'

    def _to_local_datetime(self, value):
        """Convert a stored UTC datetime to the coworking timezone.

        :param datetime value: Naive UTC datetime stored by Odoo.
        :return: Timezone-aware local datetime.
        :rtype: datetime
        """
        self.ensure_one()
        return fields.Datetime.context_timestamp(
            self.with_context(tz=self._get_timezone_name()),
            value,
        )

    def _validate_search_period(self):
        """Validate chronology, hourly boundaries, and location working time.

        :raises ValidationError: If the period is invalid, does not follow the
            full-hour grid, crosses a local day, or is outside working hours.
        """
        self.ensure_one()
        if self.end_datetime <= self.start_datetime:
            raise ValidationError(
                self.env._('The end time must be later than the start time.')
            )

        start_local = self._to_local_datetime(self.start_datetime)
        end_local = self._to_local_datetime(self.end_datetime)
        for value in (start_local, end_local):
            if value.minute or value.second or value.microsecond:
                raise ValidationError(
                    self.env._('The start and end times must be set to full hours.')
                )

        location = self.location_id
        start_hour = start_local.hour + start_local.minute / 60.0
        end_hour = end_local.hour + end_local.minute / 60.0
        if (
            start_local.date() != end_local.date()
            or start_hour < location.working_hour_from
            or end_hour > location.working_hour_to
        ):
            raise ValidationError(
                self.env._(
                    'The period must be within the location working hours and cannot cross a local calendar day.'
                )
            )

    def _get_available_resources(self):
        """Return resources matching the criteria without booking conflicts.

        :return: Available active resources in the selected location.
        :rtype: OSCoworkingResource
        """
        self.ensure_one()
        self._validate_search_period()
        resources = self.env['os.coworking.resource'].search(
            [
                ('location_id', '=', self.location_id.id),
                ('resource_type', '=', self.resource_type),
                ('capacity', '>=', self.capacity),
                ('active', '=', True),
                ('state', '=', 'available'),
            ]
        )
        conflicting_bookings = self.env['os.coworking.booking'].search(
            [
                ('resource_id', 'in', resources.ids),
                ('state', '=', 'confirmed'),
                ('start_datetime', '<', self.end_datetime),
                ('end_datetime', '>', self.start_datetime),
            ]
        )
        return resources - conflicting_bookings.resource_id

    def action_search_resources(self):
        """Search for available resources and refresh the wizard form.

        :return: Wizard action showing the current search results.
        :rtype: dict
        """
        self.ensure_one()
        resources = self._get_available_resources()
        self.write(
            {
                'available_resource_ids': [Command.set(resources.ids)],
                'selected_resource_id': False,
            }
        )
        action = self.env['ir.actions.actions']._for_xml_id(
            'OdooSchool_coworking_management.os_coworking_action_availability_wizard'
        )
        action['res_id'] = self.id
        return action

    def action_create_booking(self):
        """Open an unsaved draft booking prefilled from the selected result.

        The membership remains empty and must be selected before the booking
        is saved because the wizard client is optional.

        :return: Booking form action populated with wizard values.
        :rtype: dict
        :raises UserError: If no search result is selected.
        :raises ValidationError: If the selected resource is no longer free.
        """
        self.ensure_one()
        if not self.selected_resource_id:
            raise UserError(self.env._('Please select an available resource.'))

        available_resources = self._get_available_resources()
        if self.selected_resource_id not in available_resources:
            raise ValidationError(
                self.env._('The selected resource is no longer available for this period.')
            )

        context = {
            'default_resource_id': self.selected_resource_id.id,
            'default_start_datetime': fields.Datetime.to_string(self.start_datetime),
            'default_end_datetime': fields.Datetime.to_string(self.end_datetime),
        }
        if self.partner_id:
            context['default_partner_id'] = self.partner_id.id

        action = self.env['ir.actions.actions']._for_xml_id(
            'OdooSchool_coworking_management.os_coworking_action_booking'
        )
        action.update(
            {
                'name': self.env._('New Booking'),
                'view_mode': 'form',
                'views': [
                    (
                        self.env.ref(
                            'OdooSchool_coworking_management.os_coworking_view_booking_form'
                        ).id,
                        'form',
                    )
                ],
                'res_id': False,
                'target': 'current',
                'context': context,
            }
        )
        return action
