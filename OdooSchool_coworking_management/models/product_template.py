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
            ('one_time_booking', 'One-Time Booking'),
            ('additional_service', 'Additional Service'),
        ],
        string='Coworking Service Type',
    )
