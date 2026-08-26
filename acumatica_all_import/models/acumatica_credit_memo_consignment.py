from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from dateutil import parser as dateutil_parser


class AcumaticaVendorReturnDirectTransferStaging(models.Model):
    _name = 'acumatica.credit.memo.consignment.staging'
    _description = 'Staging Header Acumatica Credit Memo Consignment'
    _order = 'id desc'

    # --- Relasi Odoo ---
    config_id = fields.Many2one('acumatica.credit.memo.consignment.config', string="Konfigurasi API")
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")
    odoo_picking_id = fields.Many2one('stock.picking', string="Odoo Stock Picking")
    line_ids = fields.One2many(
        'acumatica.credit.memo.consignment.staging.line', 
        'receipt_line_id', 
        string="Detail Lines"
    )

    # --- Status Sinkronisasi Intern ---
    import_state = fields.Selection([
        ('pending', 'Pending'),
        ('imported', 'Imported'),
        ('updated', 'Updated'),
        ('error', 'Error')
    ], string="Status Impor", default='pending', index=True)
    import_message = fields.Text(string="Pesan Impor/Error")
    sync_date = fields.Datetime(string="Tanggal Ambil Data")
    selected = fields.Boolean(string="Pilih", default=True)
    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')



    # --- Pemetaan Data Header (Dari JSON Utama Acumatica) ---
    adt_id = fields.Char(string="Acumatica ID")
    adt_rowNumber = fields.Char(string="Acumatica Row Number")
    adt_note = fields.Char(string="Acumatica Note")
    adt_ConsignmentType = fields.Char(string="Acumatica ConsignmentType")
    adt_CreatedDateTime = fields.Char(string="Acumatica CreatedDateTime")
    adt_CustomerID = fields.Char(string="Acumatica CustomerID")
    adt_CustomerName = fields.Char(string="Acumatica CustomerName")
    adt_CustomerOrder = fields.Char(string="Acumatica CustomerOrder")
    adt_Date = fields.Char(string="Acumatica Date")
    adt_Description = fields.Char(string="Acumatica Description")
    adt_DocumentOnly = fields.Boolean(string="Acumatica DocumentOnly", readonly=True)
    adt_DueDate = fields.Char(string="Acumatica DueDate")
    adt_LastModifiedDateTime = fields.Char(string="Acumatica LastModifiedDateTime")
    adt_LocationID = fields.Char(string="Acumatica LocationID")
    adt_LocationName = fields.Char(string="Acumatica LocationName")
    adt_OrigRefNbr = fields.Char(string="Acumatica OrigRefNbr")
    adt_ReferenceNbr = fields.Char(string="Acumatica ReferenceNbr")
    adt_Status = fields.Char(string="Acumatica Status")
    adt_Type = fields.Char(string="Acumatica Type")

    total_qty = fields.Float(
        string="Total Qty (Lines)", 
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
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        """Memicu proses impor khusus untuk 1 record aktif"""
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        """Fungsi utama eksekusi pembuatan dokumen Stock Picking & Stock Move"""
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']

        imported = 0
        updated = 0
        error = 0

        # Ambil daftar unik reference number agar tidak memproses dokumen yang sama berulang kali
        for reference_nbr in self.mapped('adt_ReferenceNbr'):
            receipt_lines = self.filtered(
                lambda l: l.adt_ReferenceNbr == reference_nbr and l.import_state in ['pending', 'error']
            )
            if not receipt_lines:
                continue

            # Karena model bertipe multi-recordset, ambil baris header pertamanya secara aman
            first = receipt_lines[0]
            origin = first.adt_ReferenceNbr or False

            # Ambil seluruh baris data item (Lines) yang berelasi dengan header ini
            to_create_move_lines = first.line_ids

            print(f"Move Line count: {len(to_create_move_lines)}")

            try:
                # 1. PROTEKSI UTAMA (SAVEPOINT PER DOKUMEN): 
                # Jika lines bermasalah, pembuatan picking otomatis dibatalkan bersih (Rollback)
                with self.env.cr.savepoint():
                    print(f"[Credit Memo Consignment] Processing Document: {origin}")

                    # Tentukan jenis operasi picking (Operation Type)
                    picking_type = first.picking_type_id
                    if not picking_type:
                        raise UserError(f"Picking type (Operation Type) belum diatur pada header staging ID {first.id}.")

                    staging_line = self.env['acumatica.credit.memo.consignment.staging.line'].search([('receipt_line_id', '=', first.id)], limit=1)

                    # Cari master data gudang asal (FromWarehouseID)
                    warehouse_src = self._find_warehouse_by_code(staging_line.adt_Warehouse)
                    if not warehouse_src:
                        raise UserError(f"Gudang tidak ditemukan untuk code: {staging_line.adt_Warehouse or '-'}")

                    source_location = picking_type.default_location_src_id or warehouse_src.lot_stock_id
                    dest_location = warehouse_src.lot_stock_id
                    if not source_location:
                        raise UserError(f"Lokasi asal tidak ditemukan untuk code: {staging_line.adt_Warehouse or '-'}")
                    if not dest_location:
                        raise UserError(f"Lokasi tujuan tidak ditemukan untuk code: {staging_line.adt_Warehouse or '-'}")
                    if dest_location.usage == 'customer':
                        raise UserError("Lokasi tujuan customer hanya boleh dipakai oleh SO Shipment.")


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
                        # 'adt_type': first.adt_Type or False,
                        'adt_external_id': first.adt_id or False,
                    }

                    # Filter field agar steril dari KeyError field kustom yang tidak terdaftar di stock.picking
                    vals = {k: v for k, v in vals.items() if k in Picking._fields}

                    # Cek pencegahan duplikasi (Dedup Dokumen via Origin)
                    picking = Picking.search([('origin', '=', origin)], limit=1)
                    is_new_picking = False

                    if picking:
                        if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                            raise UserError(f"Dokumen {origin} sudah divalidasi di Odoo (State: {picking.state}), update digagalkan.")
                        picking.write(vals)
                        action_state = 'updated'
                    else:
                        picking = Picking.create(vals)
                        is_new_picking = True
                        action_state = 'imported'

                    # ---------------------------------------------------------
                    # BULK CREATION STOCK MOVES (DETAIL LINES)
                    # ---------------------------------------------------------
                    moves_to_create = []

                    for line in to_create_move_lines:
                        # Cari data produk Odoo berdasarkan InventoryID Acumatica
                        product = self._find_product_by_code(line.adt_InventoryID, )
                        if not product:
                            raise UserError(f"Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or '-'}")

                        # Cari data satuan (UOM)
                        # uom = self._find_uom_by_name(line.adt_UOM, product)
                        qty = self._parse_float(line.adt_Qty)

                        # Tentukan lokasi detail per baris barang secara spesifik (jika ada)
                        line_loc_src = picking.location_id
                        line_loc_dest = picking.location_dest_id

                        # DEDUP LOGIKA: Mengunci kombinasi ID Produk + Nomor Baris asli Acumatica
                        move_domain = [('picking_id', '=', picking.id)]
                        if 'adt_line_external_id' in Move._fields and line.adt_id:
                            move_domain.append(('adt_line_external_id', '=', line.adt_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('adt_line_nbr', '=', line.adt_rowNumber or False)
                            ]

                        existing_move = Move.search(move_domain, limit=1)
                        if existing_move:
                            continue

                        # Bangun dictionary baris barang tunggal
                        single_move_vals = {
                            'name': product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': product.uom_id.id,
                            'location_id': line_loc_src.id,
                            'location_dest_id': line_loc_dest.id,
                            # 'description_picking': line.adt_Description or False,
                            
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

                    # Eksekusi pembuatan seluruh Stock Moves secara massal di luar perulangan
                    if moves_to_create:
                        Move.create(moves_to_create)

                    # Kunci status dokumen jika seluruh perulangan sukses terlewati tanpa hambatan
                    first.write({
                        'import_state': action_state,
                        'import_message': f'Sukses diproses ke Odoo ({picking.name})',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.tracking.mixin']._resolve_error_tracking(reference_nbr, 'credit_memo_consignment')

                    # Ubah juga status sub-tabel staging lines-nya agar sinkron di UI
                    # to_create_move_lines.write({
                    #     'import_state': action_state,
                    #     'import_message': 'Imported successfully via bulk upload.',
                    # })

                    if is_new_picking:
                        imported += 1
                    else:
                        updated += 1

            except Exception as e:
                # 2. STRATEGI PENANGANAN JIKA DOKUMEN ERROR:
                # Savepoint di atas membatalkan picking/move dokumen yang gagal.
                error += 1
                self.env['acumatica.error.tracking.mixin']._persist_error_tracking(
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
                        'product_name': line.adt_Description or False,
                        'qty': self._parse_float(line.adt_Qty),
                        'uom': line.adt_UOM or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in to_create_move_lines],
                )
                # Tulis pesan kegagalan ke UI Odoo agar user tahu detail masalahnya
                first.write({
                    'import_state': 'error',
                    'import_message': str(e),
                    'odoo_picking_id': False,
                })
                print(f"[ERROR SINKRONISASI] Dokumen {reference_nbr} Gagal: {str(e)}")
                
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
    adt_Qty = fields.Char(string="Acumatica Qty")
    adt_TransactionDescription = fields.Char(string="Acumatica TransactionDescription")
    adt_UOM = fields.Char(string="Acumatica UOM")
    adt_Warehouse = fields.Char(string="Acumatica Warehouse")
