from odoo import fields, models


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
