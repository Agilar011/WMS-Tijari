from odoo import models, fields
from odoo.exceptions import UserError


class ImportReceiptWizard(models.TransientModel):
    _name = 'import.receipt.wizard'
    _description = 'Wizard Import Inventory Receipt dari Acumatica'

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
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

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()
        self.env['acumatica.receipt.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = i * self.batch_size
            batch_data = self.config_id.fetch_receipt_data(
                limit=self.batch_size,
                offset=offset,
                receipt_nbr=self.receipt_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        existing_receipts = set()
        new_receipts = set()
        lines_to_create = []

        for item in raw_list:
            receipt_nbr = item.get('receipt_nbr')
            exists = bool(receipt_nbr and Picking.search_count([('adt_receipt_nbr', '=', receipt_nbr)]))
            if exists:
                existing_receipts.add(receipt_nbr)
                msg = 'Sudah ada → akan diupdate'
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

        self.env['acumatica.receipt.line'].create(lines_to_create)
        self.write({
            'state': 'fetched',
            'total_fetched': len(raw_list),
            'total_new': len([r for r in new_receipts if r]),
            'total_existing': len([r for r in existing_receipts if r]),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.receipt.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Inventory Receipt dari Acumatica',
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
