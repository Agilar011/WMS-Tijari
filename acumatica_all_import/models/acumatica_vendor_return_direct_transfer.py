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
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order',
        readonly=True,
    )
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
    adt_DocumentOnly = fields.Boolean(string="Document Only")
    adt_ExternalRef = fields.Char(string="External Ref")
    adt_FromWarehouseID = fields.Char(string="From Warehouse ID")
    adt_FromWarehouseName = fields.Char(string="From Warehouse Name")
    adt_Hold = fields.Boolean(string="Hold Status")
    adt_LastModifiedDateTime = fields.Char(string="Last Modified Date Time")
    adt_NoteID = fields.Char(string="Note ID Header")
    adt_NoteHeaderID = fields.Char(string="Note Header ID")
    adt_PostPeriod = fields.Char(string="Post Period")
    adt_ReferenceNbr = fields.Char(string="Reference Number", index=True)
    adt_ReturnType = fields.Char(string="Return Type")
    adt_Status = fields.Char(string="Acumatica Status")
    adt_TotalQty = fields.Float(string="Total Quantity")
    adt_ToWarehouseID = fields.Char(string="To Warehouse ID")
    adt_ToWarehouseName = fields.Char(string="To Warehouse Name")
    adt_TransferType = fields.Char(string="Transfer Type")
    adt_TransType = fields.Char(string="Transaction Type")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._fill_vendor_return_picking_type()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'picking_type_id' not in vals and {'adt_FromWarehouseID', 'adt_DocumentOnly'} & set(vals):
            self._fill_vendor_return_picking_type()
        return result

    def _resolve_vendor_return_picking_type(self, warehouse_code=False):
        PickingType = self.env['stock.picking.type'].sudo()
        picking_type = PickingType.resolve_document_only_picking_type(
            target_operation_type='direct_delivery_order',
            api_acumatica='vendor_return',
            document_only=True,
            warehouse_code=warehouse_code,
        )
        if picking_type:
            return picking_type

        warehouse = self._find_warehouse_by_code(warehouse_code)
        domain = [
            ('code', '=', 'outgoing'),
            ('is_default_api', '=', True),
        ]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        picking_type = PickingType.search(domain, limit=1)
        if picking_type:
            return picking_type

        return PickingType.search([
            ('code', '=', 'outgoing'),
            ('is_default_api', '=', True),
        ], limit=1)

    def _fill_vendor_return_picking_type(self):
        for rec in self:
            if rec.picking_type_id:
                continue
            picking_type = rec._resolve_vendor_return_picking_type(rec.adt_FromWarehouseID)
            if picking_type:
                rec.picking_type_id = picking_type.id
        return True

    def action_fill_picking_type_id(self):
        self._fill_vendor_return_picking_type()
        missing = self.filtered(lambda rec: not rec.picking_type_id)
        if missing:
            raise UserError(
                'Picking Type Direct Delivery Order tidak ditemukan untuk: %s'
                % ', '.join(missing.mapped('adt_ReferenceNbr'))
            )
        return True

    def _get_or_create_consignment_location(
        self, source_location=False, customer_code=False, cons_location_code=False
    ):
        Location = self.env['stock.location'].sudo()
        if not source_location:
            raise UserError('Source location wajib diisi untuk membuat lokasi consignment.')

        customer_code = (customer_code or '').strip() or 'Unknown Customer'
        cons_location_code = (cons_location_code or '').strip() or 'Consignment'

        def get_or_create_child(parent, name, is_consignment=False):
            location = Location.search([
                ('location_id', '=', parent.id),
                ('name', '=', name),
            ], limit=1)
            vals = {
                'name': name,
                'usage': 'internal',
                'location_id': parent.id,
            }
            if source_location.company_id:
                vals['company_id'] = source_location.company_id.id
            if 'is_consignment' in Location._fields:
                vals['is_consignment'] = is_consignment
            if location:
                write_vals = {}
                if is_consignment and not location.is_consignment:
                    write_vals['is_consignment'] = True
                if write_vals:
                    location.write(write_vals)
                return location
            return Location.create(vals)

        warehouse_root = source_location
        warehouse = self.env['stock.warehouse'].sudo().search([]).filtered(
            lambda wh: source_location.parent_path.startswith(wh.view_location_id.parent_path)
        )[:1]
        if warehouse:
            warehouse_root = warehouse.view_location_id

        cons_root = get_or_create_child(warehouse_root, 'CONS')
        customer_location = get_or_create_child(cons_root, customer_code)
        return get_or_create_child(
            customer_location,
            cons_location_code,
            is_consignment=True,
        )

    def _get_vendor_return_base_location(self, first, picking_type):
        destination_warehouse = self._find_warehouse_by_code(first.adt_ToWarehouseID)
        if destination_warehouse and destination_warehouse.lot_stock_id:
            return destination_warehouse.lot_stock_id
        return picking_type.default_location_src_id

    def _get_vendor_return_source_location(self, first, picking_type):
        warehouse_src = self._find_warehouse_by_code(first.adt_FromWarehouseID)
        if warehouse_src and warehouse_src.lot_stock_id:
            return warehouse_src.lot_stock_id

        base_location = self._get_vendor_return_base_location(first, picking_type)
        if not base_location:
            raise UserError(
                f"Lokasi basis consignment tidak ditemukan untuk Vendor Return {first.adt_ReferenceNbr or '-'}."
            )

        first_line = first.line_ids[:1]
        cons_location_code = (
            (first_line.adt_FromLocationID if first_line else False)
            or (first_line.adt_ToLocationID if first_line else False)
            or first.adt_FromWarehouseID
            or 'Consignment'
        )
        return self._get_or_create_consignment_location(
            base_location,
            first.adt_FromWarehouseID,
            cons_location_code,
        )

    def _get_vendor_return_destination_location(self, first, picking_type):
        destination_warehouse = self._find_warehouse_by_code(first.adt_ToWarehouseID)
        if destination_warehouse and destination_warehouse.lot_stock_id:
            return destination_warehouse.lot_stock_id
        return picking_type.default_location_dest_id

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
        """Fungsi utama eksekusi pembuatan dokumen Internal Transfer Order."""

        imported = 0
        updated = 0
        error = 0

        # Ambil daftar unik reference number agar tidak memproses dokumen yang sama berulang kali
        for reference_nbr in self.mapped('adt_ReferenceNbr'):
            receipt_lines = self.filtered(
                lambda l: l.adt_ReferenceNbr == reference_nbr and (
                    l.import_state in ['pending', 'error']
                    or not l.odoo_internal_transfer_order_id
                )
            )
            if not receipt_lines:
                continue

            # Karena model bertipe multi-recordset, ambil baris header pertamanya secara aman
            first = receipt_lines[0]
            first_id = first.id
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
                    first._fill_vendor_return_picking_type()
                    picking_type = first.picking_type_id
                    if not picking_type:
                        raise UserError(f"Picking type (Operation Type) belum diatur pada header staging ID {first.id}.")

                    source_location = self._get_vendor_return_source_location(first, picking_type)
                    dest_location = self._get_vendor_return_destination_location(first, picking_type)
                    if not source_location:
                        raise UserError(f"Lokasi asal tidak ditemukan untuk code: {first.adt_FromWarehouseID or '-'}.")
                    if not dest_location:
                        raise UserError(f"Lokasi tujuan tidak ditemukan untuk code: {first.adt_ToWarehouseID or '-'}.")

                    transfer_service = self.env['acumatica.internal.transfer.service']
                    order, action_state = transfer_service.prepare_order(
                        origin,
                        source_location,
                        dest_location,
                        'vendor_return',
                        self._parse_dt(first.adt_Date),
                        first.adt_note or False,
                        transfer_type='transfer_out',
                    )

                    for line in to_create_move_lines:
                        # Cari data produk Odoo berdasarkan InventoryID Acumatica
                        product = self._find_product_by_code(line.adt_InventoryID)
                        if not product:
                            raise UserError(f"Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or '-'}")

                        # Cari data satuan (UOM)
                        # uom = self._find_uom_by_name(line.adt_UOM, product)
                        qty = self._parse_float(line.adt_Quantity)

                        transfer_service.create_order_move(order, product, qty, product.uom_id, line.adt_Description or product.display_name, line.adt_Description or False, {
                            'description_picking': line.adt_Description or False,
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
                            'adt_type': 'Vendor Return',
                            'transaction_type': 'internal',
                        })

                    transfer_service.set_order_ready(order)
                    # Kunci status dokumen jika seluruh perulangan sukses terlewati tanpa hambatan
                    first.write({
                        'import_state': action_state,
                        'import_message': f'Sukses diproses ke Internal Transfer ({order.name})',
                        'odoo_picking_id': False,
                        'odoo_internal_transfer_order_id': order.id,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(reference_nbr, 'vendor_return')

                    if action_state == 'imported':
                        imported += 1
                    else:
                        updated += 1

            except Exception as e:
                # 2. STRATEGI PENANGANAN JIKA DOKUMEN ERROR:
                # Savepoint di atas sudah membatalkan dokumen Odoo yang gagal.
                # Jangan rollback cursor utama karena record staging masih harus ditulis error.
                error += 1
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='vendor_return',
                    operation_type='internal',
                    origin=reference_nbr,
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

                # Tulis pesan kegagalan ke UI Odoo agar user tahu detail masalahnya
                staging = self.env['acumatica.vendor.return.direct.transfer.staging'].browse(first_id).exists()
                if staging:
                    staging.write({
                        'import_state': 'error',
                        'import_message': str(e),
                        'odoo_picking_id': False,
                        'odoo_internal_transfer_order_id': False,
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

    def _parse_float(self, value):
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
        if self.odoo_internal_transfer_order_id:
            if self.odoo_internal_transfer_order_id.picking_count:
                return self.odoo_internal_transfer_order_id.action_view_pickings()
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
    adt_LineNoteID = fields.Char(string="Line Note ID")
    adt_Quantity = fields.Float(string="Quantity")
    adt_SOOrderNbr = fields.Char(string="SO Order Number")
    adt_SOOrderType = fields.Char(string="SO Order Type")
    adt_SOShipmentNbr = fields.Char(string="SO Shipment Number")
    adt_ToLocationID = fields.Char(string="To Location ID")
    adt_UOM = fields.Char(string="Unit of Measure")
