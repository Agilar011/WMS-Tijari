import logging
import time

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

_SCHEDULER_JOB_TYPES = {
    'fetch_all_master': ('master', 'fetch'),
    'import_all_master': ('master', 'import'),
    'fetch_import_all_master': ('master', 'combined'),
    'fetch_all_transaction': ('transaction', 'fetch'),
    'import_all_transaction': ('transaction', 'import'),
    'fetch_import_all_transaction': ('transaction', 'combined'),
    'fetch_selected': (None, 'fetch'),
    'import_selected': (None, 'import'),
}


class ApiSchedulerDataType(models.Model):
    _name = 'api.scheduler.data.type'
    _description = 'API Scheduler Data Type'
    _order = 'data_category, sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    data_category = fields.Selection(
        [('master', 'Master Data'), ('transaction', 'Master Transaction')],
        required=True,
    )
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Data type code must be unique.'),
    ]

    @api.model
    def get_selection(self):
        return [(record.code, record.name) for record in self.search([])]


class ApiSchedulerJob(models.Model):
    _name = 'api.scheduler.job'
    _description = 'API Scheduler'
    _order = 'name'

    name = fields.Char(string='Job Name', required=True)
    code = fields.Char(string='Code / Technical Name', required=True)
    description = fields.Text()
    active = fields.Boolean(default=True, string='Scheduler Available')
    job_type = fields.Selection(
        [
            ('fetch_all_master', 'Fetch All Master'),
            ('import_all_master', 'Import All Master'),
            ('fetch_import_all_master', 'Fetch & Import All Master'),
            ('fetch_all_transaction', 'Fetch All Transaction'),
            ('import_all_transaction', 'Import All Transaction'),
            ('fetch_import_all_transaction', 'Fetch & Import All Transaction'),
            ('fetch_selected', 'Single Fetch'),
            ('import_selected', 'Single Import'),
            ('generate_webhook', 'Generate Webhook'),
        ],
        string='Scheduler Type',
        required=True,
        default='fetch_all_master',
    )
    selected_data_category = fields.Selection(
        [('master', 'Master Data'), ('transaction', 'Master Transaction')],
        string='Data Category',
        default='transaction',
    )
    selected_data_type_ids = fields.Many2many(
        'api.scheduler.data.type',
        'api_scheduler_job_data_type_rel',
        'scheduler_job_id',
        'data_type_id',
        string='Data',
    )
    do_not_overlap = fields.Boolean(string='Do Not Overlap', default=True)
    is_running = fields.Boolean(readonly=True, copy=False)

    ir_cron_id = fields.Many2one('ir.cron', string='Odoo Cron', readonly=True, copy=False)
    cron_active = fields.Boolean(related='ir_cron_id.active', readonly=False, string='Odoo Cron Active')
    cron_interval_number = fields.Integer(related='ir_cron_id.interval_number', readonly=False, string='Interval Value')
    cron_interval_type = fields.Selection(related='ir_cron_id.interval_type', readonly=False, string='Interval Unit')
    cron_nextcall = fields.Datetime(related='ir_cron_id.nextcall', readonly=False, string='Next Execution')
    cron_user_id = fields.Many2one(related='ir_cron_id.user_id', readonly=False, string='Run As')
    log_ids = fields.One2many('api.scheduler.log', 'scheduler_job_id', string='Log Activity', readonly=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Code / Technical Name must be unique.'),
    ]

    @api.onchange('selected_data_category')
    def _onchange_selected_data_category(self):
        for job in self:
            if any(item.data_category != job.selected_data_category for item in job.selected_data_type_ids):
                job.selected_data_type_ids = [(5, 0, 0)]

    @api.constrains('job_type', 'selected_data_category', 'selected_data_type_ids')
    def _check_selected_data_category(self):
        for job in self:
            if job.job_type not in ('fetch_selected', 'import_selected'):
                continue
            wrong_types = job.selected_data_type_ids.filtered(
                lambda item: item.data_category != job.selected_data_category
            )
            if wrong_types:
                raise ValidationError('Selected data must match the selected Data Category.')

    def action_run_now(self):
        for job in self:
            job.run_from_cron()
        return True

    def action_open_ir_cron(self):
        self.ensure_one()
        if not self.ir_cron_id:
            raise UserError('No Odoo Cron is linked to this API Scheduler.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Odoo Cron',
            'res_model': 'ir.cron',
            'view_mode': 'form',
            'res_id': self.ir_cron_id.id,
            'target': 'current',
        }

    def run_from_cron(self):
        for job in self:
            job._run_single_job()
        return True

    def _run_single_job(self):
        self.ensure_one()
        if not self.active:
            return False
        if self.do_not_overlap and self.is_running:
            self._create_log(
                status='failed',
                execution_time=fields.Datetime.now(),
                duration=0.0,
                details=[],
                message='Skipped because the previous execution is still running.',
            )
            return False

        execution_time = fields.Datetime.now()
        started = time.monotonic()
        before = self._snapshot_stats()
        status = 'success'
        message = False
        process_result = {}
        activity_log = False

        try:
            self.write({'is_running': True})
            activity_log = self._create_log(
                status='running',
                execution_time=execution_time,
                duration=0.0,
                details=[],
                message='Job sedang berjalan.',
            )
            self.env.cr.commit()
            process_result = self.with_context(
                api_scheduler_log_id=activity_log.id,
            )._run_configured_process() or {}
            message = self._build_process_message(process_result)
            if not self._is_process_result_success(process_result):
                status = 'failed'
        except Exception as exc:
            status = 'failed'
            message = str(exc)
            _logger.exception("API Scheduler %s failed.", self.code)
        finally:
            after = self._snapshot_stats()
            details = self._build_detail_values(before, after, process_result)
            duration = time.monotonic() - started
            if activity_log:
                activity_log.write({
                    'status': status,
                    'duration': duration,
                    'message': message,
                })
                self._replace_log_details(activity_log, details)
            else:
                activity_log = self._create_log(
                    status=status,
                    execution_time=execution_time,
                    duration=duration,
                    details=details,
                    message=message,
                )
            self.write({'is_running': False})
        return status == 'success'

    def _replace_log_details(self, log, details):
        """Replace detail rows and refresh aggregate counters on a live log."""
        log.detail_ids.unlink()
        log.write({
            'data_retrieved': sum(item.get('data_retrieved', 0) for item in details),
            'staging_created': sum(item.get('staging_created', 0) for item in details),
            'records_created': sum(item.get('records_created', 0) for item in details),
            'records_errors': sum(item.get('records_errors', 0) for item in details),
            'records_skipped': sum(item.get('records_skipped', 0) for item in details),
            'detail_ids': [(0, 0, item) for item in details],
        })

    def _run_configured_process(self):
        self.ensure_one()
        if self.job_type == 'generate_webhook':
            return self.env['acumatica.webhook.log'].cron_process_pending_webhook_logs()

        ImportWizard = self.env['acumatica.unified.import.wizard']
        scheduler_type = _SCHEDULER_JOB_TYPES.get(self.job_type)
        if not scheduler_type:
            raise UserError('Scheduler Type is not configured.')

        category, phase = scheduler_type
        if category is None:
            category = self.selected_data_category
            data_types = self.selected_data_type_ids.mapped('code')
            if not data_types:
                raise UserError('Pilih minimal satu Data untuk scheduler ini.')
        else:
            data_types = (
                ImportWizard.MASTER_DATA_TYPES
                if category == 'master'
                else ImportWizard.TRANSACTION_TYPES
            )

        config_model = self.env['acumatica.config'].with_context(
            api_scheduler_log_id=self.env.context.get('api_scheduler_log_id'),
            api_scheduler_job_type=self.job_type,
            api_scheduler_data_category=category,
        )
        if phase != 'combined':
            return config_model._run_scheduler_data_types(data_types, phase)

        return self._run_combined_scheduler_process(config_model, data_types)

    def _run_combined_scheduler_process(self, config_model, data_types):
        """Fetch each type, then import only types fetched successfully with data."""
        fetch_results = config_model.with_context(
            api_scheduler_combined_phase='fetch',
        )._run_scheduler_data_types(data_types, 'fetch')
        successful_fetch_types = [
            key for key in data_types
            if fetch_results.get(key, {}).get('success', False)
            and fetch_results.get(key, {}).get('data_retrieved', 0) > 0
        ]
        import_results = {}
        if successful_fetch_types:
            import_results = config_model.with_context(
                api_scheduler_combined_phase='import',
                api_scheduler_combined_run=True,
            )._run_scheduler_data_types(successful_fetch_types, 'import')

        combined_results = {}
        for key in data_types:
            fetch_result = fetch_results.get(key, {})
            import_result = import_results.get(key, {})
            messages = [
                result.get('message') for result in (fetch_result, import_result)
                if result.get('message')
            ]
            combined_results[key] = {
                'success': fetch_result.get('success', False)
                and import_result.get('success', True),
                'data_retrieved': fetch_result.get('data_retrieved', 0),
                'records_created': import_result.get('records_created', 0),
                'records_errors': fetch_result.get('records_errors', 0)
                + import_result.get('records_errors', 0),
                'records_skipped': fetch_result.get('records_skipped', 0)
                + import_result.get('records_skipped', 0),
                'message': '\n'.join(messages) or False,
            }
        return combined_results

    def _get_scheduler_data_category(self):
        self.ensure_one()
        category = _SCHEDULER_JOB_TYPES.get(self.job_type, (None, None))[0]
        if category is None and self.job_type in ('fetch_selected', 'import_selected'):
            return self.selected_data_category
        return category or False

    def _is_process_result_success(self, process_result):
        if not isinstance(process_result, dict):
            return bool(process_result)
        for result in process_result.values():
            if isinstance(result, dict):
                if not result.get('success', True):
                    return False
            elif not result:
                return False
        return True

    def _build_process_message(self, process_result):
        if not isinstance(process_result, dict):
            return False
        messages = []
        for acumatica_data, result in process_result.items():
            if isinstance(result, dict) and result.get('message') and (
                result.get('records_errors') or not result.get('success', True)
            ):
                prefix = 'Skipped with error' if result.get('success', True) else 'Failed'
                messages.append('%s: %s - %s' % (acumatica_data, prefix, result.get('message')))
            elif result is False:
                messages.append('%s: Failed' % acumatica_data)
        return '\n'.join(messages) if messages else False

    def _get_acumatica_data_definitions(self):
        self.ensure_one()
        category = self._get_scheduler_data_category()
        if category not in ('master', 'transaction'):
            return []
        Wizard = self.env['acumatica.unified.import.wizard']
        if self.job_type in ('fetch_selected', 'import_selected'):
            keys = self.selected_data_type_ids.mapped('code')
        else:
            keys = Wizard.MASTER_DATA_TYPES if category == 'master' else Wizard.TRANSACTION_TYPES
        return [
            (key, Wizard.IMPORT_MAP[key]['label'], Wizard.IMPORT_MAP[key]['line_model'])
            for key in keys if key in Wizard.IMPORT_MAP
        ]

    def _snapshot_stats(self):
        stats = {}
        for acumatica_data, label, model_name in self._get_acumatica_data_definitions():
            Model = self.env[model_name].sudo()
            stats[acumatica_data] = {
                'label': label,
                'total': Model.search_count([]),
                'created': Model.search_count([('import_state', '=', 'created')]),
                'updated': Model.search_count([('import_state', '=', 'updated')]),
                'error': Model.search_count([('import_state', '=', 'error')]),
            }
        return stats

    def _get_process_detail(self, process_result, acumatica_data):
        if isinstance(process_result, dict):
            result = process_result.get(acumatica_data)
            if isinstance(result, dict):
                return result
        return {}

    def _build_detail_values(self, before, after, process_result=False):
        details = []
        for acumatica_data, values in after.items():
            previous = before.get(acumatica_data, {})
            result = self._get_process_detail(process_result, acumatica_data)
            records_created = (
                values.get('created', 0)
                + values.get('updated', 0)
                - previous.get('created', 0)
                - previous.get('updated', 0)
            )
            staging_created = values.get('total', 0) - previous.get('total', 0)
            data_retrieved = result.get('data_retrieved', staging_created)
            records_created = result.get('records_created', records_created)
            records_errors = result.get('records_errors', values.get('error', 0) - previous.get('error', 0))
            if isinstance(process_result, dict) and acumatica_data not in process_result:
                records_errors = max(records_errors, 1)
            if result and not result.get('success', True) and not records_errors:
                records_errors = 1
            records_skipped = result.get(
                'records_skipped',
                data_retrieved - records_created - records_errors,
            )
            details.append({
                'data_type': self._get_scheduler_data_category(),
                'acumatica_data': acumatica_data,
                'data_retrieved': max(data_retrieved, 0),
                'staging_created': max(staging_created, 0),
                'records_created': max(records_created, 0),
                'records_errors': max(records_errors, 0),
                'records_skipped': max(records_skipped, 0),
            })
        return details

    def _create_log(self, status, execution_time, duration, details, message=False):
        log_values = {
            'scheduler_job_id': self.id,
            'execution_time': execution_time,
            'duration': duration,
            'data_retrieved': sum(item.get('data_retrieved', 0) for item in details),
            'staging_created': sum(item.get('staging_created', 0) for item in details),
            'records_created': sum(item.get('records_created', 0) for item in details),
            'records_errors': sum(item.get('records_errors', 0) for item in details),
            'records_skipped': sum(item.get('records_skipped', 0) for item in details),
            'status': status,
            'message': message,
            'detail_ids': [(0, 0, item) for item in details],
        }
        return self.env['api.scheduler.log'].sudo().create(log_values)


class ApiSchedulerLog(models.Model):
    _name = 'api.scheduler.log'
    _description = 'API Scheduler Log'
    _order = 'execution_time desc, id desc'

    scheduler_job_id = fields.Many2one('api.scheduler.job', string='Scheduler Job', required=True, ondelete='cascade')
    execution_time = fields.Datetime(string='Execution Time', readonly=True)
    duration = fields.Float(readonly=True)
    data_retrieved = fields.Integer(string='Data Retrieved', readonly=True)
    staging_created = fields.Integer(string='Staging Created', readonly=True)
    records_created = fields.Integer(string='Records Created', readonly=True)
    records_errors = fields.Integer(string='Records Errors', readonly=True)
    records_skipped = fields.Integer(string='Records Skipped', readonly=True)
    status = fields.Selection(
        [
            ('running', 'Running'),
            ('success', 'Success'),
            ('failed', 'Failed'),
        ],
        readonly=True,
    )
    message = fields.Text(readonly=True)
    detail_ids = fields.One2many('api.scheduler.log.detail', 'scheduler_log_id', string='Details', readonly=True)

    def action_view_details(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Scheduler Log Details',
            'res_model': 'api.scheduler.log.detail',
            'view_mode': 'list',
            'domain': [('scheduler_log_id', '=', self.id)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
            },
        }


class ApiSchedulerLogDetail(models.Model):
    _name = 'api.scheduler.log.detail'
    _description = 'API Scheduler Log Detail'
    _order = 'scheduler_log_id desc, acumatica_data'

    scheduler_log_id = fields.Many2one('api.scheduler.log', string='Scheduler Log', required=True, ondelete='cascade')
    scheduler_job_id = fields.Many2one(related='scheduler_log_id.scheduler_job_id', store=True, string='Scheduler Job')
    data_type = fields.Selection(
        [
            ('master', 'Master'),
            ('transaction', 'Transaksi'),
        ],
        readonly=True,
    )
    acumatica_data = fields.Selection(
        selection=lambda self: self.env['api.scheduler.data.type'].sudo().get_selection(),
        string='Acumatica Data',
        readonly=True,
    )
    data_retrieved = fields.Integer(string='Data Retrieved', readonly=True)
    staging_created = fields.Integer(string='Staging Created', readonly=True)
    records_created = fields.Integer(string='Records Created', readonly=True)
    records_errors = fields.Integer(string='Records Errors', readonly=True)
    records_skipped = fields.Integer(string='Records Skipped', readonly=True)
