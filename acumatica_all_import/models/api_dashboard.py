from datetime import datetime, time, timedelta

from odoo import api, fields, models


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

    _TRANSACTION_MODELS = (
        'acumatica.receipt.line', 'acumatica.transfer.line',
        'acumatica.inventory.recieved.line', 'acumatica.shipment.line',
        'acumatica.shipment.gi.staging', 'acumatica.transfer.shipment.line',
        'acumatica.inventory.issue.line', 'acumatica.issue.po.return.line',
        'acumatica.issue.line', 'acumatica.direct.transfer.staging',
        'acumatica.vendor.return.direct.transfer.staging',
        'acumatica.transfer.one.step.line', 'acumatica.transfer.two.step.line',
        'acumatica.shipment.completed.staging', 'acumatica.kit.assembly',
        'acumatica.invoice.consignment.staging',
        'acumatica.credit.memo.consignment.staging',
    )
    _MASTER_MODELS = (
        'acumatica.customer.line', 'acumatica.vendor.line',
        'acumatica.uom.line', 'acumatica.warehouse.line',
        'acumatica.stock.item.line', 'acumatica.non.stock.item.line',
    )

    @api.depends('card_type', 'data_model')
    def _compute_metrics(self):
        now = fields.Datetime.now()
        today_start = datetime.combine(fields.Date.context_today(self), time.min)
        yesterday_start = today_start - timedelta(days=1)
        week_start = today_start - timedelta(days=6)
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
                card._compute_inventory_metrics(values, now, today_start)
            elif card.card_type in ('transactions', 'master'):
                default_models = self._TRANSACTION_MODELS if card.card_type == 'transactions' else self._MASTER_MODELS
                models_to_read = (card.data_model,) if card.data_model else default_models
                for model_name in models_to_read:
                    Model = self.env.get(model_name)
                    if Model is None:
                        continue
                    values['total'] += Model.search_count([])
                    for state in ('staged', 'created', 'updated', 'rejected', 'error'):
                        key = 'errors' if state == 'error' else state
                        values[key] += Model.search_count([('import_state', '=', state)])
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

    def _compute_inventory_metrics(self, values, now, today_start):
        self.ensure_one()
        Picking = self.env['stock.picking']
        pickings = Picking.search([])
        today_end = today_start + timedelta(days=1)
        active_pickings = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))

        def scheduled_before(picking, boundary):
            return picking.scheduled_date and picking.scheduled_date < boundary

        values['total'] = len(pickings)
        values['waiting'] = len(pickings.filtered(
            lambda p: p.wms_state in ('draft', 'waiting', 'confirmed', 'waiting_response')
        ))
        values['ready'] = len(pickings.filtered(
            lambda p: p.state == 'assigned' and not any(
                getattr(move, 'quantity', 0) for move in p.move_ids
            )
        ))
        values['done_count'] = len(pickings.filtered(lambda p: p.state == 'done'))
        values['cancelled'] = len(pickings.filtered(lambda p: p.state == 'cancel'))
        values['in_progress'] = len(active_pickings.filtered(
            lambda p: any(getattr(move, 'quantity', 0) for move in p.move_ids)
        ))
        values['overdue'] = len(active_pickings.filtered(lambda p: scheduled_before(p, now)))
        values['scheduled_today'] = len(pickings.filtered(
            lambda p: p.scheduled_date and today_start <= p.scheduled_date < today_end
        ))
        values['upcoming'] = len(pickings.filtered(
            lambda p: p.scheduled_date and p.scheduled_date >= today_end
        ))

        if self.card_type == 'operation_status':
            values['staged'] = values['waiting']
            values['created'] = values['ready']
            values['updated'] = values['in_progress']
            values['errors'] = values['done_count']
            values['rejected'] = values['cancelled']
        elif self.card_type == 'delayed_operation':
            values['total'] = values['overdue']
        elif self.card_type == 'operation_schedule':
            values['total'] = values['overdue'] + values['scheduled_today'] + values['upcoming']
            values['yesterday'] = values['overdue']
            values['today'] = values['scheduled_today']
            values['last_7_days'] = values['upcoming']
        elif self.card_type == 'operation_progress':
            for picking in pickings:
                for move in picking.move_ids:
                    values['demand_qty'] += move.product_uom_qty or 0.0
                    values['processed_qty'] += getattr(move, 'quantity', 0.0) or 0.0
            values['remaining_qty'] = max(values['demand_qty'] - values['processed_qty'], 0.0)
            if values['demand_qty']:
                values['completion_percent'] = values['processed_qty'] / values['demand_qty'] * 100
            values['total'] = len(pickings)
        elif self.card_type == 'partial_discrepancy':
            partials = pickings.filtered(lambda p: p.shipment_information == 'partial')
            values['partial_count'] = len(partials)
            for picking in pickings:
                for move in picking.move_ids:
                    values['expected_qty'] += move.product_uom_qty or 0.0
                    values['received_qty'] += getattr(move, 'quantity', 0.0) or 0.0
                    values['sent_qty'] += getattr(move, 'confirmation_quantity', 0.0) or 0.0
            values['counted_qty'] = values['received_qty']
            values['discrepancy_qty'] = max(values['expected_qty'] - values['received_qty'], 0.0)
            values['total'] = values['partial_count']
        elif self.card_type == 'inventory_adjustment':
            Inventory = self.env.get('stock.inventory')
            if Inventory is not None:
                adjustments = Inventory.search([])
                values['adjustment_count'] = len(adjustments)
                values['total'] = len(adjustments)
                for adjustment in adjustments:
                    values['adjustment_variance'] += sum(
                        abs(getattr(quant, 'inventory_diff_quantity', 0.0) or 0.0)
                        for quant in adjustment.stock_quant_ids
                    )
        elif self.card_type == 'scrap_monitoring':
            Scrap = self.env['stock.scrap']
            scraps = Scrap.search([])
            values['total'] = len(scraps)
            values['scrap_draft'] = len(scraps.filtered(lambda s: s.state == 'draft'))
            values['scrap_ready'] = len(scraps.filtered(lambda s: s.state == 'ready'))
            values['scrap_done'] = len(scraps.filtered(lambda s: s.state == 'done'))
            values['scrap_qty'] = sum(
                sum((line.demand_qty or 0.0) for line in scrap.scrap_line_ids)
                or (getattr(scrap, 'scrap_qty', 0.0) or 0.0)
                for scrap in scraps
            )
            values['scrap_reason_count'] = len(scraps.filtered(lambda s: bool(s.name)))

        if self.card_type == 'operation_progress':
            values['staged'] = values['demand_qty']
            values['created'] = values['processed_qty']
            values['updated'] = values['remaining_qty']
            values['errors'] = values['completion_percent']
        elif self.card_type == 'partial_discrepancy':
            values['staged'] = values['expected_qty']
            values['created'] = values['sent_qty']
            values['updated'] = values['received_qty']
            values['errors'] = values['discrepancy_qty']
        elif self.card_type == 'inventory_adjustment':
            values['staged'] = values['adjustment_count']
            values['errors'] = values['adjustment_variance']
        elif self.card_type == 'scrap_monitoring':
            values['staged'] = values['scrap_draft']
            values['created'] = values['scrap_ready']
            values['errors'] = values['scrap_done']
            values['updated'] = values['scrap_qty']
        elif self.card_type == 'delayed_operation':
            values['errors'] = values['overdue']

        status_max = max(values['staged'], values['created'], values['updated'], values['errors'], 1)
        values['staged_bar'] = max(8, round(values['staged'] / status_max * 120))
        values['created_bar'] = max(8, round(values['created'] / status_max * 120))
        values['updated_bar'] = max(8, round(values['updated'] / status_max * 120))
        values['errors_bar'] = max(8, round(values['errors'] / status_max * 120))
        values['cancelled_bar'] = max(8, round(values['cancelled'] / max(
            values['waiting'], values['ready'], values['in_progress'], values['done_count'], values['cancelled'], 1
        ) * 120))

    def action_refresh(self):
        return {'type': 'ir.actions.client', 'tag': 'reload'}
