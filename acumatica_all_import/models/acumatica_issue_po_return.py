from dateutil import parser as dateutil_parser
import logging
import requests
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaIssuePoReturnLine(models.Model):
    _name = 'acumatica.issue.po.return.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'receipt_nbr asc, line_nbr asc, id asc'

    def _adt_picking_type_wizard_call(self):
        return (
            'import.issue.po.return.wizard',
            ({'warehouse_code': self.warehouse_code, 'document_only': self.document_only},),
            {},
        )

    product_line_ids = fields.One2many('acumatica.issue.po.return.product', 'receipt_line_id', string='Lines')
    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header Acumatica')
    line_external_id = fields.Char(string='UUID Line Acumatica')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')


    receipt_nbr = fields.Char(string='Receipt Number', index=True)
    building_code = fields.Char(string='Building ID')
    change_item_ref_nbr = fields.Char(string='Change Item Ref Nbr')
    customer_id = fields.Char(string='Customer ID')
    customer_location_id = fields.Char(string='Customer Location ID')
    customer_location_name = fields.Char(string='Customer Location Name')
    customer_name = fields.Char(string='Customer Name')
    doc_type = fields.Char(string='Doc Type')
    external_ref = fields.Char(string='External Ref')
    note_header_id = fields.Char(string='Note Header ID')
    shipment_nbr = fields.Char(string='Shipment Nbr')
    transfer_nbr = fields.Char(string='Transfer Nbr')
    trans_type = fields.Char(string='Trans Type')
    vendor_code = fields.Char(string='VendorID')
    partner_ref = fields.Char(string='Vendor Ref')
    scheduled_date = fields.Char(string='Date')
    warehouse_code = fields.Char(string='Warehouse')
    header_location_code = fields.Char(string='Header Location')
    status = fields.Char(string='Status')
    receipt_type = fields.Char(string='Type')
    actual_qty = fields.Char(string='Control Qty')
    total_qty = fields.Char(string='Total Qty')
    is_hold = fields.Char(string='Hold')
    document_only = fields.Boolean(string='Document Only')
    inventory_ref = fields.Char(string='Inventory Ref Nbr')
    post_period = fields.Char(string='Post Period')
    acumatica_write_date = fields.Char(string='Last Modified')
    note = fields.Text(string='Header Note')
    branch_warehouse = fields.Char(string='Branch')

    line_nbr = fields.Char(string='Line Nbr')
    description = fields.Char(string='Description')
    transaction_description = fields.Char(string='Transaction Description')
    line_inventory_name = fields.Char(string='Line Inventory Name')
    line_location_name = fields.Char(string='Line Location Name')
    line_note_id = fields.Char(string='Line Note ID')
    line_warehouse = fields.Char(string='Line Warehouse')
    line_warehouse_name = fields.Char(string='Line Warehouse Name')
    inventory_id = fields.Char(string='InventoryID')
    line_type = fields.Char(string='Line Type')
    location_dest_code = fields.Char(string='Location')
    open_qty = fields.Char(string='Open Qty')
    order_qty = fields.Char(string='Ordered Qty')
    po_line_number = fields.Char(string='PO Line Nbr')
    po_number = fields.Char(string='PO Number')
    po_type = fields.Char(string='PO Type')
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr')
    po_receipt_number = fields.Char(string='PO Receipt Nbr')
    product_uom_qty = fields.Char(string='Receipt Qty')
    transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr')
    transfer_order_number = fields.Char(string='Transfer Order Nbr')
    transfer_order_type = fields.Char(string='Transfer Order Type')
    transfer_shipment_number = fields.Char(string='Transfer Shipment Nbr')
    uom_code = fields.Char(string='UOM')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    line_note = fields.Text(string='Line Note')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', tracking=True)
    import_message = fields.Char(string='Generation Message', tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync')

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

    @staticmethod
    def _parse_qty(value):
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0

    def _find_vendor(self, line):
        Partner = self.env['res.partner']
        vendor = False
        if line.vendor_code:
            # vendor = Partner.search([('ref', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            vendor = Partner.search([('company_registry', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
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

    def _adt_reresolve_picking_type(self):
        """Document Only PO Return uses DDO; normal PO Return starts at Pick."""
        self.ensure_one()
        if self.document_only:
            return self.env['stock.picking.type'].resolve_document_only_picking_type(
                api_acumatica='issue_po_return',
                document_only=True,
                warehouse_code=self.warehouse_code,
                required=True,
            )
        if (
            self.picking_type_id
            and self.picking_type_id.code == 'internal'
            and self.picking_type_id.operation_category == 'pick'
        ):
            return self.picking_type_id

        wizard_name, args, kwargs = self._adt_picking_type_wizard_call()
        wizard = self.env[wizard_name]
        vals = {'config_id': self.config_id.id} if self.config_id else {}
        picking_type = wizard.new(vals)._search_picking_type(*args, **kwargs)
        if isinstance(picking_type, tuple):
            picking_type = picking_type[0]
        return picking_type or self.env['stock.picking.type']

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

        created = 0
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

        created = 0
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
                ('import_state', '=', 'staged')
            ])
            
            if not receipt_lines:
                continue

            # Gunakan satu record induk sebagai acuan pengisian data level Header/Picking.
            # Ini juga melindungi import dari staging lama yang terlanjur dobel.
            first = receipt_lines[0]

            # WAJIB: Ambil sub-transaksi database tingkat dokumen agar tidak menghentikan loop massal jika terjadi error
            with self.env.cr.savepoint():
                self.env.cr.execute('SAVEPOINT import_issue_po_return_doc')
                try:
                    vendor = self._find_vendor(first)
                    if not vendor:
                        raise UserError(
                            f'Vendor tidak ditemukan untuk VendorID: {first.vendor_code or first.partner_ref or "-"}'
                        )
                    warehouse = self._find_warehouse(first)
                    if not warehouse:
                        raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')

                    picking_type = first._adt_reresolve_picking_type()
                    if not picking_type:
                        raise UserError('Picking type Pick tidak ditemukan.')

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
                        # 'adt_type': first.receipt_type or False,
                        'adt_type': "PO Return",
                        'adt_warehouse_code': first.warehouse_code or False,
                        'adt_external_id': first.external_id or False,
                        'api_acumatica': 'issue_po_return',
                    }
                    print(f"Processing receipt {origin}, Vendor: {first.vendor_code}, Picking Type: {picking_type.name}")

                    # Filter field yang benar-benar ada di tabel stock.picking Odoo Anda
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}

                    # Pengecekan Duplikasi Dokumen menggunakan Origin
                    picking = Picking.search([('origin', '=', origin)], limit=1)

                    if picking:
                        if picking.state != 'draft':
                            raise UserError(f'Receipt {receipt_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                        picking.write(vals)
                        action_state = 'updated'
                        updated += 1
                        self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=receipt_nbr)
                        
                        # OPTIMAL: Unlink/Hapus baris lama terlebih dahulu jika melakukan update agar data tidak menumpuk double
                        picking.move_ids.unlink()
                    else:
                        picking = Picking.create(vals)
                        action_state = 'created'
                        created += 1

                    # =====================================================
                    # 2. ITERASI PRODUK BERDASARKAN RELASI KE MODEL ANAK
                    # =====================================================
                    # Menarik semua baris detail produk (acumatica.issue.po.return.product) yang terikat dengan seluruh receipt_lines ini
                    product_lines = self.env['acumatica.issue.po.return.product'].search([
                        ('receipt_line_id', 'in', receipt_lines.ids)
                    ], order='id asc')

                    unique_product_lines = self.env['acumatica.issue.po.return.product'].browse()
                    seen_line_keys = set()
                    for product_line in product_lines:
                        line_key = product_line.line_external_id or (
                            product_line.line_nbr, product_line.inventory_id
                        )
                        if line_key in seen_line_keys:
                            continue
                        seen_line_keys.add(line_key)
                        unique_product_lines |= product_line
                    product_lines = unique_product_lines

                    print(f"Memproses {len(product_lines)} baris produk untuk Receipt: {origin}")
                    
                    for item in product_lines:
                        product = ProductModel.search([('default_code', '=', item.inventory_id)], limit=1)
                        if not product:
                            raise UserError(f'Product tidak ditemukan untuk InventoryID: {item.inventory_id or "-"}')

                        uom = product.uom_id
                        # Some PO Return payloads provide only Ordered Qty.
                        qty = self._parse_qty(item.product_uom_qty)
                        if not qty:
                            qty = self._parse_qty(
                                item.order_qty or item.receipt_line_id.order_qty
                            )

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

                    # Jika seluruh baris produk di atas sukses tanpa error, tandai status sebagai created
                    receipt_lines.write({
                        'import_state': action_state,
                        'import_message': 'success',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(receipt_nbr, 'issue_po_return')
                    self.env.cr.execute('RELEASE SAVEPOINT import_issue_po_return_doc')

                except Exception as e:
                    self.env.cr.execute('ROLLBACK TO SAVEPOINT import_issue_po_return_doc')
                    import_message = f'!!! ERROR ON IMPORT PROCESS: {str(e)}'
                    print(f"Error pada dokumen receipt {receipt_nbr}: {str(e)}")
                    tracked_lines = self.env['acumatica.issue.po.return.product'].search([
                        ('receipt_line_id', 'in', receipt_lines.ids),
                    ])
                    self.env['acumatica.error.transaction']._handle_acumatica_error(
                        first,
                        [str(e)],
                        api_acumatica='issue_po_return',
                        operation_type='receipt',
                        origin=receipt_nbr,
                        partner=first.vendor_code or False,
                        location=first.warehouse_code or False,
                        location_dest=first.warehouse_dest_code or False,
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
                        } for line in tracked_lines],
                    )
                    
                    receipt_lines.write({
                        'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                        'import_message': import_message,
                        'odoo_picking_id': False,
                    })
                    
                    # Teruskan loop ke dokumen receipt berikutnya
                    continue


        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Inventory Receipt',
        #         'message': f'Generate selesai: {created} created, {updated} updated, {error} error.',
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

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
        self.search([('import_state', '=', 'staged')]).write({'selected': True})

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
        index=True,
    )

    line_note = fields.Text(
        string='Line Note',
    )

    branch_warehouse = fields.Char(
        string='Branch',
    )

    line_description = fields.Char(
        string='Description',
    )

    line_inventory_name = fields.Char(string='Line Inventory Name')
    line_location_name = fields.Char(string='Line Location Name')
    line_note_id = fields.Char(string='Line Note ID')
    line_warehouse_name = fields.Char(string='Line Warehouse Name')

    inventory_id = fields.Char(
        string='Inventory ID',
        index=True,
    )

    line_nbr = fields.Integer(
        string='Line Number',
    )

    location_code = fields.Char(
        string='Location',
    )

    product_uom_qty = fields.Float(
        string='Quantity',
        digits=(16, 4),
    )

    order_qty = fields.Char(string='Ordered Qty')

    uom_code = fields.Char(
        string='UOM',
    )

    warehouse_code = fields.Char(
        string='Warehouse',
    )
