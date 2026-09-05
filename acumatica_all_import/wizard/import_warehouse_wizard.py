from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportWarehouseWizard(models.TransientModel):
    _name = 'import.warehouse.wizard'
    _description = 'Wizard Import Warehouse dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    state       = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    total_fetched        = fields.Integer(string='Total Warehouse', readonly=True)
    batch_size           = fields.Integer(string='Batch Size untuk Import', default=20)
    fetch_skip            = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_warehouse_data(limit=self.batch_size, offset=offset)

            raw_list += batch_data

            if not batch_data:
                break

        self.total_fetched = raw_list

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.warehouse.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _check_last_modified_staging(self, item):
        Staging = self.env['acumatica.warehouse.line']
        existing = Staging.search([
            ('warehouse_id', '=', item['warehouse_id']),
            ('last_modified_dt', '!=', item['last_modified_dt'])
        ])
        if existing:
            item['import_state'] = 'staged'
            existing.write(item)

    def fetch_warehouse_data(self, limit=50, offset=0):
        """
        Fetch Warehouse + Locations dari Acumatica.
        Endpoint: /Warehouse?$expand=Locations&$top={limit}
        Return: list of dict warehouse, masing-masing punya key 'locations' (list)
        """
        self.ensure_one()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params   = {"$expand": "Locations", "$top": limit, "$skip": offset}

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Warehouse (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records Warehouse dari Acumatica", len(raw_data))

            def val(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "") or ""
                return ""

            def bval(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return bool(v.get("value", False))
                return False

            result = []
            Location = self.env['stock.location.acumatica']
            Staging = self.env['acumatica.warehouse.line']

            for item in raw_data:
                result.append({
                    # Header
                    'external_id':           item.get("id", "") or "",
                    'building_id':           val(item, "BuildingID"),
                    'row_number':            item.get("rowNumber", 0),
                    'note':                  item.get("note", {}).get("value", "") or "",
                    'is_active':             bval(item, "Active"),
                    'description':           val(item, "Description"),
                    'drop_ship_location_id': val(item, "DropShipLocationID"),
                    'last_modified_dt':      val(item, "LastModifiedDateTime"),
                    'receiving_location_id': val(item, "ReceivingLocationID"),
                    'rma_location_id':       val(item, "RMALocationID"),
                    'shipping_location_id':  val(item, "ShippingLocationID"),
                    'warehouse_id':          val(item, "WarehouseID"),
                })

            staging_by_warehouse = {
                p.warehouse_id: p.id
                for p in Staging.search([
                    ('warehouse_id', '!=', False)
                ])
            }

            location_by_warehouse = {
                p.code: p.id
                for p in Location.search([
                    ('code', '!=', False)
                ])
            }

            for item in result:
                # Cek existing warehouse
                existing_staging = False
                if item['warehouse_id']:
                    existing_staging = staging_by_warehouse.get(item['warehouse_id'])

                if existing_staging:
                    self._check_last_modified_staging(item)
                    continue

                existing_location = False
                if existing_staging:
                    existing_location = location_by_warehouse.get(item['warehouse_id'])

                msg = 'Data sudah ada' if existing_location else ''
                state = 'staged'

                self.env['acumatica.warehouse.line'].create({
                    'config_id':             self.config_id.id,
                    'building_id':           item['building_id'],
                    'row_number':            item['row_number'],
                    'external_id':           item['external_id'],
                    'warehouse_id':          item['warehouse_id'],
                    'description':           item['description'],
                    'is_active':             item['is_active'],
                    'active':                True,
                    'note':                  item['note'],
                    'drop_ship_location_id': item['drop_ship_location_id'],
                    'last_modified_dt':      item['last_modified_dt'],
                    'receiving_location_id': item['receiving_location_id'],
                    'rma_location_id':       item['rma_location_id'],
                    'shipping_location_id':  item['shipping_location_id'],
                    'import_state':          state,
                    'import_message':        msg,
                    'sync_date':             fields.Datetime.now(),
                })

            return len(result)

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    def _get_warehouse_odata_filters(self):
        self.ensure_one()
        params = []
        start_date = getattr(self, 'start_date', False)
        end_date = getattr(self, 'end_date', False)
        if start_date and end_date:
            params.append(f"LastModifiedDateTime ge datetimeoffset'{start_date}' and LastModifiedDateTime le datetimeoffset'{end_date}'")
        return params

    def fetch_all_warehouse_data(self, batch_size=False):
        """
        Ambil semua data Warehouse dari Acumatica dengan paging $skip.

        Dipakai untuk scheduler/server-side agar tidak dibatasi fetch_limit
        milik wizard manual.
        """
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        fetch_size = batch_size or self.batch_size or 50
        if fetch_size <= 0:
            raise UserError('Batch size harus lebih besar dari 0.')

        raw_count = 0
        batch_count = 0
        params = self._get_warehouse_odata_filters()

        _logger.info(
            "START FETCH ALL WAREHOUSE; CONFIG=%s, BATCH_SIZE=%s, FETCH_SKIP=%s, FILTERS=%s",
            self.config_id.display_name,
            fetch_size,
            self.fetch_skip,
            params or '-',
        )

        while True:
            offset = self.fetch_skip + (batch_count * fetch_size)
            batch_data = self.fetch_warehouse_data(limit=fetch_size, offset=offset)
            if not batch_data:
                _logger.info(
                    "STOP FETCH ALL WAREHOUSE; empty batch at OFFSET=%s, TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
                    offset,
                    raw_count,
                    batch_count,
                )
                break

            raw_count += batch_data
            batch_count += 1
            _logger.info(
                "FETCH ALL WAREHOUSE BATCH DONE; BATCH=%s, OFFSET=%s, FETCHED=%s, RUNNING_TOTAL=%s",
                batch_count,
                offset,
                batch_data,
                raw_count,
            )

            if batch_data < fetch_size:
                break

        self.write({
            'total_fetched': raw_count,
            'state': 'fetched' if raw_count else 'draft',
        })
        _logger.info(
            "FINISH FETCH ALL WAREHOUSE; TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
            raw_count,
            batch_count,
        )
        return raw_count

    def action_fetch_all_data(self):
        self.ensure_one()
        raw_count = self.fetch_all_warehouse_data()
        if not raw_count:
            raise UserError('Tidak ada data dari API')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.warehouse.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Warehouse dari Acumatica',
            'res_model': 'acumatica.warehouse.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.warehouse.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        lines._do_import()
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import Warehouse',
            'res_model': 'acumatica.warehouse.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
