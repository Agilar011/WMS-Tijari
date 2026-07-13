
from odoo import fields, models
from odoo.exceptions import UserError


class ImportInventoryIssueWizard(models.TransientModel):
    _name = 'import.inventory.issue.wizard'
    _description = 'Wizard Import Inventory Inventory Issue dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    start_date = fields.Char(string="Start Date")
    end_date = fields.Char(string="End Date")
    odata_filter = fields.Char(string='Custom OData Filter', default="TransType eq 'Issue'", help='Filter OData kustom untuk query API. Contoh: TransType eq Issue and LastModifiedDateTime gt 2026-02-12T00:00:00Z')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Delivery Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    def action_fetch_data(self):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: action_fetch_data")
        print("="*80)

        self.ensure_one()
        self.env['acumatica.receipt.change.item.line'].search([('config_id', '=', self.config_id.id)]).unlink()

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
                reference_nbr=self.reference_nbr,
                offset=offset,
                # last_modified_from=/.last_modified_from,
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
        print("="*80)
        print("[DEBUG] MASUK Ke proses login")
        print("="*80)
        
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
                # print(f"receipt Number: {reference_nbr}")
                filters.append(f"ReferenceNbr eq '{reference_nbr}'")
            if odata_filter:
                filters.append(self.config_id.odata_filter)
                filters.extend(odata_filter)
            else:
                filters.append("(Status eq 'On Hold' or Status eq 'Balanced')")
            if filters:
                params['$filter'] = ' and '.join(filters)       

            # print(endpoint)
            # print(params)
            # raise UserError(checkpoint)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                print("="*80)
                print("[DEBUG] MASUK Ke proses get data api")
                print("="*80)

                raise UserError(f'Gagal ambil data PO Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            # print(f"raw data: {raw_data}")


            result = []
            detail_result = []

            for row_number, item in enumerate(raw_data, start=1):

                print("="*80)
                print("[DEBUG] MASUK Ke proses deklarasi header")
                print("="*80)

                header = self._build_header_values(row_number, item)
                print(f"Header : {header}")

                header_id = item.get('id', '')


                # Cek apakah Detail ada dan berbentuk list / dict / array
                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                # print(f"Detail : {details}")

                # header["warehouse_code"] = self._val(details[0], 'Warehouse')
                result.append(dict(header))
                # print(f"Result: {result}")


                print("="*80)
                print("[DEBUG] MASUK Ke proses deklarasi detail")
                print("="*80)
                
                for detail in details:
                    detail_result.append(
                        self._build_detail_values(header_id, detail)
                    )                


            # _logger.info("Berhasil ambil %s rows PO Receipt dari Acumatica", len(result))
            # self._validate_staging_against_picking(result, detail_result)
            # print(f"count result: {len(result)}")
            # return len(result)
            self._create_staging_data(result, detail_result)
            print(f"count result: {len(result)}")
            return len(result)



        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


#     def _validate_staging_against_picking(self, header_list, line_list):
#         print("="*80)
#         print("[DEBUG] MASUK KE FUNGSI: _validate_staging_against_picking")
#         print("="*80)
#         Picking = self.env['stock.picking']
#         lines_to_create = []
#         sync_data = fields.Datetime.now()

#         for item in header_list:
            
#             reference_nbr = item.get('reference_nbr')

#             exists = Picking.search_read(
#                 domain=[('origin', '=', reference_nbr)],
#                 fields=['id', 'origin'],
#                 limit=1
#             )

#             # print(f"exsit data: {exists}")
#             lines_to_create.append({
#                 **item, #header odoo
#                 'odoo_picking_id' : exists[0]['id'] if exists else False,
#                 'config_id': self.config_id.id,
#                 'import_state': 'pending',
#                 'import_message': f'{reference_nbr}: Sudah ada → akan diupdate' if exists else '',
#                 'selected': True,
#                 'sync_date': sync_data,
#             })
#             print(f"line to create: {lines_to_create}")

#         if lines_to_create:
#             # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
#             unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)
#             # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
#             self._update_receipt_lines(to_update)

#             receipts = self._create_receipt_lines(to_create)
#             line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
#             if line_update:
#                 print(line_update)
#                 self._update_receipt_lines_product(line_update, to_update)

#             if line_create:
#                 print(line_create)
#                 self._create_receipt_lines_product(line_create, receipts)
#
    def _create_staging_data(self, header_list, line_list):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _create_staging_data")
        print("="*80)
        print(f"Header List: {header_list}")
        print(f"Line List: {line_list}")
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        lines_to_create = []
        sync_data = fields.Datetime.now()

        for item in header_list:
            
            lines_to_create = ({
                **item, #header odoo
                # 'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': "Data API Imported",
                'selected': True,
                'sync_date': sync_data,
            })
            print(f"line to create: {lines_to_create}")

            created_header = self.env['acumatica.inventory.issue.line'].create(lines_to_create)

            # created_header.write({'odoo_picking_id': created_header.id})

            to_create_move = [move for move in line_list if move.get('header_external_id') == item.get('external_id')]

            for move_item in to_create_move:
                created_move = self.env['acumatica.inventory.issue.product'].create({
                    'receipt_line_id' : created_header.id,
                    'line_external_id' : move_item.get('line_external_id'),
                    'inventory_id' : move_item.get('inventory_id'),
                    'location_code' : move_item.get('location_code'),
                    'uom_code' : move_item.get('uom_code'),
                    'warehouse_code' : move_item.get('warehouse_code'),
                    'branch_warehouse' : move_item.get('branch_warehouse'),
                    'line_description' : move_item.get('line_description'),
                    'line_nbr' : move_item.get('line_nbr'),
                    'line_note' : move_item.get('line_note'),
                    'product_uom_qty' : move_item.get('product_uom_qty'),
                    # 'product_uom_qty' : move_item.get('total_qty'),
                    # 'scheduled_date' : move_item.get('scheduled_date'),
                    # 'post_period' : move_item.get('post_period'),

                })

                print(f"Created Move: {created_move}")




        #     reference_nbr = item.get('receipt_nbr')

        #     exists = Picking.search_read(
        #         domain=[('origin', '=', reference_nbr)
        #                 # ,('state', '=', 'draft')
        #                 ],
        #         fields=['id', 'origin', 'state'],
        #         limit=1
        #     )

        #     existing_origins = [record['origin'] for record in exists if record.get('origin')]

        #     # print(f"exsit data: {exists}")

        # if lines_to_create:
        #     # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
        #     unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)
        #     # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
        #     self._update_receipt_lines(to_update)

        #     receipts = self._create_receipt_lines(to_create)
        #     line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
        #     if line_update:
        #         print(line_update)
        #         self._update_receipt_lines_product(line_update, to_update)

        #     if line_create:
        #         print(line_create)
        #         self._create_receipt_lines_product(line_create, receipts)
                

    # ---------------------------------------------------------
    # Filter
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    def _build_header_values(self, row_number, item):
        print(f"Item: {item}")

        type = self._search_picking_type(item)
        if type:
            # print(f"Type: {type}")
            type = type.id

        if not type:
            type = None
            print("="*80)
            print('Picking Type ID tidak ditemukan untuk warehouse code:', self._val(item, 'WarehouseID'))

        # header['picking_type_id'] = type.id if type else None        
        print("Created header value")
        print(f"Receipt number in header : {self._val(item, 'ShipmentNbr')}")

        return {
            'external_id': item.get('id', '') or '',
            'row_number': row_number,
            'note': item.get('note', {}).get('value', '') or '',
            # 'actual_amount': self._val(item, 'ControlAmount'),
            'actual_qty': self._val(item, 'ShippedQty'),
            'scheduled_date': self._val(item, 'ShipmentDate'),
            'description': self._val(item, 'Description'),
            # 'external_ref': self._val(item, 'ExternalRef'),
            # 'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
            'post_period': self._val(item, 'PostPeriod'),
            'reference_nbr': self._val(item, 'ShipmentNbr'),
            # 'reference_nbr': self._val(item, 'ReferenceNbr'),
            'status': self._val(item, 'Status'),
            # 'total_amount': self._val(item, 'TotalAmount'),
            # 'total_qty': self._val(item, 'TotalQty'),
            'trans_type': self._val(item, 'Type'),
            # 'vendor_code' : self._val(item, 'CustomerID'),
            # 'partner_ref' : self._val(item, 'CustomerID'),
            'picking_type_id': type
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
            if d.get('reference_nbr'):
                receipt_nbrs.append(d['reference_nbr'])

        existing_lines = self.env['acumatica.inventory.issue.line'].search([
            ('reference_nbr', 'in', receipt_nbrs)
        ])

        existing_map = {
            line.origin: line
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

        return self.env['acumatica.inventory.issue.line'].create(data)
    
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
    
    def _build_detail_values(self, header_id, detail):
        

        return {
            'header_external_id': header_id,
            'line_external_id': detail.get('id', '') or '',
            'line_note': detail.get('note', {}).get('value', '') or '',
            'branch_warehouse': self._val(detail, 'Branch'),
            'line_description': self._val(detail, 'Description'),
            'inventory_id': self._val(detail, 'InventoryID'),
            'line_nbr': self._val(detail, 'LineNbr'),
            'location_code': self._val(detail, 'Location'),
            'product_uom_qty': self._val(detail, 'ReceiptQty'),
            'uom_code': self._val(detail, 'UOM'),
            'warehouse_code': self._val(detail, 'WarehouseID'),
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

        product_line = self.env['acumatica.inventory.issue.product']

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



        



    # def action_fetch_data(self):
    #     self.ensure_one()
    #     self.env['acumatica.inventory.issue.line'].search([('config_id', '=', self.config_id.id)]).unlink()

    #     import math

    #     raw_list = []
    #     loop_count = math.ceil(self.fetch_limit / self.batch_size)

    #     for i in range(loop_count):
    #         offset = self.fetch_skip + (i * self.batch_size)
    #         batch_data = self.config_id.fetch_inventory_issue_data(
    #             limit=self.batch_size,
    #             offset=offset,
    #             reference_nbr=self.reference_nbr,
    #             last_modified_from=self.last_modified_from,
    #             odata_filter=self.odata_filter,
    #         )

    #         if not batch_data:
    #             break

    #         raw_list.extend(batch_data)

    #     if not raw_list:
    #         raise UserError('Tidak ada data yang diterima dari API Acumatica.')

    #     Picking = self.env['stock.picking']
    #     existing_keys = set()
    #     new_keys = set()
    #     lines_to_create = []

    #     for item in raw_list:
    #         origin = item.get('reference_nbr')
    #         exists = bool(origin and Picking.search_count([('origin', '=', origin)]))
    #         if exists:
    #             existing_keys.add(origin)
    #             msg = 'Sudah ada → move akan ditambahkan jika belum ada'
    #         else:
    #             new_keys.add(origin)
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

    #     self.env['acumatica.inventory.issue.line'].create(lines_to_create)
    #     self.write({
    #         'state': 'fetched',
    #         'total_fetched': len(raw_list),
    #         'total_new': len([x for x in new_keys if x]),
    #         'total_existing': len([x for x in existing_keys if x]),
    #     })
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'import.inventory.issue.wizard',
    #         'res_id': self.id,
    #         'view_mode': 'form',
    #         'target': 'new',
    #     }

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

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        warehouse_code = self._val(header, 'WarehouseID') 
        type = False

        print(f"Warehouse Code: {warehouse_code}")

        location = Location.search([
            ('code', '=', warehouse_code)
        ])

        print(f"Location: {location.odoo_building_id.id}")

        if location:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'outgoing'),                
                ('is_default_api', '=', True)
            ])


            print(f"Picking Type: {type}")

        return type
