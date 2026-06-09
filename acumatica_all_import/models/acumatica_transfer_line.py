import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaTransferLine(models.Model):
    _name = 'acumatica.transfer.line'
    _description = 'Data Internal Transfer dari Acumatica'
    _order = 'transfer_order_number asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    receipt_nbr = fields.Char(string='Receipt Number', readonly=True, index=True)
    transfer_order_number = fields.Char(string='Transfer Order Number', readonly=True, index=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Number', readonly=True)
    transfer_order_type = fields.Char(string='Transfer Order Type', readonly=True)
    transfer_shipment_number = fields.Char(string='Transfer Shipment Number', readonly=True)

    vendor_code = fields.Char(string='VendorID', readonly=True)
    partner_ref = fields.Char(string='Vendor Ref', readonly=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)
    header_location_code = fields.Char(string='Header Location', readonly=True)
    location_dest_code = fields.Char(string='Location', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    receipt_type = fields.Char(string='Type', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    inventory_ref = fields.Char(string='Inventory Ref Nbr', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)

    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    transaction_description = fields.Char(string='Transaction Description', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    line_type = fields.Char(string='Line Type', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    po_line_number = fields.Char(string='PO Line Nbr', readonly=True)
    po_number = fields.Char(string='PO Number', readonly=True)
    po_type = fields.Char(string='PO Type', readonly=True)
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr', readonly=True)
    po_receipt_number = fields.Char(string='PO Receipt Nbr', readonly=True)
    product_uom_qty = fields.Char(string='Receipt Qty', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Internal Transfer di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.transfer.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('receipt_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            origin = rec.receipt_nbr
            rec.exists_in_odoo = bool(origin and Picking.search_count([('origin', '=', origin)]))

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
        if not product:
            product = Product.create({
                'name': line.transaction_description or line.description or line.inventory_id or 'Unknown Product',
                'default_code': line.inventory_id or False,
                'type': 'consu',
            })
        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line.warehouse_dest_code or line.warehouse_code
        if line.code:
            warehouse = Warehouse.search([('code', '=', line.code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', line.code)], limit=1)
            else:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    
            # else:
            #     warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    # def _find_warehouse(self, line):
    #     Warehouse = self.env['stock.warehouse']
    #     code = line.warehouse_dest_code or line.warehouse_code
    #     warehouse = False
    #     if code:
    #         warehouse = Warehouse.search([('code', '=', code)], limit=1)
    #         if not warehouse:
    #             warehouse = Warehouse.search([('name', '=', code)], limit=1)
    #     return warehouse or Warehouse.search([], limit=1)

    def _find_internal_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.location_dest_code or line.header_location_code
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
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
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = updated = error = 0

        keys = self.mapped('transfer_order_number') or self.mapped('receipt_nbr')
        keys = [k for k in keys if k]
        for transfer_key in keys:
            receipt_lines = self.filtered(lambda l: (l.transfer_order_number or l.receipt_nbr) == transfer_key and l.import_state == 'pending')
            if not receipt_lines:
                continue
            first = receipt_lines[0]
            try:
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_dest_code or first.warehouse_code or "-"}')

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'internal'),
                ], limit=1) or PickingType.search([('code', '=', 'internal')], limit=1)
                if not picking_type:
                    raise UserError('Picking type internal tidak ditemukan.')

                dest_location = self._find_internal_location(first, warehouse)
                if not dest_location:
                    raise UserError(f'Location tujuan tidak ditemukan untuk code: {first.location_dest_code or first.header_location_code or "-"}')

                origin = first.receipt_nbr or False
                vals = {
                    'origin': origin,
                    'picking_type_id': picking_type.id,
                    'location_id': picking_type.default_location_src_id.id if picking_type.default_location_src_id else warehouse.lot_stock_id.id,
                    'location_dest_id': dest_location.id if dest_location else (picking_type.default_location_dest_id.id if picking_type.default_location_dest_id else warehouse.lot_stock_id.id),
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or False,

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

                picking = Picking.search([('origin', '=', origin)], limit=1)
                if picking:
                    if picking.state in ('done', 'cancel'):
                        raise UserError(f'Internal transfer {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1

                for line in receipt_lines:
                    product = self._find_product(line)
                    uom = self._find_uom(line, product)
                    line_dest = self._find_internal_location(line, warehouse) or dest_location
                    qty = self._parse_float(line.product_uom_qty)

                    existing = Move.search([
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', product.id),
                        ('name', '=', line.transaction_description or line.description or product.display_name),
                        ('product_uom_qty', '=', qty),
                    ], limit=1)
                    if existing:
                        line.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name} (move sudah ada)',
                            'odoo_picking_id': picking.id,
                        })
                        continue

                    Move.create({
                        'name': line.transaction_description or line.description or product.display_name,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': uom.id if uom else product.uom_id.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': line_dest.id if line_dest else picking.location_dest_id.id,
                        'description_picking': line.description or line.transaction_description or False,
                    })
                    line.write({
                        'import_state': action_state,
                        'import_message': f'{action_state.title()}: {picking.name}',
                        'odoo_picking_id': picking.id,
                    })
            except Exception as e:
                _logger.exception('Error import transfer %s', transfer_key)
                receipt_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
                error += len(receipt_lines)

        msg = f'Import selesai: {imported} transfer dibuat, {updated} transfer diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Internal Transfer',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada transfer di Odoo.')
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
