from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OSCoworkingLocation(models.Model):
    """Represent a physical coworking location."""

    _name = 'os.coworking.location'
    _description = 'Coworking Location'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(
        string='Code',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env._('New'),
    )
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    manager_id = fields.Many2one(
        comodel_name='res.users',
        string='Manager',
    )
    staff_user_ids = fields.Many2many(
        comodel_name='res.users',
        string='Staff',
    )
    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street 2')
    city = fields.Char(string='City')
    zip = fields.Char(string='ZIP')
    working_hour_from = fields.Float(
        string='Opening Hour',
        required=True,
        default=8.0,
    )
    working_hour_to = fields.Float(
        string='Closing Hour',
        required=True,
        default=18.0,
    )
    image_1920 = fields.Image(string='Image')
    description = fields.Text(string='Description', translate=True)
    resource_ids = fields.One2many(
        comodel_name='os.coworking.resource',
        inverse_name='location_id',
        string='Resources',
    )
    resource_count = fields.Integer(
        string='Resource Count',
        compute='_compute_resource_count',
    )
    booking_ids = fields.One2many(
        comodel_name='os.coworking.booking',
        inverse_name='location_id',
        string='Bookings',
    )
    booking_count = fields.Integer(
        string='Booking Count',
        compute='_compute_booking_count',
    )

    _code_company_unique = models.Constraint(
        'UNIQUE(company_id, code)',
        'The location code must be unique within the company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create locations and assign their sequence-generated codes.

        :param list[dict] vals_list: Values for the locations to create.
        :return: Newly created coworking locations.
        :rtype: OSCoworkingLocation
        """
        for vals in vals_list:
            if not vals.get('code') or vals['code'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.location')
                if not sequence:
                    raise ValidationError(self.env._('The coworking location sequence is not configured.'))
                vals['code'] = sequence
        return super().create(vals_list)

    @api.constrains('working_hour_from', 'working_hour_to')
    def _check_working_hours(self):
        """Validate that opening and closing hours form a valid daily range.

        :raises ValidationError: If the hours are outside the day or the
            closing hour is not later than the opening hour.
        """
        for location in self:
            if not 0.0 <= location.working_hour_from < location.working_hour_to <= 24.0:
                raise ValidationError(
                    self.env._(
                        'Working hours must be within 00:00 and 24:00, and the closing hour must be later than the opening hour.'
                    )
                )

    @api.depends('resource_ids', 'resource_ids.active')
    def _compute_resource_count(self):
        """Compute the number of active resources for each location."""
        for location in self:
            location.resource_count = len(location.resource_ids.filtered('active'))

    @api.depends('booking_ids')
    def _compute_booking_count(self):
        """Compute the number of accessible bookings for each location."""
        count_by_location = dict(
            self.env['os.coworking.booking']._read_group(
                domain=[('location_id', 'in', self.ids)],
                groupby=['location_id'],
                aggregates=['__count'],
            )
        )
        for location in self:
            location.booking_count = count_by_location.get(location, 0)

    def action_view_resources(self):
        """Open the resources that belong to the selected location.

        :return: Window action filtered by the current location.
        :rtype: dict
        """
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'OdooSchool_coworking_management.os_coworking_action_resource'
        )
        action['domain'] = [('location_id', '=', self.id)]
        action['context'] = {'default_location_id': self.id}
        return action

    def action_view_bookings(self):
        """Open the bookings that belong to the selected location.

        :return: Booking action filtered by the current location.
        :rtype: dict
        """
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'OdooSchool_coworking_management.os_coworking_action_booking'
        )
        action['domain'] = [('location_id', '=', self.id)]
        return action
