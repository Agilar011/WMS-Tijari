
import logging
from dateutil import parser as dateutil_parser
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaIssueLine(models.Model):
    _name = 'acumatica.issue.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Issue Change Item dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    def _adt_picking_type_wizard_call(self):
        return (
            'import.issue.wizard',
            ({'WarehouseID': self.warehouse_code, 'DocumentOnly': self.document_only},),
            {},
        )

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header')
    line_external_id = fields.Char(string='UUID Line')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')
    # product_line_ids = fields.Many2one('acumatica.issue.line', string='Issue Header', ondelete='cascade')
    product_line_ids = fields.One2many(
        'acumatica.issue.line.product',  # Model tujuan (detail)
        'issue_shipment_id',             # Field Many2one yang ada di model detail
        string='Product Lines'
    )


    reference_nbr = fields.Char(string='Reference Number', index=True)
    scheduled_date = fields.Char(string='Date')
    description = fields.Char(string='Header Description')
    external_ref = fields.Char(string='External Ref')
    document_only = fields.Boolean(string='Document Only')
    status = fields.Char(string='Status')
    actual_qty = fields.Char(string='Control Qty')
    total_qty = fields.Char(string='Total Qty')
    actual_amount = fields.Char(string='Control Amount')
    total_amount = fields.Char(string='Total Amount')
    post_period = fields.Char(string='Post Period')
    acumatica_write_date = fields.Char(string='Last Modified')
    trans_type = fields.Char(string='Trans Type')
    note = fields.Text(string='Header Note')
    customer_id = fields.Char(string='Customer ID')
    customer_name = fields.Char(string='Customer Name')

    line_nbr = fields.Char(string='Line Nbr')
    line_description = fields.Char(string='Description')
    inventory_id = fields.Char(string='InventoryID')
    location_code = fields.Char(string='Location')
    product_uom_qty = fields.Char(string='Qty')
    line_trans_type = fields.Char(string='Line Trans Type')
    uom_code = fields.Char(string='UOM')
    warehouse_code = fields.Char(string='Warehouse')
    branch_warehouse = fields.Char(string='Branch')
    line_note = fields.Text(string='Line Note')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged')
    import_message = fields.Char(string='Generation Message')
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync')
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
    def _parse_int(value):
        try:
            return int(value or 0)
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

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        code = line.warehouse_code
        warehouse = False
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', code)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location(self, code, warehouse=False, fallback='src'):
        Location = self.env['stock.location']
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

    def _find_partner(self, customer_code):
        if not customer_code:
            return self.env['res.partner']
        Partner = self.env['res.partner']
        return Partner.search([
            '|',
            ('adt_b_account_id', '=', customer_code),
            ('company_registry', '=', customer_code),
        ], limit=1) or Partner.search([('name', '=', customer_code)], limit=1)

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
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

    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = updated = error = 0
        keys = [k for k in self.mapped('reference_nbr') if k]

        for issue_key in keys:
            issue_lines = self.filtered(lambda l: l.reference_nbr == issue_key and l.import_state == 'staged')
            if not issue_lines:
                continue
            first = issue_lines[0]
            try:
                self.env.cr.execute('SAVEPOINT import_issue_change_item_doc')
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')

                picking_type = first._adt_reresolve_picking_type()
                # picking_type = PickingType.search([
                #     ('warehouse_id', '=', warehouse.id),
                #     ('code', '=', 'outgoing'),
                # ], limit=1) or PickingType.search([('code', '=', 'outgoing')], limit=1)
                if not picking_type:
                    raise UserError('Picking type Delivery Order tidak ditemukan.')

                source_location = warehouse.lot_stock_id or picking_type.default_location_src_id
                dest_location = picking_type.default_location_dest_id
                if not source_location:
                    raise UserError('Source location warehouse tidak ditemukan.')
                if not dest_location:
                    raise UserError('Destination location tidak ditemukan.')
                if dest_location.usage == 'customer':
                    raise UserError('Destination location customer hanya boleh dipakai oleh SO Shipment.')

                partner = self._find_partner(first.customer_id)

                vals = {
                    'origin': first.reference_nbr,
                    'partner_id': partner.id if partner else False,
                    'picking_type_id': picking_type.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,

                    'adt_receipt_nbr': first.reference_nbr or False,
                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_actual_qty': self._parse_int(first.actual_qty),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_total_qty': self._parse_int(first.total_qty),
                    'adt_type': first.trans_type or False,
                    # 'adt_warehouse_code': first.warehouse_code or False,
                    'adt_external_id': first.external_id or False,
                    'adt_external_ref': first.external_ref or False,
                }
                print(f" Type: {vals['adt_type']}, Reference: {vals['origin']}, Scheduled: {vals['scheduled_date']}")

                picking = Picking.search([('origin', '=', first.reference_nbr)], limit=1)
                if picking:
                    if picking.state != 'draft':
                        raise UserError(f'Delivery Order {first.reference_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                    self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=issue_key)
                else:
                    picking = Picking.create(vals)
                    action_state = 'created'

                if action_state == 'updated':
                    picking.move_ids.unlink()
                    imported += 1

                for line in issue_lines:
                    product = self._find_product(line)
                    if not product:
                        raise UserError(f"Product tidak ditemukan untuk InventoryID: {line.inventory_id or '-'}")
                    uom = self._find_uom(line, product)
                    qty = self._parse_int(line.product_uom_qty)

                    Move.create({
                        'name': line.line_description or product.display_name,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': uom.id if uom else product.uom_id.id,
                        'location_id': source_location.id,
                        'location_dest_id': dest_location.id,
                        'description_picking': line.line_description or False,

                        'adt_line_external_id': line.line_external_id or False,
                        'adt_inventory_id': line.line_note or False,
                        'adt_line_nbr': line.branch_warehouse or False,
                        'adt_line_type': line.line_description or False,
                        'adt_uom_code': line.uom_code or False,
                        'adt_warehouse_dest_code': line.warehouse_code or False,
                        'adt_line_type': line.line_trans_type or False,

                    })
                    line.write({
                        'import_state': action_state,
                        'import_message': f'{action_state.title()}: {picking.name}',
                        'odoo_picking_id': picking.id,
                    })

                if issue_lines.filtered('document_only'):
                    picking.action_validate_document_only_import(force=True)
                self.env['acumatica.error.transaction']._handle_acumatica_error(issue_key, 'issue_change_item')
                self.env.cr.execute('RELEASE SAVEPOINT import_issue_change_item_doc')
            except Exception as e:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT import_issue_change_item_doc')
                _logger.exception('Error import issue %s', issue_key)
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='issue_change_item',
                    operation_type='delivery',
                    origin=issue_key,
                    location=first.warehouse_code or False,
                    location_dest=dest_location.display_name if 'dest_location' in locals() and dest_location else False,
                    scheduled_date=first.scheduled_date,
                    total_qty=first.total_qty,
                    actual_qty=first.actual_qty,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.inventory_id or False,
                        'product_name': line.line_description or False,
                        'qty': self._parse_int(line.product_uom_qty),
                        'uom': line.uom_code or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in issue_lines],
                )
                issue_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                    'odoo_picking_id': False,
                })
                error += len(issue_lines)

        msg = f'Import selesai: {imported} delivery dibuat, {updated} delivery diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Delivery Order',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if not self.odoo_picking_id:
            raise UserError('Belum ada picking Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

class AcumaticaIssueLineProduct(models.Model):
    _name = 'acumatica.issue.line.product'
    _description = 'Data Issue Change Item dari Acumatica'
    _order = 'line_number asc, id asc' 
    
    issue_shipment_id = fields.Many2one('acumatica.issue.line', string='Issue Shipment', ondelete='cascade', index=True)
    line_external_id = fields.Char(string='UUID Line')

    note = fields.Text(string='Header Note')
    branch = fields.Text(string='Branch Warehouse')
    description = fields.Char(string='Header Description')
    inventory_id = fields.Char(string='InventoryID')
    line_number = fields.Integer(string='No')
    location_code = fields.Char(string='Location')
    note_id = fields.Char(string='Note ID')
    product_uom_qty = fields.Char(string='Qty')
    trans_type = fields.Char(string='Trans Type')
    uom_code = fields.Char(string='UOM')
    external_id = fields.Char(string='UUID Header')
    warehouse_code = fields.Char(string='Warehouse')
