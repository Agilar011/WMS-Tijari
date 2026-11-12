import logging
from datetime import datetime, time, timedelta, timezone

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_SCHEDULER_MASTER_FETCH_PAGE_SIZE = 5000
# Customer responses time out at the general 5,000-row page size.
_SCHEDULER_MASTER_FETCH_PAGE_SIZES = {'customer': 1000}
_SCHEDULER_MASTER_FETCH_METHODS = {
    'customer': 'fetch_all_customer_data',
    'warehouse': 'fetch_all_warehouse_data',
    'stock_item': 'fetch_all_stock_item_data',
    'non_stock_item': 'fetch_all_non_stock_item_data',
    'uom': 'fetch_all_uom_data',
    'vendor': 'fetch_all_vendor_data',
}


class AcumaticaCronJob(models.Model):
    _inherit = 'acumatica.config'
    _description = 'Cronjob'

    def _get_scheduler_fetch_options(self):
        """Read bounded scheduler fetch settings from Odoo system parameters."""
        params = self.env['ir.config_parameter'].sudo()
        raw_limit = params.get_param(
            'acumatica_all_import.scheduler_fetch_limit_per_type', default='5000',
        )
        raw_batch_size = params.get_param(
            'acumatica_all_import.scheduler_batch_size', default='1000',
        )
        try:
            fetch_limit = int(raw_limit)
            batch_size = int(raw_batch_size)
        except (TypeError, ValueError) as exc:
            raise UserError(
                'API Data Hub scheduler_fetch_limit_per_type and scheduler_batch_size '
                'must be positive integers.'
            ) from exc

        if fetch_limit <= 0:
            raise UserError('API Data Hub scheduler_fetch_limit_per_type must be greater than zero.')
        if batch_size <= 0 or batch_size > 1000:
            raise UserError(
                'API Data Hub scheduler_batch_size must be between 1 and 1000 '
                'to keep each request and ORM batch bounded.'
            )
        if batch_size > fetch_limit:
            raise UserError(
                'API Data Hub scheduler_batch_size cannot exceed scheduler_fetch_limit_per_type.'
            )
        return fetch_limit, batch_size

    def _run_scheduler_data_types(self, data_types, phase):
        """Run selected Import Data types from an API Data Hub scheduler job."""
        ImportWizard = self.env['acumatica.unified.import.wizard']
        category = self.env.context.get('api_scheduler_data_category')
        results = {}
        fetch_limit, batch_size = self._get_scheduler_fetch_options()

        if phase == 'import' and not self.env.context.get('api_scheduler_combined_run'):
            job_type = self.env.context.get('api_scheduler_job_type')
            fetch_job_type = {
                'import_all_master': 'fetch_all_master',
                'import_all_transaction': 'fetch_all_transaction',
                'import_selected': 'fetch_selected',
            }.get(job_type)
            fetch_jobs = self.env['api.scheduler.job'].search([
                ('job_type', '=', fetch_job_type),
            ]) if fetch_job_type else self.env['api.scheduler.job']
            if job_type == 'import_selected':
                fetch_jobs = fetch_jobs.filtered(
                    lambda job: job.selected_data_category == category
                    and set(data_types).intersection(job.selected_data_type_ids.mapped('code'))
                )
            fetch_logs = self.env['api.scheduler.log'].search(
                [('scheduler_job_id', 'in', fetch_jobs.ids)],
                order='execution_time desc, id desc',
            )
            if fetch_logs and fetch_logs[0].status == 'running':
                return {'fetch': self._cron_result(
                    success=False, records_errors=1,
                    message='Import ditahan: scheduler fetch masih berjalan.',
                )}
            if not fetch_logs:
                return {'fetch': self._cron_result(
                    success=False, records_errors=1,
                    message='Import ditahan: belum ada log fetch untuk kategori ini.',
                )}
            successful_types = set(
                fetch_logs[0].detail_ids.filtered(
                    lambda detail: not detail.records_errors and detail.data_retrieved > 0
                )
                .mapped('acumatica_data')
            )
            data_types = [key for key in data_types if key in successful_types]
            if not data_types:
                return {'fetch': self._cron_result(
                    success=False, records_errors=1,
                    message='Import ditahan: tidak ada tipe data yang berhasil di-fetch pada run terakhir.',
                )}

        for key in data_types:
            info = ImportWizard.IMPORT_MAP.get(key)
            if not info:
                results[key] = self._cron_result(
                    success=False, records_errors=1,
                    message='Unsupported Import Data type: %s' % key,
                )
                self._update_live_scheduler_log(key, results[key])
                continue

            type_category = 'master' if key in ImportWizard.MASTER_DATA_TYPES else 'transaction'
            if category and category != type_category:
                results[key] = self._cron_result(
                    success=False, records_errors=1,
                    message='Data type category does not match scheduler selection.',
                )
                self._update_live_scheduler_log(key, results[key])
                continue

            config = self._get_default_config_for_type(key)
            if not config:
                results[key] = self._cron_result(
                    success=False, records_errors=1,
                    message='No active API configuration found for %s.' % info['label'],
                )
                self._update_live_scheduler_log(key, results[key])
                continue

            Line = self.env[info['line_model']]
            wizard_values = {
                'import_category': type_category,
                'import_type': key,
                'import_type_master': key if type_category == 'master' else 'customer',
                'import_type_transaction': key if type_category == 'transaction' else 'po_receipt',
                'config_id': config.id,
                'fetch_limit': fetch_limit,
                'batch_size': batch_size,
                'fetch_skip': 0,
            }
            def process_data_type():
                wizard = ImportWizard.create(wizard_values)
                if phase == 'fetch':
                    try:
                        if type_category == 'master':
                            fetch_method_name = _SCHEDULER_MASTER_FETCH_METHODS.get(key)
                            if not fetch_method_name:
                                raise UserError(
                                    'No complete scheduler fetch handler is configured for %s.' % key
                                )
                            source_wizard = self.env[info['wizard_model']].create(
                                wizard._prepare_source_wizard_vals(info, config)
                            )
                            fetch_method = getattr(source_wizard, fetch_method_name, None)
                            if not fetch_method:
                                raise UserError(
                                    'Scheduler fetch handler %s is missing for %s.'
                                    % (fetch_method_name, key)
                                )
                            fetch_page_size = _SCHEDULER_MASTER_FETCH_PAGE_SIZES.get(
                                key, _SCHEDULER_MASTER_FETCH_PAGE_SIZE,
                            )
                            fetched_count = fetch_method(batch_size=fetch_page_size) or 0
                            wizard.write({'total_fetched': fetched_count})
                        else:
                            wizard.action_fetch_data()
                            fetched_count = wizard.total_fetched or 0
                    except UserError as exc:
                        if 'Tidak ada data' not in str(exc):
                            raise
                        fetched_count = 0
                    results[key] = self._cron_result(data_retrieved=fetched_count)
                else:
                    domain = [('import_state', '=', 'staged')]
                    if 'config_id' in Line._fields:
                        domain.append(('config_id', '=', config.id))
                    pending_count = Line.search_count(domain)
                    if not pending_count:
                        results[key] = self._cron_result()
                    elif not hasattr(Line, '_do_import'):
                        results[key] = self._cron_result(
                            data_retrieved=pending_count,
                            records_skipped=pending_count,
                            message='Staging model has no import handler.',
                        )
                    else:
                        initial_pending = Line.search(domain, order='id desc', limit=1)
                        if not initial_pending:
                            raise UserError(
                                'Staged records changed before the scheduler could start importing.'
                            )
                        summary = wizard.with_context(
                            api_scheduler_collect_import_summary=True,
                            api_scheduler_pending_count=pending_count,
                            api_scheduler_pending_max_id=initial_pending.id,
                        ).action_import_pending_batch()
                        results[key] = self._cron_result(
                            data_retrieved=summary['data_retrieved'],
                            records_created=summary['records_created'],
                            records_errors=summary['records_errors'],
                            records_skipped=summary['records_skipped'],
                        )

            try:
                # Fetch and import handlers may commit internally. An outer
                # savepoint would be invalidated by those commits and could
                # leave the cursor transaction aborted on error.
                process_data_type()
            except Exception as exc:
                # Clear any failed SQL transaction before persisting the
                # per-type failure result. Completed internal commits remain
                # durable; only work since the most recent commit is rolled back.
                self.env.cr.rollback()
                self.env.invalidate_all()
                _logger.exception('API Data Hub scheduler failed for data type %s.', key)
                results[key] = self._cron_result(
                    success=False, records_errors=1, records_skipped=1,
                    message=str(exc),
                )
            self._update_live_scheduler_log(key, results[key])

        return results

    def _cron_result(self, success=True, data_retrieved=0, records_created=0, records_errors=0, records_skipped=0, message=False):
        return {
            'success': success,
            'data_retrieved': data_retrieved,
            'records_created': records_created,
            'records_errors': records_errors,
            'records_skipped': records_skipped,
            'message': message,
        }

    def _run_import_step(self, key, runner, batch_size=1000, fetch_skip=0):
        """Run one legacy import step and persist its scheduler progress."""
        try:
            result = runner(batch_size=batch_size, fetch_skip=fetch_skip)
            if not isinstance(result, dict):
                result = self._cron_result(success=bool(result))
        except Exception as exc:
            self.env.cr.rollback()
            _logger.exception("Cron import %s skipped because of an error.", key)
            result = self._cron_result(
                success=False,
                records_errors=1,
                records_skipped=1,
                message=str(exc),
            )
        self._update_live_scheduler_log(key, result)
        return result

    def _update_live_scheduler_log(self, key, result):
        """Persist one completed data-type result to the scheduler's live log."""
        log_id = self.env.context.get('api_scheduler_log_id')
        if not log_id:
            return
        Log = self.env['api.scheduler.log'].sudo()
        log = Log.browse(log_id).exists()
        if not log:
            return

        values = result if isinstance(result, dict) else {}
        detail = log.detail_ids.filtered(lambda item: item.acumatica_data == key)[:1]
        detail_values = {
            'data_type': log.scheduler_job_id._get_scheduler_data_category(),
            'acumatica_data': key,
            'data_retrieved': max(values.get('data_retrieved', 0), 0),
            'staging_created': max(
                values.get('data_retrieved', 0)
                if log.scheduler_job_id.job_type in (
                    'fetch_all_master', 'fetch_all_transaction', 'fetch_selected',
                    'fetch_import_all_master', 'fetch_import_all_transaction',
                )
                else 0,
                0,
            ),
            'records_created': max(values.get('records_created', 0), 0),
            'records_errors': max(values.get('records_errors', 0), 0),
            'records_skipped': max(values.get('records_skipped', 0), 0),
        }
        if self.env.context.get('api_scheduler_combined_phase') == 'import' and detail:
            # A combined run keeps the fetch totals and adds the import outcome
            # to the same per-type detail row.
            detail_values['data_retrieved'] = detail.data_retrieved
            detail_values['staging_created'] = detail.staging_created
        if detail:
            detail.write(detail_values)
        else:
            detail = self.env['api.scheduler.log.detail'].sudo().create(
                dict(detail_values, scheduler_log_id=log.id)
            )

        details = log.detail_ids
        log.write({
            'data_retrieved': sum(details.mapped('data_retrieved')),
            'staging_created': sum(details.mapped('staging_created')),
            'records_created': sum(details.mapped('records_created')),
            'records_errors': sum(details.mapped('records_errors')),
            'records_skipped': sum(details.mapped('records_skipped')),
        })
        self.env.cr.commit()

    def _get_import_counts(self, model_name, line_ids, skipped_states=False):
        Line = self.env[model_name]
        domain = [('id', 'in', line_ids)]
        state_counts = dict(Line._read_group(domain, ['import_state'], ['__count']))
        skipped_count = sum(state_counts.get(state, 0) for state in skipped_states or ())
        return (
            state_counts.get('created', 0),
            state_counts.get('updated', 0),
            state_counts.get('error', 0),
            skipped_count,
        )

    def _get_transaction_import_definitions(self):
        return [
            ('po_receipt', 'PO Receipt', 'import.receipt.wizard', 'acumatica.receipt.line', 'put'),
            ('so_transfer', 'Transfer (In/SOTR)', 'import.transfer.wizard', 'acumatica.transfer.line', 'put'),
            ('inventory_received', 'Receipt : Inventory Receipt', 'import.inventory.recieved.wizard', 'acumatica.inventory.recieved.line', 'put'),
            ('shipment_so', 'SO Return', 'import.shipment.wizard', 'acumatica.shipment.line', 'put'),
            ('so_shipment', 'SO Shipment', 'import.so.shipment.wizard', 'acumatica.shipment.gi.staging', 'put'),
            ('transfer_shipment', 'Transfer (Out/Shipment)', 'import.transfer.shipment.wizard', 'acumatica.transfer.shipment.line', 'put'),
            ('inventory_issue', 'Issue : Inventory Issue', 'import.inventory.issue.wizard', 'acumatica.inventory.issue.line', 'put'),
            ('issue_po_return', 'PO Return', 'import.issue.po.return.wizard', 'acumatica.issue.po.return.line', 'put'),
            ('transfer_one_step', 'Transfer 1 Step', 'import.transfer.one.step.wizard', 'acumatica.transfer.one.step.line', 'put'),
            ('transfer_two_step', 'Transfer 2 Step', 'import.transfer.two.step.wizard', 'acumatica.transfer.two.step.line', 'put'),
            ('shipment_completed', 'Update SO completed', 'import.shipment.completed.wizard', 'acumatica.shipment.completed.staging', 'put'),
            ('kit_assembly', 'Manufacturing Order', 'import.kit.assembly.wizard', 'acumatica.kit.assembly', 'put'),
            ('invoice_consignment', 'Invoice Consignment', 'import.invoice.consignment.wizard', 'acumatica.invoice.consignment.staging', 'put'),
            ('credit_memo_consignment', 'Credit Memo Consignment', 'import.credit.memo.consignment.wizard', 'acumatica.credit.memo.consignment.staging', 'put'),
        ]

    def _get_transaction_date_filter_values(self, days=30):
        today = fields.Date.context_today(self)
        start_date = today - timedelta(days=days)
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        return start_date, today, start_dt.isoformat().replace('+00:00', 'Z')

    def _prepare_transaction_wizard_values(self, wizard_model, config, method, batch_size, fetch_skip):
        Wizard = self.env[wizard_model]
        values = {'config_id': config.id}
        if 'batch_size' in Wizard._fields:
            values['batch_size'] = batch_size
        if 'fetch_limit' in Wizard._fields:
            values['fetch_limit'] = batch_size
        if 'fetch_skip' in Wizard._fields:
            values['fetch_skip'] = fetch_skip
        if method == 'get':
            start_date, end_date, last_modified_from = self._get_transaction_date_filter_values()
            if 'odata_filter' in Wizard._fields:
                end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
                end_dt_str = end_dt.isoformat().replace('+00:00', 'Z')
                odata_filters = []
                if config.odata_filter:
                    odata_filters.append("(%s)" % config.odata_filter)
                if config.endpoint_name != 'Shipment':
                    odata_filters.append(
                        "Date ge datetimeoffset'%s' and Date le datetimeoffset'%s'"
                        % (last_modified_from, end_dt_str)
                    )
                odata_filters.append("LastModifiedDateTime ge datetimeoffset'%s'" % last_modified_from)
                values['odata_filter'] = ' and '.join(odata_filters)
        return values

    def _get_importable_lines(self, model_name, config):
        Line = self.env[model_name]
        domain = [('import_state', '=', 'staged')]
        config_field = Line._fields.get('config_id')
        if config_field and getattr(config_field, 'comodel_name', False) == 'acumatica.config':
            domain.append(('config_id', '=', config.id))
        if 'selected' in Line._fields:
            domain.append(('selected', '=', True))
        return Line.search(domain)

    def _import_master_lines_in_batches(self, model_name, config, batch_size=1000):
        """Import master staging rows in bounded batches.

        The upper id boundary prevents rows created during the import from
        being pulled into the same run. The id cursor also guarantees forward
        progress when an importer leaves a row in ``staged`` after processing.
        """
        Line = self.env[model_name]
        domain = [('import_state', '=', 'staged')]
        config_field = Line._fields.get('config_id')
        if config_field and getattr(config_field, 'comodel_name', False) == 'acumatica.config':
            domain.append(('config_id', '=', config.id))
        if 'selected' in Line._fields:
            domain.append(('selected', '=', True))

        max_id = Line.search([], order='id desc', limit=1).id
        last_id = 0
        imported_ids = []
        batch_number = 0
        while True:
            batch = Line.search(
                domain + [('id', '>', last_id), ('id', '<=', max_id)],
                order='id asc',
                limit=batch_size,
            )
            if not batch:
                break

            batch_number += 1
            _logger.info(
                "MASTER IMPORT BATCH; MODEL=%s, BATCH=%s, SIZE=%s, FIRST_ID=%s, LAST_ID=%s",
                model_name,
                batch_number,
                len(batch),
                batch[0].id,
                batch[-1].id,
            )
            imported_ids.extend(batch.ids)
            last_id = batch[-1].id
            batch._do_import()

        return Line.browse(imported_ids)

    def _run_master_import_only_job(self, batch_size=1000):
        """Import master staging rows after the separate fetch phase completed."""
        successful_types = self.env.context.get('acumatica_successful_master_types')
        import_scheduler_code = self.env.context.get('acumatica_scheduler_code')
        if successful_types:
            definitions_filter = set(successful_types)
        else:
            definitions_filter = None

        if import_scheduler_code and not successful_types:
            fetch_job = self.env['api.scheduler.job'].search([
                ('code', '=', 'acumatica_master_fetch'),
            ], limit=1)
            import_job = self.env['api.scheduler.job'].search([
                ('code', '=', import_scheduler_code),
            ], limit=1)
            last_fetch = self.env['api.scheduler.log'].search([
                ('scheduler_job_id', '=', fetch_job.id),
                ('status', '=', 'success'),
            ], order='execution_time desc, id desc', limit=1)
            last_import = self.env['api.scheduler.log'].search([
                ('scheduler_job_id', '=', import_job.id),
                ('status', '=', 'success'),
            ], order='execution_time desc, id desc', limit=1)
            if not last_fetch or (
                last_import and last_fetch.execution_time <= last_import.execution_time
            ):
                return {
                    'master': self._cron_result(
                        success=False,
                        records_errors=1,
                        message='Import ditahan: fetch master terakhir belum selesai atau belum berhasil.',
                    )
                }

        definitions = [
            ('customer', 'acumatica.customer.line'),
            ('vendor', 'acumatica.vendor.line'),
            ('uom', 'acumatica.uom.line'),
            ('warehouse', 'acumatica.warehouse.line'),
            ('stock_item', 'acumatica.stock.item.line'),
            ('non_stock_item', 'acumatica.non.stock.item.line'),
        ]
        results = {}
        for key, line_model in definitions:
            if definitions_filter is not None and key not in definitions_filter:
                continue
            config = self._get_default_config_for_type(key)
            if not config:
                results[key] = self._cron_result(
                    success=False,
                    records_errors=1,
                    message='No active %s config found.' % key,
                )
                self._update_live_scheduler_log(key, results[key])
                continue

            lines = self._get_importable_lines(line_model, config)
            if not lines:
                results[key] = self._cron_result()
                self._update_live_scheduler_log(key, results[key])
                continue

            imported = self._import_master_lines_in_batches(
                line_model,
                config,
                batch_size=batch_size,
            )
            imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
                line_model,
                imported.ids,
                skipped_states=['rejected'],
            )
            results[key] = self._cron_result(
                data_retrieved=len(lines),
                records_created=imported_count + updated_count,
                records_errors=error_count,
                records_skipped=skipped_count,
            )
            self._update_live_scheduler_log(key, results[key])
        return results

    def _run_transaction_import_only_job(self, batch_size=1000):
        """Import only transaction types completed by the preceding fetch phase."""
        successful_types = set(self.env.context.get('acumatica_successful_transaction_types') or [])
        if not successful_types:
            return {
                'transaction': self._cron_result(
                    success=False,
                    records_errors=1,
                    message='Import transaksi ditahan: tidak ada fetch transaksi yang berhasil.',
                )
            }

        results = {}
        for key, label, wizard_model, line_model, method in self._get_transaction_import_definitions():
            if key not in successful_types:
                continue
            config = self._get_default_config_for_type(key)
            if not config:
                results[key] = self._cron_result(
                    success=False,
                    records_errors=1,
                    message='No active %s config found.' % key,
                )
                self._update_live_scheduler_log(key, results[key])
                continue

            lines = self._get_importable_lines(line_model, config)
            if not lines:
                results[key] = self._cron_result()
                self._update_live_scheduler_log(key, results[key])
                continue
            if not hasattr(lines, '_do_import'):
                results[key] = self._cron_result(data_retrieved=len(lines))
                self._update_live_scheduler_log(key, results[key])
                continue

            imported_count = updated_count = error_count = skipped_count = 0
            for offset in range(0, len(lines), batch_size):
                batch = lines[offset:offset + batch_size]
                batch._do_import()
                counts = self._get_import_counts(
                    line_model,
                    batch.ids,
                    skipped_states=['rejected'],
                )
                imported_count += counts[0]
                updated_count += counts[1]
                error_count += counts[2]
                skipped_count += counts[3]

            results[key] = self._cron_result(
                data_retrieved=len(lines),
                records_created=imported_count + updated_count,
                records_errors=error_count,
                records_skipped=skipped_count,
            )
            self._update_live_scheduler_log(key, results[key])
        return results

    def _run_generic_transaction_import_job(self, key, batch_size=1000, fetch_skip=0):
        definition = False
        for item in self._get_transaction_import_definitions():
            if item[0] == key:
                definition = item
                break
        if not definition:
            return self._cron_result(success=False, records_errors=1, message='Unsupported transaction import: %s' % key)

        key, label, wizard_model, line_model, method = definition
        config = self._get_default_config_for_type(key)
        if not config:
            _logger.warning("Cron import %s skipped: no active %s config found.", label, key)
            return self._cron_result(message='No active %s config found; skipped.' % key)

        wizard = self.env[wizard_model].create(
            self._prepare_transaction_wizard_values(wizard_model, config, method, batch_size, fetch_skip)
        )

        try:
            wizard.action_fetch_data()
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import %s finished: no data returned from Acumatica.", label)
                return self._cron_result()
            raise

        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)
        lines = self._get_importable_lines(line_model, config)
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import %s finished: no pending staging lines.", label)
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        if not hasattr(lines, '_do_import'):
            _logger.info("Cron import %s finished: staging fetch only; model has no _do_import.", label)
            return self._cron_result(data_retrieved=data_retrieved)

        _logger.info("Cron import %s starting _do_import; PENDING_LINES=%s", label, pending_count)
        lines._do_import()

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            line_model,
            lines.ids,
            skipped_states=['rejected'],
        )
        records_created = imported_count + updated_count
        records_skipped = skipped_count + max(data_retrieved - records_created - error_count - skipped_count, 0)
        _logger.info(
            "Cron import %s finished _do_import; RETRIEVED=%s, PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, SKIPPED=%s, ERROR=%s",
            label,
            data_retrieved,
            pending_count,
            imported_count,
            updated_count,
            skipped_count,
            error_count,
        )
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=records_skipped,
        )

    def _run_customer_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Customer data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('customer')
        if not config:
            _logger.warning("Cron import Customer skipped: no active customer config found.")
            return self._cron_result(success=False, records_errors=1, message='No active customer config found.')

        wizard = self.env['import.customer.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_customer_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data dari API' in str(exc):
                _logger.info("Cron import Customer finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.customer.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Customer finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Customer starting _do_import; PENDING_LINES=%s", pending_count)
        lines = self._import_master_lines_in_batches('acumatica.customer.line', config, batch_size=1000)

        Line = self.env['acumatica.customer.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'created'),
        ])
        updated_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'updated'),
        ])
        error_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'error'),
        ])
        linked_partner_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('odoo_partner_id', '!=', False),
        ])

        _logger.info(
            "Cron import Customer finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, ERROR=%s, WITH_ODOO_PARTNER=%s",
            pending_count,
            imported_count,
            updated_count,
            error_count,
            linked_partner_count,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=max(data_retrieved - records_created - error_count, 0),
        )

    def _run_vendor_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Vendor data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('vendor')
        if not config:
            _logger.warning("Cron import Vendor skipped: no active vendor config found.")
            return self._cron_result(success=False, records_errors=1, message='No active vendor config found.')

        wizard = self.env['import.vendor.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_vendor_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data dari API' in str(exc):
                _logger.info("Cron import Vendor finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.vendor.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Vendor finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Vendor starting _do_import; PENDING_LINES=%s", pending_count)
        lines = self._import_master_lines_in_batches('acumatica.vendor.line', config, batch_size=1000)

        Line = self.env['acumatica.vendor.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'created'),
        ])
        updated_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'updated'),
        ])
        error_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'error'),
        ])
        linked_partner_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('odoo_partner_id', '!=', False),
        ])

        _logger.info(
            "Cron import Vendor finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, ERROR=%s, WITH_ODOO_PARTNER=%s",
            pending_count,
            imported_count,
            updated_count,
            error_count,
            linked_partner_count,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=max(data_retrieved - records_created - error_count, 0),
        )

    def _run_stock_item_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Stock Item data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('stock_item')
        if not config:
            _logger.warning("Cron import Stock Item skipped: no active stock_item config found.")
            return self._cron_result(success=False, records_errors=1, message='No active stock_item config found.')

        wizard = self.env['import.stock.item.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_stock_item_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import Stock Item finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.stock.item.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Stock Item finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Stock Item starting _do_import; PENDING_LINES=%s", pending_count)
        lines = self._import_master_lines_in_batches('acumatica.stock.item.line', config, batch_size=1000)

        Line = self.env['acumatica.stock.item.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'created'),
        ])
        updated_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'updated'),
        ])
        error_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'error'),
        ])
        linked_product_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('odoo_product_id', '!=', False),
        ])

        _logger.info(
            "Cron import Stock Item finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, ERROR=%s, WITH_ODOO_PRODUCT=%s",
            pending_count,
            imported_count,
            updated_count,
            error_count,
            linked_product_count,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=max(data_retrieved - records_created - error_count, 0),
        )

    def _run_non_stock_item_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Non-Stock Item data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('non_stock_item')
        if not config:
            _logger.warning("Cron import Non-Stock Item skipped: no active non_stock_item config found.")
            return self._cron_result(success=False, records_errors=1, message='No active non_stock_item config found.')

        wizard = self.env['import.non.stock.item.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_non_stock_item_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import Non-Stock Item finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.non.stock.item.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Non-Stock Item finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Non-Stock Item starting _do_import; PENDING_LINES=%s", pending_count)
        lines = self._import_master_lines_in_batches('acumatica.non.stock.item.line', config, batch_size=1000)

        Line = self.env['acumatica.non.stock.item.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'created'),
        ])
        updated_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'updated'),
        ])
        error_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'error'),
        ])
        linked_product_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('odoo_product_id', '!=', False),
        ])

        _logger.info(
            "Cron import Non-Stock Item finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, ERROR=%s, WITH_ODOO_PRODUCT=%s",
            pending_count,
            imported_count,
            updated_count,
            error_count,
            linked_product_count,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=max(data_retrieved - records_created - error_count, 0),
        )

    def _run_uom_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch UoM data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('uom')
        if not config:
            _logger.warning("Cron import UoM skipped: no active uom config found.")
            return self._cron_result(success=False, records_errors=1, message='No active uom config found.')

        wizard = self.env['import.uom.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_uom_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import UoM finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.uom.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import UoM finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import UoM starting _do_import; PENDING_LINES=%s", pending_count)
        lines = self._import_master_lines_in_batches('acumatica.uom.line', config, batch_size=1000)

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            'acumatica.uom.line',
            lines.ids,
            skipped_states=['rejected'],
        )
        records_created = imported_count + updated_count
        records_skipped = skipped_count + max(data_retrieved - records_created - error_count - skipped_count, 0)
        _logger.info(
            "Cron import UoM finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, SKIPPED=%s, ERROR=%s",
            pending_count,
            imported_count,
            updated_count,
            skipped_count,
            error_count,
        )
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=records_skipped,
        )

    def _run_warehouse_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Warehouse data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('warehouse')
        if not config:
            _logger.warning("Cron import Warehouse skipped: no active warehouse config found.")
            return self._cron_result(success=False, records_errors=1, message='No active warehouse config found.')

        wizard = self.env['import.warehouse.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_warehouse_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import Warehouse finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.warehouse.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Warehouse finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Warehouse starting _do_import; PENDING_LINES=%s", pending_count)
        lines = self._import_master_lines_in_batches('acumatica.warehouse.line', config, batch_size=1000)

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            'acumatica.warehouse.line',
            lines.ids,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=skipped_count + max(data_retrieved - records_created - error_count - skipped_count, 0),
        )

    def _run_po_receipt_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch PO Receipt data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('po_receipt')
        if not config:
            _logger.warning("Cron import PO Receipt skipped: no active po_receipt config found.")
            return self._cron_result(success=False, records_errors=1, message='No active po_receipt config found.')

        wizard = self.env['import.receipt.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_limit': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.action_fetch_data()
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import PO Receipt finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.receipt.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import PO Receipt finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import PO Receipt starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        Line = self.env['acumatica.receipt.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'created'),
        ])
        updated_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'updated'),
        ])
        error_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'error'),
        ])
        linked_picking_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('odoo_picking_id', '!=', False),
        ])

        _logger.info(
            "Cron import PO Receipt finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, ERROR=%s, WITH_ODOO_PICKING=%s",
            pending_count,
            imported_count,
            updated_count,
            error_count,
            linked_picking_count,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=max(data_retrieved - records_created - error_count, 0),
        )

    def _run_shipment_so_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch SO Return Shipment data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('shipment_so')
        if not config:
            _logger.warning("Cron import SO Return skipped: no active shipment_so config found.")
            return self._cron_result(success=False, records_errors=1, message='No active shipment_so config found.')

        wizard = self.env['import.shipment.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_shipment_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import SO Return finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0
        if self.env.context.get('acumatica_process_phase') == 'fetch':
            return self._cron_result(data_retrieved=data_retrieved)

        lines = self.env['acumatica.shipment.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import SO Return finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import SO Return starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            'acumatica.shipment.line',
            lines.ids,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=skipped_count + max(data_retrieved - records_created - error_count - skipped_count, 0),
        )

    @api.model
    def _cron_import_master_data(self, batch_size=1000, fetch_skip=0):
        """Run master data in the configured fetch/import phase."""
        _logger.info(
            "START CRON IMPORT MASTER DATA; BATCH_SIZE=%s, FETCH_SKIP=%s",
            batch_size,
            fetch_skip,
        )
        if self.env.context.get('acumatica_process_phase') == 'import':
            results = self._run_master_import_only_job(batch_size=batch_size)
        else:
            results = {
            'customer': self._run_import_step('customer', self._run_customer_import_job, batch_size, fetch_skip),
            'vendor': self._run_import_step('vendor', self._run_vendor_import_job, batch_size, fetch_skip),
            'uom': self._run_import_step('uom', self._run_uom_import_job, batch_size, fetch_skip),
            'warehouse': self._run_import_step('warehouse', self._run_warehouse_import_job, batch_size, fetch_skip),
            'stock_item': self._run_import_step('stock_item', self._run_stock_item_import_job, batch_size, fetch_skip),
            'non_stock_item': self._run_import_step('non_stock_item', self._run_non_stock_item_import_job, batch_size, fetch_skip),
            }
        _logger.info("FINISH CRON IMPORT MASTER DATA; RESULTS=%s", results)
        return results

    @api.model
    def _cron_import_transaction_data(self, batch_size=1000, fetch_skip=0):
        """Run transaction imports with method-specific fetch rules."""
        _logger.info(
            "START CRON IMPORT TRANSACTION DATA; BATCH_SIZE=%s, FETCH_SKIP=%s",
            batch_size,
            fetch_skip,
        )
        if self.env.context.get('acumatica_process_phase') == 'import':
            results = self._run_transaction_import_only_job(batch_size=batch_size)
        else:
            results = {}
            for key, label, wizard_model, line_model, method in self._get_transaction_import_definitions():
                results[key] = self._run_import_step(
                    key,
                    lambda batch_size, fetch_skip, import_key=key: self._run_generic_transaction_import_job(
                        import_key,
                        batch_size=batch_size,
                        fetch_skip=fetch_skip,
                    ),
                    batch_size,
                    fetch_skip,
                )
        _logger.info("FINISH CRON IMPORT TRANSACTION DATA; RESULTS=%s", results)
        return results
