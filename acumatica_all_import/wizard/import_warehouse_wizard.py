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
    total_new            = fields.Integer(string='Warehouse Baru', readonly=True)
    total_existing       = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    total_locations      = fields.Integer(string='Total Locations', readonly=True)
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

        # new_count = existing_count = total_loc = 0
        # WH = self.env['stock.location.acumatica']

        # for item in raw_list:
        #     # Cek existing warehouse
        #     existing = WH.browse()
        #     if item['warehouse_id']:
        #         existing = WH.search([('code', '=', item['warehouse_id'])], limit=1)

        #     if existing:
        #         existing_count += 1
        #     else:
        #         new_count += 1

        #     # Buat header line
        #     wh_line = self.env['acumatica.warehouse.line'].create({
        #         'config_id':             self.config_id.id,
        #         'building_id':           item['building_id'],
        #         'row_number':            item['row_number'],
        #         'external_id':           item['external_id'],
        #         'warehouse_id':          item['warehouse_id'],
        #         'description':           item['description'],
        #         'is_active':             item['active'],
        #         'active':                True,
        #         'note':                  item['note'],
        #         'drop_ship_location_id': item['drop_ship_location_id'],
        #         'last_modified_dt':      item['last_modified_dt'],
        #         'receiving_location_id': item['receiving_location_id'],
        #         'rma_location_id':       item['rma_location_id'],
        #         'shipping_location_id':  item['shipping_location_id'],
        #         'import_state':          'pending',
        #         'import_message':        f'Sudah ada → akan diupdate: {existing.name}' if existing else '',
        #         'selected':              True,
        #         'sync_date':             fields.Datetime.now(),
        #     })

        # self.write({
        #     'state':           'fetched',
        #     'total_fetched':   len(raw_list),
        #     'total_new':       new_count,
        #     'total_existing':  existing_count,
        #     'total_locations': total_loc,
        # })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.warehouse.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

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
                """Boolean value"""
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", False)
                return False

            result = []
            WH = self.env['stock.location.acumatica']
            wh_line = self.env['acumatica.warehouse.line']

            for item in raw_data:
                result.append({
                    # Header
                    'external_id':           item.get("id", "") or "",
                    'building_id':           val(item, "BuildingID"),
                    'row_number':            item.get("rowNumber", 0),
                    'note':                  item.get("note", {}).get("value", "") or "",
                    'active':                bval(item, "Active"),
                    'description':           val(item, "Description"),
                    'drop_ship_location_id': val(item, "DropShipLocationID"),
                    'last_modified_dt':      val(item, "LastModifiedDateTime"),
                    'receiving_location_id': val(item, "ReceivingLocationID"),
                    'rma_location_id':       val(item, "RMALocationID"),
                    'shipping_location_id':  val(item, "ShippingLocationID"),
                    'warehouse_id':          val(item, "WarehouseID"),
                })

            for item in result:
                # Cek existing warehouse
                existing = WH.browse()
                if item['warehouse_id']:
                    existing = WH.search([('code', '=', item['warehouse_id'])], limit=1)

                # if existing:
                #     continue

                self.env['acumatica.warehouse.line'].create({
                    'config_id':             self.config_id.id,
                    'building_id':           item['building_id'],
                    'row_number':            item['row_number'],
                    'external_id':           item['external_id'],
                    'warehouse_id':          item['warehouse_id'],
                    'description':           item['description'],
                    'is_active':             item['active'],
                    'active':                True,
                    'note':                  item['note'],
                    'drop_ship_location_id': item['drop_ship_location_id'],
                    'last_modified_dt':      item['last_modified_dt'],
                    'receiving_location_id': item['receiving_location_id'],
                    'rma_location_id':       item['rma_location_id'],
                    'shipping_location_id':  item['shipping_location_id'],
                    'import_state':          'pending',
                    'import_message':        f'Sudah ada → akan diupdate: {existing.name}' if existing else '',
                    'selected':              True,
                    'sync_date':             fields.Datetime.now(),
                })

            return len(result)

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

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
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
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
