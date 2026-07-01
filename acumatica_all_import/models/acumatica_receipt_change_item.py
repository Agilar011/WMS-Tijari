import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ReceiptImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaReceiptChangeItemLine(models.Model):

    _name = 'acumatica.receipt.change.item.line'
    _description = 'Data Receipt Type Change Item dari Acumatica'
    _order = 'origin asc, line_nbr asc, id asc'
    product_line_ids = fields.One2many('acumatica.receipt.change.item.product', 'receipt_line_id', string='Lines')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])
    branch = fields.Char(string="branch", readonly=True)

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    origin = fields.Char(string='Reference Number', readonly=True, index=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    description = fields.Char(string='Description Header', readonly=True)
    note = fields.Text(string='Note Header', readonly=True)
    actual_qty = fields.Float(string='ControlQty', readonly=True)
    is_hold = fields.Boolean(string='Hold', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    warehouse_code = fields.Char(string='ToWarehouseID', readonly=True)
    transfer_type = fields.Char(string='Transfer Type', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)
    external_ref = fields.Char(string='External Ref', readonly=True)

    receipt_type = fields.Char(string='Type', readonly=True)
    vendor_code = fields.Char(string='VendorID', readonly=True)


    line_nbr = fields.Char(string='Line Number', readonly=True)
    line_description = fields.Char(string='Description Line', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    product_uom_qty = fields.Float(string='Qty', readonly=True)
    line_warehouse_code = fields.Char(string='WarehouseID', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

    change_item_nbr = fields.Char(string='Change Item Nbr', readonly=True)
    shipment_nbr = fields.Char(string='Shipment Nbr', readonly=True)
    transfer_nbr = fields.Char(string='Transfer Nbr', readonly=True)
    location_code = fields.Char(string='Location Code', readonly=True)
    customer_code = fields.Char(string='Customer Code', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Picking di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')


    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.description:
            product = Product.search([('name', '=', line.description)], limit=1)
        return product

    def _find_warehouse(self, line):
            Warehouse = self.env['stock.location.acumatica']
            warehouse = False
            if line.warehouse_code:
                warehouse = Warehouse.search([('code', '=', line.warehouse_code)], limit=1)
                if warehouse:
                    if not warehouse.odoo_building_id:
                        warehouse = False
                    else:
                        warehouse = warehouse.odoo_building_id    

            return warehouse

    def _find_internal_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.location_code
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = none
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def _find_vendor(self, line):
        Partner = self.env['res.partner']
        vendor = False
        if line.vendor_code:
            # vendor = Partner.search([('ref', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            vendor = Partner.search([('company_registry', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            if not vendor:
                vendor = Partner.search([('name', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
        return vendor

    def _find_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        location = False
        if line.warehouse_code:
            location = Location.search([('code', '=', line.warehouse_code)], limit=1)
            if location:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
        return location
    
    @api.depends('origin')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.origin and Picking.search_count([('origin', '=', rec.origin)]))

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


    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
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

        origin = receipt.origin or False
        header_payload = receipt.read()[0] if receipt.exists() else {}
        error_messages = []
        error_line_payloads = []
        picking = receipt.odoo_picking_id
        action_state = 'pending'

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
                f'Operation Type for code incoming with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
            )

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
            )

        picking_vals = {
            # 'partner_id': vendor.id if vendor else False,
            'picking_type_id': picking_type.id,
            'adt_dest_location_id': dest_location.id if dest_location else False,
            'scheduled_date': receipt._parse_dt(receipt.scheduled_date),
            'origin': origin,
            'note': receipt.note or False,
            'adt_branch_warehouse': receipt.branch_warehouse or False,
            'adt_actual_qty': self._parse_float(receipt.actual_qty),
            'adt_acumatica_write_date': self._parse_dt(receipt.acumatica_write_date),
            'adt_description': receipt.description or False,
            'adt_post_period': receipt.post_period or False,
            'adt_status': receipt.status or False,
            'adt_total_qty': self._parse_float(receipt.total_qty),
            'adt_type': receipt.transfer_type or False,
            'adt_external_ref': receipt.external_ref or False,
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
                existing = picking.move_ids.filtered(
                    lambda move: (
                        move.picking_id.id == picking.id
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

                    'adt_line_external_id': receipt_line.line_external_id or False,
                    'adt_inventory_id': receipt_line.inventory_id or False,
                    'adt_line_nbr': receipt_line.line_nbr or False,
                    'adt_line_type': receipt_line.line_type or False,
                    'adt_po_line_number': receipt_line.line_nbr or False,
                    'adt_uom_code': receipt_line.uom_code or False,
                    'adt_warehouse_dest_code': receipt_line.warehouse_dest_code or False,
                    'adt_location_dest_code': receipt_line.location_code or False,
                    'adt_dest_location_id': picking.adt_dest_location_id.id if picking else False,
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

        receipt.write({
            'import_state': action_state,
            'import_message': f'{action_state.title()}: {picking.name if picking else False}',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._resolve_error_tracking(receipt)
        return action_state

    def _do_import(self):
        imported = 0
        updated = 0
        error = 0

        grouped_receipts = []
        seen_receipt_numbers = set()
        for receipt in self.sorted(lambda record: (record.origin or '', record.id)):
            receipt_key = receipt.origin or receipt.id
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
                _logger.exception("Error import receipt %s", receipt.origin or receipt.id)
                if isinstance(exc, ReceiptImportError):
                    error_payload = exc.payload
                    error_line_payloads = exc.line_payloads
                    error_message = str(exc)
                else:
                    error_payload = {'header': receipt.read()[0] if receipt.exists() else {}}
                    error_line_payloads = []
                    error_message = str(exc)

                try:
                    self._persist_error_tracking(
                        receipt,
                        [error_message],
                        line_payloads=error_line_payloads,
                        payload=error_payload,
                    )
                except Exception:
                    _logger.exception(
                        "Failed to persist error tracking for receipt %s",
                        receipt.origin or receipt.id,
                    )

                receipt.write({
                    'import_state': 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        msg = f'Import done: {imported} receipt created, {updated} receipt updated, {error} receipt error.'
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

    def _resolve_error_tracking(self, first):
        origin = first.origin or False
        if not origin:
            return

        error_data = self.env['stock.picking.acumatica.error'].search([('origin', '=', origin)], limit=1)
        if error_data:
            error_data.write({'state': 'resolved'})

    def _persist_error_tracking(self, first, error_messages, line_payloads=None, payload=None):
        origin = first.origin or False
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
                # 'location': first.warehouse_code or False,
                'location_dest': first.warehouse_code or False,
                'scheduled_date': first._parse_dt(first.scheduled_date),
                'origin': origin,
                'adt_total_qty': first._parse_float(first.total_qty),
                'adt_actual_qty': first._parse_float(first.actual_qty),
                'api_acumatica': 'receipt_change_item',
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



    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()


    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada picking di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }

    def action_select_all(self):
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})


class AcumaticaReceiptChangeItemProduct(models.Model):
    _name = 'acumatica.receipt.change.item.product'
    _description = 'Acumatica Receipt Change Item Line'
    _order = 'receipt_line_id, line_nbr, id'

    receipt_line_id = fields.Many2one(
        'acumatica.receipt.change.item.line',
        string='Receipt Header',
        required=True,
        ondelete='cascade',
        index=True,
    )

    header_external_id = fields.Char(string='Header External ID',readonly=True,index=True,)
    line_external_id = fields.Char(string='Line External ID',readonly=True,index=True,)
    line_note = fields.Text(string='Line Note',readonly=True,)
    description = fields.Char(string='Description', readonly=True)
    inventory_id = fields.Char(string='Inventory ID', readonly=True,index=True)
    line_nbr = fields.Char(string='Line Number', readonly=True)
    line_type = fields.Char(string='Line Type', readonly=True)
    location_code = fields.Char(string='Location Destination', readonly=True)
    product_uom_qty = fields.Float(string='Quantity', readonly=True)
    uom_code = fields.Char( string='UOM', readonly=True,)
    warehouse_dest_code = fields.Char(string='Warehouse Destination', readonly=True,)