
from dateutil import parser as dateutil_parser
from datetime import datetime, time, timezone

from odoo import fields, models
from odoo.exceptions import UserError


class ImportInventoryIssueWizard(models.TransientModel):
    _name = 'import.inventory.issue.wizard'
    _description = 'Wizard Import Inventory Issue dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')
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
        params = []

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
        if self.odata_filter:
            params.append(self.odata_filter)

        batch_data = self.fetch_receipt_data(
            reference_nbr=self.reference_nbr,
            odata_filter=params if params else None,
        )
        self.total_fetched = batch_data
        if not batch_data:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.inventory.issue.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------

    def _coalesce_val(self, item, *keys):
        for key in keys:
            value = self._val(item, key)
            if value not in (False, None, ''):
                return value
        return ''

    def _extract_details(self, item, detail_key):
        details = item.get(detail_key) or item.get('Details') or []
        if isinstance(details, dict):
            details = details.get('value', []) or []
        return details if isinstance(details, list) else []

    def fetch_receipt_data(self, limit=50, offset=0, reference_nbr=False, odata_filter=False):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {}
            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand

            response = session.put(endpoint, params=params, json={"TransType": {"value": ""}}, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Inventory Issue (HTTP {response.status_code}): {response.text}')

            raw_data = response.json()
            result = []
            detail_result = []
            headers_seen = set()

            data = raw_data.get("InventoryIssueGIDetails", [])
            for row_number, item in enumerate(data, start=1):
                ref = self._val(item, 'ReferenceNbr')
                if reference_nbr and ref != reference_nbr:
                    continue

                details = self._extract_details(item, self.config_id.odata_expand or 'InventoryIssueGIDetails')
                if not details:
                    details = [item]

                warehouse_code = self._coalesce_val(item, 'Warehouse', 'LineWarehouseID')
                header_id = ref or item.get('id', '')

                if header_id not in headers_seen:
                    result.append(self._build_inventory_issue_header(row_number, item, header_id, warehouse_code))
                    headers_seen.add(header_id)

                for detail in details:
                    detail_result.append(self._build_inventory_issue_detail(header_id, detail, warehouse_code))

            self.config_id.last_sync = fields.Datetime.now()
            self._validate_staging_against_picking(result, detail_result)
            return len(result)

        finally:
            self.config_id._do_logout(session)


    def _validate_staging_against_picking(self, header_list, line_list):
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
                'odoo_picking_id': exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': f'{reference_nbr}: Sudah ada -> akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })

        if lines_to_create:
            unchanged, to_update, to_create = self._search_inventory_issue_lines(lines_to_create)
            self._update_inventory_issue_lines(to_update)

            headers = self._create_inventory_issue_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                self._create_inventory_issue_lines_product(line_update, to_update)
            if line_create:
                self._create_inventory_issue_lines_product(line_create, headers)

    def _search_inventory_issue_lines(self, data):
        if not data:
            return [], [], []

        reference_nbrs = [
            item['reference_nbr']
            for item in data
            if item.get('reference_nbr')
        ]
        existing_lines = self.env['acumatica.inventory.issue.line'].search([
            ('reference_nbr', 'in', reference_nbrs)
        ])

        existing_map = {
            line.reference_nbr: line
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
            if existing.acumatica_write_date == vals.get('acumatica_write_date'):
                unchanged.append(existing)
            else:
                to_update.append({
                    'record': existing,
                    'vals': vals,
                })

        return unchanged, to_update, to_create

    def _update_inventory_issue_lines(self, data):
        if not data:
            return False
        for item in data:
            record = item['record']
            record.product_line_ids.unlink()
            record.write(item['vals'])

    def _create_inventory_issue_lines(self, data):
        if not data:
            return self.env['acumatica.inventory.issue.line']
        return self.env['acumatica.inventory.issue.line'].create(data)

    def _create_inventory_issue_lines_product(self, data, headers):
        header_map = {}
        for header in headers:
            if isinstance(header, dict):
                record = header.get('record')
                vals = header.get('vals') or {}
                if record:
                    header_map[vals.get('external_id')] = record.id
            else:
                header_map[header.external_id] = header.id

        product_vals = []
        for vals in data:
            line_vals = dict(vals)
            line_vals['receipt_line_id'] = header_map.get(line_vals.get('header_external_id'))
            if line_vals['receipt_line_id']:
                product_vals.append(line_vals)
        if product_vals:
            self.env['acumatica.inventory.issue.product'].create(product_vals)

    # ---------------------------------------------------------
    # Filter
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    def _build_inventory_issue_header(self, row_number, item, header_id, warehouse_code):
        type, fallback_warehouse_code = self._search_picking_type(item, warehouse_code=warehouse_code)
        warehouse_code = warehouse_code or fallback_warehouse_code
        if type:
            type = type.id

        if not type:
            type = None
            print("="*80)
            print('Picking Type ID tidak ditemukan untuk warehouse code:', self._val(item, 'WarehouseID'))

        return {
            'external_id': header_id or item.get('id', '') or '',
            'row_number': row_number,
            'note': self._val(item, 'NoteHeader'),
            'actual_qty': self._val(item, 'ControlQty'),
            'total_qty': str(self._val(item, 'TotalQty')),
            'scheduled_date': self._val(item, 'Date'),
            'description': self._val(item, 'Description'),
            'post_period': str(self._val(item, 'PostPeriod')),
            'reference_nbr': self._val(item, 'ReferenceNbr'),
            'status': self._val(item, 'Status'),
            'trans_type': self._val(item, 'TransType'),
            'warehouse_code': warehouse_code,
            'picking_type_id': type,
            'external_ref': self._val(item, 'ExternalRef'),
            'document_only': self._bool_val(item, 'DocumentOnly'),
            'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
            'actual_amount': self._val(item, 'ControlAmount'),
            'total_amount': self._val(item, 'TotalAmount'),
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
    
    def _build_inventory_issue_detail(self, header_id, detail, warehouse_code=None):
        return {
            'header_external_id': header_id,
            'line_external_id': detail.get('id', '') or '',
            'line_nbr': str(self._val(detail, 'LineNbr')),
            'line_note': self._val(detail, 'LineNote'),
            'branch_warehouse': self._val(detail, 'LineBranch'),
            'line_description': self._val(detail, 'LineDescription'),
            'inventory_id': self._val(detail, 'LineInventoryID'),
            'location_code': self._val(detail, 'LineLocation'),
            'product_uom_qty': str(self._val(detail, 'LineQuantity')),
            'line_trans_type': self._val(detail, 'LineTranType'),
            'uom_code': self._val(detail, 'LineUOM'),
            'warehouse_code': self._val(detail, 'LineWarehouseID') or warehouse_code,
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

    def _search_picking_type(self, header, warehouse_code=None):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        warehouse_code = warehouse_code or self._coalesce_val(header, 'Warehouse', 'WarehouseID', 'LineWarehouseID')
        type = False

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='inventory_issue',
            document_only=self._bool_val(header, 'DocumentOnly'),
            warehouse_code=warehouse_code,
        )
        if document_only_type:
            return document_only_type, warehouse_code

        print(f"Warehouse Code: {warehouse_code}")

        location = Location.search([
            ('code', '=', warehouse_code)
        ], limit=1)

        if location and location.odoo_building_id:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id),
                ('code', '=', 'outgoing'),
                ('is_default_api', '=', True)
            ], limit=1)

        return type, warehouse_code
