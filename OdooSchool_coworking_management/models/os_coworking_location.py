from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OSCoworkingLocation(models.Model):
    """Represent a physical coworking location."""

    _name = 'os.coworking.location'
    _description = 'Coworking Location'

    name = fields.Char(string='Name', required=True)
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
    description = fields.Text(string='Description')

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
