import json
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero
from markupsafe import Markup, escape

_logger = logging.getLogger(__name__)


class AcumaticaInventoryStockLine(models.Model):
    _name = 'acumatica.inventory.stock.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Inventory Stock dari Acumatica'
    _order = 'warehouse_code asc, inventory_id asc, id asc'

    external_id = fields.Char(string='UUID Header Acumatica', readonly=True, index=True)
    row_number = fields.Integer(string='No', readonly=True)
    line_external_id = fields.Char(string='UUID Line Acumatica', readonly=True, index=True)
    line_row_number = fields.Integer(string='Line No', readonly=True)

    warehouse_code = fields.Char(string='Warehouse Code', readonly=True, index=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True, index=True)
    description = fields.Char(string='Description', readonly=True)
    branch = fields.Char(string='Branch', readonly=True)
    item_status = fields.Char(string='Item Status', readonly=True)
    kode_barang_dan_jasa = fields.Char(string='Kode Barang dan Jasa', readonly=True)
    product_group = fields.Char(string='Product Group', readonly=True)
    available = fields.Float(string='Available (API)', readonly=True)
    on_hand_acumatica = fields.Float(string='On Hand Acumatica', readonly=True)
    note = fields.Text(string='Note', readonly=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    selected = fields.Boolean(string='Pilih', default=True)
    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status Import', default='staged', readonly=True)
    import_message = fields.Char(string='Generation Message', readonly=True)

    odoo_product_id = fields.Many2one('product.product', string='Document Reference', readonly=True)
    odoo_location_id = fields.Many2one('stock.location', string='Document Reference', readonly=True)
    odoo_on_hand = fields.Float(string='On Hand Odoo', readonly=True)
    match_status = fields.Selection([
        ('match', 'Match'),
        ('not_match', 'Not Match'),
        ('missing_product', 'Missing Product'),
        ('missing_location', 'Missing Location'),
        ('error', 'Error'),
    ], string='Match Status', compute='_compute_stock_snapshot', store=False)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_stock_snapshot', store=False)
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    @api.depends('inventory_id', 'warehouse_code', 'on_hand_acumatica')
    def _compute_stock_snapshot(self):
        Quant = self.env['stock.quant']
        WarehouseMap = self.env['stock.location.acumatica']
        Warehouse = self.env['stock.warehouse']
        Location = self.env['stock.location']
        Product = self.env['product.product']

        for rec in self:
            product = False
            location = False
            match_status = 'error'
            odoo_on_hand = 0.0

            if rec.inventory_id:
                product = Product.search([
                    '|',
                    ('default_code', '=', rec.inventory_id),
                    ('barcode', '=', rec.inventory_id),
                ], limit=1)
                if not product:
                    product = Product.search([('name', '=', rec.description)], limit=1) if rec.description else False

            if rec.warehouse_code:
                mapping = WarehouseMap.search([('code', '=', rec.warehouse_code)], limit=1)
                if mapping.odoo_location_id:
                    location = mapping.odoo_location_id
                elif mapping.odoo_building_id:
                    location = mapping.odoo_building_id.lot_stock_id

                if not location:
                    warehouse = Warehouse.search([('code', '=', rec.warehouse_code)], limit=1)
                    if warehouse:
                        location = warehouse.lot_stock_id

                if not location:
                    location = Location.search([
                        '|',
                        ('complete_name', '=', rec.warehouse_code),
                        ('name', '=', rec.warehouse_code),
                    ], limit=1)

            rec.odoo_product_id = product.id if product else False
            rec.odoo_location_id = location.id if location else False
            rec.exists_in_odoo = bool(product and location)

            if not product:
                rec.odoo_on_hand = 0.0
                rec.match_status = 'missing_product'
                continue
            if not location:
                rec.odoo_on_hand = 0.0
                rec.match_status = 'missing_location'
                continue

            try:
                odoo_on_hand = Quant._get_available_quantity(product, location, strict=False)
            except Exception:
                odoo_on_hand = 0.0

            rec.odoo_on_hand = odoo_on_hand
            precision = product.uom_id.rounding if product.uom_id else 0.01
            if float_compare(rec.on_hand_acumatica, odoo_on_hand, precision_rounding=precision) == 0:
                match_status = 'match'
            else:
                match_status = 'not_match'
            rec.match_status = match_status

    def action_select_all(self):
        self.search([('import_state', '=', 'staged')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})

    def action_reset_pending(self):
        self.filtered(lambda line: line.import_state in ('updated', 'error')).write({
            'import_state': 'staged',
            'import_message': False,
        })

    def action_import_selected(self):
        lines = self.filtered(lambda line: line.selected and line.import_state in ('staged', 'error'))
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

    def _find_product(self):
        self.ensure_one()
        Product = self.env['product.product']
        product = False
        if self.inventory_id:
            product = Product.search([
                '|',
                ('default_code', '=', self.inventory_id),
                ('barcode', '=', self.inventory_id),
            ], limit=1)
        if not product and self.description:
            product = Product.search([('name', '=', self.description)], limit=1)
        return product

    def _find_location(self):
        self.ensure_one()
        WarehouseMap = self.env['stock.location.acumatica']
        Warehouse = self.env['stock.warehouse']
        Location = self.env['stock.location']
        location = False

        if self.warehouse_code:
            mapping = WarehouseMap.search([('code', '=', self.warehouse_code)], limit=1)
            if mapping.odoo_location_id:
                location = mapping.odoo_location_id
            elif mapping.odoo_building_id:
                location = mapping.odoo_building_id.lot_stock_id

            if not location:
                warehouse = Warehouse.search([('code', '=', self.warehouse_code)], limit=1)
                if warehouse:
                    location = warehouse.lot_stock_id

            if not location:
                location = Location.search([
                    '|',
                    ('complete_name', '=', self.warehouse_code),
                    ('name', '=', self.warehouse_code),
                ], limit=1)

        return location

    def _sync_stock_quant_snapshot(self, product, location, on_hand_acumatica, status, message):
        Quant = self.env['stock.quant'].sudo()
        quant_domain = [
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
        ]
        quants = Quant.search(quant_domain)
        if quants:
            quants.write({
                'adt_inventory_stock_status': status,
                'adt_inventory_stock_message': message,
                'adt_inventory_stock_sync_date': fields.Datetime.now(),
            })

    def _handle_acumatica_error(self, err_msg=False):
        AcumaticaError = self.env['acumatica.error.master']
        acumatica_err_id = self.acumatica_err_id
        if not err_msg:
            if acumatica_err_id:
                acumatica_err_id.import_state = 'solved'
                return
            return

        state = 'error'
        if not acumatica_err_id:
            acumatica_err_id = AcumaticaError.create({
                'name': f'StockOnventory-{self.id}',
                'data_type': self._name,
                'import_state': state,
                'data_id': self.id,
                'error_msg': err_msg
            })
            self.acumatica_err_id = acumatica_err_id
            
        acumatica_err_id.error_msg = err_msg
        acumatica_err_id.import_state = state

    def _get_changed_fields(self, record, vals):
        changed_fields = []

        for field_name, new_value in vals.items():
            field = record._fields.get(field_name)

            if not field:
                continue

            old_value = record[field_name]

            # Normalisasi nilai
            old_value = old_value or False
            new_value = new_value or False

            if old_value != new_value:
                changed_fields.append({
                    'field_name': field_name,
                    'field_label': field.string,
                    'old_value': old_value,
                    'new_value': new_value,
                })

        return changed_fields
    
    def _log_import_result(
        self,
        state,
        message,
        record=False,
        changed_fields=None,
    ):
        titles = {
            'created': '✅ Import Berhasil',
            'updated': '🔄 Data Diperbarui',
            'error': '❌ Import Gagal',
        }

        body = Markup("""
            <p>
                <strong>{}</strong>
            </p>
            <p>{}</p>
        """).format(
            titles.get(state, 'Import Log'),
            message,
        )

        if changed_fields:
            body += Markup("""
                <p><strong>Perubahan:</strong></p>
                <ul>
            """)

            for change in changed_fields:
                old_value = change['old_value'] or '-'
                new_value = change['new_value'] or '-'

                body += Markup("""
                    <li>
                        <strong>{}</strong>:
                        {} → {}
                    </li>
                """).format(
                    escape(change['field_label']),
                    escape(str(old_value)),
                    escape(str(new_value)),
                )

            body += Markup("</ul>")

        if record:
            body += Markup("""
                <p>
                    Record Odoo:
                    <a href="#"
                    data-oe-model="{}"
                    data-oe-id="{}">
                        {}
                    </a>
                </p>
            """).format(
                escape(record._name),
                record.id,
                escape(record.display_name),
            )

        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
    
    def _do_import(self):
        Quant = self.env['stock.quant'].sudo()
        created = 0
        updated = 0
        error = 0

        for line in self:
            try:
                product = line._find_product()
                location = line._find_location()
                if not product:
                    raise UserError(f"Product {line.inventory_id or '-'} tidak ditemukan di Odoo.")
                if not location:
                    raise UserError(f"Warehouse {line.warehouse_code or '-'} tidak ditemukan di Odoo.")

                current_qty = Quant._get_available_quantity(product, location, strict=False)
                target_qty = line.on_hand_acumatica
                delta = target_qty - current_qty
                precision = product.uom_id.rounding if product.uom_id else 0.01
                _logger.info(
                    "Inventory Stock import %s / %s | old_on_hand=%.4f new_on_hand=%.4f delta=%.4f",
                    product.display_name,
                    location.display_name,
                    current_qty,
                    target_qty,
                    delta,
                )

                if not float_is_zero(delta, precision_rounding=precision):
                    Quant._update_available_quantity(product, location, delta)
                    action_state = 'updated'
                    self.env['acumatica.error.transaction']._handle_acumatica_update(
                        line,
                        origin=f"{line.inventory_id or '-'} / {line.warehouse_code or '-'}",
                    )
                    message = (
                        f"Updated: {product.display_name} @ {location.display_name} | "
                        f"old={current_qty} new={target_qty}"
                    )
                    line.message_post(
                        body=f"Updated: {product.display_name} @ {location.display_name} | \n old={current_qty} new={target_qty}",
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                    updated += 1
                else:
                    action_state = 'created'
                    message = (
                        f"Already match: {product.display_name} @ {location.display_name} | "
                        f"old={current_qty} new={target_qty}"
                    )
                    line.message_post(
                        body=f"Already match: {product.display_name} @ {location.display_name} | \n old={current_qty} new={target_qty}",
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                    if line.acumatica_err_id:
                        line.acumatica_err_id.import_state = 'resolved'
                    created += 1

                new_qty = Quant._get_available_quantity(product, location, strict=False)
                match_status = 'match' if float_compare(new_qty, target_qty, precision_rounding=precision) == 0 else 'not_match'
                self._sync_stock_quant_snapshot(product, location, target_qty, match_status, message)
                _logger.info(
                    "Inventory Stock import result %s / %s | old_on_hand=%.4f new_on_hand=%.4f target_on_hand=%.4f",
                    product.display_name,
                    location.display_name,
                    current_qty,
                    new_qty,
                    target_qty,
                )

                line.write({
                    'import_state': action_state,
                    'import_message': message,
                    'odoo_product_id': product.id,
                    'odoo_location_id': location.id,
                    'odoo_on_hand': new_qty,
                })
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    f"{line.inventory_id or '-'} / {line.warehouse_code or '-'}",
                    'inventory_stock',
                )
            except Exception as e:
                _logger.exception('Error import Inventory Stock line %s', line.id)
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    line,
                    [str(e)],
                    api_acumatica='inventory_stock',
                    operation_type='inventory',
                    origin=f"{line.inventory_id or '-'} / {line.warehouse_code or '-'}",
                    location=line.warehouse_code or False,
                    total_qty=line.on_hand_acumatica,
                    actual_qty=line.available,
                    payload={'line': line.read()[0] if line.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.inventory_id or False,
                        'product_name': line.description or False,
                        'qty': line.on_hand_acumatica,
                        'uom': False,
                        'payload': line.read()[0] if line.exists() else {},
                    }],
                )
                line.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                    'odoo_product_id': False,
                    'odoo_location_id': False,
                })

                error += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Stock',
                'message': f'Import selesai: {created} berhasil, {updated} diupdate, {error} error.',
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }
