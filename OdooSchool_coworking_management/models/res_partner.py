from odoo import fields, models


class ResPartner(models.Model):
    """Extend contacts with coworking client information."""

    _inherit = 'res.partner'

    is_coworking_client = fields.Boolean(
        string='Coworking Client',
        default=False,
    )
