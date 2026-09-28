import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError
import requests

_logger = logging.getLogger(__name__)


class ReceiptImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaTransferProductLine(models.Model):
    _name = 'acumatica.transfer.product.line'
    _description = 'Data Product SOTR dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica')
    transfer_line_id = fields.Many2one('acumatica.transfer.line', string='Transfer', ondelete='cascade')
    receipt_nbr = fields.Char(string='Receipt Number', index=True)
    line_external_id = fields.Char(string='UUID Line')
    line_branch = fields.Char(string='Line Branch')
    
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
    transfer_order_number = fields.Char(string='Transfer Order Number', index=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Number')
    transfer_order_type = fields.Char(string='Transfer Order Type')
    transfer_shipment_number = fields.Char(string='Transfer Shipment Number')
    uom_code = fields.Char(string='UOM')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    line_note = fields.Text(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')


class AcumaticaTransferLine(models.Model):
    _name = 'acumatica.transfer.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Data SOTR dari Acumatica'
    _order = 'transfer_order_number asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header')
    line_external_id = fields.Char(string='UUID Line')

    product_line_ids = fields.One2many('acumatica.transfer.product.line', 'transfer_line_id', string='Lines')
    receipt_nbr = fields.Char(string='Receipt Number', index=True)
    transfer_order_number = fields.Char(string='Transfer Order Number', index=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Number')
    transfer_order_type = fields.Char(string='Transfer Order Type')
    transfer_shipment_number = fields.Char(string='Transfer Shipment Number')

    vendor_code = fields.Char(string='VendorID')
    vendor_name = fields.Char(string='Vendor Name')
    partner_ref = fields.Char(string='Vendor Ref')
    scheduled_date = fields.Char(string='Date')
    building_code = fields.Char(string='Building Code')
    warehouse_code = fields.Char(string='Warehouse')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    header_location_code = fields.Char(string='Header Location')
    location_dest_code = fields.Char(string='Location')
    status = fields.Char(string='Status')
    receipt_type = fields.Char(string='Type')
    actual_qty = fields.Char(string='Control Qty')
    total_qty = fields.Char(string='Qty Total')
    is_hold = fields.Char(string='Hold')
    document_only = fields.Boolean(string='Document Only')
    inventory_ref = fields.Char(string='Inventory Ref Nbr')
    post_period = fields.Char(string='Post Period')
    acumatica_write_date = fields.Char(string='Last Modified')
    note = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')
    branch_warehouse = fields.Char(string='Branch')

    line_nbr = fields.Char(string='Line Nbr')
    line_branch = fields.Char(string='Line Branch')
    description = fields.Char(string='Description')
    transaction_description = fields.Char(string='Transaction Description')
    inventory_id = fields.Char(string='InventoryID')
    line_type = fields.Char(string='Line Type')
    open_qty = fields.Char(string='Open Qty')
    order_qty = fields.Char(string='Ordered Qty')
    po_line_number = fields.Char(string='PO Line Nbr')
    po_number = fields.Char(string='PO Number')
    po_type = fields.Char(string='PO Type')
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr')
    po_receipt_number = fields.Char(string='PO Receipt Nbr')
    product_uom_qty = fields.Char(string='Receipt Qty')
    uom_code = fields.Char(string='UOM')
    line_note = fields.Text(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged')
    import_message = fields.Char(string='Generation Message', tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order di Odoo',
    )
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync')

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')

    @api.depends('receipt_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            origin = rec.receipt_nbr
            rec.exists_in_odoo = bool(
                origin
                and (
                    Picking.search_count([('origin', '=', origin)])
                    or InternalTransferOrder.search_count([('external_ref', '=', origin)])
                )
            )

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

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.transaction_description:
            product = Product.search([('name', '=', line.transaction_description)], limit=1)
        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line.warehouse_code
        if code:
            warehouse = Warehouse.search([('code', '=', code), ('is_active', '=', True)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    

        return warehouse

    def _find_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        location = False
        if line.warehouse_dest_code:
            location = Location.search([('code', '=', line.warehouse_dest_code), ('is_active', '=', True)], limit=1)
            if location:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _handle_acumatica_error(self, first, error_messages=False, line_payloads=None, payload=None):
        return self.env['acumatica.error.transaction']._handle_acumatica_error(
            first,
            error_messages,
            origin=first.receipt_nbr or False,
            payload=payload,
            line_payloads=line_payloads,
        )

    def _import_single_receipt_as_transfer_in(self, receipt):
        receipt.ensure_one()

        TransferService = self.env['acumatica.internal.transfer.service']
        Move = self.env['stock.move']

        origin = receipt.receipt_nbr or False
        header_payload = receipt.read()[0] if receipt.exists() else {}
        error_messages = []
        error_line_payloads = []

        source_code = receipt.warehouse_code
        destination_code = receipt.warehouse_dest_code
        try:
            transfer_info = TransferService.classify_transfer_in_from_virtual(
                source_code,
                destination_code,
                'FromWarehouseID',
                'ToWarehouseID',
            )
        except UserError as error:
            error_messages.append(str(error))
            transfer_info = False

        if transfer_info and transfer_info['status'] == 'skip':
            receipt.write({
                'import_state': 'updated',
                'import_message': 'success',
                'odoo_internal_transfer_order_id': False,
                'odoo_picking_id': False,
            })
            self.env['acumatica.error.transaction']._handle_acumatica_update(receipt, origin=receipt.receipt_nbr or False)
            self._handle_acumatica_error(receipt)
            return 'updated'

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
            )

        source_location = transfer_info['source_location']
        destination_location = transfer_info['destination_location']
        missing_location_messages = []
        if not source_location:
            missing_location_messages.append(
                'FromWarehouseID kosong atau tidak dapat ditentukan untuk Transfer Receipt %s.'
                % (origin or receipt.id)
            )
        if not destination_location:
            missing_location_messages.append(
                'ToWarehouseID mapping tidak ditemukan untuk Transfer Receipt %s: %s.'
                % (origin or receipt.id, destination_code or '-')
            )
        if missing_location_messages:
            raise ReceiptImportError(
                '\n'.join(missing_location_messages),
                payload={'header': header_payload},
            )

        transfer_shipment_numbers = []
        for product_line in receipt.product_line_ids:
            transfer_shipment_number = (
                product_line.transfer_shipment_number or ''
            ).strip()
            if (
                transfer_shipment_number
                and transfer_shipment_number not in transfer_shipment_numbers
            ):
                transfer_shipment_numbers.append(transfer_shipment_number)

        order, action_state = TransferService.prepare_order(
            origin,
            source_location,
            destination_location,
            transfer_info['transaction_type'],
            schedule_date=receipt._parse_dt(receipt.scheduled_date),
            note=receipt.note or False,
            description=receipt.description or False,
            transfer_type='transfer_in',
            external_ref_in=origin,
            external_ref_out=','.join(transfer_shipment_numbers),
            # Keep the internal transfer's API identity explicit so each
            # generated picking can receive the correct SOTR leg type.
            adt_transaction_type='SOTR',
            document_only=receipt.document_only,
        )
        order.write({'validation_policy': 'validate_all'})

        for receipt_line in receipt.product_line_ids:
            move_vals = {}
            try:
                product = receipt._find_product(receipt_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receipt_line.inventory_id or False,
                        'product_name': receipt_line.description or False,
                        'qty': receipt._parse_float(receipt_line.product_uom_qty),
                        'uom': receipt_line.uom_code or False,
                        'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    })
                    continue

                uom = receipt._find_uom(receipt_line, product)
                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receipt_line.inventory_id or False,
                        'product_name': receipt_line.description or False,
                        'qty': receipt._parse_float(receipt_line.product_uom_qty),
                        'uom': receipt_line.uom_code or False,
                        'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    })
                    continue

                qty = receipt._parse_float(receipt_line.product_uom_qty)
                move_vals = {
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
                    'adt_quantity': qty,
                    'adt_type': receipt.receipt_type or 'Transfer Receipt',
                    'product_note': receipt_line.line_note or False,
                }
                move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                TransferService.create_order_move(
                    order,
                    product,
                    qty,
                    uom=uom,
                    name=receipt_line.transaction_description or receipt_line.description or product.display_name,
                    description=receipt_line.description or False,
                    extra_vals=move_vals,
                )

            except ReceiptImportError:
                raise
            except Exception as line_error:
                _logger.exception("Error import transfer receipt line %s", receipt_line.id)
                error_messages.append(str(line_error))
                error_line_payloads.append({
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
                    'order_id': order.id if order else False,
                },
                line_payloads=error_line_payloads,
            )

        TransferService.set_order_ready(order)
        receipt.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_internal_transfer_order_id': order.id if order else False,
            'odoo_picking_id': False,
        })
        self._handle_acumatica_error(receipt)
        return action_state

    def _import_single_receipt(self, receipt):
        receipt.ensure_one()
        return receipt._import_single_receipt_as_transfer_in(receipt)

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = receipt.receipt_nbr or False
        header_payload = receipt.read()[0] if receipt.exists() else {}
        error_messages = []
        error_line_payloads = []
        picking = receipt.odoo_picking_id
        action_state = 'staged'

        # vendor = receipt._find_vendor(receipt)
        # if not vendor:
        #     error_messages.append(
        #         f'Vendor with VendorID {receipt.vendor_code} was not found in the WMS | WMS Dependency : MASTER VENDOR.'
        #     )

        warehouse = receipt._find_warehouse(receipt)
        if not warehouse:
            error_messages.append(
                f'Warehouse with location code {receipt.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        dest_location = receipt._find_location_dest(receipt)
        if not dest_location:
            error_messages.append(
                f'Location with code {receipt.warehouse_dest_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        # picking_type = PickingType.search([
        #     ('warehouse_id', '=', warehouse.id if warehouse else False),
        #     ('operation_category', '=', 'internal'),
        #     ('code', '=', 'internal'),
        # ], limit=1)
        # if not picking_type:
        #     warehouse_txt = f"Warehouse code {warehouse.code if warehouse else '-'}"
        #     location_txt = f'Location code {receipt.warehouse_code}'
        #     error_messages.append(
        #         f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
        #     )

        print(receipt.picking_type_id)
        picking_type_id = False
        if receipt.picking_type_id:
            picking_type_id = receipt.picking_type_id.id

        if not picking_type_id:
            raise UserError('Picking_type not found')

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
            )

        picking_vals = {
            # 'partner_id': vendor.id if vendor else False,
            'picking_type_id': picking_type_id,
            'location_dest_id': dest_location.id if dest_location else False,
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
            )
            picking.write(picking_vals)
            action_state = 'updated'
            self.env['acumatica.error.transaction']._handle_acumatica_update(receipt, origin=origin)
        else:
            picking = Picking.create(picking_vals)
            action_state = 'created'

        if action_state == 'updated':
            picking.move_ids.unlink()

        for receipt_line in receipt.product_line_ids:
            move_vals = {}
            try:
                product = receipt._find_product(receipt_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receipt_line.inventory_id or False,
                        'product_name': receipt_line.description or False,
                        'qty': receipt._parse_float(receipt_line.product_uom_qty),
                        'uom': receipt_line.uom_code or False,
                        'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    })
                    continue

                uom = receipt._find_uom(receipt_line, product)
                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receipt_line.inventory_id or False,
                        'product_name': receipt_line.description or False,
                        'qty': receipt._parse_float(receipt_line.product_uom_qty),
                        'uom': receipt_line.uom_code or False,
                        'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    })
                    continue

                qty = receipt._parse_float(receipt_line.product_uom_qty)
                location_id = picking.location_id.id if picking else False
                location_dest_id = picking.location_dest_id.id if picking else False
                move_vals = {
                    'name': receipt_line.transaction_description or receipt_line.description or product.display_name,
                    'picking_id': picking.id if picking else False,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id if uom else product.uom_id.id,
                    'location_id': location_id,
                    'location_dest_id': location_dest_id,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'description_picking': receipt_line.description or False,
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
                # picking.action_confirm()

            except ReceiptImportError:
                raise

            except Exception as line_error:
                _logger.exception("Error import line %s", receipt.id)
                error_messages.append(str(line_error))
                error_line_payloads.append({
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
                line_payloads=error_line_payloads,
            )

        if receipt.document_only:
            picking.action_validate_document_only_import(force=True)

        receipt.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._handle_acumatica_error(receipt)
        return action_state

    def _do_import(self):
        created = 0
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
                if action_state == 'created':
                    created += 1
                elif action_state == 'updated':
                    updated += 1
            except Exception as exc:
                _logger.exception("Error import receipt %s", receipt.receipt_nbr or receipt.id)
                if isinstance(exc, ReceiptImportError):
                    error_payload = exc.payload
                    error_line_payloads = exc.line_payloads
                    error_message = str(exc)
                else:
                    error_payload = {'header': receipt.read()[0] if receipt.exists() else {}}
                    error_line_payloads = []
                    error_message = str(exc)

                try:
                    self._handle_acumatica_error(
                        receipt,
                        [error_message],
                        line_payloads=error_line_payloads,
                        payload=error_payload,
                    )
                except Exception:
                    _logger.exception(
                        "Failed to persist error tracking for receipt %s",
                        receipt.receipt_nbr or receipt.id,
                    )

                receipt.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        msg = f'Import done: {created} receipt created, {updated} receipt updated, {error} receipt error.'
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Inventory Receipt',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }


    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if self.odoo_internal_transfer_order_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'internal.transfer.order',
                'res_id': self.odoo_internal_transfer_order_id.id,
                'view_mode': 'form',
            }
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada transfer di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }
