from odoo import models, fields
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from datetime import datetime, time, timezone

import logging
_logger = logging.getLogger(__name__)


class ImportReceiptWizard(models.TransientModel):
    _name = 'import.receipt.wizard'
    _description = 'Wizard Import Inventory Receipt dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    receipt_nbr = fields.Char(string='Filter Receipt Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help="Contoh: 2025-01-01T00:00:00+07:00")
    wh33_filter = fields.Boolean(string='Filter WH33', help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    def action_fetch_data(self):
        self.ensure_one()

        import math

        count = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        params = []
        if self.wh33_filter:
            params.append("startswith(Warehouse,'WH33')")
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
            limit=self.batch_size,
            receipt_nbr=self.receipt_nbr,
            odata_filter=params if params else None,
        )
        count += batch_data
        self.total_fetched = count
        if not count:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.receipt.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _val(self, item, key):
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

    def _normalize_rows(self, payload):
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

    def _search_picking_type(self, building_code, document_only=False):
        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False
        if config_picking_type:
            return config_picking_type

        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        Warehouse = self.env['stock.warehouse']
        type = False

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='po_receipt',
            document_only=document_only,
            warehouse_code=building_code,
        )
        if document_only_type:
            return document_only_type

        warehouse = Warehouse.search([
            ('code', '=', building_code)
        ])
        if warehouse:
            type = PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('code', '=', 'incoming'),
                ('is_default_api', '=', True)
            ])

        return type if type else None

    def fetch_receipt_data(self, limit=50, offset=0, receipt_nbr=False, odata_filter=False):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand
            # if self.config_id.odata_select:
            #     params['$select'] = self.config_id.odata_select
            # if receipt_nbr:
            #     filters.append(f"ReceiptNbr eq '{receipt_nbr}'")
            # if odata_filter:
            #     filters.extend(odata_filter)
            # if self.config_id.odata_filter:
            #     filters.append(f"{self.config_id.odata_filter}")
            # if filters:
            #     params['$filter'] = ' and '.join(filters)

            print("Filter API:")
            print(endpoint)
            print(params)
            body = {
                "BuildingID": {
                    "value": "WH33"
                }
            }
            response = session.put(endpoint, params=params, json=body, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data PO Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = response.json()
            result = []
            detail_result = []

            seen_receipts = set()

            data = raw_data.get("PurchaseReceiptGIDetails", [])
            for row_number, item in enumerate(data, start=1):
                receipt_nbr = self._val(item, "ReceiptNbr")

                if receipt_nbr not in seen_receipts:
                    seen_receipts.add(receipt_nbr)
                    building_code = self._val(item, "BuildingID")
                    document_only = self._bool_val(item, 'DocumentOnly')
                    type = self._search_picking_type(building_code, document_only=document_only)
                    result.append({
                        'external_id': item.get('id', '') or '',
                        'row_number': row_number,
                        'note': item.get('NoteHeader', {}).get('value', '') or '',
                        'branch_warehouse': self._val(item, 'Branch'),
                        'building_code': building_code,
                        'actual_qty': self._val(item, 'ControlQty'),
                        'scheduled_date': self._val(item, 'Date'),
                        'is_hold': self._val(item, 'Hold'),
                        'inventory_ref': self._val(item, 'InventoryRefNbr'),
                        'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                        'header_location_code': self._val(item, 'Location'),
                        'note_header_id': self._val(item, 'NoteHeaderID'),
                        'post_period': self._val(item, 'PostPeriod'),
                        'receipt_nbr': self._val(item, 'ReceiptNbr'),
                        'document_only': document_only,
                        'status': self._val(item, 'Status'),
                        'total_qty': self._val(item, 'TotalQty'),
                        'receipt_type': self._val(item, 'Type'),
                        'vendor_code': self._val(item, 'VendorID'),
                        'vendor_name': self._val(item, 'VendorName'),
                        'partner_ref': self._val(item, 'VendorRef'),
                        'warehouse_code': self._val(item, 'LineWarehouseID') or self._val(item, 'Warehouse'),
                        'picking_type_id': type.id if type else None,
                    })

                detail_result.append({
                    'header_external_id': item.get('id', '') or '',
                    # 'line_external_id': item.get('id', '') or '',
                    'receipt_nbr': self._val(item, 'ReceiptNbr'),
                    'line_note': item.get('LineNote', {}).get('value', '') or '',
                    'line_note_id': self._val(item, 'LineNoteID'),
                    'line_branch': self._val(item, 'LineBranch'),
                    'description': self._val(item, 'LineDescription'),
                    'inventory_id': self._val(item, 'LineInventoryID'),
                    'line_nbr': self._val(item, 'LineNbr'),
                    'line_type': self._val(item, 'LineType'),
                    'location_dest_code': self._val(item, 'LineLocation'),
                    'open_qty': self._val(item, 'LineOpenQty'),
                    'order_qty': self._val(item, 'LineOrderedQty'),
                    'po_line_number': self._val(item, 'LinePOLineNbr'),
                    'po_number': self._val(item, 'LinePOOrderNbr'),
                    'po_type': self._val(item, 'LinePOOrderType'),
                    'po_receipt_number': self._val(item, 'LinePOReceiptNbr'),
                    'product_uom_qty': self._val(item, 'LineReceiptQty'),
                    'transfer_shipment_number': self._val(item, 'LineTransferShipmentNbr'),
                    'uom_code': self._val(item, 'LineUOM'),
                    'warehouse_dest_code': self._val(item, 'LineWarehouseID'),
                })


                # Cek apakah Detail ada dan berbentuk list / dict / array
                # details = item.get('Details') or []
                # if isinstance(details, dict):
                #     details = details.get('value', []) or []
                # if not isinstance(details, list):
                #     details = []
                # if not header['warehouse_code'] and details:
                #     header['warehouse_code'] = self._val(details[0], 'WarehouseID')
                #     type = self._search_picking_type(header)
                #     header['picking_type_id'] = type.id if type else None
                # result.append(dict(header, line_nbr='0'))


                # for detail in details:
                #     line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                #     description = self._val(detail, 'Description')
                #     warehouse_dest_code = self._val(detail, 'WarehouseID')

                #     detail_result.append({
                #         'header_external_id': header['external_id'],
                #         'line_external_id': detail.get('id', '') or '',
                #         'line_note': detail.get('note', {}).get('value', '') or '',
                #         'description': description,
                #         'inventory_id': self._val(detail, 'InventoryID'),
                #         'line_nbr': str(line_nbr),
                #         'line_type': self._val(detail, 'LineType'),
                #         'location_dest_code': self._val(detail, 'Location'),
                #         'open_qty': self._val(detail, 'OpenQty'),
                #         'order_qty': self._val(detail, 'OrderedQty'),
                #         'product_uom_qty': self._val(detail, 'ReceiptQty'),
                #         'transaction_description': self._val(detail, 'TransactionDescription'),
                #         'uom_code': self._val(detail, 'UOM'),
                #         'warehouse_dest_code': warehouse_dest_code,
                #     })

            _logger.info("Berhasil ambil %s rows PO Receipt dari Acumatica", len(result))
            self._validate_staging_against_picking(result, detail_result)
            return len(result)
            # return result
            # Picking = self.env['stock.picking']
            # existing_receipts = set()
            # new_receipts = set()
            # lines_to_create = []

            # for item in raw_list:
            #     receipt_nbr = item.get('receipt_nbr')
            #     exists = bool(receipt_nbr and Picking.search_count([('adt_receipt_nbr', '=', receipt_nbr)]))
            #     if exists:
                    
            #         msg = 'Sudah ada → akan diupdate'
            #     else:
            #         new_receipts.add(receipt_nbr)
            #         msg = ''
            #     vals = dict(item)
            #     vals.update({
            #         'config_id': self.config_id.id,
            #         'import_state': 'pending',
            #         'import_message': msg,
            #         'selected': True,
            #         'sync_date': fields.Datetime.now(),
            #     })
            #     lines_to_create.append(vals)

            # self.env['acumatica.receipt.line'].create(lines_to_create)
            # self.write({
            #     'state': 'fetched',
            #     'total_fetched': len(raw_list),
            #     'total_new': len([r for r in new_receipts if r]),
            #     'total_existing': len([r for r in existing_receipts if r]),
            # })

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    def _validate_staging_against_picking(self, header_list, line_list):
        Picking = self.env['stock.picking']
        lines_to_create = []
        sync_data = fields.Datetime.now()
        for item in header_list:
            
            receipt_nbr = item.get('receipt_nbr')
            # exists = receipt_nbr and Picking.search_count([('origin', '=', receipt_nbr)])
            exists = Picking.search_read(
                domain=[('origin', '=', receipt_nbr)],
                fields=['id', 'origin'],
                limit=1
            )
            lines_to_create.append({
                **item,
                'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': f'{receipt_nbr}: Sudah ada → akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)

            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_receipt_lines(to_update)

            receipts = self._create_receipt_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                self._update_receipt_lines_product(line_update, to_update)

            if line_create:
                self._create_receipt_lines_product(line_create, receipts)

            # to_create_filtered = self.filter_by_receipt_lines(to_create, receipts)
            # to_update_filtered = self.filter_by_receipt_lines(to_update, receipts)
            # self._create_receipt_lines_product(to_create_filtered, receipts)

    def _search_receipt_lines(self, data):
        if not data:
            return [], [], []

        receipt_nbrs = [
            d['receipt_nbr']
            for d in data
            if d.get('receipt_nbr')
        ]
        existing_lines = self.env['acumatica.receipt.line'].search([
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


            if existing.acumatica_write_date == vals['acumatica_write_date']:
                unchanged.append(existing)
            else:
                to_update.append({
                    'record': existing,
                    'vals': vals,
                })

        return unchanged, to_update, to_create

    def _update_receipt_lines(self, data):
        if not data:
            return False

        for item in data:
            record = item['record']
            vals = item['vals']

            record.write(vals)

    def _create_receipt_lines(self, data):
        if not data:
            return False

        return self.env['acumatica.receipt.line'].create(data)

    def filter_product_line(self, data, update, create):
        # buat set dari semua receipt_nbr di update
        update_ids = {
            item.get('vals', {}).get('receipt_nbr')
            for item in update
            if item.get('vals', {}).get('receipt_nbr')
        }

        # filter data yang receipt_nbr ada di update_ids
        update_final = [
            line 
            for line in data 
            if line['receipt_nbr'] in update_ids
        ]

        # buat set dari semua receipt_nbr di create
        create_ids = {
            crt['receipt_nbr'] 
            for crt in create
        }

        # filter data yang receipt_nbr ada di create_ids
        create_final = [line for line in data if line['receipt_nbr'] in create_ids]

        return update_final, create_final

    def filter_by_receipt_lines(self, data, receipts):
        """
        Filter data berdasarkan receipt_nbr yang ada di receipts.

        :param data: list of dict (to_create atau to_update)
        :param receipts: recordset receipt
        :return: list of dict yang receipt_nbr-nya ada di receipts
        """
        receipt_ids = {rec['receipt_nbr'] for rec in receipts}

        filtered_data = [
            vals for vals in data
            if vals.get('receipt_nbr') in receipt_ids
        ]

        return filtered_data

    def _create_receipt_lines_product(self, data, receipts):
        receipt_map = {
            rec['receipt_nbr']: rec.id
            for rec in receipts
        }

        for vals in data:
            vals['receipt_line_id'] = receipt_map.get(
                vals['receipt_nbr']
            )

        self.env['acumatica.receipt.product.line'].create(data)

    def _update_receipt_lines_product(self, data, receipts):
        receipt_map = {
            rec['vals']['receipt_nbr']: rec['record']['id']
            for rec in receipts
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.receipt.product.line']

        for vals in data:
            ext_id = vals.get('receipt_nbr')
            vals['receipt_line_id'] = receipt_map.get(ext_id)
            if vals['receipt_line_id']:
                domain = [('receipt_line_id', '=', vals['receipt_line_id'])]
                if vals.get('line_external_id'):
                    domain.append(('line_external_id', '=', vals['line_external_id']))
                else:
                    domain.extend([
                        ('line_nbr', '=', vals.get('line_nbr') or ''),
                        ('inventory_id', '=', vals.get('inventory_id') or ''),
                        ('po_number', '=', vals.get('po_number') or ''),
                    ])
                existing_line = product_line.search(domain, limit=1)
                if existing_line:
                    existing_line.write(vals)
                else:
                    product_line.create(vals)

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data PO Receipt dari Acumatica',
            'res_model': 'acumatica.receipt.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.receipt.line'].search([
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
            'name': 'Hasil Import Inventory Receipt',
            'res_model': 'acumatica.receipt.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
