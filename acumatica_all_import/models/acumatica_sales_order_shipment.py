import logging
import time
from dateutil import parser as dateutil_parser
from docutils.nodes import note
import requests
import ast
import json

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AcumaticaShipmentGIStaging(models.Model):
    _name = 'acumatica.shipment.gi.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Acumatica Shipment GI'
    _rec_name = 'adt_ShipmentNbr'

    def _adt_picking_type_wizard_call(self):
        return (
            'import.so.shipment.wizard',
            (self.adt_BuildingID or self.adt_WarehouseID, self.adt_OrderType),
            {'document_only': self.adt_DocumentOnly},
        )

    # shipment_ids = fields.One2many('acumatica.sales.order.shipment.staging','gi_id',string='Shipments')
    all_line_ids = fields.One2many('acumatica.sales.order.shipment.staging.line', 'gi_id',string='All Shipment Details')
    active = fields.Boolean(default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order',
        readonly=True,
    )
    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    selected = fields.Boolean(string='Pilih', default=True)
    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)
    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    odoo_shipment_status = fields.Selection([
        ('staged', 'Staged'),
        ('processed', "Telah di Proses"),
    ], string='Status Odoo', default='staged')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')
    total_qty = fields.Float(string='Total Quantity',compute='_compute_total_qty',store=True,digits=(16, 2))

    acumatica_id = fields.Char(string="atica_id")
    adt_rowNumber = fields.Char(string="rowNumber")
    adt_note = fields.Char(string="note")
    adt_Description = fields.Char(string="Description")
    adt_AddressID = fields.Char(string="AddressID")
    adt_AddressLine = fields.Char(string="AddressLine")
    adt_BuildingID = fields.Char(string="BuildingID")
    adt_City = fields.Char(string="City")
    adt_Country = fields.Char(string="Country")
    adt_CountryName = fields.Char(string="CountryName")
    adt_CustomerID = fields.Char(string="CustomerID")
    adt_CustomerName = fields.Char(string="CustomerName")
    adt_DocumentOnly = fields.Boolean(string="DocumentOnly")
    adt_FOBPoint = fields.Char(string="FOBPoint")
    adt_FOBPointDescription = fields.Char(string="FOBPointDescription")
    adt_LineDescription = fields.Char(string="LineDescription")
    adt_LineFreeItem = fields.Char(string="LineFreeItem")
    adt_LineInventoryID = fields.Char(string="LineInventoryID")
    adt_LineLocation = fields.Char(string="LineLocation")
    adt_LineNbr = fields.Char(string="LineNbr")
    adt_LineNote = fields.Char(string="LineNote")
    adt_LineNoteID = fields.Char(string="LineNoteID")
    adt_LineQuantity = fields.Char(string="LineQuantity")
    adt_LineUOM = fields.Char(string="LineUOM")
    adt_LocationID = fields.Char(string="LocationID")
    adt_LocationName = fields.Char(string="LocationName")
    lastmodifieddatetime = fields.Datetime(string="Last Modified Date", readonly=True)
    adt_NoteHeader = fields.Char(string="NoteHeader")
    adt_NoteHeaderID = fields.Char(string="NoteHeaderID")
    adt_OrderType = fields.Char(string="OrderType")
    adt_Phone = fields.Char(string="Phone")
    adt_PostalCode = fields.Char(string="PostalCode")
    adt_ShipDate = fields.Char(string="ShipDate")
    adt_IssueNbr = fields.Char(string="IssueNbr")
    adt_ShipmentNbr = fields.Char(string="ShipmentNbr")
    adt_ShipmentQty = fields.Char(string="ShipmentQty")
    adt_ShipmentType = fields.Char(string="ShipmentType")
    adt_ShipmentVolume = fields.Char(string="ShipmentVolume")
    adt_ShipmentWeight = fields.Char(string="ShipmentWeight")
    adt_ShipVia = fields.Char(string="ShipVia")
    adt_SiteIDDescription = fields.Char(string="SiteIDDescription")
    adt_State = fields.Char(string="State")
    adt_StateName = fields.Char(string="StateName")
    adt_Status = fields.Char(string="Status")
    adt_ToWarehouseID = fields.Char(string="ToWarehouseID")
    adt_WarehouseID = fields.Char(string="WarehouseID")

    # @api.depends('shipment_ids.line_ids')
    # def _compute_all_line_ids(self):
    #     for rec in self:
    #         # Ambil semua record line_ids dari setiap shipment di dalam shipment_ids
    #         rec.all_line_ids = rec.shipment_ids.mapped('line_ids')

    @api.depends('all_line_ids.adt_ShipmentQty')
    def _compute_total_qty(self):
        for rec in self:
            # Konversi setiap nilai secara paksa ke float untuk mengantisipasi tipe data str di DB
            total = 0.0
            for line in rec.all_line_ids:
                try:
                    total += float(line.adt_ShipmentQty or 0.0)
                except (ValueError, TypeError):
                    total += 0.0
            rec.total_qty = total

    _sql_constraints = [
        (
            'unique_id',
            'unique(acumatica_id)',
            'ID Number must be unique!'
        )
    ]

# =====================================================================================================================================================================
    # Main Flow Function
# =====================================================================================================================================================================

    def _do_import(self):
        print("Menjalankan fungsi do import so shipment")
        print(self)
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']
        Product = self.env['product.product']
        Partner = self.env['res.partner']
        Warehouse = self.env['stock.warehouse']

        shipment_gi = self.env['acumatica.shipment.gi.staging']
        shipment_line = self.env['acumatica.sales.order.shipment.staging.line']

        print("\n" + "=" * 120 + "\nSTART IMPORT SHIPMENT\n" + "=" * 120)

        # =====================================================
        # 1. AMBIL DAFTAR NOMOR SHIPMENT DARI RECORDSET AKTIF
        # =====================================================
        pending_shipments = self.mapped('adt_ShipmentNbr')

        if not pending_shipments:
            print("NO PENDING SHIPMENT FOUND")
            return True

        shipment_numbers = list(set(pending_shipments)) # Bersihkan duplikasi nomor

        # =====================================================
        # 2. VALIDASI DATA YANG SUDAH PROCESSED DI ODOO
        # =====================================================
        existing_pickings = Picking.search([
            ('origin', 'in', shipment_numbers),
            ('state', '!=', 'draft')
        ])

        processed_picking = existing_pickings.mapped('origin')

        # Saring dokumen yang sudah ada di Odoo dengan state selain draft
        not_pending_shipment = shipment_gi.search([
            ('adt_ShipmentNbr', 'in', processed_picking)
        ])

        for staging_rec in not_pending_shipment:
            message = f'Receipt {staging_rec.adt_ShipmentNbr} sudah ada di Odoo dengan state selain draft, tidak bisa diupdate.'
            lines = shipment_line.search([('gi_id', '=', staging_rec.id)])
            self.env['acumatica.error.transaction']._handle_acumatica_error(
                staging_rec,
                [message],
                api_acumatica='so_shipment',
                operation_type='delivery',
                origin=staging_rec.adt_ShipmentNbr,
                partner=staging_rec.adt_CustomerID or False,
                location=staging_rec.adt_WarehouseID or staging_rec.adt_LocationID or False,
                location_dest=staging_rec.adt_ToWarehouseID or False,
                scheduled_date=staging_rec.adt_ShipDate,
                total_qty=staging_rec.adt_ShipmentQty or staging_rec.total_qty,
                payload={'header': staging_rec.read()[0] if staging_rec.exists() else {}},
                line_payloads=[{
                    'inventory_id': line.adt_LineInventoryID or False,
                    'product_name': line.adt_LineDescription or False,
                    'qty': self._parse_int(line.adt_ShipmentQty),
                    'uom': line.adt_LineUOM or False,
                    'payload': line.read()[0] if line.exists() else {},
                } for line in lines],
            )
            staging_rec.write({
                'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                'import_message': message,
                'odoo_picking_id': False,
                'odoo_internal_transfer_order_id': False,
            })

        # =====================================================
        # 3. PROSES IMPORT/UPDATE UNTUK DATA YANG VALID (PENDING)
        # =====================================================
        # Ambil record data staging induk yang siap diproses (nomor dokumen tidak masuk list processed_picking)
        valid_shipments = shipment_gi.search([
            ('adt_ShipmentNbr', 'in', shipment_numbers),
            ('adt_ShipmentNbr', 'not in', processed_picking)
        ])

        for shipment in valid_shipments:
            # Ambil sub-transaksi database tingkat dokumen
            with self.env.cr.savepoint():
                self.env.cr.execute('SAVEPOINT import_so_shipment_doc')
                try:
                    if (shipment.adt_OrderType or '').strip().upper() == 'CO':
                        self._import_consignment_internal_transfer(shipment, shipment_line)
                        self.env.cr.execute('RELEASE SAVEPOINT import_so_shipment_doc')
                        continue

                    warehouse = self._find_warehouse(shipment.adt_WarehouseID)
                    if not warehouse:
                        raise UserError(f"Warehouse {shipment.adt_WarehouseID} tidak ditemukan di Odoo.")

                    picking_type = shipment._adt_reresolve_picking_type()
                    if not picking_type:
                        raise UserError(f"Operation Type Incoming untuk gudang {warehouse.name} tidak ditemukan.")

                    partner = self._find_partner(shipment.adt_CustomerID)
                    if not partner:
                        partner = self.env.user.company_id.partner_id

                    # FIXING TANGGAL ISO ACUMATICA
                    if shipment.adt_ShipDate and 'T' in str(shipment.adt_ShipDate):
                        clean_date_str = str(shipment.adt_ShipDate).split('+')[0].replace('T', ' ')
                        ship_date = fields.Datetime.to_datetime(clean_date_str)
                    else:
                        ship_date = shipment.adt_ShipDate if shipment.adt_ShipDate else fields.Datetime.now()

                    updated_vals = {
                        'partner_id': partner.id,
                        'picking_type_id': picking_type.id,
                        'location_id': picking_type.default_location_src_id.id,
                        'location_dest_id': picking_type.default_location_dest_id.id,
                        'origin': shipment.adt_ShipmentNbr,
                        'scheduled_date': ship_date,
                        'adt_type' : "Sales Order Shipment",
                        'adt_order_type': shipment.adt_OrderType or False,
                        'transaction_type' : 'outbound'
                    }

                    shipment_location_id = shipment.adt_WarehouseID
                    shipment_weight = shipment.adt_ShipmentWeight
                    shipment_volume = shipment.adt_ShipmentVolume
                    shipment_city = shipment.adt_City

                    # shipment_country = self._find_loginext_country(shipment.adt_CountryName)
                    shipment_postal_code = shipment.adt_PostalCode
                    shipment_street = shipment.adt_AddressLine


                    picking = Picking.search([
                        ('origin', '=', shipment.adt_ShipmentNbr),
                        ('state', '=', 'draft')
                    ], limit=1)

                    create_tms_state = False

                    if picking:
                        picking.write(updated_vals)
                        action_state = 'updated'
                        print(f"SUCCESS UPDATING PICKING ID: {picking.id}")
                        picking.move_ids.unlink()
                        print(f"--> SUCCESS UNLINK OLD LINES FOR PICKING ID: {picking.id}")
                    else:
                        picking = Picking.create(updated_vals)
                        action_state = 'created'
                        # exist_post_data = self.env['loginext.staging.data'].search([('odoo_shipment_number', '=', picking.origin)], limit=1)
                        # if not exist_post_data:
                        #     create_tms_state = True

                            # created_loginext_header = self._build_loginext_header(shipment.adt_ShipmentNbr, ship_date, shipment_location_id,shipment_weight, shipment_volume, partner, shipment_city, shipment_country, shipment_postal_code, shipment_street, picking.origin)

                        print(f"SUCCESS CREATING NEW PICKING ID: {picking.id}")

                    move_items = shipment_line.search([
                        ('gi_id', '=', shipment.id)
                    ])

                    move_count = 0

                    for item in move_items:
                        move_count += 1
                        product = Product.search([('default_code', '=', item.adt_LineInventoryID)], limit=1)
                        if not product:
                            raise UserError(f"Produk dengan SKU {item.adt_LineInventoryID} tidak ditemukan di Odoo.")

                        # Finding stock location for
                        product_location = self._find_warehouse_product(shipment.adt_WarehouseID)
                        if product_location:
                            print(f" Product: {product.product_tmpl_id.name} asignt to get from: {product_location} AKA {shipment.adt_WarehouseID}")

                        _logger.info("============================================================")
                        _logger.info("Warehouse ID           : %s", shipment.adt_WarehouseID)
                        _logger.info("Product                : %s (%s)", product.display_name, product.id)
                        _logger.info("Product Location       : %s", product_location)
                        _logger.info(
                            "Product Location ID    : %s",
                            product_location.id if product_location else False,
                        )
                        _logger.info(
                            "Picking Type Src Loc   : %s (%s)",
                            picking_type.default_location_src_id.display_name if picking_type.default_location_src_id else False,
                            picking_type.default_location_src_id.id if picking_type.default_location_src_id else False,
                        )


                        move_vals = {
                            'company_id': warehouse.company_id.id,
                            'product_id': product.id,
                            'product_uom': product.product_tmpl_id.uom_id.id,
                            'location_id': product_location.id if product_location else picking_type.default_location_src_id.id,
                            'location_dest_id': picking_type.default_location_dest_id.id,
                            'partner_id': partner.id,
                            'picking_id': picking.id,
                            'picking_type_id': picking_type.id,
                            'warehouse_id': picking_type.warehouse_id.id,
                            'name': item.adt_LineDescription or item.description,
                            'origin': picking.origin,
                            'description_picking': item.adt_LineDescription or item.description,
                            'product_uom_qty': float(item.adt_ShipmentQty or 0.0),
                            'date': ship_date,
                            'date_deadline': ship_date,
                            'adt_line_external_id': item.acumatica_id,
                            'adt_inventory_id': item.adt_LineInventoryID,
                            'adt_uom_code': item.adt_LineUOM,
                            'adt_line_note': item.adt_LineNote or False,
                            'adt_open_qty': float(item.adt_ShipmentQty or 0.0),
                            'adt_type': 'Sales Order Shipment',
                            'adt_line_description': item.adt_LineDescription or item.description,
                            'adt_dest_location_id' : product_location.id if product_location else picking_type.default_location_src_id.id,
                            'adt_dest_location' : shipment.adt_WarehouseID,
                            'transaction_type' : 'outbound'
                        }
                        adt_dest_location_id =  Move.create(move_vals)
                        print(f"mapped location: {adt_dest_location_id.id}")

                        item_qty = float(item.adt_ShipmentQty or 0.0)

                    #     if create_tms_state == True:
                    #         self._build_loginext_item(product, shipment.adt_OrderType, created_loginext_header.id, move_count, shipment.adt_ShipmentWeight, item_qty)


                    # if create_tms_state == True:
                    #     created_loginext_header.loginext_number_of_items = move_count

                    if shipment.adt_DocumentOnly:
                        picking.action_validate_document_only_import(force=True)

                    # Tandai sukses jika semua proses di atas berhasil tanpa memicu exception
                    shipment.write({
                        'import_state': action_state,
                        'import_message': 'success',
                        'odoo_picking_id': picking.id
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_error(shipment.adt_ShipmentNbr, 'so_shipment')
                    self.env.cr.execute('RELEASE SAVEPOINT import_so_shipment_doc')

                except Exception as e:
                    self.env.cr.execute('ROLLBACK TO SAVEPOINT import_so_shipment_doc')
                    _logger.error(f"Error importing shipment {shipment.adt_ShipmentNbr}: {str(e)}")
                    tracked_lines = shipment_line.search([('gi_id', '=', shipment.id)])
                    self.env['acumatica.error.transaction']._handle_acumatica_error(
                        shipment,
                        [str(e)],
                        api_acumatica='so_shipment',
                        operation_type='delivery',
                        origin=shipment.adt_ShipmentNbr,
                        partner=shipment.adt_CustomerID or False,
                        location=shipment.adt_WarehouseID or shipment.adt_LocationID or False,
                        location_dest=shipment.adt_ToWarehouseID or False,
                        scheduled_date=shipment.adt_ShipDate,
                        total_qty=shipment.adt_ShipmentQty or shipment.total_qty,
                        payload={'header': shipment.read()[0] if shipment.exists() else {}},
                        line_payloads=[{
                            'inventory_id': line.adt_LineInventoryID or False,
                            'product_name': line.adt_LineDescription or False,
                            'qty': self._parse_int(line.adt_ShipmentQty),
                            'uom': line.adt_LineUOM or False,
                            'payload': line.read()[0] if line.exists() else {},
                        } for line in tracked_lines],
                    )

                    # Odoo memperbolehkan modifikasi record saat ini di dalam savepoint yang gagal
                    shipment.write({
                        'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                        'import_message': f'!!! ERROR DETECTED ON IMPORT PROCESS: {str(e)}',
                        'odoo_picking_id': False,
                        'odoo_internal_transfer_order_id': False,
                    })

                    # Paksa loop untuk melanjutkan dokumen berikutnya tanpa menghentikan sistem
                    continue

        print("\n" + "=" * 120 + "\nEND OF IMPORT PROCESS\n" + "=" * 120)
        return True


    def _get_or_create_consignment_location(
        self, source_location=False, customer_code=False, cons_location_code=False
    ):
        Location = self.env['stock.location']
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
        warehouse = self.env['stock.warehouse'].search([]).filtered(
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

    def _get_or_create_transit_location(self):
        Location = self.env['stock.location']
        transit_location = Location.search([('usage', '=', 'transit')], limit=1)
        if not transit_location:
            transit_location = Location.create({
                'name': 'Transit',
                'usage': 'transit',
            })
        return transit_location

    def _import_consignment_internal_transfer(self, shipment, shipment_line):
        InternalTransferOrder = self.env['internal.transfer.order']
        Move = self.env['stock.move']
        Product = self.env['product.product']

        source_location = self._find_warehouse_product(shipment.adt_WarehouseID)
        if not source_location:
            raise UserError(
                f"Source location mapping WarehouseID {shipment.adt_WarehouseID or '-'} tidak ditemukan."
            )

        partner = self._find_partner(shipment.adt_CustomerID)
        if not partner:
            raise UserError(
                f"Customer {shipment.adt_CustomerID or '-'} tidak ditemukan di Odoo."
            )

        destination_location = self._get_or_create_consignment_location(
            source_location,
            shipment.adt_CustomerID,
            shipment.adt_ToWarehouseID or shipment.adt_LocationID or shipment.adt_LocationName,
        )
        transit_location = self._get_or_create_transit_location()

        if shipment.adt_ShipDate and 'T' in str(shipment.adt_ShipDate):
            clean_date_str = str(shipment.adt_ShipDate).split('+')[0].replace('T', ' ')
            ship_date = fields.Datetime.to_datetime(clean_date_str)
        else:
            ship_date = shipment.adt_ShipDate if shipment.adt_ShipDate else fields.Datetime.now()

        shipment_location_id = shipment.adt_WarehouseID
        shipment_weight = shipment.adt_ShipmentWeight
        shipment_volume = shipment.adt_ShipmentVolume
        shipment_city = shipment.adt_City
        # shipment_country = self._find_loginext_country(shipment.adt_CountryName)
        shipment_postal_code = shipment.adt_PostalCode
        shipment_street = shipment.adt_AddressLine

        order = InternalTransferOrder.search([
            ('external_ref', '=', shipment.adt_ShipmentNbr),
        ], limit=1)
        if order:
            if order.picking_ids:
                raise UserError(
                    f"Shipment {shipment.adt_ShipmentNbr} sudah memiliki transfer, tidak bisa diupdate."
                )
            if order.state not in ('draft', 'cancel'):
                raise UserError(
                    f"Shipment {shipment.adt_ShipmentNbr} sudah ada di state {order.state}, tidak bisa diupdate."
                )
            order.move_ids.unlink()
            order.write({
                'transaction_type': 'consignment',
                'transfer_type': 'transfer_out',
                'adt_order_type': shipment.adt_OrderType or False,
                'partner_id': partner.id,
                'location_id': source_location.id,
                'location_dest_id': destination_location.id,
                'transit_location_id': transit_location.id,
                'schedule_date': ship_date,
                'validation_policy': 'validate_all',
                'note': shipment.adt_note or shipment.adt_NoteHeader or False,
                'state': 'draft',
            })
            action_state = 'updated'
            self.env['acumatica.error.transaction']._handle_acumatica_update(shipment, origin=shipment.adt_ShipmentNbr or False)
        else:
            order = InternalTransferOrder.create({
                'external_ref': shipment.adt_ShipmentNbr,
                'transaction_type': 'consignment',
                'transfer_type': 'transfer_out',
                'adt_order_type': shipment.adt_OrderType or False,
                'partner_id': partner.id,
                'location_id': source_location.id,
                'location_dest_id': destination_location.id,
                'transit_location_id': transit_location.id,
                'schedule_date': ship_date,
                'validation_policy': 'validate_all',
                'note': shipment.adt_note or shipment.adt_NoteHeader or False,
            })
            action_state = 'created'

        move_items = shipment_line.search([('gi_id', '=', shipment.id)])
        if not move_items:
            raise UserError(f"Shipment {shipment.adt_ShipmentNbr} tidak punya detail line.")

        # created_loginext_header = False
        create_tms_state = False

        # exist_post_data = self.env['loginext.staging.data'].search([
        #     ('odoo_shipment_number', '=', shipment.adt_ShipmentNbr),
        # ], limit=1)
        # if not exist_post_data:
        #     create_tms_state = True
        #     created_loginext_header = self._build_loginext_header(
        #         shipment.adt_ShipmentNbr,
        #         ship_date,
        #         shipment_location_id,
        #         shipment_weight,
        #         shipment_volume,
        #         partner,
        #         shipment_city,
        #         shipment_country,
        #         shipment_postal_code,
        #         shipment_street,
        #         shipment.adt_ShipmentNbr,
        #     )

        move_count = 0
        for item in move_items:
            move_count += 1
            product = Product.search([('default_code', '=', item.adt_LineInventoryID)], limit=1)
            if not product:
                raise UserError(f"Produk dengan SKU {item.adt_LineInventoryID} tidak ditemukan di Odoo.")

            uom = self._find_uom(item, product)
            qty = float(item.adt_ShipmentQty or 0.0)
            move_vals = {
                'name': item.adt_LineDescription or product.display_name,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': uom.id if uom else product.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': destination_location.id,
                'internal_transfer_order_id': order.id,
                'description_picking': item.adt_LineDescription or False,
                'adt_line_external_id': item.acumatica_id,
                'adt_inventory_id': item.adt_LineInventoryID,
                'adt_uom_code': item.adt_LineUOM,
                'adt_open_qty': qty,
                'adt_quantity': qty,
                'adt_type': 'SO Consignment',
                'adt_line_description': item.adt_LineDescription or False,
                'adt_line_nbr': item.adt_LineNbr or False,
                'adt_transfer_order_number': shipment.adt_ShipmentNbr,
                'adt_transfer_order_line_number': item.adt_LineNbr or False,
                'adt_transfer_order_type': shipment.adt_OrderType or False,
                'adt_from_location_code': shipment.adt_WarehouseID or False,
                'adt_to_location_code': destination_location.complete_name,
            }
            move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
            Move.create(move_vals)

        #     if create_tms_state:
        #         self._build_loginext_item(
        #             product,
        #             shipment.adt_OrderType,
        #             created_loginext_header.id,
        #             move_count,
        #             shipment.adt_ShipmentWeight,
        #             qty,
        #         )

        # if create_tms_state:
        #     created_loginext_header.loginext_number_of_items = move_count

        order.action_ready()
        shipment.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_picking_id': False,
            'odoo_internal_transfer_order_id': order.id,
        })
        self.env['acumatica.error.transaction']._handle_acumatica_error(shipment.adt_ShipmentNbr, 'so_shipment')
        return order

# =====================================================================================================================================================================
    # Service Function
# =====================================================================================================================================================================

    def _find_responsible(self):
        user = self.env['res.users'].search([('name', '=', 'System User')], limit=1)

        if not user:
            user = self.env['res.users'].create({
                'name': 'System User',
                'login': 'system.user@aditya_sarana_graha.com',
            })

        return user

    def _find_product(self, line):
        print('Starting search product')

        Product = self.env['product.product']
        Quant = self.env['stock.quant']
        Location = self.env['stock.location']

        product = False
        abort_picking = False
        # =====================================================
        # FIND PRODUCT
        # =====================================================

        if line:

            product = Product.search([
                ('default_code', '=', line.adt_LineInventoryID)
            ], limit=1)

        else:
            print(
                # f"PRODUCT NOT FOUND | "Proses picking dibatalkan karena ada produk yang bermasalah
                f"InventoryID={line.inventoryid}"
            )

            return False

        return {
            'product': product,
        }

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line:
            partner = Partner.search([('company_registry', '=', line)], limit=1)
            if not partner:
                partner = Partner.search([('adt_b_account_id', '=', line)], limit=1)
        return partner

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse

    def _find_warehouse_product(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_location_id

        return warehouse
        # Warehouse = self.env['stock.warehouse']
        # code = line

        # # 1. Jalankan query SQL (Pastikan argumen dalam bentuk tuple/list)
        # self.env.cr.execute("""
        #     SELECT id
        #     FROM stock_warehouse
        #     WHERE code = %s
        # """, (code,))

        # # 2. Ambil hasilnya dan simpan ke dalam variabel (Hanya panggil fetchall SEKALI)
        # sql_result = self.env.cr.fetchall()
        # print(sql_result)
        # # raise UserError('checkpoint')

        # warehouse = False
        # # 3. Jika SQL menemukan data, ambil ID dari elemen pertama
        # if sql_result:
        #     warehouse_id = sql_result[0][0] # Mengambil angka 176 dari [(176, 'WH33-FG')]

        #     # 4. Cari menggunakan ORM berdasarkan ID yang didapat dari SQL
        #     # Tambahkan context active_test=False untuk berjaga-jaga jika record di-archived
        #     warehouse = Warehouse.sudo().with_context(active_test=False).search([('id', '=', warehouse_id)], limit=1)

        # # raise UserError('Checkpoint')
        # return warehouse




    def _find_destination_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.warehouse_id
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_source_location(self, warehouse=False):
        Location = self.env['stock.location']
        supplier_loc = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        if supplier_loc:
            return supplier_loc
        return Location.search([('usage', '=', 'supplier')], limit=1) or (warehouse and warehouse.lot_stock_id)

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.adt_LineUOM:
            uom = Uom.search([('name', '=', line.adt_LineUOM)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    # def _find_loginext_country(self, code):
    #     Country = self.env['loginext.master.country']

    #     country_code = Country.search([('country', '=', code)], limit=1)
    #     if country_code:
    #         final_code = country_code.code

    #     else:
    #         final_code = "IDN"

    #     return final_code

# Helper Function

    @api.depends('adt_ShipmentNbr', 'adt_OrderType')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            if not rec.adt_ShipmentNbr:
                rec.exists_in_odoo = False
            elif (rec.adt_OrderType or '').strip().upper() == 'CO':
                rec.exists_in_odoo = bool(
                    InternalTransferOrder.search_count([('external_ref', '=', rec.adt_ShipmentNbr)])
                )
            else:
                rec.exists_in_odoo = bool(
                    Picking.search_count([('origin', '=', rec.adt_ShipmentNbr)])
                )

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

    def action_import_selected(self):
        lines = self.filtered(
            lambda l: (
                l.import_state in ['staged', 'error']
                or (
                    l.import_state in ['created', 'updated']
                    and not l.odoo_picking_id
                    and not l.odoo_internal_transfer_order_id
                )
            )
        )
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        self.ensure_one()
        print(self)
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

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

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

    # def _find_loginext_wh(self, shipment_location_id):
    #     Warehouse = self.env['stock.location.acumatica']
    #     warehouse = False
    #     code = shipment_location_id
    #     print(code)
    #     if code:
    #         warehouse = Warehouse.search([('code', '=', code)], limit=1)
    #         # if warehouse:
    #         #     if not warehouse.loginext_branch:
    #         #         warehouse = False
    #         #     else:
    #         #         warehouse = warehouse.loginext_branch

    #     return warehouse


    # def _build_loginext_header(self, adt_ShipmentNbr, ship_date, shipment_location_id, ship_weight, shipment_volume, partner, shipment_city, shipment_country, shipment_postal_code, shipment_street, picking):
    #     loginext_wh = self._find_loginext_wh(shipment_location_id)

    #     loginext_order_no = f"testing-dev-{adt_ShipmentNbr}"
    #     _logger.info("loginext_order_no         : %s", loginext_order_no)
    #     _logger.info("ship_date                 : %s", ship_date)
    #     _logger.info("loginext_wh               : %s", loginext_wh)
    #     _logger.info("loginext_wh.loginext_branch : %s", loginext_wh.loginext_branch if loginext_wh else False)
    #     _logger.info("ship_weight              : %s", ship_weight)
    #     _logger.info("shipment_volume          : %s", shipment_volume)
    #     _logger.info("partner                  : %s", partner)
    #     _logger.info("partner.name             : %s", partner.name if partner else False)
    #     _logger.info("partner.id               : %s", partner.id if partner else False)
    #     _logger.info("shipment_street          : %s", shipment_street)
    #     _logger.info("shipment_city            : %s", shipment_city)
    #     _logger.info("shipment_country         : %s", shipment_country)
    #     _logger.info("shipment_postal_code     : %s", shipment_postal_code)
    #     _logger.info("loginext_state.code      : %s", loginext_wh.loginext_state.code if loginext_wh and loginext_wh.loginext_state else False)
    #     _logger.info("picking                  : %s", picking)
    #     updated_vals = {
    #         'loginext_order_no' : loginext_order_no if loginext_order_no else '',
    #         'loginext_shipment_order_dt' : ship_date if ship_date else '',
    #         'loginext_shipment_order_type_cd' : "DELIVER",
    #         'loginext_order_state' : "FORWARD"  if "FORWARD"  else '',
    #         'loginext_distribution_center' : loginext_wh.loginext_branch if loginext_wh.loginext_branch else '',
    #         'loginext_return_branch' : loginext_wh.loginext_branch if loginext_wh.loginext_branch else '',
    #         'loginext_package_weight' : ship_weight if ship_weight else '',
    #         'loginext_package_volume' : shipment_volume if shipment_volume else '',
    #         'loginext_preparation_time' : '30',
    #         'loginext_payment_type' : "Prepaid",
    #         'loginext_package_value' : ship_weight if ship_weight else '',
    #         'loginext_partial_delivery_allowed_fl' : "Y",
    #         'loginext_return_allowed_fl' : "Y",
    #         'loginext_cancellation_allowed_fl' : "Y",
    #         'loginext_deliver_service_time' : '30',
    #         'loginext_deliver_start_time_window' : ship_date if ship_date else '',
    #         'loginext_deliver_end_time_window' : ship_date if ship_date else '',
    #         'loginext_delivery_type' : "DRIVER",
    #         'loginext_deliver_branch' : loginext_wh.loginext_branch if loginext_wh.loginext_branch else '',
    #         'loginext_deliver_account_code' : partner.name if partner.name else '',
    #         'loginext_deliver_account_name' : partner.id if partner.id else '',
    #         'loginext_deliver_apartment' : shipment_street if shipment_street else '',
    #         'loginext_deliver_street_name' : shipment_street if shipment_street else '',
    #         'loginext_deliver_locality' : shipment_city if shipment_city else '',
    #         'loginext_deliver_city' : shipment_city if shipment_city else '',
    #         'loginext_deliver_state' : loginext_wh.loginext_state.code if loginext_wh.loginext_state.code else '',
    #         'loginext_deliver_country' : shipment_country if shipment_country else '',
    #         'loginext_deliver_pin_code' : shipment_postal_code if shipment_postal_code else '',
    #         'loginext_deliver_address_timezone' : "Asia/Jakarta",
    #         'loginext_deliver_notes' : f'"Delivered" atau "ShipVia"',
    #         'odoo_shipment_number' : picking if picking else '',

    #     }

    #     created_loginext_header = self.env['loginext.staging.data'].create(updated_vals)
    #     _logger.info("TMS Header Created: %s", created_loginext_header)

    #     return created_loginext_header

    # def _build_loginext_item(self, product, shipment_type, header, move_count, shipment_weight, item_qty):

    #     crate_vals = {
    #         'loginext_crate_cd' : f"{product.default_code}|{move_count}",
    #         'loginext_crate_name' : product.name,
    #         'loginext_crate_type' : shipment_type,
    #         'loginext_crate_weight' : shipment_weight,
    #         'staging_id' : header
    #     }

    #     crate = self.env['loginext.staging.crate'].create(crate_vals)
    #     _logger.info("TMS Crate Created: %s", crate)

    #     item_vals = {
    #         'loginext_item_cd' : f"{product.default_code}",
    #         'loginext_item_name' : product.name,
    #         'loginext_item_type' : shipment_type,
    #         'loginext_item_weight' : shipment_weight,
    #         'loginext_item_quantity' : item_qty,
    #         'staging_id' : header,
    #         'crate_id' : crate.id
    #     }
    #     items = self.env['loginext.staging.item'].create(item_vals)
    #     _logger.info("TMS Item Created: %s", items)




class AcumaticaSalesOrderShipmentStaging(models.Model):
    _name = 'acumatica.sales.order.shipment.staging'
    _description = 'Staging Data Shipment Receipt dari Acumatica'


    config_id = fields.Char()

    acumatica_id = fields.Char()
    rownumber = fields.Integer()
    noteid = fields.Char()
    warehousename = fields.Char()

    shiptoaddressoverride = fields.Boolean()
    shiptocontactoverride = fields.Boolean()

    note = fields.Text(string='Note', readonly=True)
    controlqty = fields.Float(string='Control Qty', readonly=True)
    customerid = fields.Char(string='Customer ID', readonly=True)
    description = fields.Text(string='Description', readonly=True)
    fobpoint = fields.Char(string='FOB Point', readonly=True)
    fobpointdescription = fields.Text(string='FOB Point Description', readonly=True)
    hold = fields.Boolean(string='Hold', readonly=True)
    insurance = fields.Float(string='Insurance', readonly=True)
    lastmodifieddatetime = fields.Datetime(string='Last Modified Date', readonly=True)
    locationid = fields.Char(string='Location ID', readonly=True)
    locationname = fields.Char(string='Location Name', readonly=True)
    operation = fields.Char(string='Operation', readonly=True)
    packagecount = fields.Integer(string='Package Count', readonly=True)
    packageweight = fields.Float(string='Package Weight', readonly=True)
    shipmentdate = fields.Date(string='Shipment Date', readonly=True)
    shipmentnbr = fields.Char(string='Shipment Number', readonly=True)
    shippedqty = fields.Float(string='Shipped Qty', readonly=True)
    shippedvolume = fields.Float(string='Shipped Volume', readonly=True)
    shippedweight = fields.Float(string='Shipped Weight', readonly=True)
    shippingzoneid = fields.Char(string='Shipping Zone ID', readonly=True)
    shipvia = fields.Char(string='Ship Via', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    towarehouseid = fields.Char(string='To Warehouse ID', readonly=True)
    type = fields.Char(string='Type', readonly=True)
    unlimitedpackages = fields.Boolean(string='Unlimited Packages', readonly=True)
    warehouseid = fields.Char(string='Warehouse ID', readonly=True)
    locationname = fields.Char(string='Location Name', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')


# =====================================================================================================================================================================
    # Service Function
# =====================================================================================================================================================================

    def _find_responsible(self):
        user = self.env['res.users'].search([('name', '=', 'System User')], limit=1)

        if not user:
            user = self.env['res.users'].create({
                'name': 'System User',
                'login': 'system.user@aditya_sarana_graha.com',
            })

        return user

    def _find_product(self, line, source_location):
        print('Starting search product')

        Product = self.env['product.product']
        Quant = self.env['stock.quant']
        Location = self.env['stock.location']

        product = False
        abort_picking = False
        # =====================================================
        # FIND PRODUCT
        # =====================================================

        if line:

            product = Product.search([
                ('default_code', '=', line.inventoryid)
            ], limit=1)

        else:
            print(
                # f"PRODUCT NOT FOUND | "Proses picking dibatalkan karena ada produk yang bermasalah
                f"InventoryID={line.inventoryid}"
            )

            return False

        if source_location:
            location = Location.search([
                ('id', '=', source_location)
            ])

        else:
            print(f"Lokasi dengan id: {source_location} Tidak ditemukan")



        print(
            f"PRODUCT FOUND | "
            f"ID={product.id} | "
            f"CODE={product.default_code} | "
        )

        # =====================================================
        # CHECK STOCK
        # =====================================================


        quants = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', '=', source_location),
        ])
        available_qty = sum(
            q.quantity - q.reserved_quantity
            for q in quants
        )

        print(
            f" | AVAILABLE QTY = {available_qty} | "
            f"REQUIRED = {line.shippedqty} | "
            f"Location = {location.complete_name} | "
        )

        if line.shippedqty and available_qty < line.shippedqty:

            print(
                f"INSUFFICIENT STOCK | "
                f"Product={product.display_name}"
            )
            abort_picking = True

        # if abort_picking:
        #     raise ValueError(f"Stock pada warehouse untuk product {product.display_name} Kosong")

        return {
            'product': product,
            'abort_picking' : abort_picking
        }

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line:
            partner = Partner.search([('ref', '=', line)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line)], limit=1)
        return partner

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse

    def _find_destination_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.warehouse_id
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_source_location(self, warehouse=False):
        Location = self.env['stock.location']
        supplier_loc = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        if supplier_loc:
            return supplier_loc
        return Location.search([('usage', '=', 'supplier')], limit=1) or (warehouse and warehouse.lot_stock_id)

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

# Helper Function

    @api.depends('shipmentnbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.receipt_nbr and Picking.search_count([('origin', '=', rec.receipt_nbr)]))

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

    def action_import_selected(self):
        lines = self.filtered(
            lambda l: (
                l.import_state in ['staged', 'error']
                or (l.import_state in ['created', 'updated'] and not l.odoo_picking_id)
            )
        )
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        self.ensure_one()
        print(self)
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

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

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})


class AcumaticaSalesOrderShipmentStagingLine(models.Model):
    _name = 'acumatica.sales.order.shipment.staging.line'
    _description = 'Staging Data Detail Shipment Receipt dari Acumatica'

    gi_id = fields.Many2one(
        'acumatica.shipment.gi.staging',
        string='GI Reference',
        ondelete='cascade'
    )

    noteid = fields.Char()

    acumatica_id = fields.Char(string="acumatica_id")
    adt_rowNumber = fields.Char(string="rowNumber")
    adt_LineInventoryID = fields.Char(string="LineInventoryID")
    adt_LineDescription = fields.Char(string="LineDescription")
    adt_LineNote = fields.Char(string="LineNote")
    adt_LineNoteID = fields.Char(string="LineNoteID")
    adt_LineLocation = fields.Char(string="LineLocation")
    adt_LineNbr = fields.Char(string="LineNbr")
    adt_LineQuantity = fields.Char(string="LineQuantity")
    adt_ShipmentQty = fields.Char(string="ShipmentQty")
    adt_LineUOM = fields.Char(string="LineUOM")
    adt_WarehouseID = fields.Char(string="WarehouseID")

    selected = fields.Boolean(string='Pilih', default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')


class AcumaticaSalesOrderShipmentStagingAllocation(models.Model):
    _name = 'acumatica.sales.order.shipment.staging.allocation'
    _description = 'Staging Data Allocation Detail Shipment Receipt dari Acumatica'

    line_id = fields.Many2one(
        'acumatica.sales.order.shipment.staging.line'
    )

    acumatica_id = fields.Char(string='ID', readonly=True)
    rownumber = fields.Integer(string='Row Number', readonly=True)
    note = fields.Text(string='Note', readonly=True)
    description = fields.Text(string='Description', readonly=True)
    inventoryid = fields.Char(string='Inventory ID', readonly=True)
    location  = fields.Char(string='Location ID', readonly=True)
    quantity = fields.Float(string='Quantity', readonly=True)
    splitlinenbr = fields.Integer(string='Split Line Number', readonly=True)
    uom = fields.Char(string='UOM', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')


class AcumaticaSalesOrderShipmentShipToAddressStaging(models.Model):
    _name = 'acumatica.sales.order.shipment.shiptoaddress.staging'
    _description = 'Staging Data Ship To Address Detail Shipment Receipt dari Acumatica'

    # shipment_id = fields.Many2one(
    #     'acumatica.sales.order.shipment.staging',
    #     required=True,
    #     ondelete='cascade'
    # )

    acumatica_id = fields.Char()
    rownumber = fields.Integer()
    note = fields.Text()

    addressline1 = fields.Char(string='Address Line 1', readonly=True)
    addressline2 = fields.Char(string='Address Line 2', readonly=True)
    city = fields.Char(string='City', readonly=True)
    country = fields.Char(string='Country', readonly=True)
    countryname = fields.Char(string='Country Name', readonly=True)
    document_only = fields.Boolean(string='Document Only', readonly=True)
    postalcode = fields.Char(string='Postal Code', readonly=True)
    state = fields.Char(string='State', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')



class AcumaticaShipmentLine(models.Model):
    _name = 'acumatica.so.shipment.line'
    _description = 'Data Shipment Receipt dari Acumatica'
    _order = 'receipt_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    receipt_nbr = fields.Char(string='Shipment Number', readonly=True, index=True)
    partner_code = fields.Char(string='CustomerID', readonly=True)
    scheduled_date = fields.Char(string='Shipment Date', readonly=True)
    warehouse_code = fields.Char(string='Warehouse Asal', readonly=True)
    warehouse_name = fields.Char(string='Warehouse Name', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Tujuan', readonly=True)
    header_location_code = fields.Char(string='Location Header', readonly=True)
    header_location_name = fields.Char(string='Location Header Name', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    shipment_type = fields.Char(string='Type', readonly=True)
    operation = fields.Char(string='Operation', readonly=True)

    note = fields.Text(string='Header Note', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    description = fields.Char(string='Description Header', readonly=True)
    fob_point = fields.Char(string='FOB Point', readonly=True)
    fob_point_description = fields.Char(string='FOB Point Description', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    is_insurance = fields.Char(string='Insurance', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    package_count = fields.Char(string='Package Count', readonly=True)
    package_weight = fields.Char(string='Package Weight', readonly=True)
    is_picked = fields.Char(string='Picked', readonly=True)
    shipped_qty = fields.Char(string='Shipped Qty Header', readonly=True)
    shipped_volume = fields.Char(string='Shipped Volume', readonly=True)
    shipped_weight = fields.Char(string='Shipped Weight', readonly=True)
    shipping_terms = fields.Char(string='Shipping Terms', readonly=True)
    shipping_settings = fields.Char(string='Shipping Settings', readonly=True)
    shipping_zone = fields.Char(string='Shipping Zone', readonly=True)
    ship_via = fields.Char(string='Ship Via', readonly=True)
    unlimited_packages = fields.Char(string='Unlimited Packages', readonly=True)
    allocations = fields.Text(string='Allocations JSON')

    acumatica_id = fields.Char(string='Acumatica ID', readonly=True)
    acumatica_row_number = fields.Integer(string='Acumatica Row Number', readonly=True)
    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    acumatica_line_number = fields.Char(string='Acumatica Line Number', readonly=True)
    line_description = fields.Char(string='Description Line', readonly=True)
    detail_note = fields.Text(string='Detail Note', readonly=True)
    is_free_item = fields.Char(string='Free Item', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    location_dest_code = fields.Char(string='Location Detail', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    order_line_number = fields.Char(string='Order Line Nbr', readonly=True)
    order_number = fields.Char(string='Order Nbr', readonly=True)
    order_type = fields.Char(string='Order Type', readonly=True)
    original_qty = fields.Char(string='Original Qty', readonly=True)
    detail_shipped_qty = fields.Char(string='Shipped Qty Detail', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    detail_warehouse_code = fields.Char(string='Warehouse Detail', readonly=True)
    adt_type = fields.Char(string='ADT Type', readonly=True)

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged', readonly=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')



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

    # Do Import from staging
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
