import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportInventoryStockWizard(models.TransientModel):
    _name = 'import.inventory.stock.wizard'
    _description = 'Wizard Import Inventory Stock dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    warehouse_value = fields.Char(string='Warehouse', default='WH33-FG')
    inventory_id_value = fields.Char(string='InventoryID')
    odata_expand = fields.Char(string='OData Expand', default='InventorySiteInquiryDetails')
    odata_top = fields.Integer(string='OData Top', default=1)

    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=50,
        help='Sesuai spesifikasi: default 50 data customer',
    )
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Data Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada', readonly=True)

    @api.onchange('config_id')
    def _onchange_config_id(self):
        if not self.config_id:
            return
        self.odata_expand = self.config_id.odata_expand or self.odata_expand
        if 'odata_top' in self.config_id._fields:
            self.odata_top = self.config_id.odata_top or self.odata_top
        if 'request_warehouse_value' in self.config_id._fields:
            self.warehouse_value = self.config_id.request_warehouse_value or self.warehouse_value
        if 'request_inventory_id_value' in self.config_id._fields:
            self.inventory_id_value = self.config_id.request_inventory_id_value or self.inventory_id_value

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
            return [payload]
        return []

    @staticmethod
    def _parse_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _build_request_body(self, warehouse=None, inventory_id=None):
        self.ensure_one()
        return {
            'Warehouse': {'value': warehouse if warehouse is not None else self.warehouse_value or ''},
            'InventoryID': {'value': inventory_id if inventory_id is not None else self.inventory_id_value or ''},
        }

    def fetch_inventory_stock_data(self, warehouse=None, inventory_id=None, odata_expand=None, odata_top=None):
        self.ensure_one()
        config = self.config_id
        if not config:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        session = config._do_login()

        AcumaticaErrorService = self.env["acumatica.webhook.error.service"]
        try:
            endpoint = f"{config.api_url}/{config.endpoint_name.lstrip('/')}"
            params = {}
            expand_value = odata_expand if odata_expand is not None else self.odata_expand
            top_value = odata_top if odata_top is not None else self.odata_top

            if expand_value:
                params['$expand'] = expand_value
            if top_value:
                params['$top'] = top_value

            payload = self._build_request_body(
                warehouse=warehouse or '',
                inventory_id=inventory_id or '',
            )

            response = session.put(endpoint, params=params, json=payload, timeout=300)
            if response.status_code != 200:

                last_error = (
                    f'Gagal ambil data Inventory Stock '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

                AcumaticaErrorService.send_error(
                    webhook_type="fetch",
                    webhook_name="inventory stock",
                    error=last_error,
                    error_type="http",
                )
                
                raise UserError(last_error)

            raw_data = self._normalize_rows(response.json())
            result = []
            for row_number, item in enumerate(raw_data, start=1):
                details = item.get('InventorySiteInquiryDetails') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    details = [{}]

                for detail in details:
                    result.append({
                        'external_id': item.get('id', '') or '',
                        'row_number': item.get('rowNumber', row_number) or row_number,
                        'line_external_id': detail.get('id', '') or '',
                        'line_row_number': detail.get('rowNumber', 0) or 0,
                        'note': self._val(detail, 'note') or self._val(item, 'note'),
                        'warehouse_code': self._val(detail, 'WarehouseID') or self._val(item, 'WarehouseID') or '',
                        'inventory_id': self._val(detail, 'InventoryID') or self._val(item, 'InventoryID'),
                        'description': self._val(detail, 'Description'),
                        'last_modified_datetime': self._val(detail, 'LastModifiedDateTime') or self._val(item, 'LastModifiedDateTime'),
                        'branch': self._val(detail, 'Branch'),
                        'item_status': self._val(detail, 'ItemStatus'),
                        'kode_barang_dan_jasa': self._val(detail, 'KodeBarangdanJasa'),
                        'product_group': self._val(detail, 'ProductGroup'),
                        'available': self._parse_float(self._val(detail, 'Available')),
                        'on_hand_acumatica': self._parse_float(self._val(detail, 'OnHand')),
                        'sync_date': fields.Datetime.now(),
                    })

            _logger.info("Berhasil ambil %s rows Inventory Stock dari Acumatica", len(result))
            return result
        finally:
            config._do_logout(session)
            config.last_sync = fields.Datetime.now()

    def action_fetch_data(self):
        self.ensure_one()
        raw_list = self.fetch_inventory_stock_data(
            warehouse=self.warehouse_value,
            inventory_id=self.inventory_id_value,
            odata_expand=self.odata_expand or None,
            odata_top=self.odata_top or None,
        )

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Line = self.env['acumatica.inventory.stock.line']
        new_count = 0
        existing_count = 0
        now = fields.Datetime.now()

        for item in raw_list:
            domain = [
                ('config_id', '=', self.config_id.id),
                ('external_id', '=', item.get('external_id', '') or ''),
                ('line_external_id', '=', item.get('line_external_id', '') or ''),
            ]
            existing = Line.search(domain, limit=1)
            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'selected': True,
                'sync_date': now,
            })
            if existing:
                incoming_last_modified = vals.get('last_modified_datetime')
                if not incoming_last_modified or existing.last_modified_datetime == incoming_last_modified:
                    continue
                existing.write(vals)
                existing_count += 1
            else:
                Line.create(vals)
                new_count += 1

        self.write({
            'state': 'fetched',
            'total_fetched': len(raw_list),
            'total_new': new_count,
            'total_existing': existing_count,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Inventory Stock',
            'res_model': 'acumatica.inventory.stock.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }
