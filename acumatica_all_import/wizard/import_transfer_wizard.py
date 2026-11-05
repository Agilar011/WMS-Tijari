from odoo import fields, models
from odoo.exceptions import UserError
from datetime import datetime

import logging
from ..utils import acumatica_data as _data

_logger = logging.getLogger(__name__)



class ImportTransferWizard(models.TransientModel):
    _name = 'import.transfer.wizard'
    _description = 'Wizard Import Internal Transfer dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    receipt_nbr = fields.Char(string='Filter Receipt Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data shipment yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Transfer Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()

        start = datetime.now()

        _logger.info(
            "========== INTERNAL TRANSFER FETCH START | "
            "fetch_limit=%s | batch_size=%s | skip=%s ==========",
            self.fetch_limit,
            self.batch_size,
            self.fetch_skip,
        )

        total = self.fetch_transfer_data()

        elapsed = (datetime.now() - start).total_seconds()

        self.total_fetched = total

        _logger.info(
            "========== INTERNAL TRANSFER FETCH END | "
            "total=%s | elapsed=%.2fs ==========",
            total,
            elapsed,
        )

        if not total:
            raise UserError(
                'Tidak ada data yang diterima dari API Acumatica.'
            )

    def _search_picking_type(
        self,
        building_code,
        document_only=False,
        picking_type_cache=None,
    ):
        if picking_type_cache is None:
            picking_type_cache = {}

        cache_key = (
            building_code,
            document_only,
        )

        if cache_key in picking_type_cache:
            return picking_type_cache[cache_key]

        config_picking_type = (
            self.config_id._get_config_picking_type()
            if self.config_id
            else False
        )

        if config_picking_type:
            picking_type_cache[cache_key] = config_picking_type
            return config_picking_type

        PickingType = self.env['stock.picking.type']
        Warehouse = self.env['stock.warehouse']

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='so_transfer',
            document_only=document_only,
            warehouse_code=building_code,
        )

        if document_only_type:
            picking_type_cache[cache_key] = document_only_type
            return document_only_type

        warehouse = Warehouse.search(
            [('code', '=', building_code)],
            limit=1,
        )

        picking_type = False

        if warehouse:
            picking_type = PickingType.search(
                [
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'incoming'),
                    ('is_default_api', '=', True),
                ],
                limit=1,
            )

        picking_type_cache[cache_key] = picking_type or False

        return picking_type or False




    


    def fetch_transfer_data(self):
        self.ensure_one()

        total_start = datetime.now()

        _logger.info(
            "========== INTERNAL TRANSFER FETCH START =========="
        )

        # Cache hanya hidup selama satu proses fetch
        shipment_warehouse_cache = {}
        picking_type_cache = {}

        # ---------------------------------------------------------
        # LOGIN
        # ---------------------------------------------------------

        session = self.config_id._do_login()
        try:
            endpoint = (
                f"{self.config_id.api_url}/"
                f"{self.config_id.endpoint_name}"
            )

            params = {}

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand

            body = {
                "BuildingID": {
                    "value": "WH33"
                }
            }

            # ---------------------------------------------------------
            # ACUMATICA API
            # ---------------------------------------------------------
            response = session.put(
                endpoint,
                params=params,
                json=body,
                timeout=300,
            )

            if response.status_code != 200:
                self.env["acumatica.webhook.error.service"].send_error(
                    webhook_type="fetch",
                    webhook_name="Transfer",
                    error=f"Gagal fetch Transfer dari Acumatica (HTTP {response.status_code}).",
                    error_type="http",
                )
                raise UserError(
                    f'Gagal ambil data Transfer Receipt '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

            # ---------------------------------------------------------
            # JSON
            # ---------------------------------------------------------

            raw_payload = response.json()

            flat_data = (
                raw_payload.get('SOTRGIDetails')
                if isinstance(raw_payload, dict)
                else None
            )

            raw_data = (
                flat_data
                or _data.acumatica_rows(raw_payload)
            )

            result = []
            detail_result = []
            seen_receipts = set()

            # ---------------------------------------------------------
            # BUILD HEADER + DETAIL
            # ---------------------------------------------------------

            build_start = datetime.now()

            for row_number, item in enumerate(
                raw_data,
                start=1,
            ):
                receipt_nbr = _data.acumatica_value(
                    item,
                    "ReceiptNbr",
                )

                transfer_shipment_nbr = _data.acumatica_value(
                    item,
                    'LineTransferShipmentNbr',
                )

                shipment_warehouse = {}

                if transfer_shipment_nbr:
                    shipment_warehouse = (
                        shipment_warehouse_cache.get(
                            transfer_shipment_nbr
                        )
                    )

                    if shipment_warehouse is None:
                        shipment_warehouse = (
                            self.search_dest_warehouse(
                                transfer_shipment_nbr,
                                session,
                            )
                            or {}
                        )

                        shipment_warehouse_cache[
                            transfer_shipment_nbr
                        ] = shipment_warehouse

                # -----------------------------------------------------
                # HEADER
                # -----------------------------------------------------

                if receipt_nbr not in seen_receipts:
                    seen_receipts.add(receipt_nbr)

                    building_code = _data.acumatica_value(
                        item,
                        "BuildingID",
                    )

                    document_only = _data.acumatica_bool(
                        item,
                        'DocumentOnly',
                    )

                    picking_type = self._search_picking_type(
                        building_code,
                        document_only=document_only,
                        picking_type_cache=picking_type_cache,
                    )

                    result.append({
                        'external_id': item.get('id', '') or '',
                        'row_number': row_number,
                        'note': (
                            item.get(
                                'NoteHeader',
                                {},
                            ).get('value', '')
                            or item.get(
                                'HeaderNote',
                                {},
                            ).get('value', '')
                            or ''
                        ),
                        'note_header_id': _data.acumatica_value(
                            item,
                            'NoteHeaderID',
                        ),
                        'branch_warehouse': _data.acumatica_value(
                            item,
                            'Branch',
                        ),
                        'building_code': building_code,
                        'actual_qty': _data.acumatica_value(
                            item,
                            'ControlQty',
                        ),
                        'scheduled_date': _data.acumatica_value(
                            item,
                            'Date',
                        ),
                        'is_hold': _data.acumatica_value(
                            item,
                            'Hold',
                        ),
                        'inventory_ref': _data.acumatica_value(
                            item,
                            'InventoryRefNbr',
                        ),
                        'acumatica_write_date': _data.acumatica_value(
                            item,
                            'LastModifiedDateTime',
                        ),
                        'header_location_code': _data.acumatica_value(
                            item,
                            'Location',
                        ),
                        'post_period': _data.acumatica_value(
                            item,
                            'PostPeriod',
                        ),
                        'receipt_nbr': receipt_nbr,
                        'document_only': document_only,
                        'stock_lebih': (
                            _data.acumatica_bool(item, 'WMSRelated')
                            or _data.acumatica_bool(item, 'wms_related')
                            or _data.acumatica_bool(item, 'StockLebih')
                            or _data.acumatica_bool(item, 'stock_lebih')
                        ),
                        'status': _data.acumatica_value(
                            item,
                            'Status',
                        ),
                        'total_qty': _data.acumatica_value(
                            item,
                            'TotalQty',
                        ),
                        'receipt_type': _data.acumatica_value(
                            item,
                            'Type',
                        ),
                        'vendor_code': _data.acumatica_value(
                            item,
                            'VendorID',
                        ),
                        'vendor_name': _data.acumatica_value(
                            item,
                            'VendorName',
                        ),
                        'partner_ref': (
                            _data.acumatica_value(
                                item,
                                'VendorRef',
                            )
                            or _data.acumatica_value(
                                item,
                                'VendorName',
                            )
                        ),
                        'warehouse_code': (
                            shipment_warehouse.get(
                                'source_warehouse'
                            )
                            or _data.acumatica_value(
                                item,
                                'FromWarehouseID',
                            )
                            or _data.acumatica_value(
                                item,
                                'WarehouseID',
                            )
                            or _data.acumatica_value(
                                item,
                                'LineFromWarehouseID',
                            )
                        ),
                        'warehouse_dest_code': (
                            shipment_warehouse.get(
                                'dest_warehouse'
                            )
                            or _data.acumatica_value(
                                item,
                                'ToWarehouseID',
                            )
                            or _data.acumatica_value(
                                item,
                                'Warehouse'
                            )
                            or _data.acumatica_value(
                                item,
                                'LineWarehouseID'
                            )
                        ),
                        'transfer_shipment_number': (
                            transfer_shipment_nbr
                        ),
                        'picking_type_id': (
                            picking_type.id
                            if picking_type
                            else None
                        ),
                    })

                # -----------------------------------------------------
                # DETAIL
                # -----------------------------------------------------

                detail_result.append({
                    'header_external_id': (
                        item.get('id', '') or ''
                    ),
                    'line_external_id': (
                        item.get('id', '') or ''
                    ),
                    'receipt_nbr': receipt_nbr,
                    'line_note': (
                        item.get(
                            'LineNote',
                            {},
                        ).get('value', '')
                        or ''
                    ),
                    'line_note_id': _data.acumatica_value(
                        item,
                        'LineNoteID',
                    ),
                    'line_branch': _data.acumatica_value(
                        item,
                        'LineBranch',
                    ),
                    'description': _data.acumatica_value(
                        item,
                        'LineDescription',
                    ),
                    'inventory_id': _data.acumatica_value(
                        item,
                        'LineInventoryID',
                    ),
                    'line_nbr': _data.acumatica_value(
                        item,
                        'LineNbr',
                    ),
                    'line_type': _data.acumatica_value(
                        item,
                        'LineType',
                    ),
                    'location_dest_code': _data.acumatica_value(
                        item,
                        'LineLocation',
                    ),
                    'open_qty': _data.acumatica_value(
                        item,
                        'LineOpenQty',
                    ),
                    'order_qty': _data.acumatica_value(
                        item,
                        'LineOrderedQty',
                    ),
                    'po_line_number': _data.acumatica_value(
                        item,
                        'LinePOLineNbr',
                    ),
                    'po_number': _data.acumatica_value(
                        item,
                        'LinePOOrderNbr',
                    ),
                    'po_type': _data.acumatica_value(
                        item,
                        'LinePOOrderType',
                    ),
                    'po_receipt_number': _data.acumatica_value(
                        item,
                        'LinePOReceiptNbr',
                    ),
                    'product_uom_qty': _data.acumatica_value(
                        item,
                        'LineReceiptQty',
                    ),
                    'transfer_shipment_number': (
                        transfer_shipment_nbr
                    ),
                    'uom_code': _data.acumatica_value(
                        item,
                        'LineUOM',
                    ),
                    'warehouse_dest_code': (
                        _data.acumatica_value(
                            item,
                            'ToWarehouseID',
                        )
                        or _data.acumatica_value(
                            item,
                            'LineWarehouseID',
                        )
                    ),
                })

            build_elapsed = (
                datetime.now() - build_start
            ).total_seconds()

            _logger.info(
                "INTERNAL TRANSFER BUILD DONE | "
                "headers=%s | details=%s | "
                "unique_shipments=%s | "
                "picking_cache=%s | "
                "elapsed=%.2fs",
                len(result),
                len(detail_result),
                len(shipment_warehouse_cache),
                len(picking_type_cache),
                build_elapsed,
            )

            # ---------------------------------------------------------
            # STAGING
            # ---------------------------------------------------------

            _logger.info(
                "INTERNAL TRANSFER STAGING START | "
                "headers=%s | details=%s",
                len(result),
                len(detail_result),
            )

            staging_start = datetime.now()

            self._validate_staging_against_picking(
                result,
                detail_result,
            )

            staging_elapsed = (
                datetime.now() - staging_start
            ).total_seconds()

            _logger.info(
                "INTERNAL TRANSFER STAGING DONE | "
                "elapsed=%.2fs",
                staging_elapsed,
            )

            self.config_id.last_sync = fields.Datetime.now()

            total_elapsed = (
                datetime.now() - total_start
            ).total_seconds()

            _logger.info(
                "========== INTERNAL TRANSFER FETCH DONE | "
                "headers=%s | details=%s | "
                "total_elapsed=%.2fs ==========",
                len(result),
                len(detail_result),
                total_elapsed,
            )

            return len(result)

        finally:
            self.config_id._do_logout(session)

    def search_dest_warehouse(self, transfer_nbr, session):
        self.ensure_one()

        if not transfer_nbr:
            return None

        start = datetime.now()

        try:
            endpoint = (
                f"{self.config_id.api_url}/Shipment"
            )

            params = {
                '$select': (
                    'ToWarehouseID,'
                    'WarehouseID,'
                    'ShipmentNbr'
                ),
                '$filter': (
                    f"ShipmentNbr eq '{transfer_nbr}'"
                ),
            }
            response = session.get(
                endpoint,
                params=params,
                timeout=300,
            )
            if response.status_code != 200:
                self.env["acumatica.webhook.error.service"].send_error(
                    webhook_type="fetch",
                    webhook_name="Transfer",
                    error=f"Gagal fetch Transfer dari Acumatica (HTTP {response.status_code}).",
                    error_type="http",
                )
                raise UserError(
                    f'Gagal ambil data Destination Warehouse '
                    f'(HTTP {response.status_code}): '
                    f'{response.text}'
                )

            raw_data = _data.acumatica_rows(
                response.json()
            )

            if not raw_data:
                _logger.warning(
                    "INTERNAL TRANSFER SHIPMENT NOT FOUND | "
                    "shipment=%s",
                    transfer_nbr,
                )
                return None

            item = raw_data[0]

            result = {
                'shipment_number': _data.acumatica_value(
                    item,
                    'ShipmentNbr',
                ),
                'dest_warehouse': _data.acumatica_value(
                    item,
                    'ToWarehouseID',
                ),
                'source_warehouse': _data.acumatica_value(
                    item,
                    'WarehouseID',
                ),
            }

            return result

        except Exception as e:
            _logger.error(
                "INTERNAL TRANSFER SHIPMENT LOOKUP ERROR | "
                "shipment=%s | error=%s",
                transfer_nbr,
                str(e),
                exc_info=True,
            )
            return None

    def _validate_staging_against_picking(
        self,
        header_list,
        line_list,
    ):
        Picking = self.env['stock.picking']
        sync_data = fields.Datetime.now()
        Header = self.env['acumatica.transfer.line']
        ProductLine = self.env['acumatica.transfer.product.line']
        receipt_numbers = [item.get('receipt_nbr') for item in header_list if item.get('receipt_nbr')]
        existing_headers = Header.search([
            ('receipt_nbr', 'in', receipt_numbers),
            ('config_id', '=', self.config_id.id),
        ])
        existing_map = {record.receipt_nbr: record for record in existing_headers}

        for item in header_list:
            receipt_nbr = item.get('receipt_nbr')
            picking = Picking.search([('origin', '=', receipt_nbr)], limit=1)
            values = {
                **item,
                'odoo_picking_id': picking.id if picking else False,
                'config_id': self.config_id.id,
                'import_state': 'staged',
                'import_message': (
                    f'{receipt_nbr}: Sudah ada → akan diupdate'
                    if picking
                    else ''
                ),
                'selected': True,
                'sync_date': sync_data,
            }
            receipt = existing_map.get(receipt_nbr)
            if receipt:
                if (
                    not values.get('acumatica_write_date')
                    or receipt.acumatica_write_date == values['acumatica_write_date']
                ):
                    continue
                receipt.write(values)
            else:
                receipt = Header.create(values)

            receipt.product_line_ids.unlink()
            product_values = [
                {**line, 'transfer_line_id': receipt.id}
                for line in line_list
                if line.get('receipt_nbr') == receipt_nbr
            ]
            if product_values:
                ProductLine.create(product_values)

    def _search_receipt_lines(self, data):
        if not data:
            return [], [], []

        receipt_nbrs = [
            d['receipt_nbr']
            for d in data
            if d.get('receipt_nbr')
        ]
        existing_lines = self.env['acumatica.transfer.line'].search([
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

            if (
                not vals.get('acumatica_write_date')
                or existing.acumatica_write_date == vals['acumatica_write_date']
            ):
                unchanged.append(existing)
                continue


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

        return self.env['acumatica.transfer.line'].create(data)

    def filter_product_line(self, data, update, create):
        # buat set dari semua external_id di update
        update_ids = {
            item.get('vals', {}).get('receipt_nbr')
            for item in update
            if item.get('vals', {}).get('receipt_nbr')
        }

        # filter data yang header_external_id ada di update_ids
        update_final = [
            line 
            for line in data 
            if line['receipt_nbr'] in update_ids
        ]

        # buat set dari semua external_id di create
        create_ids = {
            crt['receipt_nbr'] 
            for crt in create
        }

        # filter data yang header_external_id ada di create_ids
        create_final = [line for line in data if line['receipt_nbr'] in create_ids]

        return update_final, create_final
        
    def filter_by_receipt_lines(self, data, receipts):
        """
        Filter data berdasarkan header_external_id yang ada di receipts.
        
        :param data: list of dict (to_create atau to_update)
        :param receipts: recordset receipt
        :return: list of dict yang header_external_id-nya ada di receipts
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
            vals['transfer_line_id'] = receipt_map.get(
                vals['receipt_nbr']
            )

        self.env['acumatica.transfer.product.line'].create(data)

    def _update_receipt_lines_product(self, data, receipts):
        receipt_map = {
            rec['vals']['receipt_nbr']: rec['record']['id']
            for rec in receipts
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.transfer.product.line']

        for vals in data:
            ext_id = vals.get('receipt_nbr')
            vals['transfer_line_id'] = receipt_map.get(ext_id)
            if vals['transfer_line_id']:
                product_line.browse(vals['transfer_line_id']).write(vals)

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Internal Transfer dari Acumatica',
            'res_model': 'acumatica.transfer.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.transfer.line'].search([
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
            'name': 'Hasil Import Internal Transfer',
            'res_model': 'acumatica.transfer.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
