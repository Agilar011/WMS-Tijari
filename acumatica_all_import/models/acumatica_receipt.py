from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging
import requests

_logger = logging.getLogger(__name__)


class ReceiptImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaReceiptProductLine(models.Model):
    _name = 'acumatica.receipt.product.line'
    _description = 'Data Product PO Receipt dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica')
    receipt_line_id = fields.Many2one('acumatica.receipt.line', string='Receipt', ondelete='cascade')
    receipt_nbr = fields.Char(string='Receipt Number', index=True)
    line_external_id = fields.Char(string='UUID Line Acumatica')
    line_nbr = fields.Char(string='Line Nbr')
    description = fields.Char(string='Description')
    transaction_description = fields.Char(string='Transaction Description')
    inventory_id = fields.Char(string='InventoryID')
    line_type = fields.Char(string='Line Type')
    location_dest_code = fields.Char(string='Location')
    open_qty = fields.Char(string='Open Qty')
    order_qty = fields.Char(string='Ordered Qty')

    po_line_number = fields.Char(string='PO Line Nbr')
    po_number = fields.Char(string='PO Number')
    po_type = fields.Char(string='PO Type')
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr')
    po_receipt_number = fields.Char(string='PO Receipt Nbr')

    transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr')
    transfer_order_number = fields.Char(string='Transfer Order Nbr')
    transfer_order_type = fields.Char(string='Transfer Order Type')
    transfer_shipment_number = fields.Char(string='Transfer Shipment Nbr')

    product_uom_qty = fields.Char(string='Receipt Qty')
    uom_code = fields.Char(string='UOM')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    line_note = fields.Text(string='Line Note')


class AcumaticaReceiptLine(models.Model):
    _name = 'acumatica.receipt.line'
    _description = 'Data PO Receipt dari Acumatica'
    _order = 'receipt_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header Acumatica')
    line_external_id = fields.Char(string='UUID Line Acumatica')
    building_code = fields.Char(string='Building Code')

    product_line_ids = fields.One2many('acumatica.receipt.product.line', 'receipt_line_id', string='Lines')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])
    receipt_nbr = fields.Char(string='Receipt Number', index=True)
    vendor_code = fields.Char(string='VendorID')
    vendor_name = fields.Char(string='Vendor Name')
    partner_ref = fields.Char(string='Vendor Ref')
    scheduled_date = fields.Char(string='Date')
    warehouse_code = fields.Char(string='Warehouse')
    header_location_code = fields.Char(string='Header Location')
    status = fields.Char(string='Status')
    receipt_type = fields.Char(string='Type')
    actual_qty = fields.Char(string='Control Qty')
    total_qty = fields.Char(string='Total Qty')
    is_hold = fields.Char(string='Hold')
    inventory_ref = fields.Char(string='Inventory Ref Nbr')
    post_period = fields.Char(string='Post Period')
    acumatica_write_date = fields.Char(string='Last Modified')
    note = fields.Text(string='Header Note')
    branch_warehouse = fields.Char(string='Branch')

    line_nbr = fields.Char(string='Line Nbr')
    description = fields.Char(string='Description')
    transaction_description = fields.Char(string='Transaction Description')
    inventory_id = fields.Char(string='InventoryID')
    line_type = fields.Char(string='Line Type')
    location_dest_code = fields.Char(string='Location')
    open_qty = fields.Char(string='Open Qty')
    order_qty = fields.Char(string='Ordered Qty')
    po_line_number = fields.Char(string='PO Line Nbr')
    po_number = fields.Char(string='PO Number')
    po_type = fields.Char(string='PO Type')
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr')
    po_receipt_number = fields.Char(string='PO Receipt Nbr')
    product_uom_qty = fields.Char(string='Receipt Qty')
    transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr')
    transfer_order_number = fields.Char(string='Transfer Order Nbr')
    transfer_order_type = fields.Char(string='Transfer Order Type')
    transfer_shipment_number = fields.Char(string='Transfer Shipment Nbr')
    uom_code = fields.Char(string='UOM')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    line_note = fields.Text(string='Line Note')

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('receipt_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.receipt_nbr and Picking.search_count([('origin', '=', rec.receipt_nbr)]))

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    @staticmethod
    def _parse_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _find_vendor(self, line):
        Partner = self.env['res.partner']
        vendor = False
        if line.vendor_code:
            # vendor = Partner.search([('ref', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            vendor = Partner.search([('company_registry', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            if not vendor:
                vendor = Partner.search([('name', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
        return vendor

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
        #     if not product:
        #         product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        # if not product and line.transaction_description:
        #     product = Product.search([('name', '=', line.transaction_description)], limit=1)
        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        warehouse = False
        if line.building_code:
            warehouse = Warehouse.search([
                ('code', '=', line.building_code)
            ])
        return warehouse

    def _find_location_dest(self, code):
        Location = self.env['stock.location.acumatica']
        location = False
        if code:
            location = Location.search([('code', '=', code)], limit=1)
            if location:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
        return location

    def _persist_error_tracking(self, first, error_messages, line_payloads=None, payload=None):
        origin = first.receipt_nbr or False
        if not origin:
            return False

        line_payloads = line_payloads or []
        payload_text = payload if payload is not None else {}

        with self.env.registry.cursor() as cr:
            error_env = api.Environment(cr, self.env.uid, dict(self.env.context))
            Error = error_env['stock.picking.acumatica.error'].sudo()
            ErrorLine = error_env['stock.picking.acumatica.error.line'].sudo()

            error_data = Error.search([('origin', '=', origin)], limit=1)
            error_values = {
                'partner': first.vendor_code or False,
                'operation_type': 'receipt',
                'location': first.warehouse_code or False,
                'location_dest': first.warehouse_dest_code or False,
                'scheduled_date': first._parse_dt(first.scheduled_date),
                'origin': origin,
                'adt_total_qty': first._parse_float(first.total_qty),
                'adt_actual_qty': first._parse_float(first.actual_qty),
                'api_acumatica': 'po_receipt',
                'error_message': '\n'.join(error_messages),
                'payload': str(payload_text)[:1000],
                'state': 'new',
            }

            if error_data:
                error_data.write(error_values)
            else:
                error_data = Error.create(error_values)

            for line_payload in line_payloads:
                line_domain = [
                    ('error_id', '=', error_data.id),
                    ('inventory_id', '=', line_payload.get('inventory_id') or False),
                    ('qty', '=', line_payload.get('qty') or False),
                    ('uom', '=', line_payload.get('uom') or False),
                ]
                error_line = ErrorLine.search(line_domain, limit=1)
                line_values = {
                    'error_id': error_data.id,
                    'inventory_id': line_payload.get('inventory_id') or False,
                    'product_name': line_payload.get('product_name') or False,
                    'qty': line_payload.get('qty') or False,
                    'uom': line_payload.get('uom') or False,
                    'payload': str(line_payload.get('payload') or {})[:1000],
                }
                if error_line:
                    error_line.write(line_values)
                else:
                    ErrorLine.create(line_values)

            cr.commit()
            return error_data

    def _resolve_error_tracking(self, first):
        origin = first.receipt_nbr or False
        if not origin:
            return

        error_data = self.env['stock.picking.acumatica.error'].search([('origin', '=', origin)], limit=1)
        if error_data:
            error_data.write({'state': 'resolved'})

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(
            lambda l: (
                l.import_state in ['pending', 'error'] 
                or (l.import_state in ['imported', 'updated'] and not l.odoo_picking_id)
            )
        )
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _import_single_receipt(self, receipt):
        receipt.ensure_one()

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = receipt.receipt_nbr or False
        header_payload = receipt.read()[0] if receipt.exists() else {}
        error_messages = []
        all_line_payloads = []
        picking = receipt.odoo_picking_id
        action_state = 'pending'

        for receipt_line in receipt.product_line_ids:
            all_line_payloads.append({
                'inventory_id': receipt_line.inventory_id or False,
                'product_name': receipt_line.description or False,
                'qty': receipt._parse_float(receipt_line.product_uom_qty),
                'uom': receipt_line.uom_code or False,
                'payload': receipt_line.read()[0] if receipt_line.exists() else {},
            })

        vendor = receipt._find_vendor(receipt)
        if not vendor:
            error_messages.append(
                f'Vendor with VendorID {receipt.vendor_code} was not found in the WMS | WMS Dependency : MASTER VENDOR.'
            )

        warehouse = receipt._find_warehouse(receipt)
        if not warehouse:
            error_messages.append(
                f'Warehouse with location code {receipt.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        dest_location = receipt._find_location_dest(receipt.warehouse_code)
        if not dest_location:
            error_messages.append(
                f'Location with code {receipt.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        # picking_type = PickingType.search([
        #     ('warehouse_id', '=', warehouse.id if warehouse else False),
        #     ('code', '=', 'incoming'),
        # ], limit=1)
        picking_type = self.picking_type_id
        if not picking_type:
            warehouse_txt = f"Warehouse code {warehouse.code if warehouse else '-'}"
            location_txt = f'Location code {receipt.warehouse_code}'
            error_messages.append(
                f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
            )

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
                line_payloads=all_line_payloads,
            )

        picking_vals = {
            'partner_id': vendor.id if vendor else False,
            'picking_type_id': picking_type.id,
            'adt_dest_location_id': dest_location.id if dest_location else False,
            'scheduled_date': receipt._parse_dt(receipt.scheduled_date),
            'origin': origin,
            'note': receipt.note or False,
            'adt_receipt_nbr': receipt.receipt_nbr or False,
            'adt_vendor_code': receipt.vendor_code or False,
            'adt_partner_ref': receipt.partner_ref or False,
            'adt_branch_warehouse': receipt.branch_warehouse or False,
            'adt_actual_qty': receipt._parse_float(receipt.actual_qty),
            'adt_is_hold': str(receipt.is_hold or '').lower() in ('true', '1', 'yes'),
            'adt_inventory_ref': receipt.inventory_ref or False,
            'adt_acumatica_write_date': receipt._parse_dt(receipt.acumatica_write_date),
            'adt_header_location_code': receipt.header_location_code or False,
            'adt_post_period': receipt.post_period or False,
            'adt_status': receipt.status or False,
            'adt_total_qty': receipt._parse_float(receipt.total_qty),
            'adt_type': receipt.receipt_type or False,
            'adt_warehouse_code': receipt.warehouse_code or False,
            'adt_external_id': receipt.external_id or False,
        }
        picking_vals = {key: value for key, value in picking_vals.items() if key in Picking._fields}

        if picking:
            if picking.state != 'draft':
                raise ReceiptImportError(
                    f'Receipt {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.',
                    payload={'header': header_payload, 'picking_vals': picking_vals},
                    line_payloads=all_line_payloads
                )
            picking.write(picking_vals)
            action_state = 'updated'
        else:
            picking = Picking.create(picking_vals)
            action_state = 'imported'

        for receipt_line in receipt.product_line_ids:
            move_vals = {}
            try:
                product = receipt._find_product(receipt_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    # all_line_payloads.append({
                    #     'inventory_id': receipt_line.inventory_id or False,
                    #     'product_name': receipt_line.description or False,
                    #     'qty': receipt._parse_float(receipt_line.product_uom_qty),
                    #     'uom': receipt_line.uom_code or False,
                    #     'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    # })
                    continue

                uom = receipt._find_uom(receipt_line, product)
                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    # all_line_payloads.append({
                    #     'inventory_id': receipt_line.inventory_id or False,
                    #     'product_name': receipt_line.description or False,
                    #     'qty': receipt._parse_float(receipt_line.product_uom_qty),
                    #     'uom': receipt_line.uom_code or False,
                    #     'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    # })
                    continue

                dest_move_location = receipt._find_location_dest(receipt_line.warehouse_dest_code)
                if not dest_move_location:
                    error_messages.append(
                        f'Location with code {receipt_line.warehouse_dest_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
                    )

                adt_dest_location = dest_move_location.id if dest_move_location else picking.adt_dest_location_id.id or False

                qty = receipt._parse_float(receipt_line.product_uom_qty)
                existing = picking.move_ids.filtered(
                    lambda move: (
                        move.picking_id.id == picking.id
                        and move.adt_dest_location_id.id == adt_dest_location
                        and move.product_id.id == product.id
                        and move.product_uom_qty == qty
                    )
                )
                if existing:
                    continue

                move_vals = {
                    'name': receipt_line.description or product.display_name,
                    'picking_id': picking.id if picking else False,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id if uom else product.uom_id.id,
                    'location_id': picking.location_id.id if picking else False,
                    'location_dest_id': picking.location_dest_id.id if picking else False,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'description_picking': receipt_line.description or False,
                    'adt_dest_location_id': adt_dest_location,

                    'adt_line_external_id': receipt_line.line_external_id or False,
                    'adt_inventory_id': receipt_line.inventory_id or False,
                    'adt_line_nbr': receipt_line.line_nbr or False,
                    'adt_line_type': receipt_line.line_type or False,
                    'adt_open_qty': receipt._parse_float(receipt_line.open_qty),
                    'adt_order_qty': receipt._parse_float(receipt_line.order_qty),
                    'adt_po_line_number': receipt_line.po_line_number or False,
                    'adt_po_number': receipt_line.po_number or False,
                    'adt_po_type': receipt_line.po_type or False,
                    'adt_po_receipt_line_number': receipt_line.po_receipt_line_number or False,
                    'adt_po_receipt_number': receipt_line.po_receipt_number or False,
                    'adt_transfer_order_line_number': receipt_line.transfer_order_line_number or False,
                    'adt_transfer_order_number': receipt_line.transfer_order_number or False,
                    'adt_transfer_order_type': receipt_line.transfer_order_type or False,
                    'adt_transfer_shipment_number': receipt_line.transfer_shipment_number or False,
                    'adt_uom_code': receipt_line.uom_code or False,
                    'adt_warehouse_dest_code': receipt_line.warehouse_dest_code or False,
                    'adt_location_dest_code': receipt_line.location_dest_code or False,
                    'product_note': receipt_line.line_note or False,
                }
                move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                Move.create(move_vals)

            except ReceiptImportError:
                raise

            except Exception as line_error:
                _logger.exception("Error import line %s", receipt.id)
                error_messages.append(str(line_error))
                all_line_payloads.append({
                    'inventory_id': receipt_line.inventory_id or False,
                    'product_name': receipt_line.description or False,
                    'qty': receipt._parse_float(receipt_line.product_uom_qty),
                    'uom': receipt_line.uom_code or False,
                    'payload': move_vals if move_vals else (receipt_line.read()[0] if receipt_line.exists() else {}),
                })

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={
                    'header': header_payload,
                    'picking_vals': picking_vals,
                    'picking_id': picking.id if picking else False,
                },
                line_payloads=all_line_payloads,
            )

        receipt.write({
            'import_state': action_state,
            'import_message': f'{action_state.title()}: {picking.name if picking else False}',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._resolve_error_tracking(receipt)
        # picking.action_confirm()
        return action_state

    def _do_import(self):
        imported = 0
        updated = 0
        error = 0

        grouped_receipts = []
        seen_receipt_numbers = set()
        for receipt in self.sorted(lambda record: (record.receipt_nbr or '', record.id)):
            receipt_key = receipt.receipt_nbr or receipt.id
            if receipt_key in seen_receipt_numbers:
                continue
            seen_receipt_numbers.add(receipt_key)
            grouped_receipts.append(receipt)

        for receipt in grouped_receipts:
            try:
                with self.env.cr.savepoint():
                    action_state = self._import_single_receipt(receipt)
                if action_state == 'imported':
                    imported += 1
                elif action_state == 'updated':
                    updated += 1
            except Exception as exc:
                _logger.exception("Error import receipt %s", receipt.receipt_nbr or receipt.id)
                if isinstance(exc, ReceiptImportError):
                    error_payload = exc.payload
                    all_line_payloads = exc.line_payloads
                    error_message = str(exc)
                else:
                    error_payload = {'header': receipt.read()[0] if receipt.exists() else {}}
                    all_line_payloads = []
                    error_message = str(exc)

                try:
                    self._persist_error_tracking(
                        receipt,
                        [error_message],
                        line_payloads=all_line_payloads,
                        payload=error_payload,
                    )
                except Exception:
                    _logger.exception(
                        "Failed to persist error tracking for receipt %s",
                        receipt.receipt_nbr or receipt.id,
                    )

                receipt.write({
                    'import_state': 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        # msg = f'Import done: {imported} receipt created, {updated} receipt updated, {error} receipt error.'
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Inventory Receipt',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'warning',
        #         'sticky': True,
        #     }
        # }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada receipt di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }

