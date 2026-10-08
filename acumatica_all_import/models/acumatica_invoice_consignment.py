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

    adt_id = fields.Char(string="Acumatica id")
    adt_rowNumber = fields.Char(string="Acumatica rowNumber")
    adt_note = fields.Char(string="Acumatica note")
    adt_ConsignmentType = fields.Char(string="Acumatica ConsignmentType")
    adt_CreatedDateTime = fields.Char(string="Acumatica CreatedDateTime")
    adt_CustomerID = fields.Char(string="Acumatica CustomerID")
    adt_CustomerName = fields.Char(string="Acumatica CustomerName")
    adt_CustomerOrder = fields.Char(string="Acumatica CustomerOrder")
    adt_Date = fields.Char(string="Acumatica Date")
    adt_BuildingID = fields.Char(string="Acumatica BuildingID")
    adt_Description = fields.Char(string="Acumatica Description")
    adt_DocumentOnly = fields.Boolean(string="Acumatica DocumentOnly")
    adt_DueDate = fields.Char(string="Acumatica DueDate")
    adt_LastModifiedDateTime = fields.Char(string="Acumatica LastModifiedDateTime")
    adt_LocationID = fields.Char(string="Acumatica LocationID")
    adt_LocationName = fields.Char(string="Acumatica LocationName")
    adt_NoteHeaderID = fields.Char(string="Acumatica NoteHeaderID")
    adt_NoteID = fields.Char(string="Acumatica NoteID")
    adt_OrigRefNbr = fields.Char(string="Acumatica OrigRefNbr")
    adt_ReferenceNbr = fields.Char(string="Acumatica ReferenceNbr")
    adt_Status = fields.Char(string="Acumatica Status")
    adt_Type = fields.Char(string="Acumatica Type")

    product_line_ids = fields.One2many('acumatica.invoice.consignment.staging.line', 'receipt_line_id', string='Lines')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')


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

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')

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

        virtual_root = self.env.ref(
            'stock.stock_location_locations_virtual', raise_if_not_found=False
        )
        if virtual_root:
            consignment_root = Location.search([
                ('name', '=', 'Consignment'),
                ('location_id', '=', virtual_root.id),
            ], limit=1)
            consignment_code = (
                code.split('-', 1)[1].strip()
                if '-' in code
                else code
            )
            if consignment_root and consignment_code:
                location = Location.search([
                    ('name', '=', consignment_code),
                    ('location_id', '=', consignment_root.id),
                    ('is_consignment', '=', True),
                ], limit=1)
                if location:
                    return location

        mapping = Mapping.search([
            '&', ('active', '=', True),
            '|', ('code', '=', code), ('name', '=', code),
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

    def _get_invoice_consignment_destination_location(self):
        """Return the shared partner location for end-user consignment."""
        location = self.env.ref(
            'tijari_wms_18.stock_location_end_user_consignment',
            raise_if_not_found=False,
        )
        if location:
            return location

        partner_root = self.env.ref(
            'stock.stock_location_locations_partner', raise_if_not_found=False
        )
        if not partner_root:
            return self.env['stock.location'].browse()
        return self.env['stock.location'].sudo().search([
            ('name', '=', 'End User Consignment'),
            ('location_id', '=', partner_root.id),
        ], limit=1)

    def _check_invoice_consignment_reserved_qty(self, picking, reference):
        moves = picking.move_ids.filtered(lambda move: move.state not in ('done', 'cancel'))
        reserved_total = sum(
            sum(move.move_line_ids.mapped('quantity'))
            for move in moves
        )
        if reserved_total > 0:
            return

        details = []
        for move in moves:
            reserved_qty = sum(move.move_line_ids.mapped('quantity'))
            details.append(
                '- %s | Lokasi sumber: %s | Diminta: %s %s | Berhasil dialokasikan: %s %s'
                % (
                    move.product_id.display_name,
                    move.location_id.complete_name,
                    move.product_uom_qty,
                    move.product_uom.name,
                    reserved_qty,
                    move.product_uom.name,
                )
            )

        raise UserError(
            'Invoice Consignment %s belum bisa diproses karena tidak ada stok yang '
            'berhasil dialokasikan dari lokasi sumber. Periksa stok tersedia dan '
            'pastikan stok tidak sedang dialokasikan ke transaksi lain.\n\n%s'
            % (reference or '-', '\n'.join(details) or '- Tidak ada baris barang.')
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
            update_messages = []

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

                    warehouse_code = staging_line.adt_Warehouse if staging_line else False
                    picking_type = self.env['stock.picking.type'].resolve_document_only_picking_type(
                        target_operation_type='direct_delivery_order',
                        api_acumatica='invoice_consignment',
                        document_only=True,
                        warehouse_code=warehouse_code,
                        required=False,
                    )
                    if not picking_type:
                        raise UserError('Picking type Direct Delivery Order tidak ditemukan.')

                    source_location = self._find_consignment_location(warehouse_code)
                    if not source_location:
                        raise UserError(
                            f'Location CONS tidak ditemukan untuk warehouse {warehouse_code or "-"}.'
                        )

                    dest_location = self._get_invoice_consignment_destination_location()
                    if not dest_location:
                        raise UserError(
                            'Location Partners/End User Consignment tidak ditemukan.'
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
                        'desc_note': first.adt_Description or False,

                    }
                    
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}
                    
                    picking = Picking.search([('origin', '=', origin)], limit=1)
                    previous_moves = {}
                    if picking and picking.state == 'draft':
                        update_messages.extend(self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                            picking, vals,
                            field_names={'partner_id', 'picking_type_id', 'location_id', 'location_dest_id', 'scheduled_date', 'origin', 'note', 'adt_receipt_nbr', 'adt_vendor_code', 'adt_partner_ref', 'adt_branch_warehouse', 'adt_acumatica_write_date', 'adt_status', 'adt_type', 'adt_is_document_only', 'adt_external_id', 'desc_note'},
                            prefix='Header',
                        ))
                        for old_move in picking.move_ids:
                            key = str(old_move.adt_line_external_id or old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.id)
                            previous_moves[key] = {'label': old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.name, 'product': old_move.product_id.display_name or '—', 'qty': old_move.product_uom_qty, 'uom': old_move.product_uom.display_name or '—', 'destination': old_move.location_dest_id.display_name or '—', 'name': old_move.name or '—'}
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
                    update_line_snapshots = []

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
                        line_source_location = self._find_consignment_location(line.adt_Warehouse)
                        if not line_source_location:
                            raise UserError(
                                f'Location CONS tidak ditemukan untuk warehouse '
                                f'{line.adt_Warehouse or "-"} pada baris {line.adt_rowNumber or "-"}.'
                            )

                        single_move_vals = {
                            'name': line.adt_TransactionDescription or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': line_source_location.id,
                            'location_dest_id': picking.location_dest_id.id,
                            # 'description_picking': product.name or False,
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
                        update_line_snapshots.append((line, product, qty, uom or product.uom_id))

                    # DI LUAR LOOP: Eksekusi pembuatan seluruh Stock Move secara massal (Bulk Create)
                    if moves_to_create:
                        created_moves = Move.create(moves_to_create)
                        if action_state == 'updated':
                            for (source_line, product, qty, uom), created_move in zip(update_line_snapshots, created_moves):
                                line_key = str(source_line.adt_external_id or source_line.adt_rowNumber or source_line.adt_InventoryID or created_move.id)
                                old = previous_moves.pop(line_key, None)
                                label = source_line.adt_rowNumber or source_line.adt_InventoryID or '?'
                                current = {'Produk': product.display_name or '—', 'Jumlah': f'{qty:g}', 'Satuan': uom.display_name or '—', 'Lokasi tujuan': created_move.location_dest_id.display_name or '—', 'Deskripsi': created_move.name or '—'}
                                if old:
                                    previous = {'Produk': old['product'], 'Jumlah': f"{old['qty']:g}", 'Satuan': old['uom'], 'Lokasi tujuan': old['destination'], 'Deskripsi': old['name']}
                                    changes = [f'{name}: {previous[name]} → {value}' for name, value in current.items() if previous[name] != value]
                                    if changes:
                                        update_messages.append(f"• Baris {label}: " + '; '.join(changes))
                                else:
                                    update_messages.append(f"• Baris {label}: {product.display_name}, jumlah {qty:g} {uom.display_name} ditambahkan")

                    # Keep automatic processing, using normal stock reservation
                    # and validation from each staging line's source warehouse.
                    picking.action_confirm()
                    picking.action_assign()
                    self._check_invoice_consignment_reserved_qty(picking, first_reference)
                    validation_action = picking.button_validate()
                    picking._process_document_only_validation_action(validation_action)

                    # Tulis status sukses ke tabel staging kustom
                    first.write({
                        'import_state': action_state,
                        'import_message': 'success',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(first_reference, 'invoice_consignment')
                    if action_state == 'updated':
                        update_messages.extend(f"• Baris {old['label']}: {old['product']} dihapus" for old in previous_moves.values())
                        self.env['acumatica.webhook.error.service'].send_user_error(
                            webhook_type='import', webhook_name='Invoice Consignment',
                            transaction_name=first_reference or str(first.id), event_type='update',
                            message='\n'.join(update_messages) or 'Invoice Consignment berhasil disinkronkan; tidak ada field yang berubah.',
                        )
                    
                    if action_state == 'created':
                        created += 1
                    else:
                        updated += 1

            except Exception as e:
                # KOREKSI 2: Penanganan komplit jika dokumen ini gagal (Otomatis skip ke index loop selanjutnya)
                error += 1
                error_text = str(e).lower()
                if 'picking type' in error_text or 'operation type' in error_text:
                    user_message = f"Operation Type untuk Invoice Consignment {first_reference or '-'} belum tersedia. Minta admin memeriksa pengaturan tipe operasi di WMS."
                elif 'location cons' in error_text or 'consignment' in error_text or 'end user consignment' in error_text:
                    user_message = f"Lokasi consignment untuk Invoice {first_reference or '-'} belum tersedia. Periksa konfigurasi lokasi consignment di WMS."
                elif 'product tidak ditemukan' in error_text:
                    user_message = f"Produk pada Invoice Consignment {first_reference or '-'} belum terdaftar. Periksa master produk di WMS."
                elif 'reserved' in error_text or 'quantity' in error_text or 'qty' in error_text:
                    user_message = f"Stok untuk Invoice Consignment {first_reference or '-'} belum mencukupi. Periksa stok produk di lokasi consignment."
                elif 'sudah ada di odoo' in error_text or 'tidak bisa diupdate' in error_text:
                    user_message = f"Invoice Consignment {first_reference or '-'} tidak dapat diperbarui karena dokumen di WMS sudah diproses. Hubungi admin jika perubahan diperlukan."
                else:
                    user_message = False
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
                if user_message:
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type='import', webhook_name='Invoice Consignment',
                        transaction_name=first_reference or str(first.id), event_type='error', message=user_message,
                    )
                else:
                    self.env['acumatica.webhook.error.service'].send_error(
                        webhook_type='import', webhook_name='Invoice Consignment',
                        error=str(e), error_type='unexpected',
                    )

        msg = f'Generate done: {created} invoice consignment created, {updated} invoice consignment updated, {error} invoice consignment error.'
        print(f"[SUMMARY SINKRONISASI] Created: {created}, Updated: {updated}, Error: {error}")
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Generate Invoice Consignment',
        #         'message': msg,
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
    adt_LineBranchName = fields.Char(string='Acumatica Detail LineBranchName')
    adt_InventoryID = fields.Char(string='Acumatica Detail Inventory ID')
    adt_LineNoteID = fields.Char(string='Acumatica Detail LineNoteID')
    adt_NoteID = fields.Char(string='Acumatica Detail NoteID')
    adt_Qty = fields.Char(string='Acumatica Detail Quantity')
    adt_TransactionDescription = fields.Char(string='Acumatica Detail Transaction Description')
    adt_UOM = fields.Char(string='Acumatica Detail UOM')
    adt_Warehouse = fields.Char(string='Acumatica Detail Warehouse')

    # line_external_id = fields.Char(
    #     string='Line External ID',
    #     ,
    #     index=True,
    # )

    # line_note = fields.Text(
    #     string='Line Note',
    #     ,
    # )

    # branch_warehouse = fields.Char(
    #     string='Branch',
    #     ,
    # )

    # line_description = fields.Char(
    #     string='Description',
    #     ,
    # )

    # inventory_id = fields.Char(
    #     string='Inventory ID',
    #     ,
    #     index=True,
    # )

    # line_nbr = fields.Integer(
    #     string='Line Number',
    #     ,
    # )

    # location_code = fields.Char(
    #     string='Location',
    #     ,
    # )

    # product_uom_qty = fields.Float(
    #     string='Quantity',
    #     digits=(16, 4),
    #     ,
    # )

    # uom_code = fields.Char(
    #     string='UOM',
    #     ,
    # )

    # warehouse_code = fields.Char(
    #     string='Warehouse',
    #     ,
    # )
