from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OSCoworkingBooking(models.Model):
    """Represent an hourly booking of one coworking resource."""

    _name = 'os.coworking.booking'
    _description = 'Coworking Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_datetime desc, id desc'

    name = fields.Char(
        string='Number',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: self.env._('New'),
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Client',
        required=True,
        ondelete='restrict',
        domain=[('is_coworking_client', '=', True)],
        tracking=True,
    )
    resource_id = fields.Many2one(
        comodel_name='os.coworking.resource',
        string='Resource',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    location_id = fields.Many2one(
        comodel_name='os.coworking.location',
        string='Location',
        related='resource_id.location_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='resource_id.company_id',
        store=True,
        readonly=True,
    )
    start_datetime = fields.Datetime(
        string='Start',
        required=True,
        tracking=True,
    )
    end_datetime = fields.Datetime(
        string='End',
        required=True,
        tracking=True,
    )
    duration_hours = fields.Float(
        string='Duration (Hours)',
        compute='_compute_duration_hours',
        store=True,
    )

    _booking_interval_valid = models.Constraint(
        'CHECK(end_datetime > start_datetime)',
        'The booking end time must be later than the start time.',
    )

    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration_hours(self):
        """Compute the booking duration in hours from its time interval."""
        for booking in self:
            if booking.start_datetime and booking.end_datetime:
                duration = booking.end_datetime - booking.start_datetime
                booking.duration_hours = duration.total_seconds() / 3600.0
            else:
                booking.duration_hours = 0.0

    @api.constrains('start_datetime', 'end_datetime')
    def _check_hourly_interval(self):
        """Ensure that booking boundaries follow the full-hour grid.

        :raises ValidationError: If a boundary contains minutes or seconds.
        """
        for booking in self:
            boundaries = (booking.start_datetime, booking.end_datetime)
            if any(
                value and (value.minute or value.second or value.microsecond)
                for value in boundaries
            ):
                raise ValidationError(
                    self.env._('The booking start and end times must be set to full hours.')
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Create bookings and assign their sequence-generated numbers.

        :param list[dict] vals_list: Values for the bookings to create.
        :return: Newly created coworking bookings.
        :rtype: OSCoworkingBooking
        """
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.booking')
                if not sequence:
                    raise ValidationError(self.env._('The coworking booking sequence is not configured.'))
                vals['name'] = sequence
        return super().create(vals_list)
