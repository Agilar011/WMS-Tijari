from datetime import datetime, time, timezone
from odoo import fields, models
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)

class ImportTransferShipmentWizard(models.TransientModel):
    _name = 'import.transfer.shipment.wizard'
    _description = 'Wizard Import Transfer Shipment dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    shipment_nbr = fields.Char(string='Filter Shipment Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')

    wh33_filter = fields.Boolean(string='Filter WH33', help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')
    odata_filter = fields.Char(string='Custom OData Filter')

    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')


    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Transfer Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

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

    def fetch_transfer_shipment_data(self):
        self.ensure_one()

        # print("\n" + "="*60)
        # print(f">>> DATA DARI OBJECT SELF ({self._name} - ID: {self.id}) <<<")
        # print("="*60)
        # for field_name in self._fields:
        #     try:
        #         value = self[field_name]
        #         # Jika field adalah relasi Odoo (Many2one/One2many/Many2many), ambil ID atau representasinya
        #         if hasattr(value, 'ids'):
        #             value_str = f"Recordset {value._name}({value.ids})"
        #         else:
        #             value_str = str(value)
                
        #         print(f"{field_name:<30} : {value_str}")
        #     except Exception as e:
        #         print(f"{field_name:<30} : [Gagal membaca nilai: {str(e)}]")
        # print("="*60 + "\n")
        # -----------------------------------------------

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

            _logger.info("Filter API -> Endpoint: %s | Params: %s", endpoint, params)

            response = session.put(endpoint, params=params, json=body, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Shipment (HTTP {response.status_code}): {response.text}')

            raw_payload = response.json()
            raw_data = (
                raw_payload.get('ShipmentTransferGIDetails')
                if raw_payload
                else None
            ) 
            result = []
            result_line = []
            seen_shipments = set()

            for row_number, item in enumerate(raw_data, start=1):
                shipment_nbr = self._val(item, "ShipmentNbr")

                if shipment_nbr and shipment_nbr not in seen_shipments:
                    seen_shipments.add(shipment_nbr)
                    type = self._search_picking_type({
                        'warehouse_code': self._val(item, 'WarehouseID') or self._val(item, 'LineWarehouseID'),
                        'document_only': self._bool_val(item, 'DocumentOnly'),
                    })

                    result.append({
                        'external_id': item.get('id', '') or '',
                        'row_number': row_number,
                        'note': self._val(item, 'NoteHeader') or '',
                        'building_code': self._val(item, 'BuildingID'),
                        'actual_qty': self._val(item, 'ControlQty') or self._val(item, 'ShipmentQty'),
                        'partner_code': self._val(item, 'CustomerID'),
                        'customer_name': self._val(item, 'CustomerName'),
                        'description': self._val(item, 'Description') or self._val(item, 'LineDescription'),
                        'fob_point': self._val(item, 'FOBPoint'),
                        'is_hold': self._val(item, 'Hold'),
                        'is_insurance': self._val(item, 'Insurance'),
                        'document_only': self._bool_val(item, 'DocumentOnly'),
                        'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                        'header_location_code': self._val(item, 'LocationID'),
                        'location_name': self._val(item, 'LocationName'),
                        'operation': self._val(item, 'Operation'),
                        'package_count': self._val(item, 'PackageCount'),
                        'package_weight': self._val(item, 'PackageWeight'),
                        'is_picked': self._val(item, 'Picked'),
                        'scheduled_date': self._val(item, 'ShipmentDate') or self._val(item, 'ShipDate'),
                        'shipment_nbr': shipment_nbr,
                        'shipped_qty': self._val(item, 'ShippedQty') or self._val(item, 'ShipmentQty'),
                        'shipped_volume': self._val(item, 'ShippedVolume') or self._val(item, 'ShipmentVolume'),
                        'shipped_weight': self._val(item, 'ShippedWeight') or self._val(item, 'ShipmentWeight'),
                        'shipping_terms': self._val(item, 'ShippingTerms'),
                        'shipping_zone': self._val(item, 'ShippingZoneID'),
                        'ship_via': self._val(item, 'ShipVia'),
                        'status': self._val(item, 'Status'),
                        'warehouse_dest_code': self._val(item, 'ToWarehouseID'),
                        'shipment_type': self._val(item, 'Type') or self._val(item, 'ShipmentType'),
                        'warehouse_code': self._val(item, 'WarehouseID') or self._val(item, 'LineWarehouseID'),
                        'is_unlimited_packages': self._val(item, 'UnlimitedPackages'),
                        'picking_type_id': type.id if type else None,

                    })

                result_line.append({
                    'shipment_nbr': shipment_nbr,
                    'line_external_id': item.get('id', '') or '',
                    'line_note': self._val(item, 'LineNote'),
                    'line_row_number': item.get('rowNumber') or '',
                    'line_description': self._val(item, 'LineDescription'),
                    'is_free_item': self._val(item, 'LineFreeItem'),
                    'inventory_id': self._val(item, 'LineInventoryID'),
                    'line_nbr': str(self._val(item, 'LineNbr') or item.get('rowNumber') or 0),
                    'location_dest_code': self._val(item, 'LineLocationID') or self._val(item, 'LineLocation'),
                    'open_qty': self._val(item, 'LineOpenQty'),
                    'order_qty': self._val(item, 'LineOrderedQty') or self._val(item, 'LineQuantity'),
                    'order_line_number': self._val(item, 'LineOrderLineNbr'),
                    'order_number': self._val(item, 'LineOrderNbr') or self._val(item, 'OrderNbr'),
                    'order_type': self._val(item, 'LineOrderType') or self._val(item, 'OrderType'),
                    'original_qty': self._val(item, 'LineOriginalQty'),
                    'product_uom_qty': self._val(item, 'LineShippedQty') or self._val(item, 'ShippedQty') or self._val(item, 'LineQuantity'),
                    'uom_code': self._val(item, 'LineUOM'),
                    'line_warehouse_code': self._val(item, 'LineWarehouseID') or self._val(item, 'WarehouseID'),
                })

            return result, result_line
        except Exception:
            raise
        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


    def action_fetch_data(self):
        self.ensure_one()

        import math

        raw_list = []
        raw_line_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        # for i in range(loop_count):
        #     offset = self.fetch_skip + (i * self.batch_size)

        result_dict, line_dict = self.fetch_transfer_shipment_data()

        # Ambil list data dari masing-masing dictionary dengan aman
        batch_data = result_dict if isinstance(result_dict, list) else []
        batch_data_line = line_dict if isinstance(line_dict, list) else []

        # Masukkan data ke dalam list utama
        raw_list.extend(batch_data)
        raw_line_list.extend(batch_data_line)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        
        if not raw_line_list:
            raise UserError('Tidak ada data product yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        Staging = self.env['acumatica.transfer.shipment.line']
        existing_records = Staging.search([
            ('config_id', '=', self.config_id.id),
            ('shipment_nbr', 'in', [item.get('shipment_nbr') for item in raw_list if item.get('shipment_nbr')]),
        ])
        existing_map = {record.shipment_nbr: record for record in existing_records}
        existing_keys = set()
        new_keys = set()
        shipment_to_create = []
        lines_to_create = []

        for item in raw_list:
            origin = item.get('shipment_nbr')
            exists = bool(origin and Picking.search_count([('origin', '=', origin)]))
            if exists:
                existing_keys.add(origin)
                msg = 'Sudah ada → move akan ditambahkan jika belum ada'
            else:
                new_keys.add(origin)
                msg = ''

            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'import_state': 'staged',
                'import_message': msg,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })

            print(f"vals staging: {vals}")
            existing = existing_map.get(origin)
            if existing:
                existing.shipment_line_ids.unlink()
                existing.write(vals)
                created_shipment = existing
            else:
                created_shipment = Staging.create(vals)
            self.write({
                'state': 'fetched',
                'total_fetched': len(raw_list),
                'total_new': len([x for x in new_keys if x]),
                'total_existing': len([x for x in existing_keys if x]),
            })

            for line in raw_line_list:
                print(line)
                if line.get('shipment_nbr') == item.get('shipment_nbr'):
                    vals_line = ({
                        'shipment_id' : created_shipment.id,
                        'line_external_id' : line.get('line_external_id'),
                        'line_note' : line.get('line_note'),
                        'line_row_number' : line.get('line_row_number'),
                        'line_description' : line.get('line_description'),
                        'is_free_item' : line.get('is_free_item'),
                        'inventory_id' : line.get('inventory_id'),
                        'line_nbr' : line.get('line_nbr'),
                        'location_dest_code' : line.get('location_dest_code'),
                        'open_qty' : line.get('open_qty'),
                        'order_qty' : line.get('order_qty'),
                        'order_line_number' : line.get('order_line_number'),
                        'order_number' : line.get('order_number'),
                        'order_type' : line.get('order_type'),
                        'original_qty' : line.get('original_qty'),
                        'product_uom_qty' : line.get('product_uom_qty'),
                        'uom_code' : line.get('uom_code'),
                        'line_warehouse_code' : line.get('line_warehouse_code'),
                    })

                    created_move = self.env['acumatica.transfer.shipment.line.product'].create(vals_line)

                    print(f"Created Move with ID: {created_move.id}")


        


        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.transfer.shipment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def _search_picking_type(self, header):
        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False
        if config_picking_type:
            return config_picking_type

        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        warehouse_code = header.get('warehouse_code') or header.get('line_warehouse_code')
        type = False

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='transfer_shipment',
            document_only=header.get('document_only'),
            warehouse_code=warehouse_code,
        )
        if document_only_type:
            return document_only_type
        if header.get('document_only'):
            return None

        location = Location.search([
            ('code', '=', warehouse_code),
            ('is_active', '=', True),
        ], limit=1)

        
        if location:
            type = PickingType.resolve_picking_type(
                warehouse_code=warehouse_code,
                code='internal',
                operation_category='internal',
                api_acumatica='transfer_shipment',
                transaction_key='transfer_shipment',
                required=False,
            )

        return type if type else None


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Transfer Shipment dari Acumatica',
            'res_model': 'acumatica.transfer.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.transfer.shipment.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')
        lines._do_import()
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import Transfer Shipment',
            'res_model': 'acumatica.transfer.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
