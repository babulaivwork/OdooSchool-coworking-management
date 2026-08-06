from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OSCoworkingVisit(models.Model):
    """Represent a client's actual presence based on a coworking booking."""

    _name = 'os.coworking.visit'
    _description = 'Coworking Visit'
    _order = 'check_in desc, id desc'

    name = fields.Char(
        string='Number',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env._('New'),
    )
    booking_id = fields.Many2one(
        comodel_name='os.coworking.booking',
        string='Booking',
        required=True,
        ondelete='restrict',
        domain=[('state', '=', 'confirmed')],
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Client',
        related='booking_id.partner_id',
        store=True,
        readonly=True,
    )
    location_id = fields.Many2one(
        comodel_name='os.coworking.location',
        string='Location',
        related='booking_id.location_id',
        store=True,
        readonly=True,
    )
    resource_id = fields.Many2one(
        comodel_name='os.coworking.resource',
        string='Resource',
        related='booking_id.resource_id',
        store=True,
        readonly=True,
    )
    membership_id = fields.Many2one(
        comodel_name='os.coworking.membership',
        string='Membership',
        related='booking_id.membership_id',
        store=True,
        readonly=True,
    )
    check_in = fields.Datetime(
        string='Check-In',
        required=True,
        default=fields.Datetime.now,
    )
    check_out = fields.Datetime(string='Check-Out')
    duration_hours = fields.Float(
        string='Duration (Hours)',
        compute='_compute_duration_hours',
        store=True,
    )
    state = fields.Selection(
        selection=[
            ('checked_in', 'Checked In'),
            ('checked_out', 'Checked Out'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='checked_in',
        copy=False,
    )
    registered_by_id = fields.Many2one(
        comodel_name='res.users',
        string='Registered By',
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='booking_id.company_id',
        store=True,
        readonly=True,
    )
    note = fields.Text(string='Notes')

    _check_out_after_check_in = models.Constraint(
        'CHECK(check_out IS NULL OR check_out >= check_in)',
        'The check-out time cannot be earlier than the check-in time.',
    )

    @api.depends('check_in', 'check_out')
    def _compute_duration_hours(self):
        """Compute the completed visit duration in hours."""
        for visit in self:
            if visit.check_in and visit.check_out:
                duration = visit.check_out - visit.check_in
                visit.duration_hours = duration.total_seconds() / 3600.0
            else:
                visit.duration_hours = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        """Create visits and assign their sequence-generated numbers.

        :param list[dict] vals_list: Values for the visits to create.
        :return: Newly created coworking visits.
        :rtype: OSCoworkingVisit
        """
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.visit')
                if not sequence:
                    raise ValidationError(
                        self.env._('The coworking visit sequence is not configured.')
                    )
                vals['name'] = sequence
        return super().create(vals_list)
