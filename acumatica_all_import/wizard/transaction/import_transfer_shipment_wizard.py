from datetime import datetime, time, timezone
from odoo import fields, models
from odoo.exceptions import UserError

import logging
from ...utils import acumatica_data as _data


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
    def _last_modified_value(item):
        """Keep Acumatica's original LastModified value in the Char staging field."""
        candidates = (
            'LastModifiedDateTime',
            'LastModifiedOn',
            'adt_LastModifiedDateTime',
            'last_modified_datetime',
        )
        for key in candidates:
            value = _data.acumatica_value(item, key)
            if value not in (False, None, ''):
                return str(value)

        # Tolerate payloads whose serializer changes only the key casing.
        candidate_keys = {key.lower() for key in candidates}
        for key, value in item.items():
            if key.lower() in candidate_keys:
                if isinstance(value, dict):
                    value = value.get('value', '')
                if value not in (False, None, ''):
                    return str(value)
        return ''




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
                self.env["acumatica.webhook.error.service"].send_error(
                    webhook_type="fetch",
                    webhook_name="Transfer Shipment",
                    error=f"Gagal fetch Transfer Shipment dari Acumatica (HTTP {response.status_code}).",
                    error_type="http",
                )
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
                shipment_nbr = _data.acumatica_value(item, "ShipmentNbr")

                if shipment_nbr and shipment_nbr not in seen_shipments:
                    seen_shipments.add(shipment_nbr)
                    type = self._search_picking_type({
                        'warehouse_code': _data.acumatica_value(item, 'WarehouseID') or _data.acumatica_value(item, 'LineWarehouseID'),
                        'document_only': _data.acumatica_bool(item, 'DocumentOnly'),
                    })

                    result.append({
                        'external_id': item.get('id', '') or '',
                        'row_number': row_number,
                        'note': _data.acumatica_value(item, 'NoteHeader') or '',
                        'building_code': _data.acumatica_value(item, 'BuildingID'),
                        'actual_qty': _data.acumatica_value(item, 'ControlQty') or _data.acumatica_value(item, 'ShipmentQty'),
                        'partner_code': _data.acumatica_value(item, 'CustomerID'),
                        'customer_name': _data.acumatica_value(item, 'CustomerName'),
                        'description': _data.acumatica_value(item, 'Description') or _data.acumatica_value(item, 'LineDescription'),
                        'fob_point': _data.acumatica_value(item, 'FOBPoint'),
                        'is_hold': _data.acumatica_value(item, 'Hold'),
                        'is_insurance': _data.acumatica_value(item, 'Insurance'),
                        'document_only': _data.acumatica_bool(item, 'DocumentOnly'),
                        'acumatica_write_date': self._last_modified_value(item),
                        'header_location_code': _data.acumatica_value(item, 'LocationID'),
                        'location_name': _data.acumatica_value(item, 'LocationName'),
                        'operation': _data.acumatica_value(item, 'Operation'),
                        'package_count': _data.acumatica_value(item, 'PackageCount'),
                        'package_weight': _data.acumatica_value(item, 'PackageWeight'),
                        'is_picked': _data.acumatica_value(item, 'Picked'),
                        'scheduled_date': _data.acumatica_value(item, 'ShipmentDate') or _data.acumatica_value(item, 'ShipDate'),
                        'shipment_nbr': shipment_nbr,
                        'shipped_qty': _data.acumatica_value(item, 'ShippedQty') or _data.acumatica_value(item, 'ShipmentQty'),
                        'shipped_volume': _data.acumatica_value(item, 'ShippedVolume') or _data.acumatica_value(item, 'ShipmentVolume'),
                        'shipped_weight': _data.acumatica_value(item, 'ShippedWeight') or _data.acumatica_value(item, 'ShipmentWeight'),
                        'shipping_terms': _data.acumatica_value(item, 'ShippingTerms'),
                        'shipping_zone': _data.acumatica_value(item, 'ShippingZoneID'),
                        'ship_via': _data.acumatica_value(item, 'ShipVia'),
                        'status': _data.acumatica_value(item, 'Status'),
                        'warehouse_dest_code': _data.acumatica_value(item, 'ToWarehouseID'),
                        'shipment_type': _data.acumatica_value(item, 'Type') or _data.acumatica_value(item, 'ShipmentType'),
                        'warehouse_code': _data.acumatica_value(item, 'WarehouseID') or _data.acumatica_value(item, 'LineWarehouseID'),
                        'is_unlimited_packages': _data.acumatica_value(item, 'UnlimitedPackages'),
                        'picking_type_id': type.id if type else None,

                    })

                result_line.append({
                    'shipment_nbr': shipment_nbr,
                    'line_external_id': item.get('id', '') or '',
                    'line_note': _data.acumatica_value(item, 'LineNote'),
                    'line_row_number': item.get('rowNumber') or '',
                    'line_description': _data.acumatica_value(item, 'LineDescription'),
                    'is_free_item': _data.acumatica_value(item, 'LineFreeItem'),
                    'inventory_id': _data.acumatica_value(item, 'LineInventoryID'),
                    'line_nbr': str(_data.acumatica_value(item, 'LineNbr') or item.get('rowNumber') or 0),
                    'location_dest_code': _data.acumatica_value(item, 'LineLocationID') or _data.acumatica_value(item, 'LineLocation'),
                    'open_qty': _data.acumatica_value(item, 'LineOpenQty'),
                    'order_qty': _data.acumatica_value(item, 'LineOrderedQty') or _data.acumatica_value(item, 'LineQuantity'),
                    'order_line_number': _data.acumatica_value(item, 'LineOrderLineNbr'),
                    'order_number': _data.acumatica_value(item, 'LineOrderNbr') or _data.acumatica_value(item, 'OrderNbr'),
                    'order_type': _data.acumatica_value(item, 'LineOrderType') or _data.acumatica_value(item, 'OrderType'),
                    'original_qty': _data.acumatica_value(item, 'LineOriginalQty'),
                    'product_uom_qty': _data.acumatica_value(item, 'LineShippedQty') or _data.acumatica_value(item, 'ShippedQty') or _data.acumatica_value(item, 'LineQuantity'),
                    'uom_code': _data.acumatica_value(item, 'LineUOM'),
                    'line_warehouse_code': _data.acumatica_value(item, 'LineWarehouseID') or _data.acumatica_value(item, 'WarehouseID'),
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

            existing = existing_map.get(origin)
            if existing:
                incoming_last_modified = vals.get('acumatica_write_date')
                if not incoming_last_modified or existing.acumatica_write_date == incoming_last_modified:
                    continue
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



        


        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.transfer.shipment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def _search_picking_type(self, header):
        warehouse_code = header.get('warehouse_code') or header.get('line_warehouse_code')
        return self.env['acumatica.config']._resolve_transaction_picking_type(
            config=self.config_id,
            warehouse_code=warehouse_code,
            code='internal',
            operation_category='internal',
            api_acumatica='transfer_shipment',
            transaction_key='transfer_shipment',
            document_only=header.get('document_only'),
            config_policy='always',
            require_location_mapping=True,
            location_must_be_active=True,
            stop_after_document_only_miss=True,
        ) or None


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
