from odoo import models, fields
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser


class ImportReceiptWizard(models.TransientModel):
    _name = 'import.issue.po.return.wizard'
    _description = 'Wizard Import Issue Type PO Return dari Acumatica'

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
        print("[DEBUG] MASUK KE FUNGSI: action_fetch_data")
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

        batch_data = self.fetch_receipt_data()


        raw_list += batch_data


        self.total_fetched = raw_list

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.issue.po.return.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------

    def fetch_receipt_data(self):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: fetch_receipt_data")
        print("="*80)
        self.ensure_one()
        print("="*80)
        print("[DEBUG] MASUK Ke proses login")
        print("="*80)
        
        session = self.config_id._do_login()

        AcumaticaErrorService = self.env["acumatica.webhook.error.service"]
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
            if response.status_code != 200:
                print("="*80)
                print("[DEBUG] MASUK Ke proses get data api")
                print("="*80)

                last_error = (
                    f'Gagal fetch data PO Receipt '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

                AcumaticaErrorService.send_error(
                    webhook_type="fetch",
                    webhook_name="po receipt",
                    error=last_error,
                    error_type="http",
                )
                
                raise UserError(last_error)

            raw_payload = response.json()
            raw_data = (
                raw_payload.get('PurchaseReceiptReturnGIDetails')
                if isinstance(raw_payload, dict)
                else None
            ) or self._normalize_rows(raw_payload)
            result = []
            detail_result = []
            seen_receipts = set()

            for row_number, item in enumerate(raw_data, start=1):

                print("="*80)
                print("[DEBUG] MASUK Ke proses deklarasi header")
                print("="*80)

                header = self._build_header_values(row_number, item)
                header_id = header.get('receipt_nbr') or header.get('external_id')
                header['external_id'] = header_id

                print(f"header : {header}")

                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []
                if not details:
                    details = [item]

                if header_id not in seen_receipts:
                    seen_receipts.add(header_id)
                    result.append(dict(header))

                for detail in details:
                    detail_result.append(
                        self._build_detail_values(header_id, detail)
                    ) 


            # _logger.info("Berhasil ambil %s rows PO Receipt dari Acumatica", len(result))
            self._create_staging_data(result, detail_result)
            print(f"count result: {len(result)}")
            return len(result)


        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


    def _create_staging_data(self, header_list, line_list):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _create_staging_data")
        print("="*80)
        
        sync_data = fields.Datetime.now()
        created_headers = []

        for header_item in header_list:
            # 1. CARI DAN KUMPULKAN BARIS PRODUK YANG COCOK DENGAN HEADER INI
            to_create_move = [
                move for move in line_list 
                if move.get('header_external_id') == header_item.get('external_id')
            ]

            # 2. LOGIKA UTAMA: ISI WAREHOUSE_CODE HEADER DARI LINE JIKA BAWAANNYA KOSONG
            # Ganti 'warehouse_code' di bawah sesuai dengan nama key asli di header_list Anda (misal 'adt_WarehouseID' atau 'warehouse_code')
            if not header_item.get('warehouse_code') and to_create_move:
                # Ambil kode gudang dari baris pertama yang ditemukan di dalam list produk
                first_line_warehouse = to_create_move[0].get('warehouse_code')
                if first_line_warehouse:
                    header_item['warehouse_code'] = first_line_warehouse
                    picking_type = self._search_picking_type(header_item)
                    header_item['picking_type_id'] = picking_type.id if picking_type else None
                    print(f"--> [FIX] Warehouse kosong pada header {header_item.get('external_id')}, diisi otomatis dari line: {first_line_warehouse}")

            # 3. SUSUN VALUES UNTUK STAGING HEADER
            lines_to_create = {
                **header_item,
                'config_id': self.config_id.id,
                'import_state': 'staged',
                'import_message': "Data API Imported",
                'selected': True,
                'sync_date': sync_data,
            }

            receipt_nbr = lines_to_create.get('receipt_nbr')
            Staging = self.env['acumatica.issue.po.return.line']
            existing_headers = Staging.search([
                ('config_id', '=', self.config_id.id),
                ('receipt_nbr', '=', receipt_nbr),
            ], order='id asc') if receipt_nbr else Staging.browse()

            # Satu receipt hanya boleh punya satu header staging.
            # Hapus duplikat lama yang masih staged/error; record created/updated
            # tidak disentuh karena sudah terhubung ke picking Odoo.
            created_header = existing_headers[:1]
            if created_header:
                if (
                    not lines_to_create.get('acumatica_write_date')
                    or created_header.acumatica_write_date == lines_to_create['acumatica_write_date']
                ):
                    continue
                duplicate_headers = existing_headers[1:].filtered(
                    lambda record: record.import_state in ('staged', 'error')
                )
                duplicate_headers.unlink()
                created_header.write(lines_to_create)
                created_header.product_line_ids.unlink()
            else:
                created_header = Staging.create(lines_to_create)
            created_headers.append(created_header)

            # 5. CREATE DATA DETAIL BARANG (CHILD)
            seen_line_keys = set()
            for move_item in to_create_move:
                line_key = move_item.get('line_external_id') or (
                    move_item.get('line_nbr'), move_item.get('inventory_id')
                )
                if line_key in seen_line_keys:
                    continue
                seen_line_keys.add(line_key)
                self.env['acumatica.issue.po.return.product'].create({
                    'receipt_line_id': created_header.id,
                    'line_external_id': move_item.get('line_external_id'),
                    'inventory_id': move_item.get('inventory_id'),
                    'location_code': move_item.get('location_code'),
                    'uom_code': move_item.get('uom_code'),
                    'warehouse_code': move_item.get('warehouse_code'),
                    'branch_warehouse': move_item.get('branch_warehouse'),
                    'line_description': move_item.get('line_description'),
                    'line_nbr': move_item.get('line_nbr'),
                    'line_note': move_item.get('line_note'),
                    'product_uom_qty': move_item.get('product_uom_qty'),
                    'order_qty': move_item.get('order_qty'),
                })

        # return created_headers

                    



    # ---------------------------------------------------------
    # Filter
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    def _build_header_values(self, row_number, item):
         
        type = self._search_picking_type(item)
        if type:
            type = type.id
        if not type:
            type = None
            print("="*80)
            print('Picking Type ID tidak ditemukan untuk warehouse code:', self._val(item, 'Warehouse'))

        # header['picking_type_id'] = type.id if type else None        
        # print("Created header value")
        # print(f"Receipt number in header : {self._val(item, 'ReferenceNbr')}")

        return {
            'external_id': item.get('id', '') or '',
            'row_number': row_number,
            'note': self._val(item, 'NoteHeader')  or '',
            'note_header_id': self._val(item, 'NoteHeaderID'),
            'branch_warehouse': self._val(item, 'Branch'),
            'building_code': self._val(item, 'BuildingID'),
            'change_item_ref_nbr': self._val(item, 'ChangeItemRefNbr'),
            'customer_id': self._val(item, 'CustomerID'),
            'customer_location_id': self._val(item, 'CustomerLocationID'),
            'customer_location_name': self._val(item, 'CustomerLocationName'),
            'customer_name': self._val(item, 'CustomerName'),
            'actual_qty': self._val(item, 'ControlQty'),
            'total_qty': self._val(item, 'TotalQty'),
            'scheduled_date': self._val(item, 'Date'),
            'warehouse_code': self._val(item, 'Warehouse') or self._val(item, 'LineWarehouseID'),
            'header_location_code': self._val(item, 'Location'),
            # 'external_ref': self._val(item, 'ExternalRef'),
            'document_only': self._bool_val(item, 'DocumentOnly'),
            'doc_type': self._val(item, 'DocType'),
            'external_ref': self._val(item, 'ExternalRef'),
            'is_hold': self._val(item, 'Hold'),
            'inventory_ref': self._val(item, 'InventoryRefNbr'),
            'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
            'post_period': self._val(item, 'PostPeriod'),
            'receipt_nbr': self._val(item, 'ReceiptNbr'),
            'status': self._val(item, 'Status'),
            # 'total_amount': self._val(item, 'TotalAmount'),
            # 'total_qty': self._val(item, 'TotalQty'),
            'receipt_type': self._val(item, 'Type'),
            'trans_type': self._val(item, 'TransType'),
            'shipment_nbr': self._val(item, 'ShipmentNbr'),
            'transfer_nbr': self._val(item, 'TransferNbr'),
            'vendor_code' : self._val(item, 'VendorID'),
            'partner_ref' : self._val(item, 'VendorRef') or self._val(item, 'VendorName'),
            'line_nbr': self._val(item, 'LineNumber') or self._val(item, 'LineNbr'),
            'description': self._val(item, 'LineDescription') or self._val(item, 'LineInventoryName'),
            'transaction_description': self._val(item, 'LineDescription') or self._val(item, 'LineInventoryName'),
            'line_inventory_name': self._val(item, 'LineInventoryName'),
            'line_location_name': self._val(item, 'LineLocationName'),
            'line_note_id': self._val(item, 'LineNoteID'),
            'inventory_id': self._val(item, 'LineInventoryID'),
            'line_type': self._val(item, 'LineType'),
            'location_dest_code': self._val(item, 'LineLocation'),
            'open_qty': self._val(item, 'LineOpenQty'),
            'order_qty': self._val(item, 'LineOrderedQty'),
            'po_line_number': self._val(item, 'LinePOLineNbr'),
            'po_number': self._val(item, 'LinePOOrderNbr'),
            'po_type': self._val(item, 'LinePOOrderType') or self._val(item, 'Type'),
            'po_receipt_line_number': self._val(item, 'LinePOReceiptLineNbr'),
            'po_receipt_number': self._val(item, 'LinePOReceiptNbr'),
            'product_uom_qty': self._val(item, 'LineQuantity') or self._val(item, 'LineReceiptQty'),
            'transfer_order_line_number': self._val(item, 'LineTransferOrderLineNbr'),
            'transfer_order_number': self._val(item, 'LineTransferOrderNbr'),
            'transfer_order_type': self._val(item, 'LineTransferOrderType'),
            'transfer_shipment_number': self._val(item, 'LineTransferShipmentNbr'),
            'uom_code': self._val(item, 'LineUOM'),
            'warehouse_code': self._val(item, 'LineWarehouse') or self._val(item, 'LineWarehouseID'),
            'line_warehouse': self._val(item, 'LineWarehouse'),
            'line_warehouse_name': self._val(item, 'LineWarehouseName'),
            'warehouse_dest_code': self._val(item, 'LineWarehouseID') or self._val(item, 'LineWarehouse'),
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
    
    def _build_detail_values(self, header_id,detail):

        

        return {
            'header_external_id': header_id,
            'line_external_id': detail.get('id', '') or '',
            'line_note': self._val(detail, 'LineNote') or '',
            'line_note_id': self._val(detail, 'LineNoteID') or '',
            'branch_warehouse': self._val(detail, 'LineBranch') or '',
            'line_description': self._val(detail, 'LineDescription') or self._val(detail, 'LineInventoryName') or '',
            'line_inventory_name': self._val(detail, 'LineInventoryName') or '',
            'line_location_name': self._val(detail, 'LineLocationName') or '',
            'inventory_id': self._val(detail, 'LineInventoryID') or '',
            'line_nbr': self._val(detail, 'LineNumber') or self._val(detail, 'LineNbr'),
            'location_code': self._val(detail, 'LineLocation') or '',
            'order_qty': self._val(detail, 'LineOrderedQty') or '',
            'product_uom_qty': self._val(detail, 'LineQuantity') or self._val(detail, 'LineReceiptQty') or '',
            'uom_code': self._val(detail, 'LineUOM') or '',
            'warehouse_code': self._val(detail, 'LineWarehouse') or self._val(detail, 'LineWarehouseID') or '',
            'line_warehouse_name': self._val(detail, 'LineWarehouseName') or '',
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
        warehouse_code = (
            header.get('warehouse_code')
            or self._val(header, 'Warehouse')
            or self._val(header, 'LineWarehouseID')
        )
        # details = header.get('Details') or []
        document_only = header.get('document_only')
        if document_only is None:
            document_only = self._bool_val(header, 'DocumentOnly')

        # PO Return moet altijd via Pick starten.  Een eventueel
        # DocumentOnly=true uit payload mag deze transactie niet naar DDO
        # routeren.

        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False

        if not warehouse_code:
            # Normalkan struktur jika details berupa bungkus dictionary OData (mengandung key 'value')
            print("Error warehouse tidak ditemukan")

        print(warehouse_code)

        location = Location.search([
            ('code', '=', warehouse_code)
        ])

        print(f"Location: {location}")

        if location and location.odoo_building_id:
            warehouse = location.odoo_building_id
            configured_pick_type = warehouse.pick_type_id.filtered(
                lambda picking_type: (
                    picking_type.active
                    and picking_type.code == 'internal'
                    and picking_type.operation_category == 'pick'
                )
            )
            pick_type = configured_pick_type or PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('code', '=', 'internal'),
                ('operation_category', '=', 'pick'),
            ], limit=1) or PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('code', '=', 'internal'),
                ('name', 'ilike', 'Pick'),
            ], limit=1)
            if pick_type:
                return pick_type

        if (
            config_picking_type
            and config_picking_type.active
            and config_picking_type.code == 'internal'
            and config_picking_type.operation_category == 'pick'
        ):
            return config_picking_type
        return PickingType.browse()

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
            'name': 'Data PO Return dari Acumatica',
            'res_model': 'acumatica.issue.po.return.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.issue.po.return.line'].search([
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
            'name': 'Hasil Import PO Return',
            'res_model': 'acumatica.issue.po.return.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data PO Return dari Acumatica',
            'res_model': 'acumatica.issue.po.return.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.issue.po.return.line'].search([
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
            'name': 'Hasil Import PO Return',
            'res_model': 'acumatica.issue.po.return.line',
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
    #             'import_state': 'staged',
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
    #         ('import_state', '=', 'staged'),
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
    #             lambda l: l.receipt_nbr == receipt_nbr and l.import_state == 'staged'
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
