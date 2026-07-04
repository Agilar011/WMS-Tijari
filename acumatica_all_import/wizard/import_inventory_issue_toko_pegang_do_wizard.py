from odoo import models, fields
from odoo.exceptions import UserError


class ImportInventoryIssueTokoPegangDOWizard(models.TransientModel):
    _name = 'import.inventory.issue.toko.pegang.do.wizard'
    _description = 'Wizard Import Inventory Issue Toko Pegang DO dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    receipt_nbr = fields.Char(string='Filter Receipt Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help="Contoh: 2025-01-01T00:00:00+07:00")
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    start_date = fields.Char(string="Start Date")
    end_date = fields.Char(string="End Date")
    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    def action_fetch_data(self):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: action_fetch_data invoice consignment")
        print("="*80)

        self.ensure_one()

        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        params = []

        # if self.wh33_filter:
        #     params.append("Details/Warehouse(d: startswith(Details/Warehouse, 'WH33'))")
        #     print("="*80)
        #     print(f"[DEBUG] Masuk ke proses filter warehouse jika field true, WH Filter: {self.wh33_filter}")
        #     print(params)
        #     print("="*80)

        if self.start_date and self.end_date:
            params.append(f"Date ge date'{self.start_date}' and Date le date'{self.end_date}'")
            print("="*80)
            print("[DEBUG] Masuk ke proses get start and end date")
            print("="*80)

        if self.odata_filter:
            params.append(self.odata_filter)
            print("="*80)
            print("[DEBUG] MASUK proses set filter")
            print("="*80)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_receipt_data(
                limit=self.batch_size,
                reference_nbr=self.receipt_nbr,
                offset=offset,
                odata_filter=params if params else None,
            )

            if not batch_data:
                break

            raw_list += batch_data

        self.total_fetched = raw_list

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.receipt.change.item.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------

    def fetch_receipt_data(self, limit=50, offset=0, reference_nbr=False, odata_filter=False):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: fetch_receipt_data")
        print("="*80)
        self.ensure_one()
        first_row_status = False
        
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
                filters.append(f"ReceiptNbr eq '{reference_nbr}'")
            if self.config_id.odata_filter:
                filters.append(self.config_id.odata_filter)
            if filters:
                params['$filter'] = ' and '.join(filters)       

            from requests import Request
            req = Request('GET', endpoint, params=params)
            prepared_url = req.prepare().url
            
            print("="*80)
            print(f"[DEBUG URL API ACUMATICA]:\n{prepared_url}")
            print("="*80)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data PO Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            
            # PINDAHKAN KE LUAR PERULANGAN: Agar total record terhitung dengan benar
            total_imported_headers = 0 
            sync_data = fields.Datetime.now() # Pastikan variabel sync_data terdefinisi

            for row_number, item in enumerate(raw_data, start=1):
                header_id = item.get('id', '')
                header = self._build_header_values(row_number, item, first_row_status)

                lines_to_create = {
                    **header,
                    'config_id': self.config_id.id,
                    'import_state': 'pending',
                    'import_message': "Data API Imported",
                    'selected': True,
                    'sync_date': sync_data,
                }
                
                # 1. Buat Header Staging Terlebih Dahulu
                created_header = self.env['acumatica.inventory.issue.toko.pegang.do.staging'].create(lines_to_create)
                total_imported_headers += 1

                # 2. Normalisasi Data Detail/Lines
                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                # PINDAHKAN KE DALAM: Kosongkan list detail khusus untuk header/invoice aktif saat ini
                detail_to_create = [] 
                
                for detail in details:
                    # Ambil dictionary nilai detail data dari helper fungsi Anda
                    vals_detail = self._build_detail_values(header_id, detail, created_header.adt_id)
                    
                    # LANGSUNG ISI RELASI ID: Kunci utama pencegah missmatch data antar invoice!
                    vals_detail['receipt_line_id'] = created_header.id 
                    
                    detail_to_create.append(vals_detail)

                # 3. Create Bulk Detail Lines (Jauh lebih cepat dan aman dari duplikasi/missmatch)
                if detail_to_create:
                    self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].create(detail_to_create)

                warehouse_code = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([('receipt_line_id', '=', created_header.id)], limit=1)

                if warehouse_code:
                    picking_type = self._search_picking_type(warehouse_code.adt_Warehouse)

                    created_header.write({'picking_type_id': picking_type.id if picking_type else False})


                print(f"[DEBUG] Berhasil memproses Header ID: {header_id} dengan {len(detail_to_create)} baris detail.")

            print(f"Count result: {total_imported_headers}")
            return total_imported_headers

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


    # def _create_staging_data(self, header_list, line_list):
    #     print("="*80)
    #     print("[DEBUG] MASUK KE FUNGSI: _create_staging_data")
    #     print("="*80)
    #     print(f"Header List: {header_list}")
    #     print(f"Line List: {line_list}")
    #     Picking = self.env['stock.picking']
    #     Move = self.env['stock.move']
    #     lines_to_create = []
    #     sync_data = fields.Datetime.now()

    #     for item in header_list:
            
    #         lines_to_create = ({
    #             **item, #header odoo
    #             # 'odoo_picking_id' : exists[0]['id'] if exists else False,
    #             'config_id': self.config_id.id,
    #             'import_state': 'pending',
    #             'import_message': "Data API Imported",
    #             'selected': True,
    #             'sync_date': sync_data,
    #         })
    #         print(f"line to create: {lines_to_create}")

    #         created_header = self.env['acumatica.invoice.consignment.staging'].create(lines_to_create)

    #         # created_header.write({'odoo_picking_id': created_header.id})

    #         to_create_move = [move for move in line_list if move.get('header_external_id') == item.get('external_id')]

    #         for move_item in to_create_move:
    #             self.env['acumatica.invoice.consignment.staging.line'].create({
    #                 **move_item, #detail odoo
    #                 'receipt_line_id' : created_header.id,
    #                 # 'line_external_id' : move_item.get('line_external_id'),
    #                 # 'inventory_id' : move_item.get('inventory_id'),
    #                 # 'location_code' : move_item.get('location_code'),
    #                 # 'uom_code' : move_item.get('uom_code'),
    #                 # 'warehouse_code' : move_item.get('warehouse_code'),
    #                 # 'branch_warehouse' : move_item.get('branch_warehouse'),
    #                 # 'line_description' : move_item.get('line_description'),
    #                 # 'line_nbr' : move_item.get('line_nbr'),
    #                 # 'line_note' : move_item.get('line_note'),
    #                 # 'product_uom_qty' : move_item.get('product_uom_qty'),
    #                 # 'product_uom_qty' : move_item.get('total_qty'),
    #                 # 'scheduled_date' : move_item.get('scheduled_date'),
    #                 # 'post_period' : move_item.get('post_period'),

    #             })




    #     #     reference_nbr = item.get('receipt_nbr')

    #     #     exists = Picking.search_read(
    #     #         domain=[('origin', '=', reference_nbr)
    #     #                 # ,('state', '=', 'draft')
    #     #                 ],
    #     #         fields=['id', 'origin', 'state'],
    #     #         limit=1
    #     #     )

    #     #     existing_origins = [record['origin'] for record in exists if record.get('origin')]

    #     #     # print(f"exsit data: {exists}")

    #     # if lines_to_create:
    #     #     # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
    #     #     unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)
    #     #     # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
    #     #     self._update_receipt_lines(to_update)

    #     #     receipts = self._create_receipt_lines(to_create)
    #     #     line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
    #     #     if line_update:
    #     #         print(line_update)
    #     #         self._update_receipt_lines_product(line_update, to_update)

    #     #     if line_create:
    #     #         print(line_create)
    #     #         self._create_receipt_lines_product(line_create, receipts)

    # ---------------------------------------------------------
    # Filter
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    def _build_header_values(self, row_number, item, first_row_status):

        if not first_row_status:
            print("="*80)
            print(f"First Row : {item}")
            first_row_status = True

         
        # type = self._search_picking_type(item)
        # if type:
        #     type = type.id
        # if not type:
        #     type = None
        #     print("="*80)
        #     print('Picking Type ID tidak ditemukan untuk warehouse code:', self._val(item, 'Warehouse'))

        # header['picking_type_id'] = type.id if type else None        
        print("Created header value")
        print(f"Receipt number in header : {self._val(item, 'ReferenceNbr')}")

        return {

            'adt_id' : self._val(item, 'id'),
            'adt_rowNumber' : item.get('rowNumber'),
            'adt_note' : self._val(item, 'note'),
            'adt_Date' : self._val(item, 'Date'),
            'adt_Description' : self._val(item, 'Description'),
            'adt_LastModifiedDateTime' : self._val(item, 'LastModifiedDateTime'),
            'adt_document_only' : self._val(item, 'DocumentOnly'),
            # 'adt_CreatedDateTime' : self._val(item, 'CreatedDateTime'),
            # 'adt_CustomerID' : self._val(item, 'CustomerID'),
            # 'adt_CustomerName' : self._val(item, 'CustomerName'),
            # 'adt_CustomerOrder' : self._val(item, 'CustomerOrder'),
            # 'adt_DueDate' : self._val(item, 'DueDate'),
            'adt_LocationID' : self._val(item, 'Location'),
            # 'adt_LocationName' : self._val(item, 'LocationName'),
            # 'adt_OrigRefNbr' : self._val(item, 'OrigRefNbr'),
            'adt_ReferenceNbr' : self._val(item, 'ReferenceNbr'),
            'adt_Status' : self._val(item, 'Status'),
            'adt_Type' : self._val(item, 'Type'),            
            # 'external_id': item.get('id', '') or '',
            # 'row_number': row_number,
            # 'note': item.get('note', {}).get('value', '') or '',
            # 'actual_qty': self._val(item, 'ControlQty'),
            # 'total_qty': self._val(item, 'TotalQty'),
            # 'scheduled_date': self._val(item, 'Date'),
            # # 'description': self._val(item, 'Description'),
            # # 'external_ref': self._val(item, 'ExternalRef'),
            # # 'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
            'adt_post_period': self._val(item, 'PostPeriod'),
            'adt_TransType' : self._val(item, 'TransType'),
            # 'receipt_nbr': self._val(item, 'ReceiptNbr'),
            # 'status': self._val(item, 'Status'),
            # # 'total_amount': self._val(item, 'TotalAmount'),
            # # 'total_qty': self._val(item, 'TotalQty'),
            # 'po_type': self._val(item, 'Type'),
            # 'vendor_code' : self._val(item, 'VendorID'),
            # 'partner_ref' : self._val(item, 'VendorName'),
            # 'picking_type_id': type

            }


    def _update_receipt_lines(self, data):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _update_receipt_lines")
        print("="*80)
        if not data:
            return False

        for item in data:
            record = item['record']
            vals = item['vals']


            record.write(vals)

    def _search_receipt_lines(self, data):
        print(data)
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _search_receipt_lines")
        print("="*80)
        if not data:
            return [], [], []

        receipt_nbrs = []

        for d in data:
            if d.get('receipt_nbr'):
                receipt_nbrs.append(d['receipt_nbr'])

        existing_lines = self.env['acumatica.issue.po.return.line'].search([
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


    def _create_receipt_lines(self, data):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _create_receipt_lines")
        print("="*80)
        if not data:
            return False

        return self.env['acumatica.issue.po.return.line'].create(data)
    
    def filter_by_receipt_lines(self, data, receipts):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: filter_by_receipt_lines")
        print("="*80)
        """
        Filter data berdasarkan header_external_id yang ada di receipts.
        
        :param data: list of dict (to_create atau to_update)
        :param receipts: recordset receipt
        :return: list of dict yang header_external_id-nya ada di receipts
        """
        receipt_ids = {rec['external_id'] for rec in receipts}

        filtered_data = [
            vals for vals in data
            if vals.get('header_external_id') in receipt_ids
        ]

        return filtered_data




    # ---------------------------------------------------------
    # DETAIL
    # ---------------------------------------------------------
    
    def _build_detail_values(self, header_id,detail, header_id_id):
        # print(f"Detail: {detail}")

        # rownumber = detail.get('RowNumber')
        # print(f"Row Number: {rownumber}")

        

        return {
            'adt_id': self._val(detail, 'id'),
            'adt_rowNumber': self._val(detail, 'rowNumber'),
            'adt_note': self._val(detail, 'Note'),
            'adt_Branch': self._val(detail, 'Branch'),
            'adt_InventoryID': self._val(detail, 'InventoryID'),
            'adt_Qty': self._val(detail, 'Qty'),
            'adt_TransactionDescription': self._val(detail, 'Description'),
            'adt_UOM': self._val(detail, 'UOM'),
            'adt_Warehouse': self._val(detail, 'WarehouseID'),
            'adt_external_id': header_id_id,
            # 'line_external_id': detail.get('id', '') or '',
            # 'line_note': detail.get('note', {}).get('value', '') or '',
            # 'branch_warehouse': self._val(detail, 'Branch'),
            # 'line_description': self._val(detail, 'Description'),
            # 'inventory_id': self._val(detail, 'InventoryID'),
            # 'line_nbr': self._val(detail, 'LineNbr'),
            # 'location_code': self._val(detail, 'Location'),
            # 'product_uom_qty': self._val(detail, 'ReceiptQty'),
            # 'uom_code': self._val(detail, 'UOM'),
            # 'warehouse_code': self._val(detail, 'WarehouseID'),
        }

        

    def _create_receipt_lines_product(self, data, receipts):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _create_receipt_lines_product")
        print("="*80)
        receipt_map = {
            rec['external_id']: rec.id
            for rec in receipts
        }

        for vals in data:
            vals['receipt_line_id'] = receipt_map.get(
                vals['header_external_id']
            )

        self.env['acumatica.inventory.issue.product'].create(data)

    def filter_product_line(self, data, update, create):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: filter_product_line")
        print("="*80)
        # buat set dari semua external_id di update
        update_ids = {
            item.get('vals', {}).get('line_external_id')
            for item in update
            if item.get('vals', {}).get('external_id')
        }

        # filter data yang header_external_id ada di update_ids
        update_final = [
            line 
            for line in data 
            if line['line_external_id'] in update_ids
        ]

        # buat set dari semua external_id di create
        create_ids = {
            crt['external_id'] 
            for crt in create
        }

        # filter data yang header_external_id ada di create_ids
        create_final = [line for line in data if line['line_external_id'] in create_ids]

        return update_final, create_final

    def _update_receipt_lines_product(self, data, receipts):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _update_receipt_lines_product")
        print("="*80)
        receipt_map = {
            rec['vals']['external_id']: rec['record']['id']
            for rec in receipts
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.issue.po.return.product']

        for vals in data:
            ext_id = vals.get('header_external_id')
            vals['receipt_line_id'] = receipt_map.get(ext_id)
            if vals['receipt_line_id']:
                product_line.browse(vals['receipt_line_id']).write(vals)


# ---------------------------------------------------------
# API MAPPING
# ---------------------------------------------------------
# ---------------------------------------------------------
# API
# ---------------------------------------------------------
    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------    
    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        warehouse_code = header
        type = False

        print(f"Warehouse Code: {warehouse_code}")

        location = Location.search([
            ('code', '=', warehouse_code)
        ])

        print(f"Location: {location}")

        if location:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'outgoing'),                
                ('is_default_api', '=', True)
            ])

        return type

    def _normalize_rows(self, payload):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _normalize_rows")
        print("="*80)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []
    
    def _val(self, item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            
            # print("="*80)
            # print(f"[DEBUG] MASUK proses formating: {value}")
            # print("="*80)
            
            return value.get('value', '') or ''
        # print(value)
        return value or ''
    
    @staticmethod
    def _parse_dt(dt_str):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _parse_dt")
        print("="*80)
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Receipt Type Change Item dari Acumatica',
            'res_model': 'acumatica.receipt.change.item.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.receipt.change.item.line'].search([
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
            'name': 'Hasil Import Receipt Type Change Item',
            'res_model': 'acumatica.receipt.change.item.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Inventory Inventory Issue dari Acumatica',
            'res_model': 'acumatica.inventory.issue.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.inventory.issue.line'].search([
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
            'name': 'Hasil Import Delivery Order',
            'res_model': 'acumatica.inventory.issue.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
   
    # def action_fetch_data(self):
    #     self.ensure_one()
    #     self.env['acumatica.issue.po.return.line'].search([('config_id', '=', self.config_id.id)]).unlink()

    #     import math

    #     raw_list = []
    #     loop_count = math.ceil(self.fetch_limit / self.batch_size)

    #     for i in range(loop_count):
    #         offset = self.fetch_skip + (i * self.batch_size)
    #         batch_data = self.config_id.fetch_receipt_data(
    #             limit=self.batch_size,
    #             offset=offset,
    #             receipt_nbr=self.receipt_nbr,
    #             last_modified_from=self.last_modified_from,
    #             odata_filter=self.odata_filter,
    #         )

    #         if not batch_data:
    #             break

    #         raw_list.extend(batch_data)

    #     if not raw_list:
    #         raise UserError('Tidak ada data yang diterima dari API Acumatica.')

    #     Picking = self.env['stock.picking']
    #     existing_receipts = set()
    #     new_receipts = set()
    #     lines_to_create = []

    #     for item in raw_list:
    #         receipt_nbr = item.get('receipt_nbr')
    #         exists = bool(receipt_nbr and Picking.search_count([('adt_receipt_nbr', '=', receipt_nbr)]))
    #         if exists:
    #             existing_receipts.add(receipt_nbr)
    #             msg = 'Sudah ada → akan diupdate'
    #         else:
    #             new_receipts.add(receipt_nbr)
    #             msg = ''
    #         vals = dict(item)
    #         vals.update({
    #             'config_id': self.config_id.id,
    #             'import_state': 'pending',
    #             'import_message': msg,
    #             'selected': True,
    #             'sync_date': fields.Datetime.now(),
    #         })
    #         lines_to_create.append(vals)

    #     self.env['acumatica.issue.po.return.line'].create(lines_to_create)
    #     self.write({
    #         'state': 'fetched',
    #         'total_fetched': len(raw_list),
    #         'total_new': len([r for r in new_receipts if r]),
    #         'total_existing': len([r for r in existing_receipts if r]),
    #     })
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'import.issue.po.return.wizard',
    #         'res_id': self.id,
    #         'view_mode': 'form',
    #         'target': 'new',
    #     }

    # def action_view_staging(self):
    #     self.ensure_one()
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': 'Data Issue Type PO Return dari Acumatica',
    #         'res_model': 'acumatica.issue.po.return.line',
    #         'view_mode': 'list,form',
    #         'domain': [('config_id', '=', self.config_id.id)],
    #         'context': {'default_config_id': self.config_id.id},
    #     }

    # def action_import_all_pending(self):
    #     self.ensure_one()
    #     lines = self.env['acumatica.issue.po.return.line'].search([
    #         ('config_id', '=', self.config_id.id),
    #         ('import_state', '=', 'pending'),
    #         ('selected', '=', True),
    #     ])
    #     if not lines:
    #         raise UserError('Tidak ada data pending yang dipilih untuk diimport.')
    #     lines._do_import()
    #     self.state = 'done'
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': 'Hasil Import Issue Type PO Return',
    #         'res_model': 'acumatica.issue.po.return.line',
    #         'view_mode': 'list,form',
    #         'domain': [('config_id', '=', self.config_id.id)],
    #     }

    # def TestMismatchingDataBatch1(self):
    #     self.ensure_one()
    #     data = [
    #         {
    #             "id": "9fb62285-1203-e611-8805-28924a357ca0",
    #             "rowNumber": 1,
    #             "note": {
    #                 "value": ""
    #             },
    #             "Branch": {
    #                 "value": "MAIN"
    #             },
    #             "ControlQty": {
    #                 "value": 1000.000000
    #             },
    #             "Date": {
    #                 "value": "2011-12-01"
    #             },
    #             "Details": [
    #                 {
    #                     "id": "10d7d708-6f5e-4138-a354-584f2b60f3ec",
    #                     "rowNumber": 1,
    #                     "note": {
    #                         "value": ""
    #                     },
    #                     "Branch": {
    #                         "value": "MAIN"
    #                     },
    #                     "Description": {},
    #                     "InventoryID": {
    #                         "value": "PARWH00MBOX-PW-251EA"
    #                     },
    #                     "LineNbr": {
    #                         "value": 1
    #                     },
    #                     "LineType": {
    #                         "value": "Goods for IN"
    #                     },
    #                     "Location": {
    #                         "value": "FG"
    #                     },
    #                     "NoteID": {
    #                         "value": "10d7d708-6f5e-4138-a354-584f2b60f3ec"
    #                     },
    #                     "OpenQty": {
    #                         "value": 0.000000
    #                     },
    #                     "OrderedQty": {
    #                         "value": 1000.000000
    #                     },
    #                     "POLineNbr": {
    #                         "value": 1
    #                     },
    #                     "POOrderNbr": {
    #                         "value": "11-000017"
    #                     },
    #                     "POOrderType": {
    #                         "value": "Normal"
    #                     },
    #                     "POReceiptLineNbr": {},
    #                     "POReceiptNbr": {},
    #                     "ReceiptQty": {
    #                         "value": 1000.000000
    #                     },
    #                     "TransactionDescription": {
    #                         "value": "Master Box PW-251EA"
    #                     },
    #                     "TransferOrderLineNbr": {},
    #                     "TransferOrderNbr": {},
    #                     "TransferOrderType": {},
    #                     "TransferShipmentNbr": {},
    #                     "UOM": {
    #                         "value": "PIECE"
    #                     },
    #                     "Warehouse": {
    #                         "value": "WH01-FG"
    #                     },
    #                     "custom": {},
    #                     "_links": {
    #                         "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/transactions/10d7d708-6f5e-4138-a354-584f2b60f3ec/{filename}"
    #                     }
    #                 },
    #             ],
    #             "Hold": {
    #                 "value": "False"
    #             },
    #             "InventoryRefNbr": {
    #                 "value": "11-000025"
    #             },
    #             "Location": {
    #                 "value": "MAIN"
    #             },
    #             "PostPeriod": {
    #                 "value": "122011"
    #             },
    #             "ReceiptNbr": {
    #                 "value": "R11-000001"
    #             },
    #             "Status": {
    #                 "value": "Released"
    #             },
    #             "TotalQty": {
    #                 "value": 1000.000000
    #             },
    #             "Type": {
    #                 "value": "Receipt"
    #             },
    #             "VendorID": {
    #                 "value": "LM010I"
    #             },
    #             "VendorName": {
    #                 "value": "Megah Lestari Packindo, Pt"
    #             },
    #             "VendorRef": {},
    #             "Warehouse": {},
    #             "custom": {},
    #             "_links": {
    #                 "self": "/acumportal/entity/wms/25.200.002/PurchaseReceipt/9fb62285-1203-e611-8805-28924a357ca0",
    #                 "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/Document/9fb62285-1203-e611-8805-28924a357ca0/{filename}"
    #             }
    #         }
    #     ]
        
    # def TestMismatchingDataBatch2(self):
    #     self.ensure_one()
    #     data = [
    #         {
    #             "id": "9fb62285-1203-e611-8805-28924a357ca0",
    #             "rowNumber": 1,
    #             "note": {
    #                 "value": ""
    #             },
    #             "Branch": {
    #                 "value": "MAIN"
    #             },
    #             "ControlQty": {
    #                 "value": 500.000000
    #             },
    #             "Date": {
    #                 "value": "2011-12-01"
    #             },
    #             "Details": [
    #                 {
    #                     "id": "10d7d708-6f5e-4138-a354-584f2b60f3ec",
    #                     "rowNumber": 1,
    #                     "note": {
    #                         "value": ""
    #                     },
    #                     "Branch": {
    #                         "value": "MAIN"
    #                     },
    #                     "Description": {},
    #                     "InventoryID": {
    #                         "value": "PARWH00MBOX-PW-251EA"
    #                     },
    #                     "LineNbr": {
    #                         "value": 1
    #                     },
    #                     "LineType": {
    #                         "value": "Goods for IN"
    #                     },
    #                     "Location": {
    #                         "value": "FG"
    #                     },
    #                     "NoteID": {
    #                         "value": "10d7d708-6f5e-4138-a354-584f2b60f3ec"
    #                     },
    #                     "OpenQty": {
    #                         "value": 0.000000
    #                     },
    #                     "OrderedQty": {
    #                         "value": 500.000000
    #                     },
    #                     "POLineNbr": {
    #                         "value": 1
    #                     },
    #                     "POOrderNbr": {
    #                         "value": "11-000017"
    #                     },
    #                     "POOrderType": {
    #                         "value": "Normal"
    #                     },
    #                     "POReceiptLineNbr": {},
    #                     "POReceiptNbr": {},
    #                     "ReceiptQty": {
    #                         "value": 500.000000
    #                     },
    #                     "TransactionDescription": {
    #                         "value": "Master Box PW-251EA"
    #                     },
    #                     "TransferOrderLineNbr": {},
    #                     "TransferOrderNbr": {},
    #                     "TransferOrderType": {},
    #                     "TransferShipmentNbr": {},
    #                     "UOM": {
    #                         "value": "PIECE"
    #                     },
    #                     "Warehouse": {
    #                         "value": "WH01-FG"
    #                     },
    #                     "custom": {},
    #                     "_links": {
    #                         "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/transactions/10d7d708-6f5e-4138-a354-584f2b60f3ec/{filename}"
    #                     }
    #                 },
    #             ],
    #             "Hold": {
    #                 "value": "False"
    #             },
    #             "InventoryRefNbr": {
    #                 "value": "11-000025"
    #             },
    #             "Location": {
    #                 "value": "MAIN"
    #             },
    #             "PostPeriod": {
    #                 "value": "122011"
    #             },
    #             "ReceiptNbr": {
    #                 "value": "R11-000001"
    #             },
    #             "Status": {
    #                 "value": "Released"
    #             },
    #             "TotalQty": {
    #                 "value": 500.000000
    #             },
    #             "Type": {
    #                 "value": "Receipt"
    #             },
    #             "VendorID": {
    #                 "value": "LM010I"
    #             },
    #             "VendorName": {
    #                 "value": "Megah Lestari Packindo, Pt"
    #             },
    #             "VendorRef": {},
    #             "Warehouse": {},
    #             "custom": {},
    #             "_links": {
    #                 "self": "/acumportal/entity/wms/25.200.002/PurchaseReceipt/9fb62285-1203-e611-8805-28924a357ca0",
    #                 "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/Document/9fb62285-1203-e611-8805-28924a357ca0/{filename}"
    #             }
    #         }
    #     ]

    # def _test_import(self):
    #     Picking = self.env['stock.picking']
    #     Move = self.env['stock.move']
    #     PickingType = self.env['stock.picking.type']

    #     imported = 0
    #     updated = 0
    #     error = 0

    #     # proses per receipt number
    #     for receipt_nbr in self.mapped('receipt_nbr'):
    #         receipt_lines = self.filtered(
    #             lambda l: l.receipt_nbr == receipt_nbr and l.import_state == 'pending'
    #         )
    #         if not receipt_lines:
    #             continue

    #         first = receipt_lines[0]

    #         try:
    #             vendor = self._find_vendor(first)
    #             warehouse = self._find_warehouse(first)
    #             if not warehouse:
    #                 raise UserError(
    #                     f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}'
    #                 )

    #             picking_type = PickingType.search([
    #                 ('warehouse_id', '=', warehouse.id),
    #                 ('code', '=', 'incoming'),
    #             ], limit=1) or PickingType.search([
    #                 ('code', '=', 'incoming')
    #             ], limit=1)

    #             if not picking_type:
    #                 raise UserError('Picking type incoming tidak ditemukan.')

    #             dest_location = self._find_location_dest(first, warehouse)
    #             if not dest_location:
    #                 raise UserError(
    #                     f'Location tujuan tidak ditemukan untuk code: '
    #                     f'{first.location_dest_code or first.header_location_code or "-"}'
    #                 )

    #             origin = first.receipt_nbr or first.po_number or False

    #             vals = {
    #                 'partner_id': vendor.id if vendor else False,
    #                 'picking_type_id': picking_type.id,
    #                 'location_id': (
    #                     picking_type.default_location_src_id.id
    #                     if picking_type.default_location_src_id
    #                     else self.env.ref('stock.stock_location_suppliers').id
    #                 ),
    #                 'location_dest_id': dest_location.id,
    #                 'scheduled_date': self._parse_dt(first.scheduled_date),
    #                 'origin': origin,
    #                 'note': first.note or False,

    #                 # field custom, kalau ada di model
    #                 'adt_receipt_nbr': first.receipt_nbr or False,
    #                 'adt_vendor_code': first.vendor_code or False,
    #                 'adt_partner_ref': first.partner_ref or False,
    #                 'adt_branch_warehouse': first.branch_warehouse or False,
    #                 'adt_actual_qty': self._parse_float(first.actual_qty),
    #                 'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
    #                 'adt_inventory_ref': first.inventory_ref or False,
    #                 'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
    #                 'adt_header_location_code': first.header_location_code or False,
    #                 'adt_post_period': first.post_period or False,
    #                 'adt_status': first.status or False,
    #                 'adt_total_qty': self._parse_float(first.total_qty),
    #                 'adt_type': first.receipt_type or False,
    #                 'adt_warehouse_code': first.warehouse_code or False,
    #                 'adt_external_id': first.external_id or False,
    #             }

    #             # filter field yang bener-bener ada di stock.picking
    #             vals = {k: v for k, v in vals.items() if k in Picking._fields}

    #             # pakai origin buat dedup
    #             picking = Picking.search([('origin', '=', origin)], limit=1)

    #             if picking:
    #                 if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
    #                     raise UserError(
    #                         f'Receipt {receipt_nbr} sudah ada di Odoo dengan state '
    #                         f'{picking.state}, tidak bisa diupdate.'
    #                     )
    #                 picking.write(vals)
    #                 action_state = 'updated'
    #                 updated += 1
    #             else:
    #                 picking = Picking.create(vals)
    #                 action_state = 'imported'
    #                 imported += 1

    #             for line in receipt_lines:
    #                 try:
    #                     product = self._find_product(line)
    #                     if not product:
    #                         raise UserError(
    #                             f'Product tidak ditemukan untuk InventoryID: '
    #                             f'{line.inventory_id or "-"}'
    #                         )

    #                     uom = self._find_uom(line, product)
    #                     line_dest = self._find_location_dest(line, warehouse) or dest_location
    #                     qty = self._parse_float(line.product_uom_qty)

    #                     # dedup move
    #                     move_domain = [('picking_id', '=', picking.id)]
    #                     if 'adt_line_external_id' in Move._fields and line.line_external_id:
    #                         move_domain.append(('adt_line_external_id', '=', line.line_external_id))
    #                     else:
    #                         move_domain += [
    #                             ('product_id', '=', product.id),
    #                             ('product_uom_qty', '=', qty),
    #                         ]

    #                     existing_move = Move.search(move_domain, limit=1)
    #                     if existing_move:
    #                         line.write({
    #                             'import_state': action_state,
    #                             'import_message': f'Skip duplicate: {picking.name}',
    #                             'odoo_picking_id': picking.id,
    #                         })
    #                         continue

    #                     move_vals = {
    #                         'name': line.transaction_description or line.description or product.display_name,
    #                         'picking_id': picking.id,
    #                         'product_id': product.id,
    #                         'product_uom_qty': qty,
    #                         'product_uom': uom.id if uom else product.uom_id.id,
    #                         'location_id': picking.location_id.id,
    #                         'location_dest_id': line_dest.id,
    #                         'description_picking': line.description or False,

    #                         'adt_line_external_id': line.line_external_id or False,
    #                         'adt_inventory_id': line.inventory_id or False,
    #                         'adt_line_nbr': line.line_nbr or False,
    #                         'adt_line_type': line.line_type or False,
    #                         'adt_open_qty': self._parse_float(line.open_qty),
    #                         'adt_order_qty': self._parse_float(line.order_qty),
    #                         'adt_po_line_number': line.po_line_number or False,
    #                         'adt_po_number': line.po_number or False,
    #                         'adt_po_type': line.po_type or False,
    #                         'adt_po_receipt_line_number': line.po_receipt_line_number or False,
    #                         'adt_po_receipt_number': line.po_receipt_number or False,
    #                         'adt_transfer_order_line_number': line.transfer_order_line_number or False,
    #                         'adt_transfer_order_number': line.transfer_order_number or False,
    #                         'adt_transfer_order_type': line.transfer_order_type or False,
    #                         'adt_transfer_shipment_number': line.transfer_shipment_number or False,
    #                         'adt_uom_code': line.uom_code or False,
    #                         'adt_warehouse_dest_code': line.warehouse_dest_code or False,
    #                         'adt_location_dest_code': line.location_dest_code or False,
    #                         'adt_line_note': line.line_note or False,
    #                     }

    #                     # filter field yang ada di stock.move
    #                     move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}

    #                     Move.create(move_vals)

    #                     line.write({
    #                         'import_state': action_state,
    #                         'import_message': f'{action_state.title()}: {picking.name}',
    #                         'odoo_picking_id': picking.id,
    #                     })

    #                 except Exception as line_e:
    #                     line.write({
    #                         'import_state': 'error',
    #                         'import_message': str(line_e)[:200],
    #                         'odoo_picking_id': picking.id if picking else False,
    #                     })
    #                     error += 1

    #         except Exception as e:
    #             receipt_lines.write({
    #                 'import_state': 'error',
    #                 'import_message': str(e)[:200],
    #             })
    #             error += len(receipt_lines)

    #     msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'display_notification',
    #         'params': {
    #             'title': 'Import Inventory Receipt',
    #             'message': msg,
    #             'type': 'success' if error == 0 else 'warning',
    #             'sticky': True,
    #         }
    #     }
