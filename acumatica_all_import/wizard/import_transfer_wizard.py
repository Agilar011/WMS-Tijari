from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)



class ImportTransferWizard(models.TransientModel):
    _name = 'import.transfer.wizard'
    _description = 'Wizard Import Internal Transfer dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    receipt_nbr = fields.Char(string='Filter Receipt Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data shipment yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Transfer Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()

        import math

        count = 0
        batch_data = self.fetch_transfer_data()
        count += batch_data
        self.total_fetched = count

        if not count:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

    def _search_picking_type(self, building_code, document_only=False):
        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False
        if config_picking_type:
            return config_picking_type

        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        Warehouse = self.env['stock.warehouse']
        type = False

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='so_transfer',
            document_only=document_only,
            warehouse_code=building_code,
        )
        if document_only_type:
            return document_only_type

        warehouse = Warehouse.search([
            ('code', '=', building_code)
        ])
        if warehouse:
            type = PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('code', '=', 'incoming'),
                ('is_default_api', '=', True)
            ])

        return type if type else None

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    @staticmethod
    def _bool_value(value):
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, bool):
            return value
        if value in (False, None, ''):
            return False
        return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'document only')

    def _bool_val(self, item, key):
        return self._bool_value(item.get(key, {}))

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []
    
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False


    def fetch_transfer_data(self):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {}

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand

            body = {
                "BuildingID": {
                    "value": "WH33"
                }
            }

            print("Filter API:")
            print(endpoint)
            print(params)

            response = session.put(endpoint, params=params, json=body, timeout=300)
            print(f"Response: {response}")
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Receipt (HTTP {response.status_code}): {response.text}')

            raw_payload = response.json()
            flat_data = raw_payload.get('SOTRGIDetails') if isinstance(raw_payload, dict) else None
            raw_data = flat_data or self._normalize_rows(raw_payload)
            print(f"raw data: {raw_data}")
            result = []
            detail_result = []
            seen_receipts = set()
            shipment_warehouse_cache = {}

            for row_number, item in enumerate(raw_data, start=1):
                receipt_nbr = self._val(item, "ReceiptNbr")
                transfer_shipment_nbr = self._val(item, 'LineTransferShipmentNbr')
                shipment_warehouse = {}
                if transfer_shipment_nbr:
                    shipment_warehouse = shipment_warehouse_cache.get(transfer_shipment_nbr)
                    if shipment_warehouse is None:
                        shipment_warehouse = self.search_dest_warehouse(transfer_shipment_nbr, session) or {}
                        shipment_warehouse_cache[transfer_shipment_nbr] = shipment_warehouse

                if receipt_nbr not in seen_receipts:
                    seen_receipts.add(receipt_nbr)
                    building_code = self._val(item, "BuildingID")
                    document_only = self._bool_val(item, 'DocumentOnly')
                    type = self._search_picking_type(building_code, document_only=document_only)

                    result.append({
                        'external_id': item.get('id', '') or '',
                        'row_number': row_number,
                        'note': item.get('HeaderNote', {}).get('value', '') or '',
                        'branch_warehouse': self._val(item, 'Branch'),
                        'actual_qty': self._val(item, 'ControlQty'),
                        'scheduled_date': self._val(item, 'Date'),
                        'is_hold': self._val(item, 'Hold'),
                        'inventory_ref': self._val(item, 'InventoryRefNbr'),
                        'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                        'header_location_code': self._val(item, 'Location'),
                        'post_period': self._val(item, 'PostPeriod'),
                        'receipt_nbr': self._val(item, 'ReceiptNbr'),
                        'document_only': self._bool_val(item, 'DocumentOnly'),
                        'status': self._val(item, 'Status'),
                        'total_qty': self._val(item, 'TotalQty'),
                        'receipt_type': self._val(item, 'Type'),
                        'vendor_code': self._val(item, 'VendorID'),
                        'partner_ref': self._val(item, 'VendorRef') or self._val(item, 'VendorName'),
                        'warehouse_code': shipment_warehouse.get('source_warehouse') or self._val(item, 'WarehouseID'),
                        'warehouse_dest_code': shipment_warehouse.get('dest_warehouse') or self._val(item, 'Warehouse') or self._val(item, 'LineWarehouseID'),
                        'picking_type_id': type.id if type else None,

                        })

                detail_result.append({
                    # 'header_external_id': item.get('id', '') or '',
                    'line_external_id': item.get('id', '') or '',
                    'receipt_nbr': self._val(item, 'ReceiptNbr'),
                    'line_note': item.get('LineNote', {}).get('value', '') or '',
                    'description': self._val(item, 'LineDescription'),
                    'inventory_id': self._val(item, 'LineInventoryID'),
                    'line_nbr': self._val(item, 'LineNbr'),
                    'line_type': self._val(item, 'LineType'),
                    'location_dest_code': self._val(item, 'LineLocation'),
                    'open_qty': self._val(item, 'LineOpenQty'),
                    'order_qty': self._val(item, 'LineOrderedQty'),
                    'product_uom_qty': self._val(item, 'LineReceiptQty'),
                    'uom_code': self._val(item, 'LineUOM'),
                    'warehouse_dest_code': self._val(item, 'LineWarehouseID'),
                })

            _logger.info('Berhasil ambil %s rows Transfer Receipt dari Acumatica', len(result))
            self.config_id.last_sync = fields.Datetime.now()
            self._validate_staging_against_picking(result, detail_result)
            return len(result)
        finally:
            self.config_id._do_logout(session)

    def search_dest_warehouse(self, transfer_nbr, session):
        self.ensure_one()
        if not transfer_nbr:
            return None
        try:
            endpoint = f"{self.config_id.api_url}/Shipment"
            params = {
                '$select': 'ToWarehouseID, WarehouseID, ShipmentNbr', 
                '$filter': f"ShipmentNbr eq '{transfer_nbr}'"
            }

            response = session.get(endpoint, params=params, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Destination Warehouse (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())

            item = raw_data[0]  # misal ambil data pertama

            result = {
                'shipment_number': self._val(item, 'ShipmentNbr'),
                'dest_warehouse': self._val(item, 'ToWarehouseID'),
                'source_warehouse': self._val(item, 'WarehouseID'),
            }

            _logger.info('Berhasil ambil data Warehouse dari Transfer Receipt', result)
            return result
        except Exception as e:
            _logger.error('Gagal ambil data Warehouse dari Transfer Receipt: %s', str(e))
            return None


    def _validate_staging_against_picking(self, header_list, line_list):
        Picking = self.env['stock.picking']
        lines_to_create = []
        sync_data = fields.Datetime.now()
        for item in header_list:
            
            receipt_nbr = item.get('receipt_nbr')
            # exists = receipt_nbr and Picking.search_count([('origin', '=', receipt_nbr)])
            exists = Picking.search_read(
                domain=[('origin', '=', receipt_nbr)],
                fields=['id', 'origin'],
                limit=1
            )
            lines_to_create.append({
                **item,
                'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': f'{receipt_nbr}: Sudah ada → akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)
            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_receipt_lines(to_update)

            receipts = self._create_receipt_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                self._update_receipt_lines_product(line_update, to_update)

            if line_create:
                self._create_receipt_lines_product(line_create, receipts)

            # to_create_filtered = self.filter_by_receipt_lines(to_create, receipts)
            # to_update_filtered = self.filter_by_receipt_lines(to_update, receipts)
            # self._create_receipt_lines_product(to_create_filtered, receipts)

    def _search_receipt_lines(self, data):
        if not data:
            return [], [], []

        receipt_nbrs = [
            d['receipt_nbr']
            for d in data
            if d.get('receipt_nbr')
        ]
        existing_lines = self.env['acumatica.transfer.line'].search([
            ('receipt_nbr', 'in', receipt_nbrs)
        ])

        existing_map = {
            line.receipt_nbr: line
            for line in existing_lines
        }

        unchanged = []
        to_update = []
        to_create = []
        
        for vals in data:
            existing = existing_map.get(vals['receipt_nbr'])

            if not existing:
                to_create.append(vals)
                continue


            if existing.acumatica_write_date == self._parse_dt(vals['acumatica_write_date']):
                unchanged.append(existing)
            else:
                to_update.append({
                    'record': existing,
                    'vals': vals,
                })

        return unchanged, to_update, to_create

    def _update_receipt_lines(self, data):
        if not data:
            return False

        for item in data:
            record = item['record']
            vals = item['vals']


            record.write(vals)

    def _create_receipt_lines(self, data):
        if not data:
            return False

        return self.env['acumatica.transfer.line'].create(data)

    def filter_product_line(self, data, update, create):
        # buat set dari semua external_id di update
        update_ids = {
            item.get('vals', {}).get('receipt_nbr')
            for item in update
            if item.get('vals', {}).get('receipt_nbr')
        }

        # filter data yang header_external_id ada di update_ids
        update_final = [
            line 
            for line in data 
            if line['receipt_nbr'] in update_ids
        ]

        # buat set dari semua external_id di create
        create_ids = {
            crt['receipt_nbr'] 
            for crt in create
        }

        # filter data yang header_external_id ada di create_ids
        create_final = [line for line in data if line['receipt_nbr'] in create_ids]

        return update_final, create_final
        
    def filter_by_receipt_lines(self, data, receipts):
        """
        Filter data berdasarkan header_external_id yang ada di receipts.
        
        :param data: list of dict (to_create atau to_update)
        :param receipts: recordset receipt
        :return: list of dict yang header_external_id-nya ada di receipts
        """
        receipt_ids = {rec['receipt_nbr'] for rec in receipts}

        filtered_data = [
            vals for vals in data
            if vals.get('receipt_nbr') in receipt_ids
        ]

        return filtered_data

    def _create_receipt_lines_product(self, data, receipts):
        receipt_map = {
            rec['receipt_nbr']: rec.id
            for rec in receipts
        }

        for vals in data:
            vals['transfer_line_id'] = receipt_map.get(
                vals['receipt_nbr']
            )

        self.env['acumatica.transfer.product.line'].create(data)

    def _update_receipt_lines_product(self, data, receipts):
        receipt_map = {
            rec['vals']['receipt_nbr']: rec['record']['id']
            for rec in receipts
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.transfer.product.line']

        for vals in data:
            ext_id = vals.get('receipt_nbr')
            vals['transfer_line_id'] = receipt_map.get(ext_id)
            if vals['transfer_line_id']:
                product_line.browse(vals['transfer_line_id']).write(vals)

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Internal Transfer dari Acumatica',
            'res_model': 'acumatica.transfer.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.transfer.line'].search([
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
            'name': 'Hasil Import Internal Transfer',
            'res_model': 'acumatica.transfer.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
