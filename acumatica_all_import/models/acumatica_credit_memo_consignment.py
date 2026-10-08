from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from dateutil import parser as dateutil_parser


class AcumaticaVendorReturnDirectTransferStaging(models.Model):
    _name = 'acumatica.credit.memo.consignment.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Staging Header Acumatica Credit Memo Consignment'
    _order = 'id desc'

    # --- Relasi Odoo ---
    config_id = fields.Many2one('acumatica.config', string="Konfigurasi API")
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")
    odoo_picking_id = fields.Many2one('stock.picking', string="Odoo Stock Picking")
    line_ids = fields.One2many(
        'acumatica.credit.memo.consignment.staging.line', 
        'receipt_line_id', 
        string="Detail Lines"
    )

    # --- Status Sinkronisasi Intern ---
    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error')
    ], string='Status', default='staged', index=True, tracking=True)
    import_message = fields.Text(string="Generation Message", tracking=True)
    sync_date = fields.Datetime(string="Tanggal Ambil Data")
    selected = fields.Boolean(string="Pilih", default=True)
    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')



    # --- Pemetaan Data Header (Dari JSON Utama Acumatica) ---
    adt_id = fields.Char(string="Acumatica ID")
    adt_rowNumber = fields.Char(string="Acumatica Row Number")
    adt_note = fields.Char(string="Acumatica Note")
    adt_BuildingID = fields.Char(string="Acumatica BuildingID")
    adt_ConsignmentType = fields.Char(string="Acumatica ConsignmentType")
    adt_CreatedDateTime = fields.Char(string="Acumatica CreatedDateTime")
    adt_CustomerID = fields.Char(string="Acumatica CustomerID")
    adt_CustomerName = fields.Char(string="Acumatica CustomerName")
    adt_CustomerOrder = fields.Char(string="Acumatica CustomerOrder")
    adt_Date = fields.Char(string="Acumatica Date")
    adt_Description = fields.Char(string="Acumatica Description")
    adt_DocumentOnly = fields.Boolean(string="Acumatica DocumentOnly")
    adt_DueDate = fields.Char(string="Acumatica DueDate")
    adt_ExternalRef = fields.Char(string="Acumatica ExternalRef")
    adt_LastModifiedDateTime = fields.Char(string="Acumatica LastModifiedDateTime")
    adt_LocationID = fields.Char(string="Acumatica LocationID")
    adt_LocationName = fields.Char(string="Acumatica LocationName")
    adt_NoteHeaderID = fields.Char(string="Acumatica NoteHeaderID")
    adt_OrigRefNbr = fields.Char(string="Acumatica OrigRefNbr")
    adt_PostPeriod = fields.Char(string="Acumatica PostPeriod")
    adt_ReferenceNbr = fields.Char(string="Acumatica ReferenceNbr")
    adt_Status = fields.Char(string="Acumatica Status")
    adt_TotalQty = fields.Float(string="Acumatica TotalQty")
    adt_TransferType = fields.Char(string="Acumatica TransferType")
    adt_FromWarehouseID = fields.Char(string="Acumatica FromWarehouseID")
    adt_ToWarehouseID = fields.Char(string="Acumatica ToWarehouseID")
    adt_Type = fields.Char(string="Acumatica Type")

    total_qty = fields.Float(
        string="Qty Total (Lines)", 
        compute="_compute_total_qty", 
        store=True
    )

    # Tambahkan fungsi compute ini di bagian bawah kelas
    @api.depends('line_ids.adt_Qty')  # Pastikan nama field di child table sesuai (adt_Quantity atau adt_Qty)
    def _compute_total_qty(self):
        for rec in self:
            total = 0.0
            for line in rec.line_ids:
                try:
                    # Ambil nilai kuantitas dari line, ubah ke float jika tipenya Char/String di database
                    total += float(line.adt_Qty or 0.0)
                except (ValueError, TypeError):
                    total += 0.0
            rec.total_qty = total

    # =========================================================================
    # CORE PROCESS FUNCTIONS FOR Credit Memo Consignment IMPORT
    # =========================================================================

    @api.depends('adt_ReferenceNbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.adt_ReferenceNbr and Picking.search_count([('origin', '=', rec.adt_ReferenceNbr)]))

    def action_import_selected(self):
        """Memicu proses impor massal untuk record yang dicentang user"""
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_reset_pending(self):
        self.filtered(lambda record: record.import_state == 'error').write({
            'import_state': 'staged',
            'import_message': False,
        })
        return True

    def action_import_this(self):
        """Memicu proses impor khusus untuk 1 record aktif"""
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _find_consignment_location(self, warehouse_code):
        """Resolve each detail line's source CONS location like Invoice Consignment."""
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
            consignment_code = code.split('-', 1)[1].strip() if '-' in code else code
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
                if code.upper() in {'CONS', f'{building_code}-CONS'}:
                    return cons_root

        return Location.browse()

    def _get_credit_memo_consignment_destination_location(self):
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

    def _do_import(self):
        """Fungsi utama eksekusi pembuatan dokumen Stock Picking & Stock Move"""
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']

        created = 0
        updated = 0
        error = 0

        # Ambil daftar unik reference number agar tidak memproses dokumen yang sama berulang kali
        for reference_nbr in self.mapped('adt_ReferenceNbr'):
            receipt_lines = self.filtered(
                lambda l: l.adt_ReferenceNbr == reference_nbr and l.import_state in ['staged', 'error']
            )
            if not receipt_lines:
                continue

            # Karena model bertipe multi-recordset, ambil baris header pertamanya secara aman
            first = receipt_lines[0]
            origin = first.adt_ReferenceNbr or False

            # Ambil seluruh baris data item (Lines) yang berelasi dengan header ini
            to_create_move_lines = first.line_ids
            update_messages = []

            print(f"Move Line count: {len(to_create_move_lines)}")

            try:
                # 1. PROTEKSI UTAMA (SAVEPOINT PER DOKUMEN): 
                # Jika lines bermasalah, pembuatan picking otomatis dibatalkan bersih (Rollback)
                with self.env.cr.savepoint():
                    print(f"[Credit Memo Consignment] Processing Document: {origin}")

                    staging_line = self.env['acumatica.credit.memo.consignment.staging.line'].search([('receipt_line_id', '=', first.id)], limit=1)
                    if not staging_line:
                        raise UserError(f"Detail line belum ada untuk header staging ID {first.id}.")

                    # Tentukan jenis operasi picking (Operation Type)
                    warehouse_code = staging_line.adt_Warehouse
                    picking_type = self.env['stock.picking.type'].resolve_document_only_picking_type(
                        target_operation_type='direct_delivery_order',
                        api_acumatica='credit_memo_consignment',
                        document_only=True,
                        warehouse_code=warehouse_code,
                        required=False,
                    )
                    if not picking_type:
                        raise UserError(f"Picking type (Operation Type) tidak ditemukan pada header staging ID {first.id}.")

                    source_location = self._find_consignment_location(warehouse_code)
                    dest_location = self._get_credit_memo_consignment_destination_location()
                    if not source_location:
                        raise UserError(
                            f'Lokasi CONS tidak ditemukan untuk warehouse {warehouse_code or "-"}.'
                        )
                    if not dest_location:
                        raise UserError(
                            'Lokasi Partners/End User Consignment tidak ditemukan.'
                        )


                    # Definisikan dictionary payload data stock.picking Odoo
                    vals = {
                        'picking_type_id': picking_type.id,
                        'location_id': source_location.id,
                        'location_dest_id': dest_location.id,
                        'scheduled_date': self._parse_dt(first.adt_Date),
                        'origin': origin,
                        'note': first.adt_note or False,
                        
                        # Sinkronisasi Field Kustom ke Tabel stock.picking (jika kolomnya eksis)
                        'adt_receipt_nbr': origin,
                        # 'adt_branch_warehouse': first.adt_PostPeriod or False,
                        'adt_acumatica_write_date': self._parse_dt(first.adt_LastModifiedDateTime),
                        'adt_status': first.adt_Status or False,
                        'adt_type': first.adt_Type or 'Credit Memo Consignment',
                        'adt_is_document_only': False,
                        'adt_external_id': first.adt_id or False,
                    }

                    # Filter field agar steril dari KeyError field kustom yang tidak terdaftar di stock.picking
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}

                    # Cek pencegahan duplikasi (Dedup Dokumen via Origin)
                    picking = Picking.search([('origin', '=', origin)], limit=1)
                    is_new_picking = False
                    previous_moves = {}
                    if picking and picking.state == 'draft':
                        update_messages.extend(self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                            picking, vals,
                            field_names={'picking_type_id', 'location_id', 'location_dest_id', 'scheduled_date', 'origin', 'note', 'adt_receipt_nbr', 'adt_acumatica_write_date', 'adt_status', 'adt_type', 'adt_is_document_only', 'adt_external_id'},
                            prefix='Header',
                        ))
                        for old_move in picking.move_ids:
                            key = str(old_move.adt_line_external_id or old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.id)
                            previous_moves[key] = {'label': old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.name, 'product': old_move.product_id.display_name or '—', 'qty': old_move.product_uom_qty, 'uom': old_move.product_uom.display_name or '—', 'destination': old_move.location_dest_id.display_name or '—', 'name': old_move.name or '—'}

                    if picking:
                        if picking.state != 'draft':
                            raise UserError(f"Dokumen {origin} sudah divalidasi di Odoo (State: {picking.state}), update digagalkan.")
                        picking.write(vals)
                        action_state = 'updated'
                        self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=origin)
                    else:
                        picking = Picking.create(vals)
                        is_new_picking = True
                        action_state = 'created'

                    if action_state == 'updated':
                        picking.move_ids.unlink()

                    # ---------------------------------------------------------
                    # BULK CREATION STOCK MOVES (DETAIL LINES)
                    # ---------------------------------------------------------
                    moves_to_create = []
                    update_line_snapshots = []

                    for line in to_create_move_lines:
                        # Cari data produk Odoo berdasarkan InventoryID Acumatica
                        product = self._find_product_by_code(line.adt_InventoryID, )
                        if not product:
                            raise UserError(f"Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or '-'}")

                        # Cari data satuan (UOM)
                        # uom = self._find_uom_by_name(line.adt_UOM, product)
                        qty = self._parse_float(line.adt_Qty)

                        # Tentukan lokasi detail per baris barang secara spesifik (jika ada)
                        line_loc_src = self._find_consignment_location(line.adt_Warehouse)
                        if not line_loc_src:
                            raise UserError(
                                f'Lokasi CONS tidak ditemukan untuk warehouse '
                                f'{line.adt_Warehouse or "-"} pada baris '
                                f'{line.adt_rowNumber or "-"}.'
                            )
                        line_loc_dest = picking.location_dest_id

                        # Bangun dictionary baris barang tunggal
                        single_move_vals = {
                            'name': product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': product.uom_id.id,
                            'location_id': line_loc_src.id,
                            'location_dest_id': line_loc_dest.id,
                            # 'description_picking': product.name or False,
                            
                            # Custom tracking audit trail
                            'adt_line_external_id': line.adt_id or False,
                            'adt_inventory_id': line.adt_InventoryID or False,
                            'adt_line_nbr': line.adt_rowNumber or False,
                            'adt_open_qty': qty,
                            'adt_order_qty': qty,
                            'adt_uom_code': line.adt_UOM or False,
                        }

                        # Sterilkan data dari Invalid Field khusus stock.move
                        single_move_vals = {k: v for k, v in single_move_vals.items() if k in Move._fields}
                        moves_to_create.append(single_move_vals)
                        update_line_snapshots.append((line, product, qty))

                    # Eksekusi pembuatan seluruh Stock Moves secara massal di luar perulangan
                    if moves_to_create:
                        created_moves = Move.create(moves_to_create)
                        if action_state == 'updated':
                            for (source_line, product, qty), created_move in zip(update_line_snapshots, created_moves):
                                line_key = str(source_line.adt_id or source_line.adt_rowNumber or source_line.adt_InventoryID or created_move.id)
                                old = previous_moves.pop(line_key, None)
                                label = source_line.adt_rowNumber or source_line.adt_InventoryID or '?'
                                current = {'Produk': product.display_name or '—', 'Jumlah': f'{qty:g}', 'Satuan': product.uom_id.display_name or '—', 'Lokasi tujuan': created_move.location_dest_id.display_name or '—', 'Deskripsi': created_move.name or '—'}
                                if old:
                                    previous = {'Produk': old['product'], 'Jumlah': f"{old['qty']:g}", 'Satuan': old['uom'], 'Lokasi tujuan': old['destination'], 'Deskripsi': old['name']}
                                    changes = [f'{name}: {previous[name]} → {value}' for name, value in current.items() if previous[name] != value]
                                    if changes:
                                        update_messages.append(f"• Baris {label}: " + '; '.join(changes))
                                else:
                                    update_messages.append(f"• Baris {label}: {product.display_name}, jumlah {qty:g} ditambahkan")

                    picking.action_confirm()
                    picking.action_assign()
                    validation_action = picking.button_validate()
                    picking._process_document_only_validation_action(validation_action)

                    # Kunci status dokumen jika seluruh perulangan sukses terlewati tanpa hambatan
                    first.write({
                        'import_state': action_state,
                        'import_message': 'success',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(reference_nbr, 'credit_memo_consignment')
                    if action_state == 'updated':
                        update_messages.extend(f"• Baris {old['label']}: {old['product']} dihapus" for old in previous_moves.values())
                        self.env['acumatica.webhook.error.service'].send_user_error(
                            webhook_type='import', webhook_name='Credit Memo Consignment',
                            transaction_name=origin or str(first.id), event_type='update',
                            message='\n'.join(update_messages) or 'Credit Memo Consignment berhasil disinkronkan; tidak ada field yang berubah.',
                        )

                    # Ubah juga status sub-tabel staging lines-nya agar sinkron di UI
                    # to_create_move_lines.write({
                    #     'import_state': action_state,
                    #     'import_message': 'Created successfully via bulk upload.',
                    # })

                    if is_new_picking:
                        created += 1
                    else:
                        updated += 1

            except Exception as e:
                # 2. STRATEGI PENANGANAN JIKA DOKUMEN ERROR:
                # Savepoint di atas membatalkan picking/move dokumen yang gagal.
                error += 1
                error_text = str(e).lower()
                if 'picking type' in error_text or 'operation type' in error_text:
                    user_message = f"Operation Type untuk Credit Memo Consignment {origin or '-'} belum tersedia. Minta admin memeriksa pengaturan tipe operasi di WMS."
                elif 'lokasi cons' in error_text or 'consignment' in error_text or 'end user consignment' in error_text:
                    user_message = f"Lokasi consignment untuk Credit Memo {origin or '-'} belum tersedia. Periksa konfigurasi lokasi consignment di WMS."
                elif 'product tidak ditemukan' in error_text:
                    user_message = f"Produk pada Credit Memo Consignment {origin or '-'} belum terdaftar. Periksa master produk di WMS."
                elif 'detail line belum ada' in error_text:
                    user_message = f"Credit Memo Consignment {origin or '-'} belum memiliki detail produk. Lengkapi detail transaksi."
                elif 'sudah divalidasi' in error_text or 'update digagalkan' in error_text:
                    user_message = f"Credit Memo Consignment {origin or '-'} tidak dapat diperbarui karena dokumen sudah diproses. Hubungi admin jika perubahan diperlukan."
                else:
                    user_message = False
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='credit_memo_consignment',
                    operation_type='delivery',
                    origin=reference_nbr,
                    partner=getattr(first, 'adt_CustomerID', False) or False,
                    location=getattr(first, 'adt_WarehouseID', False) or getattr(first, 'adt_LocationID', False) or False,
                    location_dest=getattr(first, 'adt_ToWarehouseID', False) or False,
                    scheduled_date=first.adt_Date,
                    total_qty=getattr(first, 'adt_TotalQty', False) or getattr(first, 'total_qty', 0.0),
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.adt_InventoryID or False,
                        'product_name': line.adt_TransactionDescription or False,
                        'qty': self._parse_float(line.adt_Qty),
                        'uom': line.adt_UOM or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in to_create_move_lines],
                )
                # Tulis pesan kegagalan ke UI Odoo agar user tahu detail masalahnya
                first.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': str(e),
                    'odoo_picking_id': False,
                })
                if user_message:
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type='import', webhook_name='Credit Memo Consignment',
                        transaction_name=origin or str(first.id), event_type='error', message=user_message,
                    )
                else:
                    self.env['acumatica.webhook.error.service'].send_error(
                        webhook_type='import', webhook_name='Credit Memo Consignment',
                        error=str(e), error_type='unexpected',
                    )
                print(f"[ERROR SINKRONISASI] Dokumen {reference_nbr} Gagal: {str(e)}")

        msg = f'Generate done: {created} credit memo consignment created, {updated} credit memo consignment updated, {error} credit memo consignment error.'
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Generate Credit Memo Consignment',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }
                
    def _find_warehouse_by_code(self, code):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if code:
            warehouse = Warehouse.search([('code', '=', code), ('is_active', '=', True)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse
    
    def _find_product_by_code(self, code):
        """
        Fungsi untuk mencari Product Odoo berdasarkan kode Inventory ID dari Acumatica
        """
        Product = self.env['product.product']
        product = False
        
        if code:
            # 1. Opsi standar: Cari berdasarkan 'default_code' (Internal Reference Odoo)
            product = Product.search([('default_code', '=', code), ('active', '=', True)], limit=1)
            
            # 2. Opsi alternatif kustom: Jika Anda memiliki tabel mapping tersendiri 
            # seperti stock.location.acumatica di atas, gunakan kode di bawah ini (uncomment jika perlu):
            # ProductAcumatica = self.env['product.acumatica.mapping'] # Ganti nama model mapping Anda
            # mapping = ProductAcumatica.search([('code', '=', code)], limit=1)
            # if mapping:
            #     product = mapping.odoo_product_id

        return product

    @staticmethod
    def _parse_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

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



class AcumaticaVendorReturnDirectTransferStagingLine(models.Model):
    _name = 'acumatica.credit.memo.consignment.staging.line'
    _description = 'Staging Detail/Line Acumatica Credit Memo Consignment'
    _order = 'id desc'

    # --- Relasi Induk (ke Header) ---
    receipt_line_id = fields.Many2one(
        'acumatica.credit.memo.consignment.staging', 
        string="Header Reference", 
        ondelete='cascade', 
        index=True
    )

    # --- Pemetaan Data Baris Barang (Details JSON Array) ---
    adt_id = fields.Char(string="Acumatica Id")
    adt_rowNumber = fields.Char(string="Acumatica RowNumber")
    adt_note = fields.Char(string="Acumatica Note")
    adt_Branch = fields.Char(string="Acumatica Branch")
    adt_InventoryID = fields.Char(string="Acumatica InventoryID")
    adt_LineNoteID = fields.Char(string="Acumatica LineNoteID")
    adt_Qty = fields.Char(string="Acumatica Qty")
    adt_TransactionDescription = fields.Char(string="Acumatica TransactionDescription")
    adt_UOM = fields.Char(string="Acumatica UOM")
    adt_Warehouse = fields.Char(string="Acumatica Warehouse")
