from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


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
    membership_id = fields.Many2one(
        comodel_name='os.coworking.membership',
        string='Membership',
        required=True,
        ondelete='restrict',
        tracking=True,
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
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
    )
    reserved_hours = fields.Float(
        string='Reserved Hours',
        readonly=True,
        copy=False,
        default=0.0,
        help=(
            'Reserved from the membership when the booking is confirmed and '
            'returned when it is cancelled before check-in.'
        ),
    )
    reserved_visits = fields.Integer(
        string='Reserved Visits',
        readonly=True,
        copy=False,
        default=0,
        help=(
            'Reserved from the membership when the booking is confirmed and '
            'returned when it is cancelled before check-in.'
        ),
    )
    visit_ids = fields.One2many(
        comodel_name='os.coworking.visit',
        inverse_name='booking_id',
        string='Visits',
    )
    visit_count = fields.Integer(
        string='Visits',
        compute='_compute_visit_count',
    )
    note = fields.Text(string='Notes')

    _booking_interval_valid = models.Constraint(
        'CHECK(end_datetime > start_datetime)',
        'The booking end time must be later than the start time.',
    )
    _reserved_hours_non_negative = models.Constraint(
        'CHECK(reserved_hours >= 0)',
        'The reserved hours cannot be negative.',
    )
    _reserved_visits_non_negative = models.Constraint(
        'CHECK(reserved_visits >= 0)',
        'The reserved visits cannot be negative.',
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

    @api.depends('visit_ids')
    def _compute_visit_count(self):
        """Compute the number of accessible visits for each booking."""
        count_by_booking = dict(
            self.env['os.coworking.visit']._read_group(
                domain=[('booking_id', 'in', self.ids)],
                groupby=['booking_id'],
                aggregates=['__count'],
            )
        )
        for booking in self:
            booking.visit_count = count_by_booking.get(booking, 0)

    @api.constrains('resource_id', 'start_datetime', 'end_datetime')
    def _check_hourly_interval(self):
        """Ensure that booking boundaries follow the full-hour grid.

        :raises ValidationError: If a boundary contains minutes or seconds.
        """
        for booking in self:
            for value in (booking.start_datetime, booking.end_datetime):
                if not value:
                    continue
                local_value = booking._to_local_datetime(value)
                if local_value.minute or local_value.second or local_value.microsecond:
                    raise ValidationError(self.env._('The booking start and end times must be set to full hours.'))

    @api.constrains(
        'partner_id',
        'resource_id',
        'membership_id',
        'start_datetime',
        'end_datetime',
        'state',
    )
    def _check_confirmed_booking(self):
        """Validate resource availability and schedule for confirmed bookings."""
        for booking in self.filtered(lambda item: item.state == 'confirmed'):
            booking._validate_confirmation()

    def _validate_confirmation(self):
        """Run all checks required before confirming a booking."""
        self.ensure_one()
        self._validate_membership_eligibility()
        self._validate_resource_availability()
        self._validate_working_hours()
        self._validate_no_overlap()

    def _get_timezone_name(self):
        """Return the common timezone used for coworking operations.

        :return: Company timezone, with user timezone and UTC as fallbacks.
        :rtype: str
        """
        self.ensure_one()
        return self.company_id.partner_id.tz or self.env.user.tz or 'UTC'

    def _to_local_datetime(self, value):
        """Convert a stored UTC datetime to the coworking timezone.

        :param datetime value: Naive UTC datetime stored by Odoo.
        :return: Timezone-aware local datetime.
        :rtype: datetime
        """
        self.ensure_one()
        # Odoo stores datetimes in UTC, while location working hours represent
        # the shared local business timezone selected for coworking operations.
        return fields.Datetime.context_timestamp(
            self.with_context(tz=self._get_timezone_name()),
            value,
        )

    def _validate_resource_availability(self):
        """Ensure that the selected resource can accept a booking.

        :raises ValidationError: If the location is archived or the resource
            is archived, inactive, or under maintenance.
        """
        self.ensure_one()
        if not self.location_id.active:
            raise ValidationError(self.env._('Only resources in active coworking locations can be booked.'))
        if not self.resource_id.active or self.resource_id.state != 'available':
            raise ValidationError(self.env._('Only active and available resources can be booked.'))

    def _validate_membership_eligibility(self):
        """Ensure the membership can cover the booking.

        :raises ValidationError: If the membership has a different owner, is
            inactive, is outside its validity dates, or excludes the location.
        """
        self.ensure_one()
        membership = self.membership_id
        if membership.partner_id != self.partner_id:
            raise ValidationError(self.env._('The booking client must be the owner of the selected membership.'))
        if membership.state != 'active':
            raise ValidationError(self.env._('Only an active membership can be used for booking.'))

        start_date = self._to_local_datetime(self.start_datetime).date()
        end_date = self._to_local_datetime(self.end_datetime).date()
        if start_date < membership.date_start or end_date > membership.date_end:
            raise ValidationError(self.env._('The booking period must be within the membership validity dates.'))
        if not membership.plan_id.all_locations and membership.location_id != self.location_id:
            raise ValidationError(self.env._('The membership is not valid at the selected location.'))

    def _reserve_membership_limit(self):
        """Deduct and record the membership limit required by the booking.

        :return: Values of the technical reservation fields.
        :rtype: dict
        :raises ValidationError: If the membership limit is insufficient.
        """
        self.ensure_one()
        membership = self.membership_id
        usage_type = membership.plan_id.usage_type
        reservation_values = {
            'reserved_hours': 0.0,
            'reserved_visits': 0,
        }

        # Limits are reserved at confirmation rather than check-out so later
        # bookings cannot consume hours or visits that are already committed.
        if usage_type == 'hours':
            if (
                float_compare(
                    membership.remaining_hours,
                    self.duration_hours,
                    precision_digits=2,
                )
                < 0
            ):
                raise ValidationError(self.env._('The membership does not have enough remaining hours.'))
            membership.remaining_hours -= self.duration_hours
            reservation_values['reserved_hours'] = self.duration_hours
        elif usage_type == 'visits':
            if membership.remaining_visits < 1:
                raise ValidationError(self.env._('The membership does not have enough remaining visits.'))
            membership.remaining_visits -= 1
            reservation_values['reserved_visits'] = 1

        return reservation_values

    def _restore_membership_limit(self):
        """Return a cancelled booking reservation to its membership."""
        self.ensure_one()
        membership = self.membership_id
        membership.write(
            {
                'remaining_hours': membership.remaining_hours + self.reserved_hours,
                'remaining_visits': membership.remaining_visits + self.reserved_visits,
            }
        )
        self.write(
            {
                # Clearing these technical values prevents a repeated
                # cancellation path from returning the same limit twice.
                'reserved_hours': 0.0,
                'reserved_visits': 0,
            }
        )

    def _validate_working_hours(self):
        """Ensure the booking fits one local working day of its location.

        :raises ValidationError: If the interval crosses a local date or falls
            outside the location working hours.
        """
        self.ensure_one()
        start_local = self._to_local_datetime(self.start_datetime)
        end_local = self._to_local_datetime(self.end_datetime)
        start_hour = start_local.hour + start_local.minute / 60.0
        end_hour = end_local.hour + end_local.minute / 60.0
        location = self.location_id

        if (
            start_local.date() != end_local.date()
            or start_hour < location.working_hour_from
            or end_hour > location.working_hour_to
        ):
            raise ValidationError(
                self.env._(
                    'The booking must be within the location working hours and cannot cross a local calendar day.'
                )
            )

    def _validate_no_overlap(self):
        """Ensure the resource has no overlapping confirmed booking.

        Adjacent bookings are allowed because strict inequalities are used.

        :raises ValidationError: If another confirmed booking overlaps.
        """
        self.ensure_one()
        # Strict boundary comparisons allow adjacent intervals: an existing
        # booking may end at the exact moment when the next booking starts.
        overlapping_booking = self.search(
            [
                ('id', '!=', self.id),
                ('resource_id', '=', self.resource_id.id),
                ('state', '=', 'confirmed'),
                ('start_datetime', '<', self.end_datetime),
                ('end_datetime', '>', self.start_datetime),
            ],
            limit=1,
        )
        if overlapping_booking:
            raise ValidationError(self.env._('The resource already has a confirmed booking during this period.'))

    def action_confirm(self):
        """Confirm draft bookings after validating operational constraints.

        :return: ``True`` after all selected bookings are confirmed.
        :rtype: bool
        :raises UserError: If a booking is not in draft state.
        """
        if any(booking.state != 'draft' for booking in self):
            raise UserError(self.env._('Only draft bookings can be confirmed.'))
        for booking in self:
            booking._validate_confirmation()
            reservation_values = booking._reserve_membership_limit()
            booking.write(
                {
                    **reservation_values,
                    'state': 'confirmed',
                }
            )
            booking.message_post(body=self.env._('Booking confirmed.'))
        return True

    def action_done(self):
        """Complete confirmed bookings only after their visit is checked out.

        :return: ``True`` after all selected bookings are completed.
        :rtype: bool
        :raises UserError: If a booking is not confirmed or does not have a
            checked-out visit.
        """
        if any(booking.state != 'confirmed' for booking in self):
            raise UserError(self.env._('Only confirmed bookings can be completed.'))
        if any(not booking.visit_ids.filtered(lambda visit: visit.state == 'checked_out') for booking in self):
            raise UserError(self.env._('A booking can be completed only after its visit is checked out.'))
        self.write({'state': 'done'})
        for booking in self:
            booking.message_post(body=self.env._('Booking completed.'))
        return True

    def action_check_in(self):
        """Create a checked-in visit for one confirmed booking.

        The booking intentionally remains confirmed until the visit is
        checked out.

        :return: ``True`` after the visit is created.
        :rtype: bool
        :raises UserError: If the booking is not confirmed or already has a
            visit.
        :raises ValidationError: If the membership, location, or resource is
            no longer eligible for check-in.
        """
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(self.env._('Check-in is allowed only for a confirmed booking.'))
        if self.visit_ids:
            raise UserError(self.env._('A visit already exists for this booking.'))

        # Operational data may change after confirmation, so check the
        # membership, resource, and location again immediately before entry.
        self._validate_membership_eligibility()
        self._validate_resource_availability()

        visit = self.env['os.coworking.visit'].create(
            {
                'booking_id': self.id,
                'check_in': fields.Datetime.now(),
                'registered_by_id': self.env.user.id,
            }
        )
        self.message_post(
            body=self.env._(
                'Visit %(visit)s was created at check-in.',
                visit=visit.display_name,
            )
        )
        return True

    def action_view_visits(self):
        """Open visits linked to the selected booking.

        :return: Visit action filtered by the current booking.
        :rtype: dict
        """
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('OdooSchool_coworking_management.os_coworking_action_visit')
        action['domain'] = [('booking_id', '=', self.id)]
        return action

    def action_cancel(self):
        """Cancel confirmed bookings and return their reserved limits.

        A cancelled visit does not block this action because visit cancellation
        coordinates both lifecycle changes in one transaction.

        :return: ``True`` after all selected bookings are cancelled.
        :rtype: bool
        :raises UserError: If a booking is not confirmed or has a visit that
            has not been cancelled.
        """
        if any(booking.state != 'confirmed' for booking in self):
            raise UserError(self.env._('Only confirmed bookings can be cancelled.'))
        if any(booking.visit_ids.filtered(lambda visit: visit.state != 'cancelled') for booking in self):
            raise UserError(
                self.env._('A booking cannot be cancelled after check-in. Check out or cancel the related visit first.')
            )
        for booking in self:
            booking._restore_membership_limit()
            booking.state = 'cancelled'
            booking.message_post(body=self.env._('Booking cancelled.'))
        return True

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
