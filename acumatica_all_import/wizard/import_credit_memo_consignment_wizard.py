from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)


# toko.pegang.do
# toko_pegang_do
class ImportCreditMemoConsignmentWizard(models.TransientModel):
    _name = 'import.credit.memo.consignment.wizard'
    _description = 'Wizard Import Credit Memo Consignment dari Acumatica'

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

        print(f"Warehouse: {header}")

        location = Location.search([
            ('code', '=', header)
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
            result = []
            detail_result = []

            for row_number, item in enumerate(raw_data, start=1):
                try:
                    with self.env.cr.savepoint():
                        # PERBAIKAN: Mapping diselaraskan dengan key JSON Direct Transfer asli Anda
                        header = {

                            'adt_id' : self._val(item, 'id'),
                            'adt_rowNumber' : self._val(item, 'rowNumber'),
                            'adt_note' : self._val(item, 'note'),
                            'adt_ConsignmentType' : self._val(item, 'ConsignmentType'),
                            'adt_CreatedDateTime' : self._val(item, 'CreatedDateTime'),
                            'adt_CustomerID' : self._val(item, 'CustomerID'),
                            'adt_CustomerName' : self._val(item, 'CustomerName'),
                            'adt_CustomerOrder' : self._val(item, 'CustomerOrder'),
                            'adt_Date' : self._val(item, 'Date'),
                            'adt_Description' : self._val(item, 'Description'),
                            'adt_DueDate' : item.get('DueDate', ''),
                            'adt_LastModifiedDateTime' : self._val(item, 'LastModifiedDateTime'),
                            'adt_LocationID' : self._val(item, 'LocationID'),
                            'adt_LocationName' : self._val(item, 'LocationName'),
                            'adt_OrigRefNbr' : self._val(item, 'OrigRefNbr'),
                            'adt_ReferenceNbr' : self._val(item, 'ReferenceNbr'),
                            'adt_Status' : self._val(item, 'Status'),
                            'adt_Type' : self._val(item, 'Type'),                                       
                        }


                            
                        print(f"header : {header}")
                        created_header = self.env['acumatica.credit.memo.consignment.staging'].create(header)

                        if created_header:
                            sync_data = fields.Datetime.now()
                            # Gunakan tanda kurung (), bukan sama dengan (=)
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
                    
                        # print(f"Header: {header}")
                        result.append(header)

                        if not details:
                            raise UserError('Data Detail tidak ditemukan')

                        for detail in details:
                            print(f"detail : {detail}")
                            vals = {
                                'receipt_line_id' : created_header.id,
                                'adt_id' : detail.get('id', ''),
                                'adt_rowNumber' :  self._val(detail, 'rowNumber'), 
                                'adt_note' :  self._val(detail, 'note'), 
                                'adt_Branch' :  self._val(detail, 'Branch'), 
                                'adt_InventoryID' :  self._val(detail, 'InventoryID'), 
                                'adt_Qty' :  self._val(detail, 'Qty'), 
                                'adt_TransactionDescription' :  self._val(detail, 'TransactionDescription'), 
                                'adt_UOM' :  self._val(detail, 'UOM'), 
                                'adt_Warehouse' :  self._val(detail, 'Warehouse'), 
                            }

                            detail_result.append(vals)

                        self.config_id.last_sync = fields.Datetime.now()
                        print(f"="*60)
                        print(f"All detail result")
                        print(f"="*60)
                        warehouse_location = False

                        for item in detail_result:
                            print(item)
                            created_move = self.env['acumatica.credit.memo.consignment.staging.line'].create(item)
                            print(f"="*60)

                            if not warehouse_location:
                                warehouse_location = created_move.adt_Warehouse

                        type_record = self._search_picking_type(warehouse_location)

                        if type_record:
                            created_header.write({'picking_type_id': type_record.id if type_record else False})

                        # if not type_record:
                        #     raise UserError("Picking type untuk warehouse tersebut tidak ditemukan")
                                



                        _logger.info("Berhasil ambil %s rows PO inventory dari Acumatica", len(result))
                
                        # raise UserError('debug')

                except Exception as e:
                    print("=" * 80)
                    print(f"ERROR IMPORT HEADER KE-{row_number}")
                    print(f"Reference Number : {item.get('ReferenceNbr', {}).get('value', '')}")
                    print(f"Header UUID      : {item.get('id', '')}")
                    print(f"Error Type       : {type(e).__name__}")
                    print(f"Error Message    : {str(e)}")
                    print("Header Data :")
                    print(header if 'header' in locals() else item)
                    print("=" * 80)

                    raise UserError(f"ERROR IMPORT HEADER KE-{row_number} dengan error message: {str(e)}")

                    _logger.exception(
                        "Error import Direct Transfer %s",
                        item.get('ReferenceNbr', {}).get('value', '')
                    )
        finally:
            if session:
                self.config_id._do_logout(session)
        
        return len(result)

                        




            # Jangan lupa return hasil akhirnya di paling bawah fungsi Anda jika dibutuhkan oleh fungsi wizard induk!
            # return result, detail_result

        #     # Pastikan proses logout ditaruh di blok finally agar session tidak menggantung di Acumatica jika terjadi crash
        #     self._validate_staging_against_picking(result, detail_result)

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

            # move_to_create = self.env['acumatica.credit.memo.consignment.staging.line'].search([('receipt_line_id', '=', item.id)])

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
        existing_lines = self.env['acumatica.credit.memo.consignment.staging'].search([
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
            return self.env['acumatica.credit.memo.consignment.staging']

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

        return self.env['acumatica.credit.memo.consignment.staging'].create(headers_to_create)

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
        self.env['acumatica.credit.memo.consignment.staging.line'].create(cleaned_data)

    def _update_inventory_lines_product(self, data, inventory):
        inventory_map = {
            rec['vals']['external_id']: rec['record']['id']
            for rec in inventory
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.credit.memo.consignment.staging.line']

        for vals in data:
            ext_id = vals.get('header_external_id')
            vals['inventory_line_id'] = inventory_map.get(ext_id)
            if vals['inventory_line_id']:
                product_line.browse(vals['inventory_line_id']).write(vals)


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Credit Memo Consignment dari Acumatica',
            'res_model': 'acumatica.credit.memo.consignment.staging',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.credit.memo.consignment.staging'].search([
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
            'name': 'Hasil Import Credit Memo Consignment',
            'res_model': 'acumatica.credit.memo.consignment.staging',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
