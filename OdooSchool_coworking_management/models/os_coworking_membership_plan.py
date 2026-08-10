from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_is_zero


class OSCoworkingMembershipPlan(models.Model):
    """Represent reusable terms for a coworking membership."""

    _name = 'os.coworking.membership.plan'
    _description = 'Coworking Membership Plan'

    name = fields.Char(string='Name', required=True, translate=True)
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
    product_ids = fields.One2many(
        comodel_name='product.template',
        inverse_name='coworking_plan_id',
        string='Coworking Products',
        context={'active_test': False},
    )
    product_id = fields.Many2one(
        comodel_name='product.template',
        string='Coworking Product',
        compute='_compute_product_reference',
    )
    price = fields.Monetary(
        string='Reference Price',
        compute='_compute_product_reference',
        currency_field='currency_id',
        help='Read-only reference to the sales price of the linked coworking product.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_product_reference',
    )
    all_locations = fields.Boolean(string='All Locations', default=True)
    allow_auto_renew = fields.Boolean(
        string='Allow Automatic Renewal',
        default=False,
        help=(
            'Allows memberships using this plan to create a draft renewal '
            'after expiry.'
        ),
    )
    description = fields.Text(string='Description', translate=True)

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'The membership plan code must be unique.',
    )
    _duration_days_positive = models.Constraint(
        'CHECK(duration_days > 0)',
        'The membership plan duration must be greater than zero.',
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

    @api.depends(
        'product_ids',
        'product_ids.active',
        'product_ids.list_price',
        'product_ids.currency_id',
    )
    def _compute_product_reference(self):
        """Show the linked product and its current price as reference data."""
        for plan in self:
            product = plan.product_ids[:1]
            plan.product_id = product
            plan.price = product.list_price if product else 0.0
            plan.currency_id = product.currency_id if product else False

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

    @api.onchange('usage_type')
    def _onchange_usage_type(self):
        """Clear limits that do not apply to the selected usage type."""
        for plan in self:
            if plan.usage_type != 'hours':
                plan.included_hours = 0.0
            if plan.usage_type != 'visits':
                plan.included_visits = 0
