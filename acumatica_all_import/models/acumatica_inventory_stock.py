import json
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class AcumaticaInventoryStockConfig(models.Model):
    _name = 'acumatica.inventory.stock.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Stock'
    _rec_name = 'name'

    name = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica Inventory Stock')
    base_url = fields.Char(string='Base URL', required=True, default='http://staging.aditya.group/acumportal/entity')
    api_version = fields.Char(string='API Version', required=True, default='25.200.002')
    username = fields.Char(string='Username', required=True, default='wms')
    password = fields.Char(string='Password', required=True)
    company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
    endpoint_name = fields.Char(string='Endpoint Name', required=True, default='InventorySiteInquiry')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)

    odata_expand = fields.Char(string='OData Expand', default='InventorySiteInquiryDetails')
    odata_top = fields.Integer(string='OData Top', default=1)
    request_warehouse_value = fields.Char(string='Warehouse', default='WH33-FG')
    request_inventory_id_value = fields.Char(string='InventoryID')

    @property
    def api_url(self):
        return f"{self.base_url}/wms/{self.api_version}"

    @property
    def login_url(self):
        return f"{self.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.base_url}/auth/logout"

    def action_test_connection(self):
        self.ensure_one()
        try:
            session = self._do_login()
            self._do_logout(session)
            self.state = 'connected'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Koneksi Berhasil',
                    'message': f'Berhasil terhubung ke Acumatica ({self.base_url})',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    def _do_login(self):
        self.ensure_one()
        try:
            session = requests.Session()
            response = session.post(
                self.login_url,
                json={
                    'name': self.username,
                    'password': self.password,
                    'company': self.company_code,
                },
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )
            if response.status_code == 204:
                return session
            raise UserError(f'Login gagal (HTTP {response.status_code}): {response.text}')
        except requests.exceptions.ConnectionError:
            raise UserError(f'Tidak bisa terhubung ke server: {self.base_url}')
        except requests.exceptions.Timeout:
            raise UserError('Koneksi timeout. Periksa URL server.')

    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
            return [payload]
        return []

    def _build_request_body(self, warehouse=None, inventory_id=None):
        body = {
            'Warehouse': {'value': warehouse if warehouse is not None else self.request_warehouse_value or ''},
            'InventoryID': {'value': inventory_id if inventory_id is not None else self.request_inventory_id_value or ''},
        }
        return body

    @staticmethod
    def _parse_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0


class AcumaticaInventoryStockLine(models.Model):
    _name = 'acumatica.inventory.stock.line'
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
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status Import', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)

    odoo_product_id = fields.Many2one('product.product', string='Product Odoo', readonly=True)
    odoo_location_id = fields.Many2one('stock.location', string='Location Odoo', readonly=True)
    odoo_on_hand = fields.Float(string='On Hand Odoo', readonly=True)
    match_status = fields.Selection([
        ('match', 'Match'),
        ('not_match', 'Not Match'),
        ('missing_product', 'Missing Product'),
        ('missing_location', 'Missing Location'),
        ('error', 'Error'),
    ], string='Match Status', compute='_compute_stock_snapshot', store=False)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_stock_snapshot', store=False)

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
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})

    def action_reset_pending(self):
        self.filtered(lambda line: line.import_state in ('updated', 'error')).write({
            'import_state': 'pending',
            'import_message': False,
        })

    def action_import_selected(self):
        lines = self.filtered(lambda line: line.selected and line.import_state in ('pending', 'error'))
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

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

    def _do_import(self):
        Quant = self.env['stock.quant'].sudo()
        imported = 0
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
                    message = (
                        f"Updated: {product.display_name} @ {location.display_name} | "
                        f"old={current_qty} new={target_qty}"
                    )
                    updated += 1
                else:
                    action_state = 'imported'
                    message = (
                        f"Already match: {product.display_name} @ {location.display_name} | "
                        f"old={current_qty} new={target_qty}"
                    )
                    imported += 1

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
            except Exception as e:
                _logger.exception('Error import Inventory Stock line %s', line.id)
                line.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Stock',
                'message': f'Import selesai: {imported} berhasil, {updated} diupdate, {error} error.',
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }
