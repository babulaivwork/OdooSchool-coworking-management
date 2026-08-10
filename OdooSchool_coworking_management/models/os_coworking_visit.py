from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


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
        readonly=True,
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
    _booking_unique = models.Constraint(
        'UNIQUE(booking_id)',
        'A visit already exists for this booking.',
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

    @api.constrains('partner_id', 'state')
    def _check_no_other_open_visit(self):
        """Ensure that a client has no other checked-in visit.

        :raises ValidationError: If another open visit exists for the client.
        """
        for visit in self.filtered(lambda item: item.state == 'checked_in'):
            other_open_visit = self.search(
                [
                    ('id', '!=', visit.id),
                    ('partner_id', '=', visit.partner_id.id),
                    ('state', '=', 'checked_in'),
                ],
                limit=1,
            )
            if other_open_visit:
                raise ValidationError(
                    self.env._('The client already has an open visit.')
                )

    def action_check_out(self):
        """Check out an open visit and complete its confirmed booking.

        :return: ``True`` after the visit and booking are completed.
        :rtype: bool
        :raises UserError: If the visit is not open or its booking is no
            longer confirmed.
        """
        self.ensure_one()
        if self.state != 'checked_in':
            raise UserError(self.env._('Only a checked-in visit can be checked out.'))
        if self.booking_id.state != 'confirmed':
            raise UserError(
                self.env._('Check-out is allowed only for a confirmed booking.')
            )

        self.write(
            {
                'check_out': fields.Datetime.now(),
                'state': 'checked_out',
            }
        )
        self.booking_id.action_done()
        return True

    def action_cancel(self):
        """Cancel an open visit together with its related booking.

        The booking cancellation returns any reserved membership limit. The
        operation is atomic, so a failure rolls back both state changes.

        :return: ``True`` after the visit and booking are cancelled.
        :rtype: bool
        :raises UserError: If the visit is not checked in or its booking is
            no longer confirmed.
        """
        self.ensure_one()
        if self.state != 'checked_in':
            raise UserError(
                self.env._('Only a checked-in visit can be cancelled.')
            )
        if self.booking_id.state != 'confirmed':
            raise UserError(
                self.env._(
                    'A visit can be cancelled only while its booking is confirmed.'
                )
            )

        self.write(
            {
                'check_out': False,
                'state': 'cancelled',
            }
        )
        self.booking_id.action_cancel()
        self.booking_id.message_post(
            body=self.env._(
                'Visit %(visit)s was cancelled after check-in. '
                'Any reserved membership limit was returned.',
                visit=self.display_name,
            )
        )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """Create visits and assign their sequence-generated numbers.

        :param list[dict] vals_list: Values for the visits to create.
        :return: Newly created coworking visits.
        :rtype: OSCoworkingVisit
        """
        booking_ids = [vals.get('booking_id') for vals in vals_list if vals.get('booking_id')]
        bookings_by_id = {
            booking.id: booking
            for booking in self.env['os.coworking.booking'].browse(booking_ids).exists()
        }
        for vals in vals_list:
            booking = bookings_by_id.get(vals.get('booking_id'))
            if booking and booking.state != 'confirmed':
                raise ValidationError(
                    self.env._('A visit can be created only from a confirmed booking.')
                )
            if vals.get('state', 'checked_in') != 'checked_in' or vals.get('check_out'):
                raise ValidationError(
                    self.env._('A new visit must start in the Checked In state.')
                )
            if not vals.get('name') or vals['name'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.visit')
                if not sequence:
                    raise ValidationError(
                        self.env._('The coworking visit sequence is not configured.')
                    )
                vals['name'] = sequence
        visits = super().create(vals_list)
        visits._check_no_other_open_visit()
        return visits
