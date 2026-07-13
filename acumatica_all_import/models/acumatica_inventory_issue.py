import logging
from collections import defaultdict
from dateutil import parser as dateutil_parser
import requests

from odoo import fields, models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaInventoryIssueConfig(models.Model):
    _name = 'acumatica.inventory.issue.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Issue'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Inventory Issue')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.002')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
    endpoint_name = fields.Char(required=True, default='Shipment')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], default='draft', readonly=True)

    odata_expand = fields.Char(default='Details')
    odata_select = fields.Char()
    odata_filter = fields.Char()

    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------

    def _do_login(self):
        self.ensure_one()
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

    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass




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
                    'message': f'Berhasil terhubung ke {self.base_url}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')


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
        return []


class AcumaticaInventoryIssueLine(models.Model):
    _name = 'acumatica.inventory.issue.line'
    _description = 'Data Inventory Inventory Issue dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])

    product_line_ids = fields.One2many(
        'acumatica.inventory.issue.product',  # Model tujuan (detail)
        'receipt_line_id',             # Field Many2one yang ada di model detail
        string='Product Lines'
    )

    reference_nbr = fields.Char(string='Reference Number', readonly=True, index=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    description = fields.Char(string='Header Description', readonly=True)
    external_ref = fields.Char(string='External Ref', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    actual_amount = fields.Char(string='Control Amount', readonly=True)
    total_amount = fields.Char(string='Total Amount', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    trans_type = fields.Char(string='Trans Type', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)

    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    line_description = fields.Char(string='Description', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    location_code = fields.Char(string='Location', readonly=True)
    product_uom_qty = fields.Char(string='Qty', readonly=True)
    line_trans_type = fields.Char(string='Line Trans Type', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Delivery Order di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)
    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        print(f"Product to search: {line.inventory_id}")
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)

        print(f"Product to create: {product}")
        return product


    def _find_warehouse(self, line):
        # print(f"Line: {line}")
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False

        code = line.warehouse_code 
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', code)], limit=1)
            else:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    
            # else:
            #     warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location(self, code, warehouse=False, fallback='src'):
        Location = self.env['stock.location']
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        # if not location and warehouse:
        #     location = warehouse.lot_stock_id
        if not location and fallback == 'customer':
            location = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom
    
    def action_import_this(self):
        """Memicu proses impor khusus untuk 1 record aktif"""
        self.ensure_one()
        return self._do_import()


    def _do_import(self):
        print('Starting import for Inventory Issue with reference_nbr in:', self.mapped('reference_nbr'))
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        
        imported = updated = error = 0
        
        # Mengelompokkan lines berdasarkan reference_nbr untuk menghindari filtered() berulang
        lines_by_reference = defaultdict(lambda: self.env[self._name])
        for line in self:
            if line.reference_nbr and line.import_state == 'pending':
                lines_by_reference[line.reference_nbr] |= line

        for issue_key, issue_lines in lines_by_reference.items():
            print(f'Processing Inventory Issue with reference_nbr: {issue_key}')
            
            if not issue_lines:
                continue
                
            first = issue_lines[0]
            # print(f"value :{first}")
            
            try:
                # === PENTING: Buat Savepoint sebelum memproses satu issue_key ===
                # Jika terjadi error di dalam try ini, kita hanya me-rollback data untuk issue_key ini saja.
                self.env.cr.execute('SAVEPOINT import_issue_line')

                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')
                    
                picking_type = first.picking_type_id
                if not picking_type:
                    raise UserError('Picking type Delivery Order tidak ditemukan.')
                    
                source_location = picking_type.default_location_src_id
                dest_location = picking_type.default_location_dest_id or self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
                
                if not source_location:
                    raise UserError('Source location warehouse tidak ditemukan.')
                if not dest_location:
                    raise UserError('Destination location customer tidak ditemukan.')
                    
                vals = {
                    'origin': first.reference_nbr,
                    'picking_type_id': picking_type.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,
                    'adt_receipt_nbr': first.reference_nbr or False,
                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_int(first.total_qty),
                    'adt_warehouse_code': first.warehouse_code or False,
                    'adt_external_id': first.external_id or False,
                    'adt_type': first.trans_type or False,
                }
                
                picking = Picking.search([('origin', '=', first.reference_nbr)], limit=1)
                
                if picking:
                    if picking.state in ('done', 'cancel'):
                        raise UserError(f'Delivery Order {first.reference_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1

                to_create_move = self.env['acumatica.inventory.issue.product'].search([('receipt_line_id', '=', first.id)])
                    
                for line in to_create_move:
                    # print(line)
                    product = self._find_product(line)
                    uom = self._find_uom(line, product)
                    qty = self._parse_int(line.product_uom_qty)
                    print(f"Qty value before: {line.product_uom_qty} and after: {qty}")
                    
                    existing_move = Move.search([
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', product.id),
                    ], limit=1)
                    
                    if existing_move:
                        existing_move.write({
                            'product_uom_qty': qty,
                            'name': line.line_description or product.display_name,
                        })
                        first.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name} (move updated)',
                            'odoo_picking_id': picking.id,
                        })
                    else:
                        Move.create({
                            'name': line.line_description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': source_location.id,
                            'location_dest_id': dest_location.id,
                            'description_picking': line.line_description or False,
                        })
                        first.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name}',
                            'odoo_picking_id': picking.id,
                        })

                # === PENTING: Release Savepoint & Commit Data Sukses ===
                self.env.cr.execute('RELEASE SAVEPOINT import_issue_line')
                self.env.cr.commit()  # Mengunci data yang sukses ke database agar tidak hilang jika loop berikutnya error
                        
            except Exception as e:
                # === PENTING: Rollback hanya untuk baris yang error saja ===
                self.env.cr.execute('ROLLBACK TO SAVEPOINT import_issue_line')
                
                _logger.exception('Error import issue %s', issue_key)
                
                # Tulis pesan error ke object line (lalu commit status errornya agar tersimpan)
                issue_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
                self.env.cr.commit() 
                
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
            return int(float(value or 0))
        except Exception:
            return 0.0


# Unknown

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        print('Starting import for Inventory Issue with reference_nbr in:', self.mapped('reference_nbr'))
        self.ensure_one()
        return self._do_import()


    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

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


class AcumaticaInventoryIssueProduct(models.Model):
    _name = 'acumatica.inventory.issue.product'
    _description = 'Data Inventory Inventory Issue dari Acumatica'
    _order = 'line_nbr asc, id asc'

    receipt_line_id = fields.Many2one(
        'acumatica.inventory.issue.line',
        string='Receipt Header',
        required=True,
        ondelete='cascade',
        index=True,
    )

    line_external_id = fields.Char(string='UUID Detail', readonly=True)
    line_note = fields.Char(string='Detail Note', readonly=True)
    branch_warehouse = fields.Char(string='Warehouse Branch', readonly=True)
    line_description = fields.Char(string='Product Description', readonly=True)
    inventory_id = fields.Char(string='UUID Product', readonly=True)
    line_nbr = fields.Char(string='Product line number', readonly=True)
    location_code = fields.Char(string='Product Location', readonly=True)
    product_uom_qty = fields.Char(string='UOM Quantity', readonly=True)
    line_trans_type = fields.Char(string='Product Trans Type', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    warehouse_code = fields.Char(string='Product Warehouse', readonly=True)
    header_external_id = fields.Char(string='UUID Header', readonly=True)