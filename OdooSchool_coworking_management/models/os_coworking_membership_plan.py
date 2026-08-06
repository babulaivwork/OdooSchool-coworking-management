from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_is_zero


class OSCoworkingMembershipPlan(models.Model):
    """Represent reusable terms for a coworking membership."""

    _name = 'os.coworking.membership.plan'
    _description = 'Coworking Membership Plan'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(
        string='Code',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env._('New'),
    )
    active = fields.Boolean(string='Active', default=True)
    usage_type = fields.Selection(
        selection=[
            ('unlimited', 'Unlimited'),
            ('hours', 'Hours'),
            ('visits', 'Visits'),
        ],
        string='Usage Type',
        required=True,
        default='unlimited',
    )
    duration_days = fields.Integer(
        string='Duration (Days)',
        required=True,
        default=30,
    )
    included_hours = fields.Float(string='Included Hours', default=0.0)
    included_visits = fields.Integer(string='Included Visits', default=0)
    price = fields.Monetary(
        string='Price',
        required=True,
        default=0.0,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        readonly=True,
        default=lambda self: self.env.company.currency_id,
    )
    all_locations = fields.Boolean(string='All Locations', default=True)
    allow_auto_renew = fields.Boolean(string='Allow Automatic Renewal', default=False)
    description = fields.Text(string='Description')

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'The membership plan code must be unique.',
    )
    _duration_days_positive = models.Constraint(
        'CHECK(duration_days > 0)',
        'The membership plan duration must be greater than zero.',
    )
    _price_non_negative = models.Constraint(
        'CHECK(price >= 0)',
        'The membership plan price cannot be negative.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create membership plans and assign sequence-generated codes.

        :param list[dict] vals_list: Values for the membership plans to create.
        :return: Newly created coworking membership plans.
        :rtype: OSCoworkingMembershipPlan
        """
        for vals in vals_list:
            if not vals.get('code') or vals['code'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.membership.plan')
                if not sequence:
                    raise ValidationError(self.env._('The coworking membership plan sequence is not configured.'))
                vals['code'] = sequence
        return super().create(vals_list)

    @api.constrains('usage_type', 'included_hours', 'included_visits')
    def _check_usage_limits(self):
        """Validate that usage limits match the selected plan type.

        :raises ValidationError: If required limits are missing or incompatible
            limits are set for the selected usage type.
        """
        for plan in self:
            if plan.usage_type == 'unlimited' and (
                not float_is_zero(plan.included_hours, precision_digits=2) or plan.included_visits != 0
            ):
                raise ValidationError(self.env._('Unlimited plans must not define included hours or visits.'))
            if plan.usage_type == 'hours' and (plan.included_hours <= 0.0 or plan.included_visits != 0):
                raise ValidationError(
                    self.env._('Hourly plans require a positive number of included hours and no included visits.')
                )
            if plan.usage_type == 'visits' and (
                plan.included_visits <= 0 or not float_is_zero(plan.included_hours, precision_digits=2)
            ):
                raise ValidationError(
                    self.env._('Visit-based plans require a positive number of included visits and no included hours.')
                )
