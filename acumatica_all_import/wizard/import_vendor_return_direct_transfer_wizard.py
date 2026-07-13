from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)


# toko.pegang.do
# toko_pegang_do
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
        print('Run function get data direct transfer')
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


    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        type = False

        print(f"Warehouse: {header['adt_FromWarehouseID']}")

        location = Location.search([
            ('code', '=', header['adt_FromWarehouseID'])
        ])

            
        if location:
            print(f"location : {location}")
            print(f"location : {location.odoo_building_id.id}")
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'internal'),
                ('is_default_api', '=', True)
            ])

            print(f"Type: {type}")

        return type if type else None

    def fetch_data(self, limit=50, offset=0, reference_nbr=False, odata_filter=False):
        self.ensure_one()
        Picking = self.env['stock.picking']
        session = self.config_id._do_login()
        
        # Penampung pesan error agar bisa ditampilkan di akhir proses jika ada yang gagal
        error_messages = [] 
        result = []

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand
            if self.config_id.odata_select:
                params['$select'] = self.config_id.odata_select
            if reference_nbr:
                filters.append(f"ReferenceNbr eq '{reference_nbr}'")
            if odata_filter:
                filters.append(self.config_id.odata_filter)
                filters.extend(odata_filter)
            else:
                if self.config_id.odata_filter:
                    filters.append(f"({self.config_id.odata_filter})")
            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(f'Gagal fetch data (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            print(f"Raw Data: {raw_data}")

            for row_number, item in enumerate(raw_data, start=1):
                # Gunakan savepoint untuk membungkus satu siklus baris data
                try:
                    with self.env.cr.savepoint():
                        header = {
                            'adt_id': item.get('id', '') or '',
                            'adt_rowNumber': item.get('rowNumber', '') or '',
                            'adt_note': item.get('note', {}).get('value', '') or '',
                            'adt_Date': self._val(item, 'Date'),
                            'adt_Description': self._val(item, 'Description'),
                            'adt_ExternalRef': self._val(item, 'ExternalRef'),
                            'adt_LastModifiedDateTime': self._val(item, 'LastModifiedDateTime'),
                            'adt_PostPeriod': str(self._val(item, 'PostPeriod') or ''),
                            'adt_ReferenceNbr': self._val(item, 'ReferenceNbr'),
                            'adt_Status': self._val(item, 'Status'),
                            'adt_TotalQty': str(self._val(item, 'TotalQty') or '0.0'),
                            'adt_TransferType': self._val(item, 'TransferType'), 
                            'adt_FromWarehouseID': self._val(item, 'FromWarehouseID'),
                            'adt_ToWarehouseID': self._val(item, 'ToWarehouseID'),
                        }

                        if header.get('adt_FromWarehouseID'):
                            type_record = self._search_picking_type(header)
                            header['picking_type_id'] = type_record.id if type_record else False

                        if not header['picking_type_id']:
                            raise UserError("Picking type untuk warehouse tersebut tidak ditemukan")
                        
                        print(f"header : {header}")
                        created_header = self.env['acumatica.vendor.return.direct.transfer.staging'].create(header)

                        if created_header:
                            sync_data = fields.Datetime.now()
                            created_header.write({
                                'config_id': self.config_id.id,
                                'import_state': 'pending',
                                'import_message': "Data API Imported",
                                'selected': True,
                                'sync_date': sync_data,
                            })

                        details = item.get('Details') or []
                        if isinstance(details, dict):
                            details = details.get('value', []) or []
                        if not isinstance(details, list):
                            details = []
                    
                        if not details:
                            raise UserError('Data Detail tidak ditemukan')

                        # Array detail_result dipindah ke dalam loop agar ter-reset per dokumen
                        detail_result = []
                        for detail in details:
                            print(f"detail : {detail}")
                            vals = {      
                                'adt_id' : detail.get('id', ''),
                                'adt_rowNumber' : detail.get('rowNumber', ''), 
                                'adt_note' : self._val(detail, 'note'), 
                                'adt_Description' : self._val(detail, 'Description'), 
                                'adt_FromLocationID' : self._val(detail, 'FromLocationID'), 
                                'adt_InventoryID' : self._val(detail, 'InventoryID'), 
                                'adt_LineNumber' : self._val(detail, 'LineNumber'), 
                                'adt_NoteID' : self._val(detail, 'NoteID'), 
                                'adt_Quantity' : self._val(detail, 'Quantity'), 
                                'adt_SOOrderNbr' : self._val(detail, 'SOOrderNbr'), 
                                'adt_SOOrderType' : self._val(detail, 'SOOrderType'), 
                                'adt_SOShipmentNbr' : self._val(detail, 'SOShipmentNbr'), 
                                'adt_ToLocationID' : self._val(detail, 'ToLocationID'), 
                                'adt_UOM' : self._val(detail, 'UOM'), 
                                'receipt_line_id' : created_header.id
                            }
                            detail_result.append(vals)

                        print(f"="*60)
                        print(f"All detail result")
                        print(f"="*60)

                        for detail_item in detail_result:
                            self.env['acumatica.vendor.return.direct.transfer.staging.line'].create(detail_item)
                            print(detail_item)
                            print(f"="*60)

                        self.config_id.last_sync = fields.Datetime.now()
                        result.append(header)
                        _logger.info("Berhasil ambil data ke-%s (Ref: %s) dari Acumatica", row_number, header.get('adt_ReferenceNbr'))

                    # === PENTING: Commit jika satu siklus header + detail sukses tanpa error ===
                    self.env.cr.commit()

                except Exception as e:
                    # Jika error, context manager `with savepoint()` otomatis me-rollback perubahan dokumen ini saja
                    err_msg = f"Gagal import baris ke-{row_number} (Ref: {item.get('ReferenceNbr', {}).get('value', 'N/A')}): {str(e)}"
                    _logger.error(err_msg)
                    error_messages.append(err_msg)
                    continue  # Lanjutkan ke data berikutnya tanpa menghentikan loop

        finally:
            if session:
                self.config_id._do_logout(session)

        # Jika di akhir proses ada data yang error, kita tampilkan semua informasinya
        if error_messages:
            summary = "\n".join(error_messages[:10])  # Batasi tampilkan 10 baris saja agar pop-up tidak penuh
            if len(error_messages) > 10:
                summary += f"\n... dan {len(error_messages) - 10} error lainnya."
            # raise UserError(f"Proses fetch selesai dengan beberapa error:\n{summary}")
        
        return len(result)

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
                'import_state': 'pending',
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

            # KOREKSI 3: Ubah acumatica_write_date menjadi adt_LastModifiedDateTime sesuai model staging Anda
            if existing.adt_LastModifiedDateTime == vals.get('acumatica_write_date'):
                unchanged.append(existing)
            else:
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
                'import_state': 'pending',
                'import_message': 'Data API Imported',
                'sync_date': sync_date,
                'selected': True,
                
                'adt_id': vals.get('external_id'),
                'adt_rowNumber': vals.get('row_number'),
                'adt_note': vals.get('note'),
                'adt_Date': vals.get('scheduled_date'),
                'adt_Description': vals.get('description'),
                'adt_ExternalRef': vals.get('external_ref'),
                'adt_LastModifiedDateTime': vals.get('acumatica_write_date'),
                
                # KOREKSI: Sesuaikan nama field dengan model python staging header (Menggunakan adt_Location)
                # 'adt_Location': vals.get('location_code'), 
                
                'adt_PostPeriod': vals.get('post_period'),
                'adt_ReferenceNbr': vals.get('reference_nbr'),
                'adt_Status': vals.get('status'),
                'adt_TotalQty': self._parse_float(vals.get('total_qty')),
                'adt_TransferType': vals.get('transfer_type'),
                'adt_FromWarehouseID': vals.get('warehouse_code'),
                'adt_ToWarehouseID': vals.get('warehouse_dest_code'),
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
            'adt_SOOrderNbr', 
            'adt_SOShipmentNbr', 
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
            'so_order_nbr': 'adt_SOOrderNbr',
            'so_shipment_nbr': 'adt_SOShipmentNbr',
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
