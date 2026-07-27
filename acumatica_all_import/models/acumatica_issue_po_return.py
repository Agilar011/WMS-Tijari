from dateutil import parser as dateutil_parser
import logging
import requests
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaIssuePoReturnConfig(models.Model):
    _name = 'acumatica.issue.po.return.config'
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

            if self.odata_expand:
                params['$expand'] = self.odata_expand

            body = {
                "BuildingID": {
                    "value": "WH33"
                }
            }

            response = session.put(endpoint, params=params, json=body, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Inventory Receipt (HTTP {response.status_code}): {response.text}')

            raw_payload = response.json()
            raw_data = raw_payload.get('PurchaseReceiptGIDetails') if isinstance(raw_payload, dict) else None
            raw_data = raw_data or self._normalize_rows(raw_payload)
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
                    'warehouse_code': self._val(item, 'Warehouse') or self._val(item, 'LineWarehouseID'),
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
                    warehouse_dest_code = self._val(detail, 'Warehouse') or self._val(detail, 'LineWarehouseID') or header.get('warehouse_code')

                    result.append({
                        **header,
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'description': description,
                        'inventory_id': self._val(detail, 'InventoryID') or self._val(detail, 'LineInventoryID'),
                        'line_nbr': str(line_nbr),
                        'line_type': self._val(detail, 'LineType'),
                        'location_dest_code': self._val(detail, 'Location'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'product_uom_qty': self._val(detail, 'ReceiptQty'),
                        'transaction_description': self._val(detail, 'TransactionDescription'),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_dest_code': warehouse_dest_code,
                        'warehouse_code': warehouse_dest_code,
                    })

            _logger.info("Berhasil ambil %s rows Inventory Receipt dari Acumatica", len(result))
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()


class AcumaticaIssuePoReturnLine(models.Model):
    _name = 'acumatica.issue.po.return.line'
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'receipt_nbr asc, line_nbr asc, id asc'
    product_line_ids = fields.One2many('acumatica.issue.po.return.product', 'receipt_line_id', string='Lines')
    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header Acumatica', readonly=True)
    line_external_id = fields.Char(string='UUID Line Acumatica', readonly=True)

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])


    receipt_nbr = fields.Char(string='Receipt Number', readonly=True, index=True)
    vendor_code = fields.Char(string='VendorID', readonly=True)
    partner_ref = fields.Char(string='Vendor Ref', readonly=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    header_location_code = fields.Char(string='Header Location', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    receipt_type = fields.Char(string='Type', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    document_only = fields.Boolean(string='Document Only', readonly=True)
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
    location_dest_code = fields.Char(string='Location', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    po_line_number = fields.Char(string='PO Line Nbr', readonly=True)
    po_number = fields.Char(string='PO Number', readonly=True)
    po_type = fields.Char(string='PO Type', readonly=True)
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr', readonly=True)
    po_receipt_number = fields.Char(string='PO Receipt Nbr', readonly=True)
    product_uom_qty = fields.Char(string='Receipt Qty', readonly=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr', readonly=True)
    transfer_order_number = fields.Char(string='Transfer Order Nbr', readonly=True)
    transfer_order_type = fields.Char(string='Transfer Order Type', readonly=True)
    transfer_shipment_number = fields.Char(string='Transfer Shipment Nbr', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

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

    @api.depends('receipt_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.receipt_nbr and Picking.search_count([('adt_receipt_nbr', '=', rec.receipt_nbr)]))

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

    def _find_vendor(self, line):
        Partner = self.env['res.partner']
        vendor = False
        if line.vendor_code:
            vendor = Partner.search([('ref', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            if not vendor:
                vendor = Partner.search([('name', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
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
        Product = self.env['product.product']

        product = False

        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)

        if not product and line.transaction_description:
            product = Product.search([('name', '=', line.transaction_description)], limit=1)

        if not product:
            name = line.transaction_description or line.description or line.inventory_id or 'Unknown Product'
            existing = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if existing:
                return existing
            product = Product.create({
                'name': name,
                'default_code': line.inventory_id or False,
                'type': 'consu',  # stockable
            })

        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        warehouse = False
        if line.warehouse_code:
            warehouse = Warehouse.search([('code', '=', line.warehouse_code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', line.warehouse_code)], limit=1)
            else:
                warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location_dest(self, line, warehouse=False):
        Location = self.env['stock.location']
        location = False
        if line.location_dest_code:
            location = Location.search([('complete_name', '=', line.location_dest_code)], limit=1)
            if not location:
                location = Location.search([('name', '=', line.location_dest_code)], limit=1)
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
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
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

        imported = 0
        updated = 0
        error = 0

        print(f"self: {self}")
        # raise UserError("Debug")

        # proses per receipt number
    def _do_import(self):
        print("Menjalankan fungsi do import issue po return")
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        ProductModel = self.env['product.product']

        imported = 0
        updated = 0

        # =====================================================
        # 1. GROUPING BERDASARKAN RECEIPT NUMBER DARI STAGING INDUK
        # =====================================================
        # Menggunakan self.mapped('receipt_nbr') untuk mendapatkan daftar nomor unik
        unique_receipt_numbers = list(set([nbr for nbr in self.mapped('receipt_nbr') if nbr]))

        for receipt_nbr in unique_receipt_numbers:
            # Cari seluruh record induk staging yang memiliki receipt_nbr yang sama dan berstatus pending
            receipt_lines = self.env['acumatica.issue.po.return.line'].search([
                ('receipt_nbr', '=', receipt_nbr),
                ('import_state', '=', 'pending')
            ])
            
            if not receipt_lines:
                continue

            # Gunakan record induk pertama sebagai acuan pengisian data level Header/Picking
            first = receipt_lines[0]

            # WAJIB: Ambil sub-transaksi database tingkat dokumen agar tidak menghentikan loop massal jika terjadi error
            with self.env.cr.savepoint():
                try:
                    vendor = self._find_vendor(first)
                    warehouse = self._find_warehouse(first)
                    if not warehouse:
                        raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')

                    picking_type = first.picking_type_id
                    if not picking_type:
                        raise UserError('Picking type outgoing tidak ditemukan.')

                    dest_location = self._find_location_dest(first, warehouse)
                    if not dest_location:
                        raise UserError(
                            f'Location tujuan tidak ditemukan untuk code: '
                            f'{first.location_dest_code or first.header_location_code or "-"}'
                        )
                    if dest_location.usage == 'customer':
                        raise UserError('Location tujuan customer hanya boleh dipakai oleh SO Shipment.')

                    origin = first.receipt_nbr or first.po_number or False

                    # Susun values untuk Header stock.picking
                    vals = {
                        'partner_id': vendor.id if vendor else False,
                        'picking_type_id': picking_type.id,
                        'location_id': (
                            picking_type.default_location_src_id.id
                            if picking_type.default_location_src_id
                            else self.env.ref('stock.stock_location_suppliers').id
                        ),
                        'location_dest_id': dest_location.id,
                        'scheduled_date': self._parse_dt(first.scheduled_date) if hasattr(first, 'scheduled_date') and first.scheduled_date else fields.Datetime.now(),
                        'origin': origin,
                        'note': first.note or False,

                        # Field kustom level header (jika didefinisikan pada model stock.picking Anda)
                        'adt_receipt_nbr': first.receipt_nbr or False,
                        'adt_vendor_code': first.vendor_code or False,
                        'adt_partner_ref': first.partner_ref or False,
                        'adt_branch_warehouse': first.branch_warehouse or False,
                        'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
                        'adt_inventory_ref': first.inventory_ref or False,
                        'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date) if hasattr(first, 'acumatica_write_date') else False,
                        'adt_header_location_code': first.header_location_code or False,
                        'adt_post_period': first.post_period or False,
                        'adt_status': first.status or False,
                        'adt_total_qty': self._parse_int(first.total_qty) if hasattr(first, 'total_qty') else 0,
                        'adt_type': first.receipt_type or False,
                        'adt_warehouse_code': first.warehouse_code or False,
                        'adt_external_id': first.external_id or False,
                    }
                    print(f"Processing receipt {origin}, Vendor: {first.vendor_code}, Picking Type: {picking_type.name}")

                    # Filter field yang benar-benar ada di tabel stock.picking Odoo Anda
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}

                    # Pengecekan Duplikasi Dokumen menggunakan Origin
                    picking = Picking.search([('origin', '=', origin)], limit=1)

                    if picking:
                        if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                            raise UserError(f'Receipt {receipt_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                        picking.write(vals)
                        action_state = 'updated'
                        updated += 1
                        
                        # OPTIMAL: Unlink/Hapus baris lama terlebih dahulu jika melakukan update agar data tidak menumpuk double
                        picking.move_ids.unlink()
                    else:
                        picking = Picking.create(vals)
                        action_state = 'imported'
                        imported += 1

                    # =====================================================
                    # 2. ITERASI PRODUK BERDASARKAN RELASI KE MODEL ANAK
                    # =====================================================
                    # Menarik semua baris detail produk (acumatica.issue.po.return.product) yang terikat dengan seluruh receipt_lines ini
                    product_lines = self.env['acumatica.issue.po.return.product'].search([
                        ('receipt_line_id', 'in', receipt_lines.ids)
                    ])

                    print(f"Memproses {len(product_lines)} baris produk untuk Receipt: {origin}")
                    
                    for item in product_lines:
                        product = ProductModel.search([('default_code', '=', item.inventory_id)], limit=1)
                        if not product:
                            raise UserError(f'Product tidak ditemukan untuk InventoryID: {item.inventory_id or "-"}')

                        uom = product.uom_id
                        qty = self._parse_int(item.product_uom_qty) if hasattr(item, 'product_uom_qty') else float(item.product_uom_qty or 0.0)

                        move_vals = {
                            # PERBAIKAN: Hapus kata 'item.description' yang memicu AttributeError
                            'name': item.line_description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': dest_location.id,
                            # PERBAIKAN: Hapus kata 'item.description'
                            'description_picking': item.line_description or False,

                            'adt_line_external_id': item.line_external_id or False,
                            'adt_inventory_id': item.inventory_id or False,
                            'adt_line_nbr': item.line_nbr or False,
                            'adt_uom_code': item.uom_code or False,
                            'adt_warehouse_code': item.warehouse_code or False,
                            'adt_location_code': item.location_code or False,
                            'adt_line_note': item.line_note or False,
                            'adt_type': 'Issue PO Return',
                        }
                        
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}
                        Move.create(move_vals)

                    if receipt_lines.filtered('document_only'):
                        picking.action_validate_document_only_import(force=True)

                    # Jika seluruh baris produk di atas sukses tanpa error, tandai status sebagai imported
                    receipt_lines.write({
                        'import_state': action_state,
                        'import_message': f'Berhasil diproses menjadi Picking Odoo: {picking.name}',
                        'odoo_picking_id': picking.id,
                    })

                except Exception as e:
                    # =====================================================
                    # PERBAIKAN FATAL: JANGAN MEMANGGIL cr.rollback() atau cr.commit() DI SINI!
                    # =====================================================
                    # Cukup tulis status log error ke baris staging ini.
                    # Blok `with self.env.cr.savepoint():` di atas otomatis membatalkan pembuatan picking/move yang rusak.
                    import_message = f'!!! ERROR ON IMPORT PROCESS: {str(e)}'
                    print(f"Error pada dokumen receipt {receipt_nbr}: {str(e)}")
                    
                    receipt_lines.write({
                        'import_state': 'error',
                        'import_message': import_message
                    })
                    
                    # Teruskan loop ke dokumen receipt berikutnya
                    continue


        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Receipt',
                'message': "test",
                'type': 'success',
                'sticky': True,
            }
        }

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


class AcumaticaIssuePoReturnProduct(models.Model):
    _name = 'acumatica.issue.po.return.product'
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'line_nbr asc, id asc'

    receipt_line_id = fields.Many2one(
        'acumatica.issue.po.return.line',
        string='Receipt Header',
        required=True,
        ondelete='cascade',
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

    branch_warehouse = fields.Char(
        string='Branch',
        readonly=True,
    )

    line_description = fields.Char(
        string='Description',
        readonly=True,
    )

    inventory_id = fields.Char(
        string='Inventory ID',
        readonly=True,
        index=True,
    )

    line_nbr = fields.Integer(
        string='Line Number',
        readonly=True,
    )

    location_code = fields.Char(
        string='Location',
        readonly=True,
    )

    product_uom_qty = fields.Float(
        string='Quantity',
        digits=(16, 4),
        readonly=True,
    )

    uom_code = fields.Char(
        string='UOM',
        readonly=True,
    )

    warehouse_code = fields.Char(
        string='Warehouse',
        readonly=True,
    )
