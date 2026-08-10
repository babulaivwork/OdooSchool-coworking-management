from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class OSCoworkingMembership(models.Model):
    """Represent a personal coworking membership for a client."""

    _name = 'os.coworking.membership'
    _description = 'Coworking Membership'
    _inherit = ['mail.thread', 'mail.activity.mixin']

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
    plan_id = fields.Many2one(
        comodel_name='os.coworking.membership.plan',
        string='Membership Plan',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    location_id = fields.Many2one(
        comodel_name='os.coworking.location',
        string='Location',
        ondelete='restrict',
        help='Leave empty to allow the membership at all coworking locations.',
        tracking=True,
    )
    date_start = fields.Date(
        string='Start Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    date_end = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
    )
    remaining_hours = fields.Float(
        string='Remaining Hours',
        default=0.0,
    )
    remaining_visits = fields.Integer(
        string='Remaining Visits',
        default=0,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('frozen', 'Frozen'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
    )
    payment_status = fields.Selection(
        selection=[
            ('unpaid', 'Unpaid'),
            ('paid', 'Paid'),
        ],
        string='Payment Status',
        required=True,
        readonly=True,
        default='unpaid',
        copy=False,
        tracking=True,
    )
    payment_date = fields.Date(
        string='Payment Date',
        readonly=True,
        copy=False,
        tracking=True,
    )
    auto_renew = fields.Boolean(
        string='Automatic Renewal',
        default=False,
        tracking=True,
        help=(
            'Creates a draft renewal after expiry. The renewal is not '
            'activated automatically.'
        ),
    )
    freeze_date = fields.Date(
        string='Freeze Date',
        readonly=True,
        copy=False,
    )
    total_frozen_days = fields.Integer(
        string='Total Frozen Days',
        readonly=True,
        copy=False,
        default=0,
    )
    previous_membership_id = fields.Many2one(
        comodel_name='os.coworking.membership',
        string='Previous Membership',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    renewed_membership_id = fields.Many2one(
        comodel_name='os.coworking.membership',
        string='Renewed Membership',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
    note = fields.Text(string='Notes')

    _date_range_valid = models.Constraint(
        'CHECK(date_end >= date_start)',
        'The membership end date must be on or after the start date.',
    )
    _remaining_hours_non_negative = models.Constraint(
        'CHECK(remaining_hours >= 0)',
        'The remaining hours cannot be negative.',
    )
    _remaining_visits_non_negative = models.Constraint(
        'CHECK(remaining_visits >= 0)',
        'The remaining visits cannot be negative.',
    )

    @api.model
    def _calculate_end_date(self, date_start, duration_days):
        """Calculate an inclusive membership end date.

        :param date date_start: First valid day of the membership.
        :param int duration_days: Number of calendar days in the plan.
        :return: Inclusive final valid day of the membership.
        :rtype: date
        """
        return fields.Date.to_date(date_start) + relativedelta(days=duration_days - 1)

    @api.model_create_multi
    def create(self, vals_list):
        """Create memberships and assign their sequence-generated numbers.

        :param list[dict] vals_list: Values for the memberships to create.
        :return: Newly created coworking memberships.
        :rtype: OSCoworkingMembership
        """
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == self.env._('New'):
                sequence = self.env['ir.sequence'].next_by_code('os.coworking.membership')
                if not sequence:
                    raise ValidationError(self.env._('The coworking membership sequence is not configured.'))
                vals['name'] = sequence
            if not vals.get('date_start'):
                vals['date_start'] = fields.Date.context_today(self)
            if vals.get('plan_id') and not vals.get('date_end'):
                plan = self.env['os.coworking.membership.plan'].browse(vals['plan_id'])
                vals['date_end'] = self._calculate_end_date(vals['date_start'], plan.duration_days)
        return super().create(vals_list)

    @api.onchange('plan_id', 'date_start')
    def _onchange_plan_or_start_date(self):
        """Update the end date and renewal option from the selected plan."""
        for membership in self:
            if membership.plan_id and membership.date_start:
                membership.date_end = membership._calculate_end_date(
                    membership.date_start,
                    membership.plan_id.duration_days,
                )
            else:
                membership.date_end = False
            if membership.plan_id and not membership.plan_id.allow_auto_renew:
                membership.auto_renew = False

    @api.constrains('auto_renew', 'plan_id')
    def _check_auto_renew_allowed(self):
        """Ensure automatic renewal is enabled only by a supporting plan.

        :raises ValidationError: If renewal is enabled for an unsupported plan.
        """
        for membership in self:
            if membership.auto_renew and not membership.plan_id.allow_auto_renew:
                raise ValidationError(
                    self.env._('Automatic renewal is not allowed for the selected membership plan.')
                )

    def _get_coworking_product(self):
        """Return the product linked to the selected membership plan.

        Archived products remain valid for historical memberships and invoices.

        :return: Product that defines the membership invoice amount.
        :rtype: product.template
        :raises UserError: If the plan does not have a linked product.
        """
        self.ensure_one()
        product = self.env['product.template'].with_context(active_test=False).search(
            [('coworking_plan_id', '=', self.plan_id.id)],
            limit=1,
        )
        if not product:
            raise UserError(
                self.env._(
                    'Configure a coworking membership product for the selected '
                    'plan before confirming payment or printing the invoice.'
                )
            )
        return product

    def action_mark_as_paid(self):
        """Mark unpaid draft memberships as paid.

        The linked product is checked before payment because its sales price is
        the single source of the invoice amount.

        :return: ``True`` after all selected memberships are marked as paid.
        :rtype: bool
        :raises UserError: If a membership cannot be marked as paid.
        """
        payment_date = fields.Date.context_today(self)
        for membership in self:
            if membership.state != 'draft' or membership.payment_status != 'unpaid':
                raise UserError(
                    self.env._('Only unpaid draft memberships can be marked as paid.')
                )
            membership._get_coworking_product()
            membership.write(
                {
                    'payment_status': 'paid',
                    'payment_date': payment_date,
                }
            )
            membership.message_post(
                body=self.env._(
                    'Membership payment confirmed on %(date)s.',
                    date=fields.Date.to_string(payment_date),
                )
            )
        return True

    def action_activate(self):
        """Activate draft memberships and initialize their usage limits.

        :return: ``True`` after all selected memberships are activated.
        :rtype: bool
        :raises UserError: If a membership cannot be activated.
        """
        for membership in self:
            if membership.state != 'draft':
                raise UserError(self.env._('Only draft memberships can be activated.'))
            if membership.payment_status != 'paid':
                raise UserError(self.env._('Only a paid membership can be activated.'))
            if not membership.plan_id.all_locations and not membership.location_id:
                raise UserError(
                    self.env._('A location is required for a membership plan limited to one location.')
                )
            if membership.auto_renew and not membership.plan_id.allow_auto_renew:
                raise UserError(
                    self.env._('Automatic renewal is not allowed for the selected membership plan.')
                )

            values = {
                'state': 'active',
                'remaining_hours': 0.0,
                'remaining_visits': 0,
            }
            if membership.plan_id.usage_type == 'hours':
                values['remaining_hours'] = membership.plan_id.included_hours
            elif membership.plan_id.usage_type == 'visits':
                values['remaining_visits'] = membership.plan_id.included_visits
            membership.write(values)
            membership.message_post(body=self.env._('Membership activated.'))
        return True

    def action_freeze(self):
        """Freeze active memberships and remember the first frozen day.

        :return: ``True`` after all selected memberships are frozen.
        :rtype: bool
        :raises UserError: If a membership is not active.
        """
        today = fields.Date.context_today(self)
        for membership in self:
            if membership.state != 'active':
                raise UserError(self.env._('Only active memberships can be frozen.'))
            membership.write(
                {
                    'state': 'frozen',
                    'freeze_date': today,
                }
            )
            membership.message_post(
                body=self.env._(
                    'Membership frozen on %(date)s.',
                    date=fields.Date.to_string(today),
                )
            )
        return True

    def action_unfreeze(self):
        """Unfreeze memberships and extend their end dates.

        :return: ``True`` after all selected memberships are unfrozen.
        :rtype: bool
        :raises UserError: If a membership is not frozen correctly.
        """
        today = fields.Date.context_today(self)
        for membership in self:
            if membership.state != 'frozen' or not membership.freeze_date:
                raise UserError(self.env._('Only frozen memberships can be unfrozen.'))
            frozen_days = (today - membership.freeze_date).days
            membership.write(
                {
                    'state': 'active',
                    'date_end': membership.date_end + relativedelta(days=frozen_days),
                    'freeze_date': False,
                    'total_frozen_days': membership.total_frozen_days + frozen_days,
                }
            )
            membership.message_post(
                body=self.env._(
                    'Membership unfrozen after %(days)s full calendar day(s).',
                    days=frozen_days,
                )
            )
        return True

    def action_cancel(self):
        """Terminate active or frozen memberships before their end dates.

        :return: ``True`` after all selected memberships are cancelled.
        :rtype: bool
        :raises UserError: If a membership cannot be cancelled.
        """
        for membership in self:
            if membership.state not in ('active', 'frozen'):
                raise UserError(self.env._('Only active or frozen memberships can be terminated.'))
            membership.write(
                {
                    'state': 'cancelled',
                    'freeze_date': False,
                }
            )
            membership.message_post(body=self.env._('Membership terminated early.'))
        return True

    def _prepare_renewal_values(self):
        """Prepare values for a draft membership renewal.

        :return: Values for a new membership linked to the current one.
        :rtype: dict
        """
        self.ensure_one()
        date_start = self.date_end + relativedelta(days=1)
        return {
            'partner_id': self.partner_id.id,
            'plan_id': self.plan_id.id,
            'location_id': self.location_id.id,
            'date_start': date_start,
            'date_end': self._calculate_end_date(date_start, self.plan_id.duration_days),
            'auto_renew': self.auto_renew and self.plan_id.allow_auto_renew,
            'previous_membership_id': self.id,
        }

    def _create_renewal(self):
        """Create one linked draft renewal for an expired membership.

        :return: Existing or newly created renewal membership.
        :rtype: OSCoworkingMembership
        :raises UserError: If the membership has not expired.
        """
        self.ensure_one()
        if self.renewed_membership_id:
            return self.renewed_membership_id
        if self.state != 'expired':
            raise UserError(self.env._('A renewal can be created only for an expired membership.'))

        renewal = self.create(self._prepare_renewal_values())
        self.renewed_membership_id = renewal
        self.message_post(
            body=self.env._(
                'Renewal draft %(membership)s created.',
                membership=renewal.display_name,
            )
        )
        return renewal

    @api.model
    def _cron_expire_memberships(self):
        """Expire ended memberships and prepare automatic renewal drafts."""
        today = fields.Date.context_today(self)
        memberships = self.search(
            [
                ('state', '=', 'active'),
                ('date_end', '<', today),
            ]
        )
        for membership in memberships:
            membership.state = 'expired'
            membership.message_post(
                body=self.env._(
                    'Membership expired after %(date)s.',
                    date=fields.Date.to_string(membership.date_end),
                )
            )
            if (
                membership.auto_renew
                and membership.plan_id.allow_auto_renew
                and not membership.renewed_membership_id
            ):
                membership._create_renewal()
