
import logging
from dateutil import parser as dateutil_parser
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaIssueConfig(models.Model):
    _name = 'acumatica.issue.config'
    _description = 'Konfigurasi Koneksi Acumatica - Issue Change Item'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Issue Change Item')
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
    odata_filter = fields.Char(default="Type eq 'Issue' and Operation eq 'Issue'")

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

    def fetch_issue_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
        self.ensure_one()
        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/{self.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.odata_expand:
                params['$expand'] = self.odata_expand
            if self.odata_select:
                params['$select'] = self.odata_select
            if reference_nbr:
                filters.append(f"ReferenceNbr eq '{reference_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            if odata_filter:
                filters.append(f"({odata_filter})")
            # elif self.odata_filter:
            #     filters.append(f"({self.odata_filter})")

            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Issue Change Item (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            print(f"Get Inventory Issue data from Acumatica: {len(raw_data)} records fetched with params: {params}")
            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'branch_warehouse': self._val(item, 'Branch'),
                    'actual_amount': self._val(item, 'ControlAmount'),
                    'actual_qty': self._val(item, 'ControlQty'),
                    'scheduled_date': self._val(item, 'Date'),
                    'description': self._val(item, 'Description'),
                    'external_ref': self._val(item, 'ExternalRef'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'status': self._val(item, 'Status'),
                    'total_amount': self._val(item, 'TotalAmount'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'trans_type': self._val(item, 'TransType') or self._val(item, 'Type'),
                }
                print(f" Get data : {header['reference_nbr']}, Trans Type: {header['trans_type']}, Status: {header['status']}")


                details = item.get('Details') or item.get('details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    result.append(dict(header, line_nbr='0'))
                    continue

                for detail in details:
                    line_nbr = self._val(detail, 'LineNumber') or self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    result.append({
                        **header,
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'branch_warehouse': self._val(detail, 'Branch'),
                        'line_description': self._val(detail, 'Description'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'location_code': self._val(detail, 'Location'),
                        'product_uom_qty': self._val(detail, 'Qty'),
                        'line_trans_type': self._val(detail, 'TranType'),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_code': self._val(detail, 'WarehouseID'),
                    })

            _logger.info('Berhasil ambil %s rows Issue Change Item dari Acumatica', len(result))
            self.last_sync = fields.Datetime.now()
            return result
        finally:
            self._do_logout(session)

class AcumaticaIssueLine(models.Model):
    _name = 'acumatica.issue.line'
    _description = 'Data Issue Change Item dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

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

    config_id = fields.Many2one('acumatica.issue.config', string='Konfigurasi', readonly=True, ondelete='cascade')
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
        keys = [k for k in self.mapped('reference_nbr') if k]

        for issue_key in keys:
            issue_lines = self.filtered(lambda l: l.reference_nbr == issue_key and l.import_state == 'pending')
            if not issue_lines:
                continue
            first = issue_lines[0]
            try:
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'outgoing'),
                ], limit=1) or PickingType.search([('code', '=', 'outgoing')], limit=1)
                if not picking_type:
                    raise UserError('Picking type Delivery Order tidak ditemukan.')

                source_location = warehouse.lot_stock_id or picking_type.default_location_src_id
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
                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.trans_type or False,
                    # 'adt_warehouse_code': first.warehouse_code or False,
                    'adt_external_id': first.external_id or False,
                    'adt_external_ref': first.external_ref or False,
                }
                print(f" Type: {vals['adt_type']}, Reference: {vals['origin']}, Scheduled: {vals['scheduled_date']}")

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

                for line in issue_lines:
                    product = self._find_product(line)
                    uom = self._find_uom(line, product)
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
            except Exception as e:
                _logger.exception('Error import issue %s', issue_key)
                issue_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
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
