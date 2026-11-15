import json
import logging
from datetime import datetime, time, timedelta
from time import time as unix_time

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ApiDataHubDashboardCard(models.Model):
    _name = 'api.data.hub.dashboard.card'
    _description = 'API Data Hub Dashboard Card'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    card_type = fields.Selection([
        ('transactions', 'Transactions'),
        ('master', 'Product / Master Data'),
        ('webhook', 'Webhook Activity'),
        ('scheduler', 'Scheduler Activity'),
        ('operation_status', 'Operation by Status'),
        ('delayed_operation', 'Delayed Operation'),
        ('operation_schedule', 'Operation Schedule'),
        ('operation_progress', 'Operation Progress'),
        ('partial_discrepancy', 'Partial & Discrepancy'),
        ('inventory_adjustment', 'Inventory Adjustment'),
        ('scrap_monitoring', 'Scrap Monitoring'),
    ], required=True, readonly=True)
    dashboard_scope = fields.Selection([
        ('api', 'API Data Hub'),
        ('inventory', 'Inventory'),
    ], default='api', required=True, readonly=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    dashboard_visible = fields.Boolean(default=False)
    data_model = fields.Char(readonly=True)
    section_title = fields.Char(readonly=True)
    section_start = fields.Boolean(default=False, readonly=True)
    total = fields.Integer(compute='_compute_metrics')
    staged = fields.Integer(compute='_compute_metrics')
    created = fields.Integer(compute='_compute_metrics')
    updated = fields.Integer(compute='_compute_metrics')
    rejected = fields.Integer(compute='_compute_metrics')
    errors = fields.Integer(compute='_compute_metrics')
    today = fields.Integer(compute='_compute_metrics')
    yesterday = fields.Integer(compute='_compute_metrics')
    last_7_days = fields.Integer(compute='_compute_metrics')
    success = fields.Integer(compute='_compute_metrics')
    failed = fields.Integer(compute='_compute_metrics')
    staged_bar = fields.Integer(compute='_compute_metrics')
    created_bar = fields.Integer(compute='_compute_metrics')
    updated_bar = fields.Integer(compute='_compute_metrics')
    errors_bar = fields.Integer(compute='_compute_metrics')
    today_bar = fields.Integer(compute='_compute_metrics')
    yesterday_bar = fields.Integer(compute='_compute_metrics')
    last_7_days_bar = fields.Integer(compute='_compute_metrics')
    waiting = fields.Integer(compute='_compute_metrics')
    ready = fields.Integer(compute='_compute_metrics')
    in_progress = fields.Integer(compute='_compute_metrics')
    done_count = fields.Integer(compute='_compute_metrics')
    cancelled = fields.Integer(compute='_compute_metrics')
    cancelled_bar = fields.Integer(compute='_compute_metrics')
    overdue = fields.Integer(compute='_compute_metrics')
    scheduled_today = fields.Integer(compute='_compute_metrics')
    upcoming = fields.Integer(compute='_compute_metrics')
    demand_qty = fields.Float(compute='_compute_metrics')
    processed_qty = fields.Float(compute='_compute_metrics')
    remaining_qty = fields.Float(compute='_compute_metrics')
    completion_percent = fields.Float(compute='_compute_metrics')
    expected_qty = fields.Float(compute='_compute_metrics')
    sent_qty = fields.Float(compute='_compute_metrics')
    received_qty = fields.Float(compute='_compute_metrics')
    counted_qty = fields.Float(compute='_compute_metrics')
    discrepancy_qty = fields.Float(compute='_compute_metrics')
    partial_count = fields.Integer(compute='_compute_metrics')
    adjustment_count = fields.Integer(compute='_compute_metrics')
    adjustment_variance = fields.Float(compute='_compute_metrics')
    scrap_draft = fields.Integer(compute='_compute_metrics')
    scrap_ready = fields.Integer(compute='_compute_metrics')
    scrap_done = fields.Integer(compute='_compute_metrics')
    scrap_qty = fields.Float(compute='_compute_metrics')
    scrap_reason_count = fields.Integer(compute='_compute_metrics')

    _INVENTORY_METRICS_CACHE_TTL = 300

    @api.depends('card_type', 'data_model')
    def _compute_metrics(self):
        now = fields.Datetime.now()
        today_start = datetime.combine(fields.Date.context_today(self), time.min)
        yesterday_start = today_start - timedelta(days=1)
        week_start = today_start - timedelta(days=6)
        import_metrics_by_model = {}
        inventory_metrics = None
        import_registry = self.env['acumatica.unified.import.wizard']
        default_models_by_type = {
            'transactions': tuple(
                import_registry.IMPORT_MAP[key]['line_model']
                for key in import_registry.TRANSACTION_TYPES
                if key in import_registry.IMPORT_MAP
            ),
            'master': tuple(
                import_registry.IMPORT_MAP[key]['line_model']
                for key in import_registry.MASTER_DATA_TYPES
                if key in import_registry.IMPORT_MAP
            ),
        }
        for card in self:
            values = {field: 0 for field in (
                'total', 'staged', 'created', 'updated', 'rejected', 'errors',
                'today', 'yesterday', 'last_7_days', 'success', 'failed',
                'staged_bar', 'created_bar', 'updated_bar', 'errors_bar',
                'today_bar', 'yesterday_bar', 'last_7_days_bar',
                'waiting', 'ready', 'in_progress', 'done_count', 'cancelled', 'cancelled_bar',
                'overdue', 'scheduled_today', 'upcoming', 'demand_qty',
                'processed_qty', 'remaining_qty', 'completion_percent',
                'expected_qty', 'sent_qty', 'received_qty', 'counted_qty',
                'discrepancy_qty', 'partial_count', 'adjustment_count',
                'adjustment_variance', 'scrap_draft', 'scrap_ready',
                'scrap_done', 'scrap_qty', 'scrap_reason_count',
            )}
            if card.dashboard_scope == 'inventory':
                if inventory_metrics is None:
                    inventory_metrics = card._get_inventory_metrics(now, today_start)
                card._apply_inventory_metrics(values, inventory_metrics)
            elif card.card_type in ('transactions', 'master'):
                default_models = default_models_by_type[card.card_type]
                models_to_read = (card.data_model,) if card.data_model else default_models
                for model_name in models_to_read:
                    Model = self.env.get(model_name)
                    if Model is None:
                        continue
                    if model_name not in import_metrics_by_model:
                        metrics = {key: 0 for key in (
                            'total', 'staged', 'created', 'updated', 'rejected', 'errors',
                        )}
                        if 'import_state' in Model._fields:
                            grouped_counts = Model._read_group(
                                [], ['import_state'], ['__count'],
                            )
                            for state, count in grouped_counts:
                                metrics['total'] += count
                                key = 'errors' if state == 'error' else state
                                if key in metrics and state:
                                    metrics[key] += count
                        else:
                            metrics['total'] = Model.search_count([])
                        import_metrics_by_model[model_name] = metrics

                    for key, count in import_metrics_by_model[model_name].items():
                        values[key] += count
            elif card.card_type == 'webhook':
                Model = self.env.get('acumatica.webhook.log')
                if Model is not None:
                    values['total'] = Model.search_count([])
                    values['today'] = Model.search_count([('create_date', '>=', today_start)])
                    values['yesterday'] = Model.search_count([
                        ('create_date', '>=', yesterday_start), ('create_date', '<', today_start),
                    ])
                    values['last_7_days'] = Model.search_count([('create_date', '>=', week_start)])
                    values['success'] = Model.search_count([('state', '=', 'processed')])
                    values['failed'] = Model.search_count([('state', '=', 'error')])
            elif card.card_type == 'scheduler':
                Model = self.env.get('api.scheduler.log')
                if Model is not None:
                    values['total'] = Model.search_count([])
                    values['today'] = Model.search_count([('execution_time', '>=', today_start)])
                    values['yesterday'] = Model.search_count([
                        ('execution_time', '>=', yesterday_start), ('execution_time', '<', today_start),
                    ])
                    values['last_7_days'] = Model.search_count([('execution_time', '>=', week_start)])
                    values['success'] = Model.search_count([('status', '=', 'success')])
                    values['failed'] = Model.search_count([('status', '=', 'failed')])
            state_max = max(values['staged'], values['created'], values['updated'], values['errors'], 1)
            date_max = max(values['today'], values['yesterday'], values['last_7_days'], 1)
            for source, target in (
                ('staged', 'staged_bar'), ('created', 'created_bar'),
                ('updated', 'updated_bar'), ('errors', 'errors_bar'),
            ):
                values[target] = max(8, round(values[source] / state_max * 120))
            for source, target in (
                ('today', 'today_bar'), ('yesterday', 'yesterday_bar'),
                ('last_7_days', 'last_7_days_bar'),
            ):
                values[target] = max(8, round(values[source] / date_max * 120))
            for field, value in values.items():
                setattr(card, field, value)

    @api.model
    def _get_inventory_metrics(self, now, today_start):
        """Return a short-lived, user/company-scoped inventory snapshot."""
        cache_key = self._inventory_metrics_cache_key()
        Parameters = self.env['ir.config_parameter'].sudo()
        cached_value = Parameters.get_param(cache_key)
        if cached_value:
            try:
                payload = json.loads(cached_value)
                cache_age = unix_time() - float(payload.get('computed_at', 0))
                if (
                    cache_age >= 0
                    and isinstance(payload.get('metrics'), dict)
                ):
                    # Never make a returning dashboard request wait for a cold
                    # full-history scan. A cron refreshes expired entries.
                    return payload['metrics']
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        metrics = self._compute_inventory_metrics_snapshot(now, today_start)
        self._store_inventory_metrics_snapshot(metrics, today_start)
        return metrics

    @api.model
    def _store_inventory_metrics_snapshot(self, metrics, today_start):
        self.env['ir.config_parameter'].sudo().set_param(
            self._inventory_metrics_cache_key(),
            json.dumps({
                'computed_at': unix_time(),
                'snapshot_date': today_start.date().isoformat(),
                'metrics': metrics,
            }),
        )

    @api.model
    def _inventory_metrics_cache_key(self):
        companies = ','.join(str(company_id) for company_id in sorted(self.env.companies.ids))
        return f'acumatica_all_import.inventory_metrics.{self.env.uid}.{companies or "none"}'

    @api.model
    def _compute_inventory_metrics_snapshot(self, now, today_start):
        """Aggregate stock data once when the cache is missing or refreshed."""
        Picking = self.env['stock.picking']
        pickings_by_state = Picking._read_group([], ['state'], ['__count'])
        state_counts = {state: count for state, count in pickings_by_state}
        pickings_by_wms_state = Picking._read_group([], ['wms_state'], ['__count'])
        wms_state_counts = {state: count for state, count in pickings_by_wms_state}
        total_pickings = sum(state_counts.values())
        today_end = today_start + timedelta(days=1)
        assigned = state_counts.get('assigned', 0)
        active_domain = [('state', 'not in', ('done', 'cancel'))]
        nonzero_move_domain = [('move_ids.quantity', '!=', 0)]
        in_progress = Picking.search_count(active_domain + nonzero_move_domain)
        assigned_with_quantity = Picking.search_count(
            [('state', '=', 'assigned')] + nonzero_move_domain
        )
        overdue = Picking.search_count(
            active_domain + [('scheduled_date', '<', now)]
        )
        scheduled_today = Picking.search_count([
            ('scheduled_date', '>=', today_start), ('scheduled_date', '<', today_end),
        ])
        upcoming = Picking.search_count([('scheduled_date', '>=', today_end)])
        partial_count = Picking.search_count([('shipment_information', '=', 'partial')])

        Move = self.env['stock.move']
        move_totals = Move._read_group(
            [('picking_id', '!=', False)], [],
            ['product_uom_qty:sum', 'quantity:sum', 'confirmation_quantity:sum'],
        )
        demand_qty, processed_qty, sent_qty = move_totals[0] if move_totals else (0.0, 0.0, 0.0)

        metrics = {
            'total': total_pickings,
            'waiting': sum(
                wms_state_counts.get(state, 0)
                for state in ('draft', 'waiting', 'confirmed', 'waiting_response')
            ),
            'ready': max(assigned - assigned_with_quantity, 0),
            'in_progress': in_progress,
            'done_count': state_counts.get('done', 0),
            'cancelled': state_counts.get('cancel', 0),
            'overdue': overdue,
            'scheduled_today': scheduled_today,
            'upcoming': upcoming,
            'demand_qty': demand_qty or 0.0,
            'processed_qty': processed_qty or 0.0,
            'sent_qty': sent_qty or 0.0,
            'partial_count': partial_count,
            'adjustment_count': 0,
            'adjustment_variance': 0.0,
            'scrap_draft': 0,
            'scrap_ready': 0,
            'scrap_done': 0,
            'scrap_total': 0,
            'scrap_qty': 0.0,
            'scrap_reason_count': 0,
        }

        Inventory = self.env.get('stock.inventory')
        if Inventory is not None:
            adjustments = Inventory.search([])
            metrics['adjustment_count'] = len(adjustments)
            metrics['adjustment_variance'] = sum(
                abs(getattr(quant, 'inventory_diff_quantity', 0.0) or 0.0)
                for quant in adjustments.mapped('stock_quant_ids')
            )

        Scrap = self.env.get('stock.scrap')
        if Scrap is not None:
            scraps = Scrap.search([])
            metrics['scrap_total'] = len(scraps)
            metrics['scrap_draft'] = sum(scrap.state == 'draft' for scrap in scraps)
            metrics['scrap_ready'] = sum(scrap.state == 'ready' for scrap in scraps)
            metrics['scrap_done'] = sum(scrap.state == 'done' for scrap in scraps)
            metrics['scrap_qty'] = sum(
                sum(line.demand_qty or 0.0 for line in scrap.scrap_line_ids)
                or (getattr(scrap, 'scrap_qty', 0.0) or 0.0)
                for scrap in scraps
            )
            metrics['scrap_reason_count'] = sum(bool(scrap.name) for scrap in scraps)
        return metrics

    @api.model
    def _cron_refresh_inventory_metrics_cache(self):
        """Refresh expired snapshots for users who have opened Inventory Dashboard."""
        prefix = 'acumatica_all_import.inventory_metrics.'
        Parameters = self.env['ir.config_parameter'].sudo()
        cached_parameters = Parameters.search([('key', 'like', prefix + '%')])
        Users = self.env['res.users'].sudo()
        dashboard_group_ids = {
            self.env.ref('stock.group_stock_manager').id,
            self.env.ref('base.group_system').id,
        }

        for parameter in cached_parameters:
            try:
                user_part, company_part = parameter.key[len(prefix):].split('.', 1)
                user_id = int(user_part)
                company_ids = [int(company_id) for company_id in company_part.split(',') if company_id]
                payload = json.loads(parameter.value or '{}')
                cache_age = unix_time() - float(payload.get('computed_at', 0))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            user = Users.browse(user_id).exists()
            if not user or not user.active:
                parameter.unlink()
                continue
            if not dashboard_group_ids.intersection(user.groups_id.ids):
                continue
            if not set(company_ids).issubset(set(user.company_ids.ids)):
                continue
            dashboard_model = self.with_user(user)
            if company_ids:
                dashboard_model = dashboard_model.with_context(allowed_company_ids=company_ids)
            now = fields.Datetime.now()
            today_start = datetime.combine(fields.Date.context_today(dashboard_model), time.min)
            if (
                0 <= cache_age < self._INVENTORY_METRICS_CACHE_TTL
                and payload.get('snapshot_date') == today_start.date().isoformat()
                and isinstance(payload.get('metrics'), dict)
            ):
                continue
            try:
                metrics = dashboard_model._compute_inventory_metrics_snapshot(now, today_start)
                dashboard_model._store_inventory_metrics_snapshot(metrics, today_start)
            except Exception:
                _logger.exception(
                    'Failed to refresh Inventory Dashboard metrics for user_id=%s companies=%s',
                    user_id,
                    company_ids,
                )

    def _apply_inventory_metrics(self, values, metrics):
        self.ensure_one()
        if self.card_type == 'operation_status':
            values['total'] = metrics['total']
            values['waiting'] = metrics['waiting']
            values['ready'] = metrics['ready']
            values['in_progress'] = metrics['in_progress']
            values['done_count'] = metrics['done_count']
            values['cancelled'] = metrics['cancelled']
            values['staged'] = metrics['waiting']
            values['created'] = metrics['ready']
            values['updated'] = metrics['in_progress']
            values['errors'] = metrics['done_count']
            values['rejected'] = metrics['cancelled']
        elif self.card_type == 'delayed_operation':
            values['overdue'] = metrics['overdue']
            values['total'] = metrics['overdue']
            values['errors'] = metrics['overdue']
        elif self.card_type == 'operation_schedule':
            values['overdue'] = metrics['overdue']
            values['scheduled_today'] = metrics['scheduled_today']
            values['upcoming'] = metrics['upcoming']
            values['total'] = metrics['overdue'] + metrics['scheduled_today'] + metrics['upcoming']
            values['yesterday'] = metrics['overdue']
            values['today'] = metrics['scheduled_today']
            values['last_7_days'] = metrics['upcoming']
        elif self.card_type == 'operation_progress':
            values['total'] = metrics['total']
            values['demand_qty'] = metrics['demand_qty']
            values['processed_qty'] = metrics['processed_qty']
            values['remaining_qty'] = max(metrics['demand_qty'] - metrics['processed_qty'], 0.0)
            if metrics['demand_qty']:
                values['completion_percent'] = metrics['processed_qty'] / metrics['demand_qty'] * 100
            values['staged'] = values['demand_qty']
            values['created'] = values['processed_qty']
            values['updated'] = values['remaining_qty']
            values['errors'] = values['completion_percent']
        elif self.card_type == 'partial_discrepancy':
            values['partial_count'] = metrics['partial_count']
            values['expected_qty'] = metrics['demand_qty']
            values['received_qty'] = metrics['processed_qty']
            values['sent_qty'] = metrics['sent_qty']
            values['counted_qty'] = metrics['processed_qty']
            values['discrepancy_qty'] = max(metrics['demand_qty'] - metrics['processed_qty'], 0.0)
            values['total'] = metrics['partial_count']
            values['staged'] = values['expected_qty']
            values['created'] = values['sent_qty']
            values['updated'] = values['received_qty']
            values['errors'] = values['discrepancy_qty']
        elif self.card_type == 'inventory_adjustment':
            values['adjustment_count'] = metrics['adjustment_count']
            values['adjustment_variance'] = metrics['adjustment_variance']
            values['total'] = metrics['adjustment_count']
            values['staged'] = metrics['adjustment_count']
            values['errors'] = metrics['adjustment_variance']
        elif self.card_type == 'scrap_monitoring':
            values['total'] = metrics['scrap_total']
            values['scrap_draft'] = metrics['scrap_draft']
            values['scrap_ready'] = metrics['scrap_ready']
            values['scrap_done'] = metrics['scrap_done']
            values['scrap_qty'] = metrics['scrap_qty']
            values['scrap_reason_count'] = metrics['scrap_reason_count']
            values['staged'] = metrics['scrap_draft']
            values['created'] = metrics['scrap_ready']
            values['errors'] = metrics['scrap_done']
            values['updated'] = metrics['scrap_qty']

        if self.card_type == 'operation_status':
            status_max = max(
                values['waiting'], values['ready'], values['in_progress'],
                values['done_count'], values['cancelled'], 1,
            )
            values['cancelled_bar'] = max(8, round(values['cancelled'] / status_max * 120))

    def action_refresh(self):
        if any(card.dashboard_scope == 'inventory' for card in self):
            now = fields.Datetime.now()
            today_start = datetime.combine(fields.Date.context_today(self), time.min)
            metrics = self._compute_inventory_metrics_snapshot(now, today_start)
            self._store_inventory_metrics_snapshot(metrics, today_start)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_open_metric(self):
        self.ensure_one()
        if self.dashboard_scope != 'inventory':
            raise UserError('Drill-down ini hanya tersedia untuk kartu Inventory Dashboard.')

        metric = self.env.context.get('dashboard_metric', 'card')
        now = fields.Datetime.now()
        today_start = datetime.combine(fields.Date.context_today(self), time.min)
        today_end = today_start + timedelta(days=1)
        active_states = ('done', 'cancel')
        model_name = 'stock.picking'
        domain = []

        if self.card_type == 'operation_status':
            if metric == 'waiting':
                domain = [('wms_state', 'in', ('draft', 'waiting', 'confirmed', 'waiting_response'))]
            elif metric == 'ready':
                assigned = self.env[model_name].search([('state', '=', 'assigned')])
                ready_ids = assigned.filtered(
                    lambda picking: not any(getattr(move, 'quantity', 0) for move in picking.move_ids)
                ).ids
                domain = [('id', 'in', ready_ids)]
            elif metric == 'in_progress':
                domain = [('state', 'not in', active_states), ('move_ids.quantity', '>', 0)]
            elif metric == 'done':
                domain = [('state', '=', 'done')]
            elif metric == 'cancelled':
                domain = [('state', '=', 'cancel')]
        elif self.card_type == 'delayed_operation':
            domain = [('state', 'not in', active_states), ('scheduled_date', '<', now)]
        elif self.card_type == 'operation_schedule':
            if metric == 'card':
                domain = [
                    '|',
                    '&', ('state', 'not in', active_states), ('scheduled_date', '<', now),
                    '|',
                    '&', ('scheduled_date', '>=', today_start), ('scheduled_date', '<', today_end),
                    ('scheduled_date', '>=', today_end),
                ]
            elif metric == 'overdue':
                domain = [('state', 'not in', active_states), ('scheduled_date', '<', now)]
            elif metric == 'today':
                domain = [('scheduled_date', '>=', today_start), ('scheduled_date', '<', today_end)]
            elif metric == 'upcoming':
                domain = [('scheduled_date', '>=', today_end)]
        elif self.card_type == 'partial_discrepancy':
            domain = [('shipment_information', '=', 'partial')]
        elif self.card_type == 'inventory_adjustment':
            model_name = 'stock.inventory'
        elif self.card_type == 'scrap_monitoring':
            model_name = 'stock.scrap'
            scrap_states = {'draft': 'draft', 'ready': 'ready', 'done': 'done'}
            if metric in scrap_states:
                domain = [('state', '=', scrap_states[metric])]
        elif self.card_type != 'operation_progress':
            raise UserError('Jenis kartu ini belum memiliki daftar detail.')

        if self.env.get(model_name) is None:
            raise UserError('Model detail untuk kartu ini tidak tersedia.')

        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} - {metric.replace("_", " ").title()}',
            'res_model': model_name,
            'view_mode': 'list,form',
            'domain': domain,
            'target': 'current',
        }
