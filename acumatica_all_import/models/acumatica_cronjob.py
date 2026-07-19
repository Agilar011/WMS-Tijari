import logging

from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaCronJob(models.Model):
    _inherit = 'acumatica.config'
    _description = 'Cronjob'

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
        try:
            with self.env.cr.savepoint():
                result = runner(batch_size=batch_size, fetch_skip=fetch_skip)
            if isinstance(result, dict):
                return result
            return self._cron_result(success=bool(result))
        except Exception as exc:
            _logger.exception("Cron import %s failed.", key)
            return self._cron_result(
                success=False,
                records_errors=1,
                message=str(exc),
            )

    def _get_import_counts(self, model_name, line_ids, skipped_states=False):
        Line = self.env[model_name]
        domain = [('id', 'in', line_ids)]
        imported_count = Line.search_count(domain + [('import_state', '=', 'imported')])
        updated_count = Line.search_count(domain + [('import_state', '=', 'updated')])
        error_count = Line.search_count(domain + [('import_state', '=', 'error')])
        skipped_count = 0
        if skipped_states:
            skipped_count = Line.search_count(domain + [('import_state', 'in', skipped_states)])
        return imported_count, updated_count, error_count, skipped_count

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

        lines = self.env['acumatica.customer.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Customer finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Customer starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        Line = self.env['acumatica.customer.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'imported'),
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

    def _run_customer_location_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Customer Location data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('customer_location')
        if not config:
            _logger.warning("Cron import Customer Location skipped: no active customer_location config found.")
            return self._cron_result(success=False, records_errors=1, message='No active customer_location config found.')

        wizard = self.env['import.customer.location.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_customer_location_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data dari API' in str(exc):
                _logger.info("Cron import Customer Location finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0

        lines = self.env['acumatica.customer.location.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Customer Location finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Customer Location starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        Line = self.env['acumatica.customer.location.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'imported'),
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
            "Cron import Customer Location finished _do_import; PENDING_BEFORE=%s, IMPORTED=%s, UPDATED=%s, ERROR=%s, WITH_ODOO_PARTNER=%s",
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

        lines = self.env['acumatica.vendor.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Vendor finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Vendor starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        Line = self.env['acumatica.vendor.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'imported'),
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

        lines = self.env['acumatica.stock.item.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Stock Item finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Stock Item starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        Line = self.env['acumatica.stock.item.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'imported'),
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

        lines = self.env['acumatica.non.stock.item.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Non-Stock Item finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Non-Stock Item starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        Line = self.env['acumatica.non.stock.item.line']
        imported_count = Line.search_count([
            ('id', 'in', lines.ids),
            ('import_state', '=', 'imported'),
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

        lines = self.env['acumatica.uom.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import UoM finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import UoM starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            'acumatica.uom.line',
            lines.ids,
            skipped_states=['skipped'],
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

        lines = self.env['acumatica.warehouse.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Warehouse finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Warehouse starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

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

        lines = self.env['acumatica.receipt.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
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
            ('import_state', '=', 'imported'),
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

        lines = self.env['acumatica.shipment.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
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

    def _run_receipt_external_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Receipt External data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('receipt_external')
        if not config:
            _logger.warning("Cron import Receipt External skipped: no active receipt_external config found.")
            return self._cron_result(success=False, records_errors=1, message='No active receipt_external config found.')

        wizard = self.env['import.receipt.external.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_limit': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.action_fetch_data()
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import Receipt External finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0

        lines = self.env['acumatica.receipt.external.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Receipt External finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Receipt External starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            'acumatica.receipt.external.line',
            lines.ids,
        )
        records_created = imported_count + updated_count
        return self._cron_result(
            data_retrieved=data_retrieved,
            records_created=records_created,
            records_errors=error_count,
            records_skipped=skipped_count + max(data_retrieved - records_created - error_count - skipped_count, 0),
        )

    def _run_toko_pegang_do_import_job(self, batch_size=1000, fetch_skip=0):
        """Fetch Toko Pegang DO data from Acumatica and import pending staging lines."""
        config = self._get_default_config_for_type('toko_pegang_do')
        if not config:
            _logger.warning("Cron import Toko Pegang DO skipped: no active toko_pegang_do config found.")
            return self._cron_result(success=False, records_errors=1, message='No active toko_pegang_do config found.')

        wizard = self.env['import.toko.pegang.do.wizard'].create({
            'config_id': config.id,
            'batch_size': batch_size,
            'fetch_skip': fetch_skip,
        })

        try:
            wizard.fetch_all_toko_pegang_do_data(batch_size=batch_size)
        except UserError as exc:
            if 'Tidak ada data' in str(exc):
                _logger.info("Cron import Toko Pegang DO finished: no data returned from Acumatica.")
                return self._cron_result()
            raise
        data_retrieved = wizard.total_fetched or 0

        lines = self.env['acumatica.toko.pegang.do.line'].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        pending_count = len(lines)
        if not lines:
            _logger.info("Cron import Toko Pegang DO finished: no pending staging lines.")
            return self._cron_result(data_retrieved=data_retrieved, records_skipped=data_retrieved)

        _logger.info("Cron import Toko Pegang DO starting _do_import; PENDING_LINES=%s", pending_count)
        lines._do_import()

        imported_count, updated_count, error_count, skipped_count = self._get_import_counts(
            'acumatica.toko.pegang.do.line',
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
        """Run Master Data imports in dependency order."""
        _logger.info(
            "START CRON IMPORT MASTER DATA; BATCH_SIZE=%s, FETCH_SKIP=%s",
            batch_size,
            fetch_skip,
        )
        results = {
            'customer': self._run_import_step('customer', self._run_customer_import_job, batch_size, fetch_skip),
            # 'customer_location': self._run_import_step('customer_location', self._run_customer_location_import_job, batch_size, fetch_skip),
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
        """Run transaction imports. PO Receipt is the first supported transaction API."""
        _logger.info(
            "START CRON IMPORT TRANSACTION DATA; BATCH_SIZE=%s, FETCH_SKIP=%s",
            batch_size,
            fetch_skip,
        )
        results = {
            'po_receipt': self._run_import_step('po_receipt', self._run_po_receipt_import_job, batch_size, fetch_skip),
            'shipment_so': self._run_import_step('shipment_so', self._run_shipment_so_import_job, batch_size, fetch_skip),
            'receipt_external': self._run_import_step('receipt_external', self._run_receipt_external_import_job, batch_size, fetch_skip),
            'toko_pegang_do': self._run_import_step('toko_pegang_do', self._run_toko_pegang_do_import_job, batch_size, fetch_skip),
        }
        _logger.info("FINISH CRON IMPORT TRANSACTION DATA; RESULTS=%s", results)
        return results
