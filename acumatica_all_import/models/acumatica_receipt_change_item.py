import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaReceiptChangeItemLine(models.Model):

    _name = 'acumatica.receipt.change.item.line'
    _description = 'Data Receipt Type Change Item dari Acumatica'
    _order = 'origin asc, line_nbr asc, id asc'
    product_line_ids = fields.One2many('acumatica.receipt.change.item.product', 'receipt_line_id', string='Lines')
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
    # location_code = fields.Char(string='Location', readonly=True)
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

    config_id = fields.Many2one('acumatica.receipt.change.item.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')


    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------
    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']
        Error = self.env['stock.picking.acumatica.error']
        ErrorLine = self.env['stock.picking.acumatica.error.line']


        imported = 0
        updated = 0
        error = 0

        for line in self:
            print(f"line: {line}, line origin: {line.origin}")
            first = line
            origin = line.origin
            error_list = []
            try:
                # Cari vendor, inventory, warehouse, uom. kalo salah satu tidak sync di wms, maka record akan masuk ke stock_picking_error.
                vendor = self._find_vendor(first)
                if not vendor:
                    error_list.append(f'Vendor with VendorID {first.vendor_code} was not found in the WMS | MASTER VENDOR.')

                warehouse = self._find_warehouse(first)
                if not warehouse:
                    error_list.append(f'Warehouse with location code {first.warehouse_code} was not found in the WMS | MAPPING WAREHOUSE.')

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id if warehouse else False),
                    ('code', '=', 'incoming'),
                ], limit=1)

                # if not picking_type:
                #     raise UserError('Picking type incoming tidak ditemukan.')

                dest_location = self._find_location_dest(first)
                if not dest_location:
                    error_list.append(f'Location with code {first.warehouse_code} was not found in the WMS | MAPPING WAREHOUSE.')
            
                vals = {
                    'origin': first.origin,
                    'picking_type_id': picking_type.id,
                    'location_id': picking_type.default_location_src_id.id if picking_type.default_location_src_id else None,
                    'location_dest_id': dest_location.id if dest_location else (picking_type.default_location_dest_id.id if picking_type.default_location_dest_id else None),
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or False,

                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_description': first.description or False,
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.transfer_type or False,
                    'adt_external_ref': first.external_ref or False,
                }

                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Picking._fields}

                # pakai origin buat dedup
                picking = self.odoo_picking_id
                error_data = False
                if error_list:
                    error_data = Error.search([('origin', '=', origin)], limit=1)
                    if not error_data:
                        error_data = Error.create({
                            'partner': first.vendor_code or False,
                            'operation_type': 'receipt',
                            'location': first.warehouse_code or False,
                            'location_dest': dest_location.id if dest_location else (picking_type.default_location_dest_id.id if picking_type.default_location_dest_id else None),
                            'scheduled_date': self._parse_dt(first.scheduled_date),
                            'origin': origin,
                            'adt_total_qty': self._parse_float(first.total_qty),
                            'adt_actual_qty': self._parse_float(first.actual_qty),
                            'api_acumatica': 'po_receipt',
                            'error_message': '\n'.join(error_list),
                            'payload': str(vals)[:1000],
                        })

                else:
                    if picking:
                        if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned') and picking:
                            raise UserError(
                                f'Receipt {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.'
                            )
                        picking.write(vals)
                        action_state = 'updated'
                        updated += 1
                    else:
                        picking = Picking.create(vals)
                        picking.action_confirm()
                        action_state = 'imported'
                        imported += 1

                for line in self.product_line_ids:
                    try:
                        product = self._find_product(line)
                        if not product:
                            error_list.append(f'Product with InventoryID {line.inventory_id} was not found in the WMS | MASTER PRODUCT.')

                        uom = self._find_uom(line, product)
                        # line_dest = self._find_location_dest(line, warehouse) or dest_location
                        qty = self._parse_float(line.product_uom_qty)

                        # dedup move
                        move_domain = [('picking_id', '=', picking.id if picking else False)]
                        if 'adt_line_external_id' in Move._fields and line.line_external_id:
                            move_domain.append(('adt_line_external_id', '=', line.line_external_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('product_uom_qty', '=', qty),
                            ]

                        existing_move = Move.search(move_domain, limit=1)
                        if existing_move:
                            first.write({
                                'import_state': 'updated',
                                'import_message': f'Skip duplicate: {picking.name if picking else False}',
                                'odoo_picking_id': picking.id if picking else False,
                            })
                            continue

                        move_vals = {
                            'name': line.transaction_description or line.description or product.display_name,
                            'picking_id': picking.id if picking else False,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id if picking else False,
                            'location_dest_id': picking.location_dest_id.id if picking else False,
                            'warehouse_id': warehouse.id if warehouse else False,
                            'description_picking': line.description or False,

                            'adt_line_external_id': line.line_external_id or False,
                            'adt_inventory_id': line.inventory_id or False,
                            'adt_line_nbr': line.line_nbr or False,
                            'adt_line_type': line.line_type or False,
                            'adt_open_qty': self._parse_float(line.open_qty),
                            'adt_order_qty': self._parse_float(line.order_qty),
                            'adt_po_line_number': line.line_nbr or False,
                            # 'adt_po_number': line.po_number or False,
                            # 'adt_po_type': line.po_type or False,
                            # 'adt_po_receipt_line_number': line.po_receipt_line_number or False,
                            # 'adt_po_receipt_number': line.po_receipt_number or False,
                            # 'adt_transfer_order_line_number': line.transfer_order_line_number or False,
                            # 'adt_transfer_order_number': line.transfer_order_number or False,
                            # 'adt_transfer_order_type': line.transfer_order_type or False,
                            # 'adt_transfer_shipment_number': line.transfer_shipment_number or False,
                            'adt_uom_code': line.uom_code or False,
                            'adt_warehouse_dest_code': line.warehouse_dest_code or False,
                            'adt_location_dest_code': line.location_dest_code or False,
                            'adt_line_note': line.line_note or False,
                        }

                        # filter field yang ada di stock.move
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}
                        if error_data:
                            ErrorLine.create({
                                'error_id': error_data.id,
                                'inventory_id': line.inventory_id or False,
                                'product_name': line.description or False,
                                'qty': line.product_uom_qty or False,
                                'uom': line.uom_code or False,
                            })
                            continue

                        if error_list:                                
                            error_line_data = ErrorLine.search([('error_id', '=', error.id)], limit=1)
                            if not error_line_data:
                                error_line_data = ErrorLine.create({
                                    'error_id': error_data.id,
                                    'inventory_id': line.inventory_id or False,
                                    'product_name': line.description or False,
                                    'qty': line.product_uom_qty or False,
                                    'uom': line.uom_code or False,
                                    'payload': str(move_vals)[:1000],
                                })
                                error += 1
                        else:
                            Move.create(move_vals)

                        first.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name if picking else False}',
                            'odoo_picking_id': picking.id if picking else False,
                        })


                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        line.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_picking_id': picking.id if picking else False,
                        })
                        error += 1

                if error_list:
                    _logger.exception("Error import receipt %s", origin)
                    self.write({
                        'import_state': 'error',
                        'import_message': '\n'.join(error_list),
                    })
                    error += 1

            except Exception as e:
                _logger.exception("Error import receipt %s", origin)
                self.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                # error += len(receipt_lines)

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

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)
        if not product:
            product = Product.create({
                'name': line.line_description or line.inventory_id or 'Unknown Product',
                'default_code': line.inventory_id or False,
                'type': 'consu',
            })
        return product

    def _find_warehouse(self, line):
            Warehouse = self.env['stock.location.acumatica']
            warehouse = False
            if line.line_warehouse_code:
                warehouse = Warehouse.search([('code', '=', line.line_warehouse_code)], limit=1)
                if not warehouse:
                    warehouse = Warehouse.search([('name', '=', line.line_warehouse_code)], limit=1)
                else:
                    if not warehouse.odoo_building_id:
                        warehouse = False
                    else:
                        warehouse = warehouse.odoo_building_id    
                # else:
                #     warehouse = Warehouse.search([('id', '=', 1)], limit=1)
            return warehouse or Warehouse.search([], limit=1)

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
    
    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # DETAIL
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # API MAPPING
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # API
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------

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

    header_external_id = fields.Char(
        string='Header External ID',
        readonly=True,
        index=True,
    )

    line_external_id = fields.Char(
        string='Line External ID',
        readonly=True,
        index=True,
    )

    line_note = fields.Text(
        string='Line Note',
        readonly=True,
    )

    description = fields.Char(
        string='Description',
        readonly=True,
    )

    inventory_id = fields.Char(
        string='Inventory ID',
        readonly=True,
        index=True,
    )

    line_nbr = fields.Char(
        string='Line Number',
        readonly=True,
    )

    line_type = fields.Char(
        string='Line Type',
        readonly=True,
    )

    location_dest_code = fields.Char(
        string='Location Destination',
        readonly=True,
    )

    open_qty = fields.Float(
        string='Open Qty',
        readonly=True,
    )

    order_qty = fields.Float(
        string='Order Qty',
        readonly=True,
    )

    product_uom_qty = fields.Float(
        string='Quantity',
        readonly=True,
    )

    transaction_description = fields.Char(
        string='Transaction Description',
        readonly=True,
    )

    uom_code = fields.Char(
        string='UOM',
        readonly=True,
    )

    warehouse_dest_code = fields.Char(
        string='Warehouse Destination',
        readonly=True,
    )

