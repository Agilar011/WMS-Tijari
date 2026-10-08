from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from dateutil import parser as dateutil_parser


class AcumaticaDirectTransferStaging(models.Model):
    _name = 'acumatica.direct.transfer.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Staging Header Acumatica Direct Transfer'
    _order = 'id desc'

    def _adt_picking_type_wizard_call(self):
        if not self.adt_FromWarehouseID:
            return False
        return (
            'import.direct.transfer.wizard',
            ({'adt_FromWarehouseID': self.adt_FromWarehouseID, 'adt_DocumentOnly': self.adt_DocumentOnly},),
            {},
        )

    # --- Relasi Odoo ---
    config_id = fields.Many2one('acumatica.config', string="Konfigurasi API")
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")
    odoo_picking_id = fields.Many2one('stock.picking', string="Odoo Stock Picking")
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order',
    )
    line_ids = fields.One2many(
        'acumatica.direct.transfer.staging.line', 
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
    ], string="Status", default='staged', index=True)
    import_message = fields.Text(string="Generation Message")
    sync_date = fields.Datetime(string="Tanggal Ambil Data")
    selected = fields.Boolean(string="Pilih", default=True)

    # --- Pemetaan Data Header (Dari JSON Utama Acumatica) ---
    adt_id = fields.Char(string="Acumatica Guid ID")
    adt_rowNumber = fields.Integer(string="Row Number")
    adt_note = fields.Char(string="Note Header")
    adt_Date = fields.Char(string="Transfer Date")
    adt_Description = fields.Char(string="Description Header")
    adt_DocumentOnly = fields.Boolean(string="Document Only")
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

    def _get_vendor_return_document_source_location(self, first):
        """Resolve Vendor Return Document source from the consignment location.

        ``FromWarehouseID`` is a consignment identifier for this API flow, not
        an Odoo location mapping code.  Keep this lookup aligned with the
        Vendor Return staging flow and do not require an
        ``stock.location.acumatica.odoo_location_id`` for the source.
        """
        Location = self.env['stock.location']
        warehouse_code = (first.adt_FromWarehouseID or '').strip()
        normalized_code = (
            warehouse_code.split('-', 1)[1].strip()
            if '-' in warehouse_code
            else warehouse_code
        )
        source_locations = Location.search([
            ('name', 'in', list({warehouse_code, normalized_code} - {''})),
            ('is_consignment', '=', True),
        ], order='id')
        def is_consignment_branch(location):
            current = location.location_id
            while current:
                if (current.name or '').strip().upper() in {'CONS', 'CONSIGNMENT'}:
                    return True
                current = current.location_id
            return False

        source_location = source_locations.filtered(is_consignment_branch)[:1]
        if not source_location:
            source_location = source_locations[:1]
        if not source_location:
            raise UserError(
                f'Lokasi consignment tidak ditemukan untuk FromWarehouseID '
                f'{first.adt_FromWarehouseID or "-"}.'
            )
        return source_location

    def action_import_this(self):
        """Memicu proses impor khusus untuk 1 record aktif"""
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _do_import(self):
        """Import Vendor Return Document as Inter Warehouse / Transfer In."""
        TransferService = self.env['acumatica.internal.transfer.service']

        imported = 0
        updated = 0
        error = 0

        for reference_nbr in self.mapped('adt_ReferenceNbr'):
            receipt_lines = self.filtered(
                lambda l: l.adt_ReferenceNbr == reference_nbr
                and l.import_state in ['staged', 'error']
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]
            origin = first.adt_ReferenceNbr or False
            to_create_move_lines = first.line_ids
            update_messages = []

            try:
                with self.env.cr.savepoint():
                    source_location = self._get_vendor_return_document_source_location(first)
                    destination_mapping = TransferService._find_location_mapping(
                        first.adt_ToWarehouseID,
                        'ToWarehouseID',
                    )
                    destination_location = (
                        destination_mapping.odoo_location_id
                        if destination_mapping else False
                    )
                    if not destination_location:
                        raise UserError(
                            f'Lokasi tujuan belum ter-mapping untuk '
                            f'ToWarehouseID {first.adt_ToWarehouseID or "-"}.'
                        )

                    if not to_create_move_lines:
                        raise UserError(f'Transfer {origin or "-"} tidak memiliki detail produk.')

                    existing_order = self.env['internal.transfer.order'].search([
                        ('external_ref', '=', origin),
                    ], limit=1)
                    previous_moves = {}
                    if existing_order:
                        for old_move in existing_order.move_ids:
                            key = str(old_move.adt_line_external_id or old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.id)
                            previous_moves[key] = {
                                'label': old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.name,
                                'product': old_move.product_id.display_name or '—',
                                'qty': old_move.product_uom_qty,
                                'uom': old_move.product_uom.display_name or '—',
                                'destination': old_move.location_dest_id.display_name or '—',
                                'name': old_move.name or '—',
                            }
                        update_messages.extend(self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                            existing_order,
                            {
                                'external_ref_in': origin,
                                'external_ref_out': origin,
                                'transaction_type': 'inter_warehouse',
                                'transfer_type': 'transfer_in',
                                'location_id': source_location.id,
                                'location_dest_id': destination_location.id,
                                'schedule_date': self._parse_dt(first.adt_Date) or fields.Datetime.now(),
                                'note': first.adt_note or False,
                                'description': first.adt_Description or False,
                                'adt_transaction_type': 'Vendor Return Document',
                                'document_only': True,
                            },
                            field_names={'external_ref_in', 'external_ref_out', 'transaction_type', 'transfer_type', 'location_id', 'location_dest_id', 'schedule_date', 'note', 'description', 'adt_transaction_type', 'document_only'},
                            prefix='Header',
                        ))
                        update_messages.extend(self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                            existing_order,
                            {'adt_order_type': first.adt_TransferType or first.adt_TransType or first.adt_ReturnType or False},
                            field_names={'adt_order_type'},
                            prefix='Header',
                        ))

                    order, action_state = TransferService.prepare_order(
                        origin,
                        source_location,
                        destination_location,
                        'inter_warehouse',
                        self._parse_dt(first.adt_Date),
                        first.adt_note or False,
                        description=first.adt_Description or False,
                        transfer_type='transfer_in',
                        external_ref_in=origin,
                        adt_transaction_type='Vendor Return Document',
                        document_only=True,
                    )
                    order.write({
                        'adt_order_type': (
                            first.adt_TransferType
                            or first.adt_TransType
                            or first.adt_ReturnType
                            or False
                        ),
                    })

                    for line in to_create_move_lines:
                        product = self._find_product_by_code(line.adt_InventoryID)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.adt_InventoryID or "-"}'
                            )

                        qty = self._parse_float(line.adt_Quantity)
                        created_move = TransferService.create_order_move(
                            order,
                            product,
                            qty,
                            product.uom_id,
                            line.adt_Description or product.display_name,
                            line.adt_Description or False,
                            {
                                # 'description_picking': product.name or False,
                                'adt_line_external_id': line.adt_id or False,
                                'adt_inventory_id': line.adt_InventoryID or False,
                                'adt_line_nbr': line.adt_rowNumber or False,
                                'adt_open_qty': qty,
                                'adt_order_qty': qty,
                                'adt_uom_code': line.adt_UOM or False,
                                'adt_from_location_code': line.adt_FromLocationID or False,
                                'adt_to_location_code': line.adt_ToLocationID or False,
                                'adt_transfer_order_number': origin,
                                'adt_transfer_order_line_number': line.adt_LineNumber or line.adt_rowNumber or False,
                                'adt_transfer_order_type': first.adt_TransferType or first.adt_ReturnType or False,
                                'adt_quantity': qty,
                                'adt_type': 'Vendor Return Document',
                                'transaction_type': 'internal',
                            },
                        )

                        if action_state == 'updated':
                            line_key = str(line.adt_id or line.adt_LineNumber or line.adt_rowNumber or line.adt_InventoryID or created_move.id)
                            old = previous_moves.pop(line_key, None)
                            label = line.adt_LineNumber or line.adt_rowNumber or line.adt_InventoryID or '?'
                            current = {
                                'Produk': product.display_name or '—',
                                'Jumlah': f'{qty:g}',
                                'Satuan': product.uom_id.display_name or '—',
                                'Lokasi tujuan': created_move.location_dest_id.display_name or '—',
                                'Deskripsi': created_move.name or '—',
                            }
                            if old:
                                previous = {'Produk': old['product'], 'Jumlah': f"{old['qty']:g}", 'Satuan': old['uom'], 'Lokasi tujuan': old['destination'], 'Deskripsi': old['name']}
                                changes = [f'{name}: {previous[name]} → {value}' for name, value in current.items() if previous[name] != value]
                                if changes:
                                    update_messages.append(f"• Baris {label}: " + '; '.join(changes))
                            else:
                                update_messages.append(f"• Baris {label}: {product.display_name}, jumlah {qty:g} ditambahkan")

                    if action_state == 'updated':
                        update_messages.extend(f"• Baris {old['label']}: {old['product']} dihapus" for old in previous_moves.values())

                    TransferService.set_order_ready(order)
                    if order.document_only:
                        order._auto_validate_pickings_by_leg(('delivery', 'receipt'))
                    first.write({
                        'import_state': action_state,
                        'import_message': (
                            f'Sukses diproses ke Internal Transfer ({order.name})'
                        ),
                        'odoo_picking_id': False,
                        'odoo_internal_transfer_order_id': order.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(
                        first,
                        api_acumatica='vendor_return_document',
                        operation_type='internal',
                        origin=origin,
                    )

                    if action_state == 'updated':
                        self.env['acumatica.webhook.error.service'].send_user_error(
                            webhook_type='import',
                            webhook_name='Vendor Return Document',
                            transaction_name=origin or str(first.id),
                            event_type='update',
                            message='\n'.join(update_messages) or 'Transfer berhasil disinkronkan; tidak ada field yang berubah.',
                        )

                    if action_state == 'created':
                        imported += 1
                    else:
                        updated += 1
            except Exception as error_value:
                error += 1
                error_text = str(error_value).lower()
                if 'lokasi consignment tidak ditemukan' in error_text:
                    user_message = f"Lokasi consignment untuk warehouse sumber {first.adt_FromWarehouseID or '-'} belum ditemukan. Periksa lokasi consignment di WMS."
                elif 'lokasi tujuan' in error_text or 'towarehouseid' in error_text:
                    user_message = f"Warehouse tujuan {first.adt_ToWarehouseID or '-'} belum memiliki mapping lokasi aktif. Periksa mapping warehouse tujuan di WMS."
                elif 'product tidak ditemukan' in error_text:
                    user_message = f"Produk dengan kode {getattr(locals().get('line'), 'adt_InventoryID', False) or '-'} belum terdaftar. Periksa master produk di WMS."
                elif 'tidak memiliki detail produk' in error_text:
                    user_message = f"Transfer {origin or '-'} belum bisa diproses karena belum memiliki baris produk. Lengkapi detail transaksi."
                elif 'tidak bisa diupdate' in error_text or 'sudah ada di state' in error_text or 'sudah tidak draft' in error_text:
                    user_message = f"Transfer {origin or '-'} tidak dapat diperbarui karena proses sebelumnya sudah berjalan. Periksa status transfer terkait di WMS."
                elif 'operation type' in error_text or 'picking type' in error_text:
                    user_message = f"Operation Type untuk Vendor Return Document {origin or '-'} belum tersedia. Minta admin memeriksa pengaturan transfer di WMS."
                else:
                    user_message = False
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(error_value)],
                    api_acumatica='vendor_return_document',
                    operation_type='internal',
                    origin=origin,
                    location=first.adt_FromWarehouseID or False,
                    location_dest=first.adt_ToWarehouseID or False,
                    scheduled_date=first.adt_Date,
                    total_qty=first.adt_TotalQty,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.adt_InventoryID or False,
                        'product_name': line.adt_Description or False,
                        'qty': self._parse_float(line.adt_Quantity),
                        'uom': line.adt_UOM or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in to_create_move_lines],
                )
                first.write({
                    'import_state': 'error',
                    'import_message': str(error_value),
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': False,
                })
                if user_message:
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type='import', webhook_name='Vendor Return Document',
                        transaction_name=origin or str(first.id),
                        event_type='error', message=user_message,
                    )
                else:
                    self.env['acumatica.webhook.error.service'].send_error(
                        webhook_type='import', webhook_name='Vendor Return Document',
                        error=str(error_value), error_type='unexpected',
                    )

        return {
            'imported': imported,
            'updated': updated,
            'error': error,
        }

    def _do_import_legacy_picking(self):
        """Fungsi utama eksekusi pembuatan dokumen Stock Picking & Stock Move"""
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']

        imported = 0
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

            print(f"Move Line count: {len(to_create_move_lines)}")

            try:
                # 1. PROTEKSI UTAMA (SAVEPOINT PER DOKUMEN): 
                # Jika lines bermasalah, pembuatan picking otomatis dibatalkan bersih (Rollback)
                with self.env.cr.savepoint():
                    print(f"[DIRECT TRANSFER] Processing Document: {origin}")

                    # Tentukan jenis operasi picking (Operation Type)
                    picking_type = first._adt_reresolve_picking_type()
                    if not picking_type:
                        raise UserError(f"Picking type (Operation Type) belum diatur pada header staging ID {first.id}.")

                    # Cari master data gudang asal (FromWarehouseID)
                    warehouse_src = self._find_warehouse_by_code(first.adt_FromWarehouseID)
                    if not warehouse_src:
                        raise UserError(f"Gudang asal tidak ditemukan untuk code: {first.adt_FromWarehouseID or '-'}")

                    # Cari master data gudang tujuan (ToWarehouseID)
                    warehouse_dest = self._find_warehouse_by_code(first.adt_ToWarehouseID)
                    if not warehouse_dest:
                        raise UserError(f"Gudang tujuan tidak ditemukan untuk code: {first.adt_ToWarehouseID or '-'}")

                    source_location = warehouse_src.lot_stock_id or picking_type.default_location_src_id
                    dest_location = warehouse_dest.lot_stock_id
                    if not source_location:
                        raise UserError(f"Lokasi asal tidak ditemukan untuk code: {first.adt_FromWarehouseID or '-'}")
                    if not dest_location:
                        raise UserError(f"Lokasi tujuan tidak ditemukan untuk code: {first.adt_ToWarehouseID or '-'}")
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

                    for line in to_create_move_lines:
                        # Cari data produk Odoo berdasarkan InventoryID Acumatica
                        product = self._find_product_by_code(line.adt_InventoryID)
                        if not product:
                            raise UserError(f"Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or '-'}")

                        # Cari data satuan (UOM)
                        # uom = self._find_uom_by_name(line.adt_UOM, product)
                        qty = self._parse_float(line.adt_Quantity)

                        # Tentukan lokasi detail per baris barang secara spesifik (jika ada)
                        line_loc_src = picking.location_id
                        line_loc_dest = picking.location_dest_id

                        # Bangun dictionary baris barang tunggal
                        single_move_vals = {
                            'name': line.adt_Description or product.display_name,
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

                    # Eksekusi pembuatan seluruh Stock Moves secara massal di luar perulangan
                    if moves_to_create:
                        Move.create(moves_to_create)

                    if first.adt_DocumentOnly:
                        picking.action_validate_document_only_import(force=True)

                    # Kunci status dokumen jika seluruh perulangan sukses terlewati tanpa hambatan
                    first.write({
                        'import_state': action_state,
                        'import_message': f'Sukses diproses ke Odoo ({picking.name})',
                        'odoo_picking_id': picking.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(reference_nbr, 'direct_transfer')

                    if is_new_picking:
                        imported += 1
                    else:
                        updated += 1

            except Exception as e:
                # 2. STRATEGI PENANGANAN JIKA DOKUMEN ERROR:
                # Savepoint di atas membatalkan picking/move dokumen yang gagal.
                error += 1
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='direct_transfer',
                    operation_type='internal',
                    origin=reference_nbr,
                    location=first.adt_FromWarehouseID or False,
                    location_dest=first.adt_ToWarehouseID or False,
                    scheduled_date=first.adt_Date,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.adt_InventoryID or False,
                        'product_name': line.adt_Description or False,
                        'qty': self._parse_float(line.adt_Quantity),
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

        return product


    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False
        
    def _parse_float(self, value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def action_open_picking(self):
        self.ensure_one()
        if self.odoo_internal_transfer_order_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'internal.transfer.order',
                'res_id': self.odoo_internal_transfer_order_id.id,
                'view_mode': 'form',
            }
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada receipt di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }



class AcumaticaDirectTransferStagingLine(models.Model):
    _name = 'acumatica.direct.transfer.staging.line'
    _description = 'Staging Detail/Line Acumatica Direct Transfer'
    _order = 'id desc'

    # --- Relasi Induk (ke Header) ---
    receipt_line_id = fields.Many2one(
        'acumatica.direct.transfer.staging', 
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
