import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaInventoryRecievedLine(models.Model):
    _name = 'acumatica.inventory.recieved.line'
    _description = 'Data Inventory Recieved dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    reference_nbr = fields.Char(string='Reference Number', readonly=True, index=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    header_description = fields.Char(string='Header Description', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    transfer_type = fields.Char(string='Transfer Type', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)
    external_ref = fields.Char(string='External Ref', readonly=True)

    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)
    location_code = fields.Char(string='Location', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    product_uom_qty = fields.Char(string='Qty', readonly=True)
    detail_warehouse_code = fields.Char(string='Detail Warehouse', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Delivery Order di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.inventory.recieved.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('reference_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.reference_nbr and Picking.search_count([('origin', '=', rec.reference_nbr)]))

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
        if not product and line.description:
            product = Product.search([('name', '=', line.description)], limit=1)
        if not product:
            product = Product.create({
                'name': line.description or line.inventory_id or 'Unknown Product',
                'default_code': line.inventory_id or False,
                'type': 'consu',
            })
        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        code = line.detail_warehouse_code or line.warehouse_code
        warehouse = False
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', code)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.location_code
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_delivery_picking_type(self, warehouse=False):
        PickingType = self.env['stock.picking.type']
        picking_type = False
        if warehouse:
            picking_type = PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('code', '=', 'incoming'),
            ], limit=1)
        if not picking_type:
            picking_type = PickingType.search([('code', '=', 'incoming')], limit=1)
        return picking_type

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

        imported = updated = error = 0
        refs = [k for k in self.mapped('reference_nbr') if k]
        for ref in refs:
            receipt_lines = self.filtered(lambda l: l.reference_nbr == ref and l.import_state == 'pending')
            if not receipt_lines:
                continue
            first = receipt_lines[0]
            try:
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(f'Warehouse tidak ditemukan untuk code: {first.detail_warehouse_code or first.warehouse_code or "-"}')

                picking_type = self._find_delivery_picking_type(warehouse)
                if not picking_type:
                    raise UserError('Picking type delivery/outgoing tidak ditemukan.')

                dest_location = self._find_location(first, warehouse)
                if not dest_location:
                    raise UserError(f'Location tujuan tidak ditemukan untuk code: {first.location_code or "-"}')

                vals = {
                    'origin': first.reference_nbr,
                    'picking_type_id': picking_type.id,
                    'location_id': picking_type.default_location_src_id.id if picking_type.default_location_src_id else (warehouse.lot_stock_id.id if warehouse else self.env.ref('stock.stock_location_stock').id),
                    'location_dest_id': dest_location.id if dest_location else (picking_type.default_location_dest_id.id if picking_type.default_location_dest_id else warehouse.lot_stock_id.id),
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.header_description or False,

                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.transfer_type or False,
                    'adt_external_ref': first.external_ref or False,
                }

                picking = Picking.search([('origin', '=', first.reference_nbr)], limit=1)
                if picking:
                    if picking.state in ('done', 'cancel'):
                        raise UserError(f'Receipt {first.reference_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
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
                    qty = self._parse_float(line.product_uom_qty)
                    move_name = line.description or product.display_name
                    move_dest = self._find_location(line, warehouse) or dest_location or picking.location_dest_id

                    existing = Move.search([
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', product.id),
                        ('name', '=', move_name),
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
                        'name': move_name,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': uom.id if uom else product.uom_id.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': move_dest.id,
                        'description_picking': line.description or False,

                        'adt_inventory_id': line.line_note or False,
                        'adt_line_nbr': line.line_nbr or False,
                        'adt_line_type': line.line_description or False,
                        'adt_open_qty': self._parse_float(line.open_qty),
                        'adt_order_qty': self._parse_float(line.order_qty),
                        'adt_uom_code': line.uom_code or False,
                        'adt_warehouse_dest_code': line.warehouse_code or False,
                        'adt_type': first.transfer_type or False,
                    })
                    line.write({
                        'import_state': action_state,
                        'import_message': f'{action_state.title()}: {picking.name}',
                        'odoo_picking_id': picking.id,
                    })
            except Exception as e:
                _logger.exception('Error import inventory recieved %s', ref)
                receipt_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
                error += len(receipt_lines)

        msg = f'Import selesai: {imported} delivery dibuat, {updated} delivery diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Recieved to Delivery Order',
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
            raise UserError('Belum diimport, belum ada delivery order di Odoo.')
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
