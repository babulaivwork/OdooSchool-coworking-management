from odoo import api, fields, models


class ResPartner(models.Model):
    """Extend contacts with coworking client information."""

    _inherit = 'res.partner'

    is_coworking_client = fields.Boolean(
        string='Coworking Client',
        default=False,
    )
    coworking_membership_ids = fields.One2many(
        comodel_name='os.coworking.membership',
        inverse_name='partner_id',
        string='Coworking Memberships',
    )
    coworking_membership_count = fields.Integer(
        string='Memberships',
        compute='_compute_coworking_membership_count',
    )
    coworking_booking_ids = fields.One2many(
        comodel_name='os.coworking.booking',
        inverse_name='partner_id',
        string='Coworking Bookings',
    )
    coworking_booking_count = fields.Integer(
        string='Bookings',
        compute='_compute_coworking_booking_count',
    )

    @api.depends('coworking_membership_ids')
    def _compute_coworking_membership_count(self):
        """Compute the number of accessible memberships for each contact."""
        count_by_partner = dict(
            self.env['os.coworking.membership']._read_group(
                domain=[('partner_id', 'in', self.ids)],
                groupby=['partner_id'],
                aggregates=['__count'],
            )
        )
        for partner in self:
            partner.coworking_membership_count = count_by_partner.get(partner, 0)

    @api.depends('coworking_booking_ids')
    def _compute_coworking_booking_count(self):
        """Compute the number of accessible bookings for each contact."""
        count_by_partner = dict(
            self.env['os.coworking.booking']._read_group(
                domain=[('partner_id', 'in', self.ids)],
                groupby=['partner_id'],
                aggregates=['__count'],
            )
        )
        for partner in self:
            partner.coworking_booking_count = count_by_partner.get(partner, 0)

    def action_view_coworking_memberships(self):
        """Open the coworking memberships of the selected contact.

        :return: Membership action filtered by the current contact.
        :rtype: dict
        """
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'OdooSchool_coworking_management.os_coworking_action_membership'
        )
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action

    def action_view_coworking_bookings(self):
        """Open the coworking bookings of the selected contact.

        :return: Booking action filtered by the current contact.
        :rtype: dict
        """
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'OdooSchool_coworking_management.os_coworking_action_booking'
        )
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action
