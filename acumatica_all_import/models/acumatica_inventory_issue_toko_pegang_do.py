from dateutil import parser as dateutil_parser
import logging
import requests
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaInventoryIssueTokoPegangDOConfig(models.Model):
    _name = 'acumatica.inventory.issue.toko.pegang.do.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Receipt Import'
    _rec_name = 'name'

    name = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url = fields.Char(string='Base URL', required=True, default='http://staging.aditya.group/acumportal/entity')
    api_version = fields.Char(string='API Version', required=True, default='25.200.002')
    username = fields.Char(string='Username', required=True, default='wms')
    password = fields.Char(string='Password', required=True)
    company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
    endpoint_name = fields.Char(string='Endpoint Name', required=True, default='PurchaseReceipt')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)
    odata_expand = fields.Char(
        string='OData Expand',
        default='Details',
        help='Contoh: Details atau Details,OtherChild'
    )
    odata_select = fields.Char(
        string='OData Select',
        help='Optional: pilih field tertentu'
    )
    odata_filter = fields.Char(
        string='OData Filter',
        default="Type eq 'Return'"
    )

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
            if session:
                self._do_logout(session)
                self.state = 'connected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Koneksi Berhasil!',
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
                    "name": self.username,
                    "password": self.password,
                    "company": self.company_code
                },
                headers={"Content-Type": "application/json"},
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

    def _val(self, item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    def _normalize_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    def fetch_receipt_data(self, limit=50, offset=0, receipt_nbr=False, last_modified_from=False, odata_filter=False):
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
            if receipt_nbr:
                filters.append(f"ReceiptNbr eq '{receipt_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            if self.odata_filter:
                filters.append(f"({self.odata_filter})")
            else:
                filters.append("(Type eq 'Receipt')")

            if filters:
                params['$filter'] = ' and '.join(filters)       

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Inventory Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'branch_warehouse': self._val(item, 'Branch'),
                    'actual_qty': self._val(item, 'ControlQty'),
                    'scheduled_date': self._val(item, 'Date'),
                    'is_hold': self._val(item, 'Hold'),
                    'inventory_ref': self._val(item, 'InventoryRefNbr'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'Location'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'receipt_nbr': self._val(item, 'ReceiptNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'receipt_type': self._val(item, 'Type'),
                    'vendor_code': self._val(item, 'VendorID'),
                    'partner_ref': self._val(item, 'VendorRef'),
                    'warehouse_code': self._val(item, 'Warehouse'),
                }
                print(f" Get data : {header['receipt_nbr']}, Type: {header['receipt_type']}, Status: {header['status']}")           

                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    result.append(dict(header, line_nbr='0'))
                    continue

                for detail in details:
                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    description = self._val(detail, 'Description') or self._val(detail, 'TransactionDescription')
                    warehouse_dest_code = self._val(detail, 'Warehouse') or header.get('warehouse_code')

                    result.append({
                        **header,
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'description': description,
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'line_type': self._val(detail, 'LineType'),
                        'location_dest_code': self._val(detail, 'Location'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'product_uom_qty': self._val(detail, 'ReceiptQty'),
                        'transaction_description': self._val(detail, 'TransactionDescription'),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_dest_code': warehouse_dest_code,
                    })

            _logger.info("Berhasil ambil %s rows Inventory Receipt dari Acumatica", len(result))
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()


class AcumaticaInventoryIssueTokoPegangDO(models.Model):
    _name = 'acumatica.inventory.issue.toko.pegang.do.staging'
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'adt_ReferenceNbr asc, adt_rowNumber asc, id asc'

    adt_id = fields.Char(string="Acumatica id", readonly=True)
    adt_rowNumber = fields.Char(string="Acumatica rowNumber", readonly=True)
    adt_note = fields.Char(string="Acumatica note", readonly=True)
    adt_TransType = fields.Char(string="Acumatica TransType", readonly=True)
    adt_CreatedDateTime = fields.Char(string="Acumatica CreatedDateTime", readonly=True)
    adt_CustomerID = fields.Char(string="Acumatica CustomerID", readonly=True)
    adt_CustomerName = fields.Char(string="Acumatica CustomerName", readonly=True)
    adt_CustomerOrder = fields.Char(string="Acumatica CustomerOrder", readonly=True)
    adt_Date = fields.Char(string="Acumatica Date", readonly=True)
    adt_Description = fields.Char(string="Acumatica Description", readonly=True)
    adt_DueDate = fields.Char(string="Acumatica DueDate", readonly=True)
    adt_LastModifiedDateTime = fields.Char(string="Acumatica LastModifiedDateTime", readonly=True)
    adt_LocationID = fields.Char(string="Acumatica LocationID", readonly=True)
    adt_LocationName = fields.Char(string="Acumatica LocationName", readonly=True)
    adt_OrigRefNbr = fields.Char(string="Acumatica OrigRefNbr", readonly=True)
    adt_ReferenceNbr = fields.Char(string="Acumatica ReferenceNbr", readonly=True)
    adt_Status = fields.Char(string="Acumatica Status", readonly=True)
    adt_Type = fields.Char(string="Acumatica Type", readonly=True)
    adt_post_period = fields.Char(string="Acumatica PostPeriod", readonly=True)
    adt_document_only = fields.Boolean(string="Acumatica DocumentOnly", readonly=True)

    adt_ControlQty = fields.Float(string="Acumatica ControlQty", readonly=True)
    adt_ExternalRef = fields.Char(string="Acumatica ExternalRef", readonly=True)
    adt_NoteId = fields.Char(string="Acumatica NoteId", readonly=True)
    adt_TotalQty = fields.Float(string="Acumatica TotalQty", readonly=True)

    product_line_ids = fields.One2many('acumatica.inventory.issue.toko.pegang.do.staging.line', 'receipt_line_id', string='Lines')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])


    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('adt_ReferenceNbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.adt_ReferenceNbr and Picking.search_count([('origin', '=', rec.adt_ReferenceNbr)]))

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
            if not value:
                return 0
            # Konversi dulu ke float untuk menghilangkan tanda titik desimal, baru jadikan int
            return int(float(value))
        except Exception:
            return 0

    def _find_vendor(self, line):
        Partner = self.env['res.partner']
        vendor = False
        if line.adt_CustomerName:
            vendor = Partner.search([('ref', '=', line.adt_CustomerName), ('is_company', '=', True)], limit=1)
            if not vendor:
                vendor = Partner.search([('name', '=', line.adt_CustomerName), ('is_company', '=', True)], limit=1)
        return vendor

    # def _find_product(self, line):
    #     Product = self.env['product.product']
    #     product = False
    #     if line.inventory_id:
    #         product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
    #         if not product:
    #             product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
    #     if not product and line.transaction_description:
    #         product = Product.search([('name', '=', line.transaction_description)], limit=1)
    #     return product
    def _find_product(self, line):
        print(f"Finding product for line: {line}")
        Product = self.env['product.product']

        product = False

        if line.adt_InventoryID:
            product = Product.search([('default_code', '=', line.adt_InventoryID)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.adt_InventoryID)], limit=1)

        if not product and line.adt_TransactionDescription:
            product = Product.search([('name', '=', line.adt_TransactionDescription)], limit=1)

        if not product:
            name = line.adt_TransactionDescription or line.adt_InventoryID or 'Unknown Product'
            product = Product.search([('default_code', '=', line.adt_InventoryID)], limit=1)
            if not product:
                print("Product not found.")  # Debugging line to check if the method is called


        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        warehouse = False
        if line:
            warehouse = Warehouse.search([('code', '=', line)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', line)], limit=1)
            else:
                warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location_dest(self, line, warehouse=False):
        staging_line = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([
            ('receipt_line_id', '=', line.id)
        ], limit=1)

        Location = self.env['stock.location']
        location = False
        if staging_line.adt_Warehouse:
            location = Location.search([('complete_name', '=', staging_line.adt_Warehouse)], limit=1)
            if not location:
                location = Location.search([('name', '=', staging_line.adt_Warehouse)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        print(f"Finding location for staging line: {staging_line}, Found location: {location}")
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.adt_UOM:
            uom = Uom.search([('name', '=', line.adt_UOM)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        print(f"action_import_this called on {self}")
        self.ensure_one()
        return self._do_import()
    
    # def _do_import(self):
    #     Picking = self.env['stock.picking']
    #     Move = self.env['stock.move']
    #     PickingType = self.env['stock.picking.type']

    #     imported = 0
    #     updated = 0
    #     error = 0

    #     print(f"self: {self}")
    #     # raise UserError("Debug")

    #     # proses per receipt number
    #     for receipt_nbr in self.mapped('adt_ReferenceNbr'):
    #         receipt_lines = self.filtered(
    #             lambda l: l.adt_ReferenceNbr == receipt_nbr and l.import_state == 'pending'
    #         )
    #         if not receipt_lines:
    #             continue

    #         first = receipt_lines[0]

    #         try:
    #             vendor = self._find_vendor(first)

    #             if not vendor:
    #                 print(f"Vendor not found: {first.adt_CustomerName}")

    #             staging_line = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([
    #                 ('receipt_line_id', '=', first.id)
    #             ], limit=1)

    #             # Ambil nilai adt_Warehouse jika record-nya ditemukan agar tidak error (Safe-get)
    #             warehouse_code = staging_line.adt_Warehouse if staging_line else False
    #             branch_warehouse = staging_line.adt_Branch if staging_line else False
    #             warehouse = self._find_warehouse(warehouse_code)
    #             if not warehouse:
    #                 raise UserError(
    #                     f'Warehouse tidak ditemukan untuk code: {staging_line.adt_Warehouse or "-"}'
    #                 )

    #             # picking_type = PickingType.search([
    #             #     ('warehouse_id', '=', warehouse.id),
    #             #     ('code', '=', 'outgoing'),
    #             # ], limit=1) or PickingType.search([
    #             #     ('code', '=', 'outgoing')
    #             # ], limit=1)

    #             picking_type = first.picking_type_id

    #             if not picking_type:
    #                 raise UserError('Picking type outgoing tidak ditemukan.')

    #             dest_location = self._find_location_dest(first, warehouse)
    #             if not dest_location:
    #                 raise UserError(
    #                     f'Location tujuan tidak ditemukan untuk code: '
    #                     # f'{first.location_dest_code or first.header_location_code or "-"}'
    #                 )

    #             origin = first.adt_ReferenceNbr or False

    #             vals = {
    #                 'partner_id': vendor.id if vendor else False,
    #                 'picking_type_id': picking_type.id,
    #                 'location_id': (
    #                     picking_type.default_location_src_id.id
    #                     if picking_type.default_location_src_id
    #                     else self.env.ref('stock.stock_location_suppliers').id
    #                 ),
    #                 'location_dest_id': dest_location.id,
    #                 'scheduled_date': self._parse_dt(first.adt_Date),
    #                 'origin': origin,
    #                 'note': first.adt_note or False,

    #                 # field custom, kalau ada di model
    #                 'adt_receipt_nbr': first.adt_ReferenceNbr or False,
    #                 'adt_vendor_code': first.adt_CustomerName or False,
    #                 'adt_partner_ref': first.adt_LocationName or False,
    #                 'adt_branch_warehouse': branch_warehouse or False,
    #                 # 'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
    #                 # 'adt_inventory_ref': first.inventory_ref or False,
    #                 'adt_acumatica_write_date': self._parse_dt(first.adt_LastModifiedDateTime),
    #                 # 'adt_header_location_code': first.header_location_code or False,
    #                 # 'adt_post_period': first.post_period or False,
    #                 'adt_status': first.adt_Status or False,
    #                 # 'adt_total_qty': self._parse_int(first.total_qty),
    #                 'adt_type': first.adt_Type or False,
    #                 # 'adt_warehouse_code': first.adt_Type or False,
    #                 'adt_external_id': first.adt_id or False,
    #             }
    #             print(f"Get Issue PO Return data from Acumatica: Processing receipt {origin}, Status: {first.adt_Status}, Type : {first.adt_Type}, Picking Type: {picking_type.name}")

    #             # filter field yang bener-bener ada di stock.picking
    #             vals = {k: v for k, v in vals.items() if k in Picking._fields}

    #             # pakai origin buat dedup
    #             picking = Picking.search([('origin', '=', origin)], limit=1)

    #             if picking:
    #                 if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
    #                     raise UserError(
    #                         f'Receipt {receipt_nbr} sudah ada di Odoo dengan state '
    #                         f'{picking.state}, tidak bisa diupdate.'
    #                     )
    #                 picking.write(vals)
    #                 action_state = 'updated'
    #                 updated += 1
    #             else:
    #                 picking = Picking.create(vals)
    #                 # picking.action_confirm()
    #                 action_state = 'imported'
    #                 imported += 1

    #             # print(f"Line : {receipt_lines}")
    #             to_create_move = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([('receipt_line_id', '=', first.id)])

    #             for line in to_create_move:
    #                 try:
    #                     product = self._find_product(line)
    #                     if not product:
    #                         raise UserError(
    #                             f'Product tidak ditemukan untuk InventoryID: '
    #                             f'{line.inventory_id or "-"}'
    #                         )

    #                     uom = self._find_uom(line, product)
    #                     line_dest = self._find_location_dest(line, warehouse) or dest_location
    #                     qty = self._parse_int(line.adt_Qty)

    #                     # dedup move
    #                     move_domain = [('picking_id', '=', picking.id)]
    #                     if 'adt_line_external_id' in Move._fields and line.adt_external_id:
    #                         move_domain.append(('adt_line_external_id', '=', line.adt_external_id))
    #                     else:
    #                         move_domain += [
    #                             ('product_id', '=', product.id),
    #                             ('product_uom_qty', '=', qty),
    #                         ]

    #                     existing_move = Move.search(move_domain, limit=1)
    #                     if existing_move:
    #                         first.write({
    #                             # 'import_state': action_state,
    #                             'import_message': f'Skip duplicate: {picking.name}',
    #                             'odoo_picking_id': picking.id,
    #                         })
    #                         continue

    #                     move_vals = {
    #                         'name': line.adt_TransactionDescription or product.display_name,
    #                         'picking_id': picking.id,
    #                         'product_id': product.id,
    #                         'product_uom_qty': qty,
    #                         'product_uom': uom.id if uom else product.uom_id.id,
    #                         'location_id': picking.location_id.id,
    #                         'location_dest_id': line_dest.id,
    #                         'description_picking': line.adt_TransactionDescription or False,

    #                         'adt_line_external_id': line.adt_external_id or False,
    #                         'adt_inventory_id': line.adt_InventoryID or False,
    #                         'adt_line_nbr': line.adt_rowNumber or False,
    #                         'adt_open_qty': self._parse_int(line.adt_Qty),
    #                         'adt_order_qty': self._parse_int(line.adt_Qty),
    #                         'adt_uom_code': line.adt_UOM or False,
    #                         'adt_line_note': line.adt_note or False,
    #                     }

    #                     # filter field yang ada di stock.move
    #                     move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}
    #                     print(f"Move to created: {move_vals}")

    #                     # raise UserError('debug.')
    #                     Move.create(move_vals)

    #                     first.write({
    #                         'import_state': action_state,
    #                         'import_message': f'{action_state.title()}: {picking.name}',
    #                         'odoo_picking_id': picking.id,
    #                     })

    #                 except Exception as line_e:
    #                     _logger.exception("Error import line %s", line.id)
    #                     first.write({
    #                         'import_message': str(line_e)[:200],
    #                         'odoo_picking_id': picking.id if picking else False,
    #                     })
    #                     error += 1

    #         except Exception as e:
    #             _logger.exception("Error import receipt %s", receipt_nbr)
    #             receipt_lines.write({
    #                 'import_state': 'error',
    #                 'import_message': str(e)[:200],
    #             })
    #             error += len(receipt_lines)

    #             raise UserError(f'Error import receipt {receipt_nbr}: {str(e)}')

    #     msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
    #     # raise UserError('debug')
    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'display_notification',
    #         'params': {
    #             'title': 'Import Inventory Receipt',
    #             'message': msg,
    #             'type': 'success' if error == 0 else 'warning',
    #             'sticky': True,
    #         }
    #     }

    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = 0
        updated = 0
        error = 0

        print(f"self: {self}")

        # 1. Ambil seluruh data pending untuk referensi filtering
        staging_records = self.env['acumatica.inventory.issue.toko.pegang.do.staging'].search([
            ('import_state', '=', 'pending')
        ]).mapped('adt_ReferenceNbr')

        print(f"Staging to process: {staging_records}")

        picking_to_update = self.env['stock.picking'].search([
            ('state', '=', 'draft'),
            ('origin', 'in', staging_records)
        ]).mapped('origin')

        print(f"Picking To Update: {picking_to_update}")

        picking_to_skip = self.env['stock.picking'].search([
            ('state', '!=', 'draft'),
            ('origin', 'in', staging_records)
        ]).mapped('origin')
        
        print(f"Picking to skip: {picking_to_skip}")
        
        picking_to_create = set(staging_records) - set(picking_to_update) - set(picking_to_skip)
        print(f"Picking to create: {picking_to_create}")

        # PERULANGAN UTAMA PER DOKUMEN STAGING
        for first in self:
        
            # KOREKSI 1: Gunakan 'continue' (BUKAN return) agar dokumen lain tetap diproses
            if first.adt_ReferenceNbr not in picking_to_create:
                print(f"Receipt {first.adt_ReferenceNbr} dilewati karena statusnya masuk ke list update/skip.")
                continue

            try:
                # 2. BUNGKUS DENGAN SAVEPOINT: Jika error, rollback hanya terjadi pada dokumen aktif ini
                with self.env.cr.savepoint():
                    print(f"Processing receipt {first.adt_ReferenceNbr}")
                    vendor = self._find_vendor(first)
                    if not vendor:
                        print(f"Vendor not found: {first.adt_CustomerName}")

                    staging_line = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([
                        ('receipt_line_id', '=', first.id)
                    ], limit=1)

                    warehouse_code = staging_line.adt_Warehouse if staging_line else False
                    branch_warehouse = staging_line.adt_Branch if staging_line else False
                    warehouse = self._find_warehouse(warehouse_code)
                    if not warehouse:
                        raise UserError(
                            f'Warehouse tidak ditemukan untuk code: {staging_line.adt_Warehouse or "-"}'
                        )

                    picking_type = first.picking_type_id
                    if not picking_type:
                        raise UserError('Picking type outgoing tidak ditemukan.')

                    dest_location = self._find_location_dest(first, warehouse)
                    if not dest_location:
                        raise UserError(
                            f'Location tujuan tidak ditemukan untuk code: {warehouse_code or "-"}'
                        )
                    if dest_location.usage == 'customer':
                        raise UserError('Location tujuan customer hanya boleh dipakai oleh SO Shipment.')

                    origin = first.adt_ReferenceNbr or False

                    vals = {
                        'partner_id': vendor.id if vendor else False,
                        'picking_type_id': picking_type.id,
                        'location_id': (
                            picking_type.default_location_src_id.id
                            if picking_type.default_location_src_id
                            else self.env.ref('stock.stock_location_suppliers').id
                        ),
                        'location_dest_id': dest_location.id,
                        'scheduled_date': self._parse_dt(first.adt_Date),
                        'origin': origin,
                        'note': first.adt_note or False,
                        'adt_receipt_nbr': first.adt_ReferenceNbr or False,
                        'adt_vendor_code': first.adt_CustomerName or False,
                        'adt_partner_ref': first.adt_LocationName or False,
                        'adt_branch_warehouse': branch_warehouse or False,
                        'adt_acumatica_write_date': self._parse_dt(first.adt_LastModifiedDateTime),
                        'adt_status': first.adt_Status or False,
                        'adt_type': first.adt_Type or False,
                        'adt_external_id': first.adt_id or False,
                    }
                    
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}
                    
                    picking = Picking.create(vals)
                    action_state = 'imported'

                    to_create_move = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([
                        ('receipt_line_id', '=', first.id)
                    ])

                    print(f"Processing {len(to_create_move)} lines for receipt {first.adt_ReferenceNbr}")

                    # Inisialisasi list kosong sebelum loop lines dimulai
                    moves_to_create = []

                    print(f"Processing {len(to_create_move)} lines for receipt {first.adt_ReferenceNbr}")

                    # PERULANGAN LINES
                    for line in to_create_move:
                        product = self._find_product(line)
                        if not product:
                            # Jika produk tidak ketemu, raise error ini akan membatalkan (rollback) pembuatan picking!
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        line_dest = self._find_location_dest(line, warehouse) or picking.location_dest_id
                        if line_dest.usage == 'customer':
                            raise UserError('Location tujuan customer hanya boleh dipakai oleh SO Shipment.')
                        qty = self._parse_int(line.adt_Qty)
                        print(f"Quantity: {qty} for actual value: {line.adt_Qty}")

                        move_domain = [('picking_id', '=', picking.id)]
                        if 'adt_line_external_id' in Move._fields and line.adt_external_id:
                            move_domain.append(('adt_line_external_id', '=', line.adt_external_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('adt_line_nbr', '=', line.adt_rowNumber or False) 
                            ]

                        existing_move = Move.search(move_domain, limit=1)
                        if existing_move:
                            continue

                        # Buat dictionary data untuk satu baris barang
                        single_move_vals = {
                            'name': line.adt_TransactionDescription or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': line_dest.id,
                            'description_picking': line.adt_TransactionDescription or False,
                            'adt_line_external_id': line.adt_external_id or False,
                            'adt_inventory_id': line.adt_InventoryID or False,
                            'adt_line_nbr': line.adt_rowNumber or False,
                            'adt_open_qty': qty,
                            'adt_order_qty': qty,
                            'adt_uom_code': line.adt_UOM or False,
                        }
                        
                        # Saring field yang benar-benar ada di tabel stock.move Odoo Anda
                        single_move_vals = {k: v for k, v in single_move_vals.items() if k in Move._fields}
                        
                        # Masukkan ke dalam antrean list bulk create
                        moves_to_create.append(single_move_vals)

                    # DI LUAR LOOP: Eksekusi pembuatan seluruh Stock Move secara massal (Bulk Create)
                    if moves_to_create:
                        Move.create(moves_to_create)

                    if first.adt_document_only:
                        picking.action_validate_document_only_import(force=True)

                    # Tulis status sukses ke tabel staging kustom
                    first.write({
                        'import_state': action_state,
                        'import_message': f'Sukses diproses ke {picking.name}',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(first.adt_ReferenceNbr, 'toko_pegang_do')
                    
                    imported += 1

            except Exception as e:
                # KOREKSI 2: Penanganan komplit jika dokumen ini gagal (Otomatis skip ke index loop selanjutnya)
                error += 1
                tracked_lines = self.env['acumatica.inventory.issue.toko.pegang.do.staging.line'].search([
                    ('receipt_line_id', '=', first.id),
                ])
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='toko_pegang_do',
                    operation_type='delivery',
                    origin=first.adt_ReferenceNbr,
                    partner=first.adt_CustomerID or False,
                    location=getattr(first, 'adt_WarehouseID', False) or first.adt_LocationID or False,
                    location_dest=getattr(first, 'adt_ToWarehouseID', False) or False,
                    scheduled_date=first.adt_Date,
                    total_qty=first.adt_TotalQty,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.adt_InventoryID or False,
                        'product_name': line.adt_TransactionDescription or False,
                        'qty': self._parse_int(line.adt_Qty),
                        'uom': line.adt_UOM or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in tracked_lines],
                )
                
                first.write({
                    'import_state': 'error',
                    'import_message': str(e),
                    'odoo_picking_id': False,
                })
                print(f"[ERROR IMPORT] Dokumen {first.adt_ReferenceNbr} Gagal: {str(e)}")

        print(f"[SUMMARY SINKRONISASI] Imported: {imported}, Updated: {updated}, Error: {error}")
        return imported, updated, error


    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada receipt di Odoo.')
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

    # def action_import_this(self):
    #     self.ensure_one()
    #     return self._do_import()



class AcumaticaInventoryIssueTokoPegangDOLine(models.Model):
    _name = 'acumatica.inventory.issue.toko.pegang.do.staging.line'
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'adt_rowNumber asc, id asc'

    receipt_line_id = fields.Many2one(
        'acumatica.inventory.issue.toko.pegang.do.staging',
        string='Receipt Header',
        required=True,
        ondelete='cascade',
        index=True,
    )

    adt_external_id = fields.Char(string='Acumatica External ID')
    adt_id = fields.Char(string='Acumatica Detail ID')
    adt_rowNumber = fields.Char(string='Acumatica Detail Row Number')
    adt_note = fields.Char(string='Acumatica Detail Note')
    adt_Branch = fields.Char(string='Acumatica Detail Branch')
    adt_InventoryID = fields.Char(string='Acumatica Detail Inventory ID')
    adt_Qty = fields.Char(string='Acumatica Detail Quantity')
    adt_TransactionDescription = fields.Char(string='Acumatica Detail Transaction Description')
    adt_UOM = fields.Char(string='Acumatica Detail UOM')
    adt_Warehouse = fields.Char(string='Acumatica Detail Warehouse')

    # line_external_id = fields.Char(
    #     string='Line External ID',
    #     readonly=True,
    #     index=True,
    # )

    # line_note = fields.Text(
    #     string='Line Note',
    #     readonly=True,
    # )

    # branch_warehouse = fields.Char(
    #     string='Branch',
    #     readonly=True,
    # )

    # line_description = fields.Char(
    #     string='Description',
    #     readonly=True,
    # )

    # inventory_id = fields.Char(
    #     string='Inventory ID',
    #     readonly=True,
    #     index=True,
    # )

    # line_nbr = fields.Integer(
    #     string='Line Number',
    #     readonly=True,
    # )

    # location_code = fields.Char(
    #     string='Location',
    #     readonly=True,
    # )

    # product_uom_qty = fields.Float(
    #     string='Quantity',
    #     digits=(16, 4),
    #     readonly=True,
    # )

    # uom_code = fields.Char(
    #     string='UOM',
    #     readonly=True,
    # )

    # warehouse_code = fields.Char(
    #     string='Warehouse',
    #     readonly=True,
    # )
