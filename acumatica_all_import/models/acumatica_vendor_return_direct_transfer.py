from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from dateutil import parser as dateutil_parser


class AcumaticaVendorReturnDirectTransferStaging(models.Model):
    _name = 'acumatica.vendor.return.direct.transfer.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Staging Header Acumatica Direct Transfer'
    _order = 'id desc'

    def _adt_picking_type_wizard_call(self):
        if not self.adt_FromWarehouseID:
            return False
        return (
            'import.vendor.return.direct.transfer.wizard',
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
        'acumatica.vendor.return.direct.transfer.staging.line', 
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
            self._fill_vendor_return_picking_type(force=True)
        return result

    def _resolve_vendor_return_picking_type(self, warehouse_code=False, document_only=False):
        PickingType = self.env['stock.picking.type'].sudo()
        if document_only:
            picking_type = PickingType.resolve_document_only_picking_type(
                target_operation_type='direct_delivery_order',
                api_acumatica='vendor_return',
                document_only=True,
                warehouse_code=warehouse_code,
            )
            if picking_type:
                return picking_type

        warehouse = self._find_warehouse_by_code(warehouse_code)
        picking_type = PickingType.resolve_picking_type(
            warehouse=warehouse,
            warehouse_code=warehouse_code,
            code='outgoing',
            operation_category='delivery',
            api_acumatica='vendor_return',
            transaction_key='vendor_return',
            required=False,
        )
        if picking_type:
            return picking_type

        return PickingType.search([
            ('code', '=', 'outgoing'),
            ('operation_category', '=', 'delivery'),
            ('active', '=', True),
        ], limit=1)

    def _fill_vendor_return_picking_type(self, force=False):
        for rec in self:
            if rec.picking_type_id and not force:
                continue
            picking_type = rec._resolve_vendor_return_picking_type(
                rec.adt_FromWarehouseID, rec.adt_DocumentOnly
            )
            if picking_type:
                rec.picking_type_id = picking_type.id
        return True

    def action_reset_pending(self):
        self.filtered(lambda record: record.import_state == 'error').write({
            'import_state': 'staged',
            'import_message': False,
        })
        return True

    def _get_vendor_return_base_location(self, first, picking_type):
        Location = self.env['stock.location']
        warehouse_code = (first.adt_FromWarehouseID or '').strip()
        normalized_code = (
            warehouse_code.split('-', 1)[1].strip()
            if '-' in warehouse_code
            else warehouse_code
        )
        source_location = Location.search([
            ('name', 'in', list({warehouse_code, normalized_code} - {''})),
            ('is_consignment', '=', True),
            ('location_id.name', '=', 'Consignment'),
        ], limit=1)
        if not source_location:
            raise UserError(
                f'Lokasi consignment tidak ditemukan untuk FromWarehouseID '
                f'{first.adt_FromWarehouseID or "-"}.'
            )
        return source_location

    def _get_vendor_return_source_location(self, first, picking_type):
        base_location = self._get_vendor_return_base_location(first, picking_type)
        if not base_location:
            raise UserError(
                f"Lokasi basis consignment tidak ditemukan untuk Vendor Return {first.adt_ReferenceNbr or '-'}."
            )

        return base_location

    def _get_vendor_return_destination_location(self, first, picking_type):
        warehouse_code = (first.adt_ToWarehouseID or '').strip()
        mapping = self.env['stock.location.acumatica'].search([
            ('code', '=', warehouse_code),
            ('is_active', '=', True),
        ], limit=1)
        if not mapping:
            raise UserError(
                f'Mapping ToWarehouseID tidak ditemukan di '
                f'stock.location.acumatica: {first.adt_ToWarehouseID or "-"}.'
            )
        if not mapping.odoo_location_id:
            raise UserError(
                f'Lokasi Odoo untuk ToWarehouseID '
                f'{first.adt_ToWarehouseID or "-"} belum diisi pada '
                'stock.location.acumatica.'
            )
        return mapping.odoo_location_id

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

    def action_import_this(self):
        """Memicu proses impor khusus untuk 1 record aktif"""
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _do_import(self):
        """Fungsi utama eksekusi pembuatan dokumen Internal Transfer Order."""

        imported = 0
        updated = 0
        error = 0

        # Ambil daftar unik reference number agar tidak memproses dokumen yang sama berulang kali
        for reference_nbr in self.mapped('adt_ReferenceNbr'):
            receipt_lines = self.filtered(
                lambda l: l.adt_ReferenceNbr == reference_nbr and (
                    l.import_state in ['staged', 'error']
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
                    first._fill_vendor_return_picking_type(force=True)
                    picking_type = first._adt_reresolve_picking_type()
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
                        'inter_warehouse',
                        self._parse_dt(first.adt_Date),
                        first.adt_note or False,
                        description=first.adt_Description or False,
                        transfer_type='transfer_in',
                        adt_transaction_type='Vendor Return',
                        document_only=first.adt_DocumentOnly,
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

                    if action_state == 'created':
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
