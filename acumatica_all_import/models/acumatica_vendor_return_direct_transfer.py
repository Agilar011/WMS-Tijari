from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from dateutil import parser as dateutil_parser


class AcumaticaVendorReturnDirectTransferStaging(models.Model):
    _name = 'acumatica.vendor.return.direct.transfer.staging'
    _description = 'Staging Header Acumatica Direct Transfer'
    _order = 'id desc'

    # --- Relasi Odoo ---
    config_id = fields.Many2one('acumatica.direct.transfer.config', string="Konfigurasi API")
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")
    odoo_picking_id = fields.Many2one('stock.picking', string="Odoo Stock Picking")
    line_ids = fields.One2many(
        'acumatica.vendor.return.direct.transfer.staging.line', 
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

    # --- Pemetaan Data Header (Dari JSON Utama Acumatica) ---
    adt_id = fields.Char(string="Acumatica Guid ID")
    adt_rowNumber = fields.Integer(string="Row Number")
    adt_note = fields.Char(string="Note Header")
    adt_Date = fields.Char(string="Transfer Date")
    adt_Description = fields.Char(string="Description Header")
    adt_DocumentOnly = fields.Char(string="Document Only")
    adt_ExternalRef = fields.Char(string="External Ref")
    adt_FromWarehouseID = fields.Char(string="From Warehouse ID")
    adt_Hold = fields.Boolean(string="Hold Status")
    adt_LastModifiedDateTime = fields.Char(string="Last Modified Date Time")
    adt_NoteID = fields.Char(string="Note ID Header")
    adt_PostPeriod = fields.Char(string="Post Period")
    adt_ReferenceNbr = fields.Char(string="Reference Number", index=True)
    adt_ReturnType = fields.Char(string="Return Type")
    adt_Status = fields.Char(string="Acumatica Status")
    adt_TotalQty = fields.Float(string="Total Quantity")
    adt_ToWarehouseID = fields.Char(string="To Warehouse ID")
    adt_TransferType = fields.Char(string="Transfer Type")
    adt_TransType = fields.Char(string="Transaction Type")

    # =========================================================================
    # CORE PROCESS FUNCTIONS FOR DIRECT TRANSFER IMPORT
    # =========================================================================

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
                    print(f"[DIRECT TRANSFER] Processing Document: {origin}")

                    # Tentukan jenis operasi picking (Operation Type)
                    picking_type = first.picking_type_id
                    if not picking_type:
                        raise UserError(f"Picking type (Operation Type) belum diatur pada header staging ID {first.id}.")

                    # Cari master data gudang asal (FromWarehouseID)
                    warehouse_src = self._find_warehouse_by_code(first.adt_FromWarehouseID)
                    if not warehouse_src:
                        warehouse_src = picking_type.default_location_src_id.id
                        # raise UserError(f"Gudang asal tidak ditemukan untuk code: {first.adt_FromWarehouseID or '-'}")

                    # Cari master data gudang tujuan (ToWarehouseID)
                    warehouse_dest = self._find_warehouse_by_code(first.adt_ToWarehouseID)
                    if not warehouse_dest:
                        warehouse_dest = picking_type.default_location_desc_id.id
                        raise UserError(f"Gudang tujuan tidak ditemukan untuk code: {first.adt_ToWarehouseID or '-'}")


                    # Definisikan dictionary payload data stock.picking Odoo
                    vals = {
                        'picking_type_id': picking_type.id,
                        'location_id': picking_type.default_location_src_id.id or warehouse_src.lot_stock_id.id,
                        'location_dest_id': picking_type.default_location_dest_id.id or warehouse_dest.lot_stock_id.id,
                        'scheduled_date': self._parse_dt(first.adt_Date),
                        'origin': origin,
                        'note': first.adt_note or False,
                        
                        # Sinkronisasi Field Kustom ke Tabel stock.picking (jika kolomnya eksis)
                        'adt_receipt_nbr': origin,
                        'adt_branch_warehouse': first.adt_PostPeriod or False,
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
                        product = self._find_product_by_code(line.adt_InventoryID, line.adt_Description)
                        if not product:
                            raise UserError(f"Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or '-'}")

                        # Cari data satuan (UOM)
                        uom = self._find_uom_by_name(line.adt_UOM, product)
                        qty = self._parse_float(line.adt_Quantity)

                        # Tentukan lokasi detail per baris barang secara spesifik (jika ada)
                        line_loc_src = self._find_location_by_code(line.adt_FromLocationID, warehouse_src) or picking.location_id
                        line_loc_dest = self._find_location_by_code(line.adt_ToLocationID, warehouse_dest) or picking.location_dest_id

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
                            'name': line.adt_Description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': line_loc_src.id,
                            'location_dest_id': line_loc_dest.id,
                            'description_picking': line.adt_Description or False,
                            
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

                    # Ubah juga status sub-tabel staging lines-nya agar sinkron di UI
                    to_create_move_lines.write({
                        'import_state': action_state,
                        'import_message': 'Imported successfully via bulk upload.',
                    })

                    if is_new_picking:
                        imported += 1
                    else:
                        updated += 1

            except Exception as e:
                # 2. STRATEGI PENANGANAN JIKA DOKUMEN ERROR:
                # Batalkan transaksi database (Picking dihapus total dari SQL memory)
                error += 1
                self.env.cr.rollback()

                # Tulis pesan kegagalan ke UI Odoo agar user tahu detail masalahnya
                first.write({
                    'import_state': 'error',
                    'import_message': str(e),
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
    _name = 'acumatica.vendor.return.direct.transfer.staging.line'
    _description = 'Staging Detail/Line Acumatica Direct Transfer'
    _order = 'id desc'

    # --- Relasi Induk (ke Header) ---
    receipt_line_id = fields.Many2one(
        'acumatica.vendor.return.direct.transfer.staging', 
        string="Header Reference", 
        ondelete='cascade', 
        index=True
    )

    # --- Pemetaan Data Baris Barang (Details JSON Array) ---
    adt_id = fields.Char(string="Line Guid ID")
    adt_rowNumber = fields.Integer(string="Line Row Number")
    adt_note = fields.Char(string="Line Note")
    adt_Description = fields.Char(string="Line Description")
    adt_FromLocationID = fields.Char(string="From Location ID")
    adt_InventoryID = fields.Char(string="Inventory ID", index=True)
    adt_LineNumber = fields.Integer(string="Line Number")
    adt_NoteID = fields.Char(string="Note ID Line")
    adt_Quantity = fields.Float(string="Quantity")
    adt_SOOrderNbr = fields.Char(string="SO Order Number")
    adt_SOOrderType = fields.Char(string="SO Order Type")
    adt_SOShipmentNbr = fields.Char(string="SO Shipment Number")
    adt_ToLocationID = fields.Char(string="To Location ID")
    adt_UOM = fields.Char(string="Unit of Measure")
