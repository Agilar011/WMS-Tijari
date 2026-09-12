from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)


class ImportDirectTransferWizard(models.TransientModel):
    _name = 'import.vendor.return.direct.transfer.wizard'
    _description = 'Wizard Import Inventory Recieved dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter' , help='Filter tambahan untuk query OData. Contoh: TransDate ge 2026-01-01T00:00:00Z')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Data Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    def action_fetch_data(self):
        self.ensure_one()

        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        params = []
        if self.start_date and self.end_date:
            params.append(f"Date ge date'{self.start_date}' and Date le date'{self.end_date}'")
        if self.odata_filter:
            params.append(self.odata_filter)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_data(
                limit=self.batch_size,
                offset=offset,
                reference_nbr=self.reference_nbr,
                odata_filter=params if params else None,
            )

            if not batch_data:
                break

            raw_list += batch_data

        self.total_fetched = raw_list
        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    @staticmethod
    def _bool_val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'y', 'document only')
        return bool(value)

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
        
    def _parse_float(self, value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _parse_int(self, value):
        try:
            return int(value or 0)
        except Exception:
            return 0


    def _search_picking_type(self, header):
        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False
        if config_picking_type:
            return config_picking_type

        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        type = False

        document_only_type = PickingType.resolve_document_only_picking_type(
            target_operation_type='direct_delivery_order',
            api_acumatica='vendor_return',
            document_only=header.get('adt_DocumentOnly'),
            warehouse_code=header.get('adt_FromWarehouseID'),
        )
        if document_only_type:
            return document_only_type

        print(f"Warehouse: {header['adt_FromWarehouseID']}")

        location = Location.search([
            ('code', '=', header['adt_FromWarehouseID'])
        ])

            
        if location:
            type = PickingType.resolve_picking_type(
                warehouse_code=header['adt_FromWarehouseID'],
                code='outgoing',
                operation_category='delivery',
                api_acumatica='vendor_return',
                transaction_key='vendor_return_direct_transfer',
                required=False,
            )

            print(f"Type: {type}")

        return type if type else None

    def fetch_data(self, limit=50, offset=0, reference_nbr=False, odata_filter=False):
        self.ensure_one()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {}

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand

            response = session.put(endpoint, params=params, json=self._get_vendor_return_fetch_body(), timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal fetch data (HTTP {response.status_code}): {response.text}')

            raw_data = self._extract_response_rows(response.json())
            raw_data = self._filter_response_rows(raw_data, reference_nbr, odata_filter)
            raw_data = raw_data[offset:offset + limit] if limit else raw_data[offset:]
            headers = []
            details = []
            seen_references = set()

            for row_number, item in enumerate(raw_data, start=1):
                header = self._prepare_vendor_return_header_vals(item, row_number)
                reference = header.get('adt_ReferenceNbr')
                if not reference:
                    continue
                if reference not in seen_references:
                    seen_references.add(reference)
                    headers.append(header)

                item_details = self._get_detail_rows(item) or [item]
                for detail in item_details:
                    details.append(self._prepare_vendor_return_line_vals(
                        detail,
                        reference,
                    ))

            self._upsert_vendor_return_staging(headers, details)
            _logger.info("Berhasil ambil %s rows Vendor Return dari Acumatica", len(headers))
            return len(headers)

        finally:
            if session:
                self.config_id._do_logout(session)

    def _get_vendor_return_fetch_body(self):
        return {
            "ReturnType": {
                "value": "Return Transfer"
            }
        }

    def _extract_response_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        for key in (
            'VendorReturnDocumentGIDetails',
            'VendorReturnGIDetails',
            'TransferOrderGIDetails',
            'TransferPinjamanGIDetails',
            'Details',
        ):
            rows = payload.get(key)
            if isinstance(rows, dict):
                rows = rows.get('value', []) or []
            if isinstance(rows, list):
                return rows

        return self._normalize_rows(payload)

    def _filter_response_rows(self, rows, reference_nbr=False, odata_filter=False):
        if reference_nbr:
            rows = [
                item for item in rows
                if self._val(item, 'ReferenceNbr') == reference_nbr
            ]
        if self.last_modified_from:
            rows = [
                item for item in rows
                if self._val(item, 'LastModifiedDateTime') >= self.last_modified_from
            ]
        return rows

    def _get_detail_rows(self, item):
        details = (
            item.get('VendorReturnDocumentGIDetails')
            or item.get('VendorReturnGIDetails')
            or item.get('TransferOrderGIDetails')
            or item.get('Details')
            or []
        )
        if isinstance(details, dict):
            details = details.get('value', []) or []
        if not isinstance(details, list):
            return []
        return details

    def _prepare_vendor_return_header_vals(self, item, row_number):
        header = {
            'adt_id': item.get('id', '') or '',
            'adt_rowNumber': self._parse_int(item.get('rowNumber') or row_number),
            'adt_note': self._val(item, 'NoteHeader') or self._val(item, 'note'),
            'adt_Date': self._val(item, 'Date'),
            'adt_Description': self._val(item, 'Description'),
            'adt_DocumentOnly': self._bool_val(item, 'DocumentOnly'),
            'adt_ExternalRef': self._val(item, 'ExternalRef'),
            'adt_LastModifiedDateTime': self._val(item, 'LastModifiedDateTime'),
            'adt_NoteHeaderID': self._val(item, 'NoteHeaderID') or self._val(item, 'NoteID'),
            'adt_PostPeriod': str(self._val(item, 'PostPeriod') or ''),
            'adt_ReferenceNbr': self._val(item, 'ReferenceNbr'),
            'adt_ReturnType': self._val(item, 'ReturnType'),
            'adt_Status': self._val(item, 'Status'),
            'adt_TotalQty': self._parse_float(self._val(item, 'TotalQty')),
            'adt_TransferType': self._val(item, 'TransferType'),
            'adt_FromWarehouseID': self._val(item, 'FromWarehouseID'),
            'adt_FromWarehouseName': self._val(item, 'FromWarehouseName'),
            'adt_ToWarehouseID': self._val(item, 'ToWarehouseID'),
            'adt_ToWarehouseName': self._val(item, 'ToWarehouseName'),
            'config_id': self.config_id.id,
            'import_state': 'staged',
            'selected': True,
            'sync_date': fields.Datetime.now(),
        }
        if header.get('adt_FromWarehouseID'):
            type_record = self._search_picking_type(header)
            header['picking_type_id'] = type_record.id if type_record else False
        return header

    def _prepare_vendor_return_line_vals(self, item, reference_nbr):
        return {
            'reference_nbr': reference_nbr,
            'adt_id': item.get('id', '') or '',
            'adt_rowNumber': self._parse_int(item.get('rowNumber')),
            'adt_note': self._val(item, 'LineNote') or self._val(item, 'note'),
            'adt_Description': self._val(item, 'LineDescription') or self._val(item, 'Description'),
            'adt_FromLocationID': self._val(item, 'LineFromLocationID') or self._val(item, 'FromLocationID'),
            'adt_InventoryID': self._val(item, 'LineInventoryID') or self._val(item, 'InventoryID'),
            'adt_LineNumber': self._parse_int(self._val(item, 'LineNumber') or self._val(item, 'LineNbr')),
            'adt_NoteID': self._val(item, 'LineNoteID') or self._val(item, 'NoteID'),
            'adt_LineNoteID': self._val(item, 'LineNoteID') or self._val(item, 'NoteID'),
            'adt_Quantity': self._parse_float(self._val(item, 'LineQuantity') or self._val(item, 'Quantity')),
            'adt_SOOrderNbr': self._val(item, 'LineSOOrderNbr') or self._val(item, 'SOOrderNbr'),
            'adt_SOOrderType': self._val(item, 'LineSOOrderType') or self._val(item, 'SOOrderType'),
            'adt_SOShipmentNbr': self._val(item, 'LineSOShipmentNbr') or self._val(item, 'SOShipmentNbr'),
            'adt_ToLocationID': self._val(item, 'LineToLocationID') or self._val(item, 'ToLocationID'),
            'adt_UOM': self._val(item, 'LineUOM') or self._val(item, 'UOM'),
        }

    def _upsert_vendor_return_staging(self, headers, details):
        if not headers:
            return

        InternalTransferOrder = self.env['internal.transfer.order']
        Header = self.env['acumatica.vendor.return.direct.transfer.staging']
        Detail = self.env['acumatica.vendor.return.direct.transfer.staging.line']
        reference_nbrs = [vals['adt_ReferenceNbr'] for vals in headers if vals.get('adt_ReferenceNbr')]
        existing_headers = Header.search([
            ('adt_ReferenceNbr', 'in', reference_nbrs),
            ('config_id', '=', self.config_id.id),
        ])
        existing_map = {record.adt_ReferenceNbr: record for record in existing_headers}

        detail_map = {}
        for vals in details:
            detail_map.setdefault(vals.pop('reference_nbr'), []).append(vals)

        for vals in headers:
            reference_nbr = vals.get('adt_ReferenceNbr')
            if not reference_nbr:
                continue

            order = InternalTransferOrder.search([('external_ref', '=', reference_nbr)], limit=1)
            vals.update({
                'odoo_internal_transfer_order_id': order.id if order else False,
                'import_message': f'{reference_nbr}: Sudah ada - akan diupdate' if order else 'Data API Imported',
            })

            existing = existing_map.get(reference_nbr)
            if existing:
                if (
                    not vals.get('adt_LastModifiedDateTime')
                    or existing.adt_LastModifiedDateTime == vals['adt_LastModifiedDateTime']
                ):
                    continue
                existing.write(vals)
                header = existing
                header.line_ids.unlink()
            else:
                header = Header.create(vals)

            line_vals = [
                {**line, 'receipt_line_id': header.id}
                for line in detail_map.get(reference_nbr, [])
            ]
            if line_vals:
                Detail.create(line_vals)

    def _validate_staging_against_picking(self, header_list, line_list):
        print("Running validate picking function")
        Picking = self.env['stock.picking']
        lines_to_create = []
        sync_data = fields.Datetime.now()
        for item in header_list:
            
            reference_nbr = item.get('reference_nbr')
            exists = Picking.search_read(
                domain=[('origin', '=', reference_nbr)],
                fields=['id', 'origin'],
                limit=1
            )
            lines_to_create.append({
                **item,
                'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'staged',
                'import_message': f'{reference_nbr}: Sudah ada → akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })

            # move_to_create = self.env['acumatica.vendor.return.direct.transfer.staging.line'].search([('receipt_line_id', '=', item.id)])

            print(f"Length line to create{len(lines_to_create)}")

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_inventory_lines(lines_to_create)
            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_inventory_lines(to_update)

            inventory = self._create_inventory_lines(to_create)
            self._create_inventory_lines_product(lines_to_create, inventory)

    def _search_inventory_lines(self, data):
        if not data:
            return [], [], []

        # Ambil daftar nomor referensi dari data dictionary wizard
        reference_nbrs = [
            d['reference_nbr']
            for d in data
            if d.get('reference_nbr')
        ]
        
        # KOREKSI 1: Gunakan field asli model database staging 'adt_ReferenceNbr'
        existing_lines = self.env['acumatica.vendor.return.direct.transfer.staging'].search([
            ('adt_ReferenceNbr', 'in', reference_nbrs)
        ])

        # KOREKSI 2: Gunakan line.adt_ReferenceNbr untuk mapping key dokumen database
        existing_map = {
            line.adt_ReferenceNbr: line
            for line in existing_lines
        }

        unchanged = []
        to_update = []
        to_create = []
        
        for vals in data:
            existing = existing_map.get(vals['reference_nbr'])

            if not existing:
                to_create.append(vals)
                continue

            to_update.append({
                'record': existing,
                'vals': vals,
            })

        return unchanged, to_update, to_create

    def _update_inventory_lines(self, data):
        if not data:
            return False

        for item in data:
            record = item['record']
            vals = item['vals']


            record.write(vals)

    def _create_inventory_lines(self, data):
        if not data:
            return self.env['acumatica.vendor.return.direct.transfer.staging']

        sync_date = fields.Datetime.now()
        headers_to_create = []

        for vals in data:
            header_vals = {
                'config_id': self.config_id.id,
                'import_state': 'staged',
                'import_message': 'Data API Imported',
                'sync_date': sync_date,
                'selected': True,
                
                'adt_id': vals.get('external_id'),
                'adt_rowNumber': vals.get('row_number'),
                'adt_note': vals.get('note'),
                'adt_Date': vals.get('scheduled_date'),
                'adt_Description': vals.get('description'),
                'adt_DocumentOnly': vals.get('document_only'),
                'adt_ExternalRef': vals.get('external_ref'),
                'adt_LastModifiedDateTime': vals.get('acumatica_write_date'),
                'adt_NoteID': vals.get('note_id'),
                'adt_NoteHeaderID': vals.get('note_header_id'),
                
                # KOREKSI: Sesuaikan nama field dengan model python staging header (Menggunakan adt_Location)
                # 'adt_Location': vals.get('location_code'), 
                
                'adt_PostPeriod': vals.get('post_period'),
                'adt_ReferenceNbr': vals.get('reference_nbr'),
                'adt_ReturnType': vals.get('return_type'),
                'adt_Status': vals.get('status'),
                'adt_TotalQty': self._parse_float(vals.get('total_qty')),
                'adt_TransferType': vals.get('transfer_type'),
                'adt_FromWarehouseID': vals.get('warehouse_code'),
                'adt_FromWarehouseName': vals.get('warehouse_name'),
                'adt_ToWarehouseID': vals.get('warehouse_dest_code'),
                'adt_ToWarehouseName': vals.get('warehouse_dest_name'),
                'picking_type_id': vals.get('picking_type_id'),
            }
            headers_to_create.append(header_vals)

        return self.env['acumatica.vendor.return.direct.transfer.staging'].create(headers_to_create)

    def filter_product_line(self, data, update, create):
        # buat set dari semua external_id di update
        update_ids = {
            item.get('vals', {}).get('external_id')
            for item in update
            if item.get('vals', {}).get('external_id')
        }

        # filter data yang header_external_id ada di update_ids
        update_final = [
            line 
            for line in data 
            if line['header_external_id'] in update_ids
        ]

        # buat set dari semua external_id di create
        create_ids = {
            crt['external_id'] 
            for crt in create
        }

        # filter data yang header_external_id ada di create_ids
        create_final = [line for line in data if line['header_external_id'] in create_ids]

        return update_final, create_final
        
    def filter_by_inventory_lines(self, data, inventory):
        """
        Filter data berdasarkan header_external_id yang ada di inventory.
        
        :param data: list of dict (to_create atau to_update)
        :param inventory: recordset inventory
        :return: list of dict yang header_external_id-nya ada di inventory
        """
        inventory_ids = {rec['external_id'] for rec in inventory}

        filtered_data = [
            vals for vals in data
            if vals.get('header_external_id') in inventory_ids
        ]

        return filtered_data

    def _create_inventory_lines_product(self, data, inventory):
        inventory_map = {
            rec['adt_id']: rec.id
            for rec in inventory
        }

        # 1. Tentukan field apa saja yang VALID dan boleh masuk ke tabel staging line
        valid_line_fields = [
            'receipt_line_id', 
            'adt_id', 
            'adt_rowNumber', 
            'adt_LineNumber', 
            'adt_note', 
            'adt_Description', 
            'adt_FromLocationID', 
            'adt_ToLocationID', 
            'adt_InventoryID', 
            'adt_NoteID',
            'adt_SOOrderNbr', 
            'adt_SOOrderType',
            'adt_SOShipmentNbr', 
            'adt_LineNoteID',
            'adt_UOM', 
            'adt_Quantity'
        ]

        # Pemetaan nama key lama (API) ke nama field baru (Tabel Staging)
        field_mapping = {
            'row_number': 'adt_rowNumber',
            'line_nbr': 'adt_LineNumber',
            'note': 'adt_note',
            'description': 'adt_Description',
            'from_location_code': 'adt_FromLocationID',
            'to_location_code': 'adt_ToLocationID',
            'inventory_id': 'adt_InventoryID',
            'note_id': 'adt_NoteID',
            'so_order_nbr': 'adt_SOOrderNbr',
            'so_order_type': 'adt_SOOrderType',
            'so_shipment_nbr': 'adt_SOShipmentNbr',
            'line_note_id': 'adt_LineNoteID',
            'uom_code': 'adt_UOM',
            'product_uom_qty': 'adt_Quantity',
        }

        cleaned_data = []

        for vals in data:
            print(f"Vals: {vals}")
            # Petakan link ID staging header ke field receipt_line_id
            current_id = vals.get('external_id') or vals.get('adt_id')
            vals['receipt_line_id'] = inventory_map.get(current_id)

            if 'external_id' in vals:
                vals['adt_id'] = vals.pop('external_id')

            # Ubah nama key lama menjadi nama field adt_
            for old_key, new_key in field_mapping.items():
                if old_key in vals:
                    vals[new_key] = vals.pop(old_key)

            # --- BAGIAN PEMBERSIHAN FIELD HEADER ---
            # Buat dictionary baru yang HANYA berisi field valid untuk model line
            line_vals = {
                key: value for key, value in vals.items() if key in valid_line_fields
            }

            # move_vals = {
            #     'adt_id' : vals['external_id'],
            #     'adt_rowNumber' : vals['row_number']
            #     'adt_note' : vals['note']
            #     'adt_Description' : vals['description']
            #     'adt_FromLocationID' : vals['warehouse_code']
            #     'adt_InventoryID' : vals['']
            #     'adt_LineNumber' : vals['']
            #     'adt_NoteID' : vals['']
            #     'adt_Quantity' : vals['']
            #     'adt_SOOrderNbr' : vals['']
            #     'adt_SOOrderType' : vals['']
            #     'adt_SOShipmentNbr' : vals['']
            #     'adt_ToLocationID' : vals['']
            #     'adt_UOM'                 : vals['']
            # }
            
            cleaned_data.append(line_vals)



        print(f"Data Bersih Siap Create: {cleaned_data}")

        # Lakukan batch create menggunakan data yang sudah bersih dari field header
        self.env['acumatica.vendor.return.direct.transfer.staging.line'].create(cleaned_data)

    def _update_inventory_lines_product(self, data, inventory):
        inventory_map = {
            rec['vals']['external_id']: rec['record']['id']
            for rec in inventory
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.vendor.return.direct.transfer.staging.line']

        for vals in data:
            ext_id = vals.get('header_external_id')
            vals['inventory_line_id'] = inventory_map.get(ext_id)
            if vals['inventory_line_id']:
                product_line.browse(vals['inventory_line_id']).write(vals)


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Inventory Recieved dari Acumatica',
            'res_model': 'acumatica.vendor.return.direct.transfer.staging',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.vendor.return.direct.transfer.staging'].search([
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
            'name': 'Hasil Import Inventory Recieved',
            'res_model': 'acumatica.vendor.return.direct.transfer.staging',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
