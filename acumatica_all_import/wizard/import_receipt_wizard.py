from odoo import models, fields
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)


class ImportReceiptWizard(models.TransientModel):
    _name = 'import.receipt.wizard'
    _description = 'Wizard Import Inventory Receipt dari Acumatica'

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    receipt_nbr = fields.Char(string='Filter Receipt Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help="Contoh: 2025-01-01T00:00:00+07:00")
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
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
        # self.env['acumatica.receipt.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        params = []
        if self.wh33_filter:
            params.append("startswith(Warehouse,'WH33')")
        if self.start_date and self.end_date:
            params.append(f"Date ge date'{self.start_date}' and Date le date'{self.end_date}'")
        if self.odata_filter:
            params.append(self.odata_filter)


        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_receipt_data(
                limit=self.batch_size,
                offset=offset,
                receipt_nbr=self.receipt_nbr,
                odata_filter=params if params else None,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)

        # if not raw_list:
        #     raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        # Picking = self.env['stock.picking']
        # existing_receipts = set()
        # new_receipts = set()
        # lines_to_create = []

        # for item in raw_list:
        #     receipt_nbr = item.get('receipt_nbr')
        #     exists = bool(receipt_nbr and Picking.search_count([('adt_receipt_nbr', '=', receipt_nbr)]))
        #     if exists:
        #         existing_receipts.add(receipt_nbr)
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

    def fetch_receipt_data(self, limit=50, offset=0, receipt_nbr=False, odata_filter=False):
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
            if receipt_nbr:
                filters.append(f"ReceiptNbr eq '{receipt_nbr}'")
            if odata_filter:
                filters.append(self.config_id.odata_filter)
                filters.extend(odata_filter)
            else:
                filters.append("(Type eq 'Receipt')")
            if filters:
                params['$filter'] = ' and '.join(filters)       

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data PO Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            detail_result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'branch_warehouse': self._val(item, 'Branch'),
                    'actual_qty': self._val(item, 'ControlQty'),
                    'scheduled_date': self._val(item, 'Date'),
                    'is_hold': self._val(item, 'Hold'),
                    'inventory_ref': self._val(item, 'InventoryRefNbr'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'Location'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'receipt_nbr': self._val(item, 'ReceiptNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'receipt_type': self._val(item, 'Type'),
                    'vendor_code': self._val(item, 'VendorID'),
                    'partner_ref': self._val(item, 'VendorRef'),
                    'warehouse_code': self._val(item, 'Warehouse'),
                }

                # Cek apakah Detail ada dan berbentuk list / dict / array
                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []
                header["warehouse_code"] = self._val(details[0], 'Warehouse')
                result.append(dict(header, line_nbr='0'))


                for detail in details:
                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    description = self._val(detail, 'TransactionDescription') or self._val(detail, 'Description')
                    warehouse_dest_code = self._val(detail, 'Warehouse')

                    detail_result.append({
                        'header_external_id': header['external_id'],
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'description': description,
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'line_type': self._val(detail, 'LineType'),
                        'location_dest_code': self._val(detail, 'Location'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'product_uom_qty': self._val(detail, 'ReceiptQty'),
                        'transaction_description': self._val(detail, 'TransactionDescription'),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_dest_code': warehouse_dest_code,
                    })

            _logger.info("Berhasil ambil %s rows PO Receipt dari Acumatica", len(result))
            self._validate_staging_against_picking(result, detail_result)
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
        existing_receipts = set()
        new_receipts = set()
        lines_to_create = []
        for item in header_list:
            receipt_nbr = item.get('receipt_nbr')
            exists = bool(receipt_nbr and Picking.search_count([('origin', '=', receipt_nbr)]))
            if exists:
                existing_receipts.add(receipt_nbr)
                msg = f'{receipt_nbr}: Sudah ada → akan diupdate'
            else:
                new_receipts.add(receipt_nbr)
                msg = ''
            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': msg,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })
            lines_to_create.append(vals)

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_receipt_lines(lines_to_create)
            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_receipt_lines(to_update)

            receipts = self._create_receipt_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                self._create_receipt_lines_product(line_update, to_update)
            elif line_create:
                self._create_receipt_lines_product(line_create, receipts)

            # to_create_filtered = self.filter_by_receipt_lines(to_create, receipts)
            # to_update_filtered = self.filter_by_receipt_lines(to_update, receipts)
            # self._create_receipt_lines_product(to_create_filtered, receipts)



    def _search_receipt_lines(self, data):
        if not data:
            return False

        unchanged = []
        to_update = []
        to_create = []
        
        for line in data:
            existing_line = self.env['acumatica.receipt.line'].search([
                ('receipt_nbr', '=', line['receipt_nbr'])
            ], limit=1)

            if not existing_line:
                to_create.append(line)
                continue

            if existing_line.acumatica_write_date == self._parse_dt(line['acumatica_write_date']):
                unchanged.append(existing_line)
            else:
                to_update.append(existing_line)

        return unchanged, to_update, to_create

    def _update_receipt_lines(self, data):
        if not data:
            return False

        return self.env['acumatica.receipt.line'].write(data)

    def _create_receipt_lines(self, data):
        if not data:
            return False

        return self.env['acumatica.receipt.line'].create(data)

    def filter_product_line(self, data, update, create):
        # buat set dari semua external_id di update
        update_ids = {upd['external_id'] for upd in update}

        # filter data yang header_external_id ada di update_ids
        update_final = [line for line in data if line['header_external_id'] in update_ids]

        # buat set dari semua external_id di create
        create_ids = {crt['external_id'] for crt in create}

        # filter data yang header_external_id ada di create_ids
        create_final = [line for line in data if line['header_external_id'] in create_ids]

        return update_final, create_final
        
    def filter_by_receipt_lines(self, data, receipts):
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

    def _create_receipt_lines_product(self, data, receipts):
        receipt_map = {
            rec['external_id']: rec.id
            for rec in receipts
        }

        for vals in data:
            vals['receipt_line_id'] = receipt_map.get(
                vals['header_external_id']
            )

        self.env['acumatica.receipt.product.line'].create(data)


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

    def TestMismatchingDataBatch1(self):
        self.ensure_one()
        data = [
            {
                "id": "9fb62285-1203-e611-8805-28924a357ca0",
                "rowNumber": 1,
                "note": {
                    "value": ""
                },
                "Branch": {
                    "value": "MAIN"
                },
                "ControlQty": {
                    "value": 1000.000000
                },
                "Date": {
                    "value": "2011-12-01"
                },
                "Details": [
                    {
                        "id": "10d7d708-6f5e-4138-a354-584f2b60f3ec",
                        "rowNumber": 1,
                        "note": {
                            "value": ""
                        },
                        "Branch": {
                            "value": "MAIN"
                        },
                        "Description": {},
                        "InventoryID": {
                            "value": "PARWH00MBOX-PW-251EA"
                        },
                        "LineNbr": {
                            "value": 1
                        },
                        "LineType": {
                            "value": "Goods for IN"
                        },
                        "Location": {
                            "value": "FG"
                        },
                        "NoteID": {
                            "value": "10d7d708-6f5e-4138-a354-584f2b60f3ec"
                        },
                        "OpenQty": {
                            "value": 0.000000
                        },
                        "OrderedQty": {
                            "value": 1000.000000
                        },
                        "POLineNbr": {
                            "value": 1
                        },
                        "POOrderNbr": {
                            "value": "11-000017"
                        },
                        "POOrderType": {
                            "value": "Normal"
                        },
                        "POReceiptLineNbr": {},
                        "POReceiptNbr": {},
                        "ReceiptQty": {
                            "value": 1000.000000
                        },
                        "TransactionDescription": {
                            "value": "Master Box PW-251EA"
                        },
                        "TransferOrderLineNbr": {},
                        "TransferOrderNbr": {},
                        "TransferOrderType": {},
                        "TransferShipmentNbr": {},
                        "UOM": {
                            "value": "PIECE"
                        },
                        "Warehouse": {
                            "value": "WH01-FG"
                        },
                        "custom": {},
                        "_links": {
                            "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/transactions/10d7d708-6f5e-4138-a354-584f2b60f3ec/{filename}"
                        }
                    },
                ],
                "Hold": {
                    "value": "False"
                },
                "InventoryRefNbr": {
                    "value": "11-000025"
                },
                "Location": {
                    "value": "MAIN"
                },
                "PostPeriod": {
                    "value": "122011"
                },
                "ReceiptNbr": {
                    "value": "R11-000001"
                },
                "Status": {
                    "value": "Released"
                },
                "TotalQty": {
                    "value": 1000.000000
                },
                "Type": {
                    "value": "Receipt"
                },
                "VendorID": {
                    "value": "LM010I"
                },
                "VendorName": {
                    "value": "Megah Lestari Packindo, Pt"
                },
                "VendorRef": {},
                "Warehouse": {},
                "custom": {},
                "_links": {
                    "self": "/acumportal/entity/wms/25.200.002/PurchaseReceipt/9fb62285-1203-e611-8805-28924a357ca0",
                    "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/Document/9fb62285-1203-e611-8805-28924a357ca0/{filename}"
                }
            }
        ]
        
    def TestMismatchingDataBatch2(self):
        self.ensure_one()
        data = [
            {
                "id": "9fb62285-1203-e611-8805-28924a357ca0",
                "rowNumber": 1,
                "note": {
                    "value": ""
                },
                "Branch": {
                    "value": "MAIN"
                },
                "ControlQty": {
                    "value": 500.000000
                },
                "Date": {
                    "value": "2011-12-01"
                },
                "Details": [
                    {
                        "id": "10d7d708-6f5e-4138-a354-584f2b60f3ec",
                        "rowNumber": 1,
                        "note": {
                            "value": ""
                        },
                        "Branch": {
                            "value": "MAIN"
                        },
                        "Description": {},
                        "InventoryID": {
                            "value": "PARWH00MBOX-PW-251EA"
                        },
                        "LineNbr": {
                            "value": 1
                        },
                        "LineType": {
                            "value": "Goods for IN"
                        },
                        "Location": {
                            "value": "FG"
                        },
                        "NoteID": {
                            "value": "10d7d708-6f5e-4138-a354-584f2b60f3ec"
                        },
                        "OpenQty": {
                            "value": 0.000000
                        },
                        "OrderedQty": {
                            "value": 500.000000
                        },
                        "POLineNbr": {
                            "value": 1
                        },
                        "POOrderNbr": {
                            "value": "11-000017"
                        },
                        "POOrderType": {
                            "value": "Normal"
                        },
                        "POReceiptLineNbr": {},
                        "POReceiptNbr": {},
                        "ReceiptQty": {
                            "value": 500.000000
                        },
                        "TransactionDescription": {
                            "value": "Master Box PW-251EA"
                        },
                        "TransferOrderLineNbr": {},
                        "TransferOrderNbr": {},
                        "TransferOrderType": {},
                        "TransferShipmentNbr": {},
                        "UOM": {
                            "value": "PIECE"
                        },
                        "Warehouse": {
                            "value": "WH01-FG"
                        },
                        "custom": {},
                        "_links": {
                            "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/transactions/10d7d708-6f5e-4138-a354-584f2b60f3ec/{filename}"
                        }
                    },
                ],
                "Hold": {
                    "value": "False"
                },
                "InventoryRefNbr": {
                    "value": "11-000025"
                },
                "Location": {
                    "value": "MAIN"
                },
                "PostPeriod": {
                    "value": "122011"
                },
                "ReceiptNbr": {
                    "value": "R11-000001"
                },
                "Status": {
                    "value": "Released"
                },
                "TotalQty": {
                    "value": 500.000000
                },
                "Type": {
                    "value": "Receipt"
                },
                "VendorID": {
                    "value": "LM010I"
                },
                "VendorName": {
                    "value": "Megah Lestari Packindo, Pt"
                },
                "VendorRef": {},
                "Warehouse": {},
                "custom": {},
                "_links": {
                    "self": "/acumportal/entity/wms/25.200.002/PurchaseReceipt/9fb62285-1203-e611-8805-28924a357ca0",
                    "files:put": "/acumportal/entity/wms/25.200.002/files/PX.Objects.PO.POReceiptEntry/Document/9fb62285-1203-e611-8805-28924a357ca0/{filename}"
                }
            }
        ]

    def _test_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = 0
        updated = 0
        error = 0

        # proses per receipt number
        for receipt_nbr in self.mapped('receipt_nbr'):
            receipt_lines = self.filtered(
                lambda l: l.receipt_nbr == receipt_nbr and l.import_state == 'pending'
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]

            try:
                vendor = self._find_vendor(first)
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(
                        f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}'
                    )

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'incoming'),
                ], limit=1) or PickingType.search([
                    ('code', '=', 'incoming')
                ], limit=1)

                if not picking_type:
                    raise UserError('Picking type incoming tidak ditemukan.')

                dest_location = self._find_location_dest(first, warehouse)
                if not dest_location:
                    raise UserError(
                        f'Location tujuan tidak ditemukan untuk code: '
                        f'{first.location_dest_code or first.header_location_code or "-"}'
                    )

                origin = first.receipt_nbr or first.po_number or False

                vals = {
                    'partner_id': vendor.id if vendor else False,
                    'picking_type_id': picking_type.id,
                    'location_id': (
                        picking_type.default_location_src_id.id
                        if picking_type.default_location_src_id
                        else self.env.ref('stock.stock_location_suppliers').id
                    ),
                    'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'origin': origin,
                    'note': first.note or False,

                    # field custom, kalau ada di model
                    'adt_receipt_nbr': first.receipt_nbr or False,
                    'adt_vendor_code': first.vendor_code or False,
                    'adt_partner_ref': first.partner_ref or False,
                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
                    'adt_inventory_ref': first.inventory_ref or False,
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_header_location_code': first.header_location_code or False,
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.receipt_type or False,
                    'adt_warehouse_code': first.warehouse_code or False,
                    'adt_external_id': first.external_id or False,
                }

                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Picking._fields}

                # pakai origin buat dedup
                picking = Picking.search([('origin', '=', origin)], limit=1)

                if picking:
                    if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                        raise UserError(
                            f'Receipt {receipt_nbr} sudah ada di Odoo dengan state '
                            f'{picking.state}, tidak bisa diupdate.'
                        )
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1

                for line in receipt_lines:
                    try:
                        product = self._find_product(line)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.inventory_id or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        line_dest = self._find_location_dest(line, warehouse) or dest_location
                        qty = self._parse_float(line.product_uom_qty)

                        # dedup move
                        move_domain = [('picking_id', '=', picking.id)]
                        if 'adt_line_external_id' in Move._fields and line.line_external_id:
                            move_domain.append(('adt_line_external_id', '=', line.line_external_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('product_uom_qty', '=', qty),
                            ]

                        existing_move = Move.search(move_domain, limit=1)
                        if existing_move:
                            line.write({
                                'import_state': action_state,
                                'import_message': f'Skip duplicate: {picking.name}',
                                'odoo_picking_id': picking.id,
                            })
                            continue

                        move_vals = {
                            'name': line.transaction_description or line.description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': line_dest.id,
                            'description_picking': line.description or False,

                            'adt_line_external_id': line.line_external_id or False,
                            'adt_inventory_id': line.inventory_id or False,
                            'adt_line_nbr': line.line_nbr or False,
                            'adt_line_type': line.line_type or False,
                            'adt_open_qty': self._parse_float(line.open_qty),
                            'adt_order_qty': self._parse_float(line.order_qty),
                            'adt_po_line_number': line.po_line_number or False,
                            'adt_po_number': line.po_number or False,
                            'adt_po_type': line.po_type or False,
                            'adt_po_receipt_line_number': line.po_receipt_line_number or False,
                            'adt_po_receipt_number': line.po_receipt_number or False,
                            'adt_transfer_order_line_number': line.transfer_order_line_number or False,
                            'adt_transfer_order_number': line.transfer_order_number or False,
                            'adt_transfer_order_type': line.transfer_order_type or False,
                            'adt_transfer_shipment_number': line.transfer_shipment_number or False,
                            'adt_uom_code': line.uom_code or False,
                            'adt_warehouse_dest_code': line.warehouse_dest_code or False,
                            'adt_location_dest_code': line.location_dest_code or False,
                            'adt_line_note': line.line_note or False,
                        }

                        # filter field yang ada di stock.move
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}

                        Move.create(move_vals)

                        line.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name}',
                            'odoo_picking_id': picking.id,
                        })

                    except Exception as line_e:
                        line.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_picking_id': picking.id if picking else False,
                        })
                        error += 1

            except Exception as e:
                receipt_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                error += len(receipt_lines)

        msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Receipt',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }
