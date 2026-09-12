from dateutil import parser as dateutil_parser
import logging
import requests
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AcumaticaInvoiceConsignment(models.Model):
    _name = 'acumatica.invoice.consignment.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'adt_ReferenceNbr asc, adt_rowNumber asc, id asc'

    def _adt_picking_type_wizard_call(self):
        line = self.env['acumatica.invoice.consignment.staging.line'].search(
            [('receipt_line_id', '=', self.id)], limit=1,
        )
        if not line.adt_Warehouse:
            return False
        return ('import.invoice.consignment.wizard', (line.adt_Warehouse,), {})

    adt_id = fields.Char(string="Acumatica id", readonly=True)
    adt_rowNumber = fields.Char(string="Acumatica rowNumber", readonly=True)
    adt_note = fields.Char(string="Acumatica note", readonly=True)
    adt_ConsignmentType = fields.Char(string="Acumatica ConsignmentType", readonly=True)
    adt_CreatedDateTime = fields.Char(string="Acumatica CreatedDateTime", readonly=True)
    adt_CustomerID = fields.Char(string="Acumatica CustomerID", readonly=True)
    adt_CustomerName = fields.Char(string="Acumatica CustomerName", readonly=True)
    adt_CustomerOrder = fields.Char(string="Acumatica CustomerOrder", readonly=True)
    adt_Date = fields.Char(string="Acumatica Date", readonly=True)
    adt_BuildingID = fields.Char(string="Acumatica BuildingID", readonly=True)
    adt_Description = fields.Char(string="Acumatica Description", readonly=True)
    adt_DocumentOnly = fields.Boolean(string="Acumatica DocumentOnly", readonly=True)
    adt_DueDate = fields.Char(string="Acumatica DueDate", readonly=True)
    adt_LastModifiedDateTime = fields.Char(string="Acumatica LastModifiedDateTime", readonly=True)
    adt_LocationID = fields.Char(string="Acumatica LocationID", readonly=True)
    adt_LocationName = fields.Char(string="Acumatica LocationName", readonly=True)
    adt_NoteHeaderID = fields.Char(string="Acumatica NoteHeaderID", readonly=True)
    adt_NoteID = fields.Char(string="Acumatica NoteID", readonly=True)
    adt_OrigRefNbr = fields.Char(string="Acumatica OrigRefNbr", readonly=True)
    adt_ReferenceNbr = fields.Char(string="Acumatica ReferenceNbr", readonly=True)
    adt_Status = fields.Char(string="Acumatica Status", readonly=True)
    adt_Type = fields.Char(string="Acumatica Type", readonly=True)

    product_line_ids = fields.One2many('acumatica.invoice.consignment.staging.line', 'receipt_line_id', string='Lines')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')


    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)
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
            existing = Product.search([('default_code', '=', line.adt_InventoryID)], limit=1)
            if existing:
                return existing
            
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
        staging_line = self.env['acumatica.invoice.consignment.staging.line'].search([
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
        return location

    def _find_consignment_location(self, warehouse_code):
        """Cari lokasi sumber CONS untuk Invoice Consignment."""
        Location = self.env['stock.location'].sudo()
        Mapping = self.env['stock.location.acumatica'].sudo()
        code = (warehouse_code or '').strip()
        if not code:
            return Location.browse()

        mapping = Mapping.search([
            '|', ('code', '=', code), ('name', '=', code),
            ('active', '=', True),
        ], limit=1)
        if mapping.odoo_location_id and (
            mapping.odoo_location_id.is_consignment
            or 'CONS' in (mapping.odoo_location_id.complete_name or '').upper()
        ):
            return mapping.odoo_location_id

        location = Location.search([
            ('name', '=', code),
            ('is_consignment', '=', True),
        ], limit=1)
        if location:
            return location

        building_code = code.split('-', 1)[0].upper()
        warehouse = self.env['stock.warehouse'].search([
            ('code', '=', building_code),
        ], limit=1)
        if warehouse:
            cons_root = Location.search([
                ('name', '=', 'CONS'),
                ('location_id', '=', warehouse.view_location_id.id),
            ], limit=1)
            if cons_root:
                location = Location.search([
                    ('name', '=', code),
                    ('location_id', '=', cons_root.id),
                    ('is_consignment', '=', True),
                ], limit=1)
                if location:
                    return location
                if code.upper() == 'CONS' or code.upper() == f'{building_code}-CONS':
                    return cons_root

        return Location.browse()

    def _get_invoice_consignment_virtual_location(self, warehouse_code):
        building_code = (warehouse_code or '').strip().split('-', 1)[0].upper()
        if not building_code:
            return self.env['stock.location'].browse()
        return self.env['acumatica.internal.transfer.service'].get_or_create_virtual_building_location(
            building_code,
        )

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.adt_UOM:
            uom = Uom.search([('name', '=', line.adt_UOM)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

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

        # 1. Ambil seluruh data pending untuk referensi filtering
        staging_records = self.env['acumatica.invoice.consignment.staging'].search([
            ('import_state', '=', 'staged')
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
        
        # PERULANGAN UTAMA PER DOKUMEN STAGING
        for first in self:
            first_id = first.id
            first_reference = first.adt_ReferenceNbr

            try:
                # 2. BUNGKUS DENGAN SAVEPOINT: Jika error, rollback hanya terjadi pada dokumen aktif ini
                with self.env.cr.savepoint():
                    print(f"Processing receipt {first_reference}")
                    vendor = self._find_vendor(first)
                    if not vendor:
                        print(f"Vendor not found: {first.adt_CustomerName}")

                    staging_line = self.env['acumatica.invoice.consignment.staging.line'].search([
                        ('receipt_line_id', '=', first.id)
                    ], limit=1)

                    branch_warehouse = staging_line.adt_Branch if staging_line else False

                    picking_type = first.picking_type_id
                    if not picking_type:
                        picking_type = self.env['stock.picking.type'].resolve_picking_type(
                            warehouse_code=staging_line.adt_Warehouse if staging_line else False,
                            code='outgoing',
                            operation_category='delivery',
                            api_acumatica='invoice_consignment',
                            transaction_key='invoice_consignment',
                            required=False,
                        )
                    if not picking_type:
                        raise UserError('Picking type Direct Delivery Order tidak ditemukan.')

                    warehouse_code = staging_line.adt_Warehouse if staging_line else False
                    source_location = self._find_consignment_location(warehouse_code)
                    if not source_location:
                        raise UserError(
                            f'Location CONS tidak ditemukan untuk warehouse {warehouse_code or "-"}.'
                        )

                    dest_location = self._get_invoice_consignment_virtual_location(warehouse_code)
                    if not dest_location:
                        raise UserError(
                            f'Virtual location tidak ditemukan untuk warehouse {warehouse_code or "-"}.'
                        )

                    origin = first.adt_ReferenceNbr or False

                    vals = {
                        'partner_id': vendor.id if vendor else False,
                        'picking_type_id': picking_type.id,
                        'location_id': source_location.id,
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
                        'adt_is_document_only': False,
                        'adt_external_id': first.adt_id or False,
                    }
                    
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}
                    
                    picking = Picking.search([('origin', '=', origin)], limit=1)
                    if picking:
                        if picking.state != 'draft':
                            raise UserError(
                                f'Invoice Consignment {origin} sudah ada di Odoo dengan state '
                                f'{picking.state}, tidak bisa diupdate.'
                            )
                        picking.write(vals)
                        action_state = 'updated'
                        picking.move_ids.unlink()
                    else:
                        picking = Picking.create(vals)
                        action_state = 'created'

                    to_create_move = self.env['acumatica.invoice.consignment.staging.line'].search([
                        ('receipt_line_id', '=', first.id)
                    ])

                    print(f"Processing {len(to_create_move)} lines for receipt {first_reference}")

                    # Inisialisasi list kosong sebelum loop lines dimulai
                    moves_to_create = []

                    print(f"Processing {len(to_create_move)} lines for receipt {first_reference}")

                    # PERULANGAN LINES
                    for line in to_create_move:
                        product = self._find_product(line)
                        if not product:
                            # Jika produk tidak ketemu, raise error ini akan membatalkan (rollback) pembuatan picking!
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        qty = self._parse_int(line.adt_Qty)
                        print(f"Quantity: {qty} for actual value: {line.adt_Qty}")

                        # Buat dictionary data untuk satu baris barang
                        single_move_vals = {
                            'name': line.adt_TransactionDescription or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': picking.location_dest_id.id,
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


                    # Tulis status sukses ke tabel staging kustom
                    first.write({
                        'import_state': action_state,
                        'import_message': 'success',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(first_reference, 'invoice_consignment')
                    
                    if action_state == 'created':
                        created += 1
                    else:
                        updated += 1

            except Exception as e:
                # KOREKSI 2: Penanganan komplit jika dokumen ini gagal (Otomatis skip ke index loop selanjutnya)
                error += 1
                tracked_lines = self.env['acumatica.invoice.consignment.staging.line'].search([
                    ('receipt_line_id', '=', first.id),
                ])
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='invoice_consignment',
                    operation_type='internal',
                    origin=first_reference,
                    partner=first.adt_CustomerID or False,
                    location=getattr(first, 'adt_WarehouseID', False) or first.adt_LocationID or False,
                    location_dest=getattr(first, 'adt_ToWarehouseID', False) or False,
                    scheduled_date=first.adt_Date,
                    total_qty=getattr(first, 'adt_TotalQty', 0.0),
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.adt_InventoryID or False,
                        'product_name': line.adt_TransactionDescription or False,
                        'qty': self._parse_int(line.adt_Qty),
                        'uom': line.adt_UOM or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in tracked_lines],
                )
                
                staging = self.env['acumatica.invoice.consignment.staging'].browse(first_id).exists()
                if staging:
                    staging.write({
                        'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                        'import_message': str(e),
                        'odoo_picking_id': False,
                    })
                print(f"[ERROR IMPORT] Dokumen {first_reference} Gagal: {str(e)}")

        msg = f'Generate done: {created} invoice consignment created, {updated} invoice consignment updated, {error} invoice consignment error.'
        print(f"[SUMMARY SINKRONISASI] Created: {created}, Updated: {updated}, Error: {error}")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Generate Invoice Consignment',
                'message': msg,
                'type': 'success' if error == 0 else 'danger',
                'sticky': True,
            }
        }


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


class AcumaticaInvoiceConsignmentLine(models.Model):
    _name = 'acumatica.invoice.consignment.staging.line'
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'adt_rowNumber asc, id asc'

    receipt_line_id = fields.Many2one(
        'acumatica.invoice.consignment.staging',
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
    adt_LineBranchName = fields.Char(string='Acumatica Detail LineBranchName', readonly=True)
    adt_InventoryID = fields.Char(string='Acumatica Detail Inventory ID')
    adt_LineNoteID = fields.Char(string='Acumatica Detail LineNoteID', readonly=True)
    adt_NoteID = fields.Char(string='Acumatica Detail NoteID', readonly=True)
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
