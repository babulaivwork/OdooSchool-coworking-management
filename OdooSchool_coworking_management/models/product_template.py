from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    """Extend products with coworking service information."""

    _inherit = 'product.template'

    is_coworking_service = fields.Boolean(
        string='Coworking Service',
        default=False,
    )
    coworking_service_type = fields.Selection(
        selection=[
            ('membership', 'Membership'),
            ('additional_service', 'Additional Service'),
        ],
        string='Coworking Service Type',
    )
    coworking_plan_id = fields.Many2one(
        comodel_name='os.coworking.membership.plan',
        string='Coworking Membership Plan',
        copy=False,
        ondelete='restrict',
    )

    _coworking_plan_unique = models.Constraint(
        'UNIQUE(coworking_plan_id)',
        'A coworking membership plan can be linked to only one product.',
    )

    @api.constrains(
        'is_coworking_service',
        'coworking_service_type',
        'coworking_plan_id',
        'type',
        'list_price',
    )
    def _check_coworking_service_configuration(self):
        """Ensure coworking product fields describe a consistent service.

        :raises ValidationError: If the product type, service type, plan, or
            membership price is incompatible with its coworking settings.
        """
        for product in self:
            if not product.is_coworking_service:
                if product.coworking_service_type or product.coworking_plan_id:
                    raise ValidationError(
                        self.env._('A non-coworking product cannot define a coworking service type or membership plan.')
                    )
                continue
            if product.type != 'service':
                raise ValidationError(self.env._('A coworking product must use the Service product type.'))
            if not product.coworking_service_type:
                raise ValidationError(self.env._('A coworking service type is required.'))
            if product.coworking_service_type == 'membership':
                if not product.coworking_plan_id:
                    raise ValidationError(self.env._('A coworking membership service requires a membership plan.'))
                if product.list_price < 0.0:
                    raise ValidationError(self.env._('A coworking membership price cannot be negative.'))
            elif product.coworking_plan_id:
                raise ValidationError(self.env._('Only a coworking membership service can define a membership plan.'))

    @api.onchange('is_coworking_service', 'coworking_service_type')
    def _onchange_coworking_service_configuration(self):
        """Clear coworking values that no longer apply to the product."""
        for product in self:
            if not product.is_coworking_service:
                product.coworking_service_type = False
                product.coworking_plan_id = False
            elif product.coworking_service_type != 'membership':
                product.coworking_plan_id = False
