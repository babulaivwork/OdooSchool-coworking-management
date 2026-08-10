from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OSCoworkingResource(models.Model):
    """Represent a coworking resource available for booking."""

    _name = 'os.coworking.resource'
    _description = 'Coworking Resource'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(
        string='Code',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env._('New'),
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help=(
            'Archive the resource when it should no longer appear in regular '
            'lists. This is separate from its operational state.'
        ),
    )
    location_id = fields.Many2one(
        comodel_name='os.coworking.location',
        string='Location',
        required=True,
        ondelete='restrict',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='location_id.company_id',
        store=True,
        readonly=True,
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
        string='Capacity',
        required=True,
        default=1,
    )
    hourly_rate = fields.Monetary(
        string='Hourly Rate',
        required=True,
        default=0.0,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('maintenance', 'Maintenance'),
            ('inactive', 'Inactive'),
        ],
        string='State',
        required=True,
        default='available',
        help=(
            'Controls whether the resource can be booked. Maintenance and '
            'inactive resources cannot be confirmed in bookings.'
        ),
    )
    image_1920 = fields.Image(string='Image')
    description = fields.Text(string='Description', translate=True)

    _code_location_unique = models.Constraint(
        'UNIQUE(location_id, code)',
        'The resource code must be unique within the location.',
    )
    _capacity_positive = models.Constraint(
        'CHECK(capacity > 0)',
        'The resource capacity must be greater than zero.',
    )
    _hourly_rate_non_negative = models.Constraint(
        'CHECK(hourly_rate >= 0)',
        'The hourly rate cannot be negative.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create resources and assign their sequence-generated codes.

        :param list[dict] vals_list: Values for the resources to create.
        :return: Newly created coworking resources.
        :rtype: OSCoworkingResource
        """
        for vals in vals_list:
            if not vals.get('code') or vals['code'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.resource')
                if not sequence:
                    raise ValidationError(self.env._('The coworking resource sequence is not configured.'))
                vals['code'] = sequence
        return super().create(vals_list)
