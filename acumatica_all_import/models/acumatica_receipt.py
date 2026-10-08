from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging
import requests

_logger = logging.getLogger(__name__)


class ReceiptImportError(Exception):
    def __init__(
        self,
        message,
        payload=None,
        line_payloads=None,
        user_message=None,
        technical_errors=None,
    ):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []
        self.user_message = user_message or False
        self.technical_errors = technical_errors or []


class AcumaticaReceiptProductLine(models.Model):
    _name = 'acumatica.receipt.product.line'
    _description = 'Data Product PO Receipt dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica')
    receipt_line_id = fields.Many2one('acumatica.receipt.line', string='Receipt', ondelete='cascade')
    receipt_nbr = fields.Char(string='Receipt Number', index=True)
    line_external_id = fields.Char(string='UUID Line Acumatica')
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

    transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr')
    transfer_order_number = fields.Char(string='Transfer Order Nbr')
    transfer_order_type = fields.Char(string='Transfer Order Type')
    transfer_shipment_number = fields.Char(string='Transfer Shipment Nbr')

    product_uom_qty = fields.Char(string='Receipt Qty')
    uom_code = fields.Char(string='UOM')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    line_note = fields.Text(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')


class AcumaticaReceiptLine(models.Model):
    _name = 'acumatica.receipt.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Data PO Receipt dari Acumatica'
    _order = 'receipt_nbr asc, line_nbr asc, id asc'

    def _adt_picking_type_wizard_call(self):
        return ('import.receipt.wizard', (self.building_code,), {'document_only': self.document_only})

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header Acumatica')
    line_external_id = fields.Char(string='UUID Line Acumatica')
    building_code = fields.Char(string='Building Code')

    product_line_ids = fields.One2many('acumatica.receipt.product.line', 'receipt_line_id', string='Lines')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')
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
    line_note_id = fields.Char(string='Line Note ID')
    acumatica_err_id = fields.Many2one('acumatica.error.transaction', string='Error ID')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', tracking=True)
    import_message = fields.Char(string='Generation Message', tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')

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

    def _handle_acumatica_error(self, first, error_messages=False):
        AcumaticaError = self.env['acumatica.error.transaction']
        acumatica_err_id = self.acumatica_err_id
        if not error_messages:
            if acumatica_err_id:
                acumatica_err_id.import_state = 'created'
                return
            return

        state = 'error'
        if not acumatica_err_id:
            acumatica_err_id = AcumaticaError.create({
                'name': f'{first.receipt_nbr or False}',
                'data_type': self._name,
                'import_state': state,
                'data_id': self.id,
                'error_msg': error_messages
            })
            self.acumatica_err_id = acumatica_err_id

        acumatica_err_id.import_state = state
        acumatica_err_id.error_msg = error_messages

    def _handle_acumatica_update(self, first):
        AcumaticaError = self.env['acumatica.error.transaction']
        state = 'updated'
        acumatica_update_id = AcumaticaError.search([
            ('data_type', '=', self._name),
            ('data_id', '=', self.id),
        ], order='id', limit=1)
        if not acumatica_update_id:
            acumatica_update_id = AcumaticaError.create({
                'name': f'{first.receipt_nbr or False}',
                'data_type': self._name,
                'import_state': state,
                'data_id': self.id,
                'error_msg': f'Updated: {first.receipt_nbr or False} in {fields.Datetime.now()}'
            })

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def _find_existing_receipt_move(self, picking, receipt_line, used_move_ids):
        """Match by Acumatica line identity, never by the current product."""
        candidates = picking.move_ids.filtered(lambda move: move.id not in used_move_ids)
        if receipt_line.line_nbr:
            move = candidates.filtered(lambda item: item.adt_line_nbr == receipt_line.line_nbr)[:1]
            if move:
                return move
        if receipt_line.line_external_id:
            move = candidates.filtered(
                lambda item: item.adt_line_external_id == receipt_line.line_external_id
            )[:1]
            if move:
                return move
        if receipt_line.po_receipt_line_number:
            return candidates.filtered(
                lambda item: item.adt_po_receipt_line_number == receipt_line.po_receipt_line_number
            )[:1]
        return self.env['stock.move']

    def action_import_selected(self):
        lines = self.filtered(
            lambda l: (
                l.import_state in ['staged', 'error']
                or (l.import_state in ['created', 'updated'] and not l.odoo_picking_id)
            )
        )
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

    def _import_single_receipt(self, receipt):
        receipt.ensure_one()

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = receipt.receipt_nbr or False
        header_payload = receipt.read()[0] if receipt.exists() else {}
        error_messages = []
        user_messages = []
        technical_errors = []
        all_line_payloads = []
        picking = receipt.odoo_picking_id
        action_state = 'staged'
        update_messages = []

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
            user_messages.append(
                f"Vendor dengan kode {receipt.vendor_code or '-'} belum terdaftar. "
                "Periksa master vendor di WMS."
            )

        warehouse = receipt._find_warehouse(receipt)
        if not warehouse:
            error_messages.append(
                f'Warehouse with location code {receipt.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )
            user_messages.append(
                f"Warehouse dengan kode {receipt.building_code or '-'} "
                "belum ditemukan atau tidak aktif. Periksa mapping warehouse di WMS."
            )

        dest_location = receipt._find_location_dest(receipt.warehouse_code)
        if not dest_location:
            error_messages.append(
                f'Location with code {receipt.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )
            user_messages.append(
                f"Lokasi tujuan dengan kode {receipt.warehouse_code or '-'} "
                "belum ditemukan atau tidak aktif. Periksa mapping lokasi di WMS."
            )

        # picking_type = PickingType.search([
        #     ('warehouse_id', '=', warehouse.id if warehouse else False),
        #     ('code', '=', 'incoming'),
        # ], limit=1)
        picking_type = receipt._adt_reresolve_picking_type()
        if not picking_type:
            warehouse_txt = f"Warehouse code {warehouse.code if warehouse else '-'}"
            location_txt = f'Location code {receipt.warehouse_code}'
            error_messages.append(
                f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
            )
            user_messages.append(
                f"Tipe operasi untuk {warehouse_txt if warehouse else location_txt} belum tersedia. "
                "Periksa pengaturan tipe operasi di WMS."
            )

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
                line_payloads=all_line_payloads,
                user_message="\n".join(user_messages),
            )

        scheduled_date = receipt._parse_dt(receipt.scheduled_date)
        picking_vals = {
            'partner_id': vendor.id if vendor else False,
            'picking_type_id': picking_type.id,
            'adt_dest_location_id': dest_location.id if dest_location else False,
            'scheduled_date': scheduled_date,
            'origin': origin,
            'note': receipt.note or False,
            'adt_receipt_nbr': receipt.receipt_nbr or False,
            'adt_vendor_code': receipt.vendor_code or False,
            'adt_partner_ref': receipt.partner_ref or False,
            'adt_branch_warehouse': receipt.branch_warehouse or False,
            # 'adt_actual_qty': receipt._parse_float(receipt.actual_qty),
            'adt_is_hold': str(receipt.is_hold or '').lower() in ('true', '1', 'yes'),
            'adt_inventory_ref': receipt.inventory_ref or False,
            'adt_acumatica_write_date': receipt._parse_dt(receipt.acumatica_write_date),
            'adt_header_location_code': receipt.header_location_code or False,
            'adt_post_period': receipt.post_period or False,
            'adt_status': receipt.status or False,
            'adt_total_qty': receipt._parse_float(receipt.total_qty),
            # 'adt_type': receipt.receipt_type or False,
            'adt_type': "PO Receipt",
            'adt_warehouse_code': receipt.warehouse_code or False,
            'adt_external_id': receipt.external_id or False,
        }
        picking_vals = {key: value for key, value in picking_vals.items() if key in Picking._fields}

        if picking:
            if picking.state != 'draft':
                raise ReceiptImportError(
                    f'Receipt {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.',
                    payload={'header': header_payload, 'picking_vals': picking_vals},
                    line_payloads=all_line_payloads,
                    user_message=(
                        f"Receipt {origin} tidak dapat diperbarui karena dokumen di WMS "
                        f"sudah berstatus {picking.state}. Hubungi admin jika perubahan diperlukan."
                    ),
                )
            update_messages.extend(
                self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                    picking,
                    picking_vals,
                    field_names={
                        'partner_id', 'picking_type_id', 'scheduled_date', 'origin',
                        'note', 'adt_receipt_nbr', 'adt_vendor_code', 'adt_partner_ref',
                        'adt_branch_warehouse', 'adt_is_hold', 'adt_inventory_ref',
                        'adt_header_location_code', 'adt_post_period', 'adt_status',
                        'adt_total_qty', 'adt_type', 'adt_warehouse_code',
                    },
                    prefix="Header",
                )
            )
            picking.write(picking_vals)
            receipt._handle_acumatica_update(receipt)
            action_state = 'updated'
        else:
            picking = Picking.create(picking_vals)
            receipt._handle_acumatica_error(
                receipt
            )
            action_state = 'created'

        used_move_ids = set()
        for receipt_line in receipt.product_line_ids:
            move_vals = {}
            try:
                product = receipt._find_product(receipt_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    user_messages.append(
                        f"Produk dengan kode {receipt_line.inventory_id or '-'} belum terdaftar. "
                        "Hubungi admin untuk melengkapi master produk di WMS."
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

                dest_code = receipt_line.warehouse_dest_code
                dest_move_location = receipt._find_location_dest(dest_code)
                if not dest_move_location:
                    error_messages.append(
                        f'Location with code {receipt_line.warehouse_dest_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
                    )
                    user_messages.append(
                        f"Lokasi tujuan untuk baris {receipt_line.line_nbr or '-'} "
                        f"(kode {receipt_line.warehouse_dest_code or '-'}) belum ditemukan "
                        "atau tidak aktif. Periksa mapping lokasi di WMS."
                    )

                adt_dest_location = dest_move_location.id if dest_move_location else picking.adt_dest_location_id.id or False

                qty = receipt._parse_float(receipt_line.product_uom_qty)
                move_vals = {
                    'name': receipt_line.description or product.display_name,
                    'picking_id': picking.id if picking else False,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id if uom else product.uom_id.id,
                    'date': scheduled_date,
                    'location_id': picking.location_id.id if picking else False,
                    'location_dest_id': adt_dest_location,
                    'warehouse_id': warehouse.id if warehouse else False,
                    # 'description_picking': product.name or False,
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
                existing = receipt._find_existing_receipt_move(
                    picking,
                    receipt_line,
                    used_move_ids,
                )
                line_label = (
                    receipt_line.line_nbr
                    or receipt_line.line_external_id
                    or receipt_line.inventory_id
                    or "?"
                )
                if existing:
                    update_messages.extend(
                        self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                            existing,
                            move_vals,
                            field_names={
                                'name', 'product_id', 'product_uom_qty', 'product_uom',
                                'location_id', 'location_dest_id', 'date', 'product_note',
                            },
                            prefix=f"Baris {line_label}",
                        )
                    )
                    existing.write(move_vals)
                    used_move_ids.add(existing.id)
                else:
                    created_move = Move.create(move_vals)
                    if action_state == 'updated':
                        update_messages.append(
                            f"• Baris {line_label}: produk "
                            f"{product.display_name}, jumlah {qty:g} ditambahkan"
                        )
                    used_move_ids.add(created_move.id)

            except ReceiptImportError:
                raise

            except Exception as line_error:
                _logger.exception("Error import line %s", receipt.id)
                error_messages.append(str(line_error))
                technical_errors.append(str(line_error))
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
                user_message="\n".join(user_messages),
                technical_errors=technical_errors,
            )

        managed_moves = picking.move_ids.filtered(
            lambda move: (
                move.adt_line_external_id
                or move.adt_line_nbr
                or move.adt_po_receipt_line_number
            )
        )
        stale_moves = managed_moves.filtered(lambda move: move.id not in used_move_ids)
        if stale_moves:
            if action_state == 'updated':
                for stale_move in stale_moves:
                    stale_label = stale_move.adt_line_nbr or stale_move.adt_inventory_id or stale_move.name
                    update_messages.append(
                        f"• Baris {stale_label}: {stale_move.product_id.display_name} dihapus"
                    )
            stale_moves.unlink()

        if receipt.document_only:
            picking.action_validate_document_only_import(force=True)

        receipt.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_picking_id': picking.id if picking else False,
        })
        # picking.action_confirm()
        return action_state, update_messages

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
                    action_state, update_messages = self._import_single_receipt(receipt)
                if action_state == 'created':
                    created += 1
                elif action_state == 'updated':
                    updated += 1
                    message = "\n".join(update_messages) or (
                        "Receipt berhasil disinkronkan; tidak ada field yang berubah."
                    )
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type="import",
                        webhook_name="PO Receipt",
                        transaction_name=receipt.receipt_nbr or str(receipt.id),
                        event_type="update",
                        message=message,
                    )
            except Exception as exc:
                _logger.exception("Error import receipt %s", receipt.receipt_nbr or receipt.id)
                if isinstance(exc, ReceiptImportError):
                    error_payload = exc.payload
                    all_line_payloads = exc.line_payloads
                    error_message = str(exc)
                    user_message = exc.user_message
                    technical_errors = exc.technical_errors
                else:
                    error_payload = {'header': receipt.read()[0] if receipt.exists() else {}}
                    all_line_payloads = []
                    error_message = str(exc)
                    user_message = False
                    technical_errors = [str(exc)]

                if technical_errors:
                    self.env['acumatica.webhook.error.service'].send_error(
                        webhook_type="import",
                        webhook_name="PO Receipt",
                        error="\n".join(technical_errors),
                        error_type="unexpected",
                    )

                try:
                    receipt._handle_acumatica_error(
                        receipt,
                        error_message,
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
                if user_message:
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type="import",
                        webhook_name="PO Receipt",
                        transaction_name=receipt.receipt_nbr or str(receipt.id),
                        event_type="error",
                        message=user_message,
                    )
                continue

        msg = f'Generate done: {created} receipt created, {updated} receipt updated, {error} receipt error.'
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Generate Inventory Receipt',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

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
