from odoo import models, fields
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from datetime import datetime, time, timezone

import logging
_logger = logging.getLogger(__name__)


class ImportReceiptChangeItemWizard(models.TransientModel):
    _name = 'import.receipt.change.item.wizard'
    _description = 'Wizard Import Receipt Type Change Item dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')
    odata_filter = fields.Char(string='Custom OData Filter', default="TransType eq 'Change Item'", help='Filter tambahan untuk query OData. Contoh: TransDate ge 2026-01-01T00:00:00Z')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Picking Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    wh33_filter = fields.Boolean(string='WH33 Only', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')


    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    def action_fetch_data(self):
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
            start_date_datetime_str = datetime.combine(
                fields.Date.to_date(self.start_date),
                time.min,
                tzinfo=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
            end_date_datetime_str = datetime.combine(
                fields.Date.to_date(self.end_date),
                time.min,
                tzinfo=timezone.utc,
            ).isoformat().replace("+00:00", "Z")

            params.append(f"Date ge datetimeoffset'{start_date_datetime_str}' and Date le datetimeoffset'{end_date_datetime_str}'")
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

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']

        location = Location.search([
            ('code', '=', header['warehouse_code'])
        ])
        if location:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'incoming'),
                ('is_default_api', '=', True)
            ])

        return type if type else None

    def fetch_receipt_data(self, limit=50, offset=0, reference_nbr=False, odata_filter=False):
        self.ensure_one()        
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
                filters.append(self.config_id.odata_filter)
            if filters:
                params['$filter'] = ' and '.join(filters)       

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data PO Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            detail_result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = self._build_header_values(row_number, item)

                # Cek apakah Detail ada dan berbentuk list / dict / array
                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []
                header["warehouse_code"] = self._val(details[0], 'Warehouse')
                type = self._search_picking_type(header)
                header['picking_type_id'] = type.id if type else None
                result.append(dict(header))

                print("="*80)
                print("[DEBUG] MASUK Ke proses deklarasi detail")
                print("="*80)
                
                for detail in details:
                    detail_result.append(
                        self._build_detail_values(header, detail)
                    )                


            # _logger.info("Berhasil ambil %s rows PO Receipt dari Acumatica", len(result))
            self._validate_staging_against_picking(result, detail_result)
            print(f"count result: {len(result)}")
            return len(result)


        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


    def _validate_staging_against_picking(self, header_list, line_list):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: _validate_staging_against_picking")
        print("="*80)
        Picking = self.env['stock.picking']
        lines_to_create = []
        sync_data = fields.Datetime.now()

        for item in header_list:
            
            reference_nbr = item.get('origin')

            exists = Picking.search_read(
                domain=[('origin', '=', reference_nbr)],
                fields=['id', 'origin'],
                limit=1
            )

            # print(f"exsit data: {exists}")
            lines_to_create.append({
                **item,
                'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': f'{reference_nbr}: Sudah ada → akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })
            print(f"line to create: {lines_to_create}")

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)
            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_receipt_lines(to_update)

            receipts = self._create_receipt_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                print(line_update)
                self._update_receipt_lines_product(line_update, to_update)

            if line_create:
                print(line_create)
                self._create_receipt_lines_product(line_create, receipts)

    def _build_header_values(self, row_number, item):

        print("Created header value")
        print(f"Receipt number in header : {self._val(item, 'ReferenceNbr')}")

        return {
            'external_id': item.get('id', '') or '',
            'row_number': row_number,
            'note': item.get('note', {}).get('value', '') or '',
            'branch_warehouse': self._val(item, 'Branch'),
            'actual_qty': self._val(item, 'ControlQty'),
            'scheduled_date': self._val(item, 'Date'),
            'is_hold': self._val(item, 'Hold'),
            'inventory_id': self._val(item, 'InventoryRefNbr'),
            'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
            'location_code': self._val(item, 'Location'),
            'post_period': self._val(item, 'PostPeriod'),
            'origin': self._val(item, 'ReferenceNbr'),
            'status': self._val(item, 'Status'),
            'total_qty': self._val(item, 'TotalQty'),
            'vendor_code': self._val(item, 'Customer'),
            'transfer_type': self._val(item, 'TransType'),
            # 'warehouse_code': self._val(item, 'Warehouse'),
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
            if d.get('origin'):
                receipt_nbrs.append(d['origin'])

        existing_lines = self.env['acumatica.receipt.change.item.line'].search([
            ('origin', 'in', receipt_nbrs)
        ])

        existing_map = {
            line.origin: line
            for line in existing_lines
        }

        unchanged = []
        to_update = []
        to_create = []
        
        for vals in data:
            existing = existing_map.get(vals['origin'])

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

        return self.env['acumatica.receipt.change.item.line'].create(data)
    
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
    
    def _build_detail_values(self, header, detail):
        

        return {
            'header_external_id': header['external_id'],
            'line_external_id': detail.get('id', '') or '',
            'line_note': detail.get('note', {}).get('value', '') or '',
            'description': self._val(detail, 'Description'),
            'inventory_id': self._val(detail, 'InventoryID'),
            'line_nbr': self._val(detail, 'LineNumber'),
            'location_code': self._val(detail, 'Location'),
            'product_uom_qty': self._val(detail, 'Quantity'),
            'uom_code': self._val(detail, 'UOM'),
            'warehouse_dest_code': self._val(detail, 'Warehouse'),
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

        self.env['acumatica.receipt.change.item.product'].create(data)

    def filter_product_line(self, data, update, create):
        print("="*80)
        print("[DEBUG] MASUK KE FUNGSI: filter_product_line")
        print("="*80)
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

        product_line = self.env['acumatica.receipt.change.item.product']

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



        
