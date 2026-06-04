import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaTransferShipmentLine(models.Model):
    _name = 'acumatica.transfer.shipment.line'
    _description = 'Data Transfer Shipment dari Acumatica'
    _order = 'shipment_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)
    line_row_number = fields.Char(string='Row Number Detail', readonly=True)

    shipment_nbr = fields.Char(string='Shipment Number', readonly=True, index=True)
    partner_code = fields.Char(string='CustomerID', readonly=True)
    description = fields.Char(string='Description Header', readonly=True)
    fob_point = fields.Char(string='FOB Point', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    is_insurance = fields.Char(string='Insurance', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    header_location_code = fields.Char(string='Location Header', readonly=True)
    operation = fields.Char(string='Operation', readonly=True)
    package_count = fields.Char(string='Package Count', readonly=True)
    package_weight = fields.Char(string='Package Weight', readonly=True)
    is_picked = fields.Char(string='Picked', readonly=True)
    scheduled_date = fields.Char(string='Shipment Date', readonly=True)
    shipped_qty = fields.Char(string='Shipped Qty Header', readonly=True)
    shipped_volume = fields.Char(string='Shipped Volume', readonly=True)
    shipped_weight = fields.Char(string='Shipped Weight', readonly=True)
    shipping_terms = fields.Char(string='Shipping Terms', readonly=True)
    shipping_zone = fields.Char(string='Shipping Zone', readonly=True)
    ship_via = fields.Char(string='Ship Via', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    warehouse_dest_code = fields.Char(string='To Warehouse', readonly=True)
    shipment_type = fields.Char(string='Type', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    is_unlimited_packages = fields.Char(string='Unlimited Packages', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)

    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    line_description = fields.Char(string='Description Detail', readonly=True)
    is_free_item = fields.Char(string='Free Item', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    location_dest_code = fields.Char(string='LocationID', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    order_line_number = fields.Char(string='Order Line Nbr', readonly=True)
    order_number = fields.Char(string='Order Number', readonly=True, index=True)
    order_type = fields.Char(string='Order Type', readonly=True)
    original_qty = fields.Char(string='Original Qty', readonly=True)
    product_uom_qty = fields.Char(string='Shipped Qty Detail', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    line_warehouse_code = fields.Char(string='Warehouse Detail', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Picking di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.transfer.shipment.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    receipt_type = fields.Char(string='Receipt Type', readonly=True)

    @api.depends('shipment_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.shipment_nbr and Picking.search_count([('origin', '=', rec.shipment_nbr)]))

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
        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)
        if not product:
            product = Product.create({
                'name': line.line_description or line.inventory_id or 'Unknown Product',
                'default_code': line.inventory_id or False,
                'type': 'consu',
            })
        return product

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line.partner_code:
            partner = Partner.search([('ref', '=', line.partner_code)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.partner_code)], limit=1)
        return partner

    def _find_warehouse_by_code(self, code):
        Warehouse = self.env['stock.warehouse']
        if not code:
            return Warehouse.search([], limit=1)
        warehouse = Warehouse.search([('code', '=', code)], limit=1)
        if not warehouse:
            warehouse = Warehouse.search([('name', '=', code)], limit=1)
        return warehouse

    def _find_location(self, code, warehouse=False, fallback_field='lot_stock_id'):
        Location = self.env['stock.location']
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse and hasattr(warehouse, fallback_field):
            location = getattr(warehouse, fallback_field)
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
        shipment_keys = [k for k in self.mapped('shipment_nbr') if k]

        for shipment_key in shipment_keys:
            shipment_lines = self.filtered(lambda l: l.shipment_nbr == shipment_key and l.import_state == 'pending')
            if not shipment_lines:
                continue
            first = shipment_lines[0]
            try:
                source_wh = self._find_warehouse_by_code(first.warehouse_code or first.line_warehouse_code)
                dest_wh = self._find_warehouse_by_code(first.warehouse_dest_code)
                if not source_wh:
                    raise UserError(f'Warehouse asal tidak ditemukan untuk code: {first.warehouse_code or first.line_warehouse_code or "-"}')

                picking_type = PickingType.search([
                    ('warehouse_id', '=', source_wh.id),
                    ('code', '=', 'outgoing'),
                ], limit=1) or PickingType.search([('code', '=', 'outgoing')], limit=1)
                if not picking_type:
                    raise UserError('Picking type outgoing tidak ditemukan.')

                src_location = self._find_location(first.header_location_code, source_wh, 'lot_stock_id') or (picking_type.default_location_src_id or source_wh.lot_stock_id)
                dest_location = False
                if dest_wh:
                    dest_location = dest_wh.lot_stock_id
                if not dest_location:
                    dest_location = self._find_location(first.location_dest_code, source_wh, 'lot_stock_id')
                dest_location = dest_location or picking_type.default_location_dest_id or source_wh.lot_stock_id

                vals = {
                    'origin': first.shipment_nbr,
                    'partner_id': self._find_partner(first).id if self._find_partner(first) else False,
                    'picking_type_id': picking_type.id,
                    'location_id': src_location.id,
                    'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,

                    'adt_type': first.receipt_type or False,
                }

                picking = Picking.search([('origin', '=', first.shipment_nbr)], limit=1)
                if picking:
                    if picking.state in ('done', 'cancel'):
                        raise UserError(f'Transfer shipment {first.shipment_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1

                for line in shipment_lines:
                    product = self._find_product(line)
                    uom = self._find_uom(line, product)
                    line_dest = dest_wh.lot_stock_id if dest_wh else False
                    if not line_dest:
                        line_dest = self._find_location(line.location_dest_code, source_wh, 'lot_stock_id') or dest_location
                    qty = self._parse_float(line.product_uom_qty)

                    existing = Move.search([
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', product.id),
                        ('name', '=', line.line_description or product.display_name),
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
                        'name': line.line_description or product.display_name,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': uom.id if uom else product.uom_id.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': line_dest.id if line_dest else picking.location_dest_id.id,
                        'description_picking': line.line_description or False,
                    })
                    line.write({
                        'import_state': action_state,
                        'import_message': f'{action_state.title()}: {picking.name}',
                        'odoo_picking_id': picking.id,
                    })
            except Exception as e:
                _logger.exception('Error import transfer shipment %s', shipment_key)
                shipment_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
                error += len(shipment_lines)

        msg = f'Import selesai: {imported} transfer dibuat, {updated} transfer diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Transfer Shipment',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})
