import logging
import time
from dateutil import parser as dateutil_parser
from docutils.nodes import note
import requests
import ast

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

class AcumaticaShipmentGIStaging(models.Model):
    _name = 'acumatica.shipment.gi.staging'
    _description = 'Acumatica Shipment GI'
    _rec_name = 'shipment_nbr'

    shipment_ids = fields.One2many(
            'acumatica.sales.order.shipment.staging',
            'gi_id',
            string='Shipments'
        )    

    acumatica_id = fields.Char('Acumatica ID')
    row_number = fields.Integer('Row Number')

    shipment_nbr = fields.Char('Shipment Number')
    ship_date = fields.Datetime('Ship Date')

    customer = fields.Char('Customer')
    customer_name = fields.Char('Customer Name')

    warehouse_id = fields.Char('Warehouse')
    location = fields.Char('Location')
    location_name = fields.Char('Location Name')

    status = fields.Char('Status')
    shipment_type = fields.Char('Type')

    confirmed = fields.Boolean('Confirmed')
    hold = fields.Boolean('Hold')
    document_only = fields.Boolean('Document Only')
    override_address = fields.Boolean('Override Address')

    address_id = fields.Char('Address ID')
    address_line1 = fields.Char('Address Line 1')
    address_line2 = fields.Char('Address Line 2')
    address_line3 = fields.Char('Address Line 3')

    city = fields.Char('City')
    state = fields.Char('State')
    state_name = fields.Char('State Name')

    country = fields.Char('Country')
    country_name = fields.Char('Country Name')

    postal_code = fields.Char('Postal Code')

    ship_via = fields.Char('Ship Via')
    ship_via_description = fields.Char('Ship Via Description')
    ship_via_address = fields.Char('Ship Via Address')
    ship_via_city = fields.Char('Ship Via City')
    ship_via_phone = fields.Char('Ship Via Phone')
    ship_via_status = fields.Char('Ship Via Status')

    fob_point = fields.Char('FOB Point')
    fob_point_description = fields.Char('FOB Point Description')

    note_ship_via = fields.Char('Note Ship Via')

    order_type = fields.Char('Order Type')

    shipped_quantity = fields.Float('Shipped Quantity')
    shipped_weight = fields.Float('Shipped Weight')
    shipped_volume = fields.Float('Shipped Volume')

    site_id_description = fields.Char('Site Description')
    to_warehouse_id = fields.Char('To Warehouse')

    note = fields.Text('Note')

    active = fields.Boolean(default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    
    odoo_shipment_status = fields.Selection([
        ('pending', "Belum di Proses"),
        ('processed', "Telah di Proses"),
    ], string='Status Odoo', default='pending')


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
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']
        Product = self.env['product.product']
        ErrorPicking = self.env['stock.picking.acumatica.error']  # Pastikan nama model error_picking disesuaikan dengan manifest Anda

        shipment_gi = self.env['acumatica.shipment.gi.staging']
        shipment_header = self.env['acumatica.sales.order.shipment.staging']
        shipment_line = self.env['acumatica.sales.order.shipment.staging.line']

        print("\n" + "=" * 120 + "\nSTART IMPORT SHIPMENT\n" + "=" * 120)

        # =====================================================
        # GET STAGING PENDING
        # =====================================================
        pending_shipments = shipment_gi.search([
            ('odoo_shipment_status', '=', 'pending')
        ])

        print(f"Pending Shipment Count : {len(pending_shipments)}")

        if not pending_shipments:
            print("NO PENDING SHIPMENT FOUND")
            return True

        shipment_numbers = pending_shipments.mapped('shipment_nbr')
        print(f"Shipment Numbers : {shipment_numbers}")

        # =====================================================
        # PICKING EXISTING
        # =====================================================
        existing_pickings = Picking.search([
            ('origin', 'in', shipment_numbers)
        ])

        print(f"Existing Picking Count : {len(existing_pickings)}")

        pickings_by_origin = {}
        for picking in existing_pickings:
            pickings_by_origin.setdefault(
                (picking.origin or '').strip(),
                []
            ).append(picking)

        # =====================================================
        # PROCESS SHIPMENT
        # =====================================================
        for shipment in pending_shipments:
            print("\n" + "#" * 120 + f"\nPROCESS SHIPMENT : {shipment.shipment_nbr}\n" + "#" * 120)
            
            shipment_number = (shipment.shipment_nbr or '').strip()

            # MEKANISME SAVEPOINT DIMULAI DISINI
            # Jika terjadi error di dalam blok 'with', Odoo hanya me-rollback perubahan untuk shipment ini saja.
            try:
                with self.env.cr.savepoint():
                    
                    # =================================================
                    # VALIDASI DATA MANUAL (RAISE ERROR JIKA GAGAL)
                    # =================================================
                    
                    # 1. WAREHOUSE
                    warehouse = self._find_warehouse(shipment.warehouse_id)
                    if not warehouse:
                        raise ValidationError(f"Warehouse {shipment.warehouse_id} tidak ditemukan")

                    # 2. PARTNER
                    partner = self._find_partner(shipment.customer)
                    if not partner:
                        raise ValidationError(f"Customer {shipment.customer} tidak ditemukan")

                    # 3. USER
                    responsible_user = self._find_responsible()

                    # 4. PICKING TYPE
                    picking_type = PickingType.search([
                        ('warehouse_id', '=', warehouse.id),
                        ('code', '=', 'outgoing')
                    ], limit=1)
                    
                    if not picking_type:
                        raise ValidationError(f"Picking Type 'outgoing' untuk Warehouse {warehouse.name} tidak ditemukan")

                    # Ambil Default Destination Location untuk mencegah error mandatory 'To' (location_dest_id)
                    # Odoo 18 membutuhkan default destination location pada stock move line
                    default_dest_location = picking_type.default_location_dest_id.id
                    if not default_dest_location:
                        raise ValidationError(f"Default Destination Location pada Picking Type {picking_type.name} belum diatur.")

                    # =================================================
                    # RELATED & ACTIVE PICKINGS
                    # =================================================
                    related_pickings = pickings_by_origin.get(shipment_number, [])
                    active_pickings = [p for p in related_pickings if p.state in ('draft', 'assigned')]

                    # =================================================
                    # UPDATE PICKING BRANCH
                    # =================================================
                    if active_pickings:
                        print("\n" + ">" * 80 + "\nUPDATE PICKING BRANCH\n" + ">" * 80)
                        
                        for picking in active_pickings:
                            updated_vals = {
                                'partner_id': partner.id,
                                'scheduled_date': shipment.ship_date,
                                'note': shipment.note,
                                'adt_receipt_nbr': shipment.shipment_nbr,
                                'adt_partner_ref': shipment.customer,
                                'adt_status': shipment.status,
                                'adt_trans_type': shipment.shipment_type,
                                'adt_external_id': shipment.acumatica_id,
                            }
                            picking.write(updated_vals)
                            print(f"SUCCESS UPDATING PICKING ID: {picking.id}")

                            # shipment_line_to_update = shipment_line.search([
                            #     'shipment_id', '=', shipment.id
                            # ])

                            # for item in shipment_line_to_update:
                            #     move = Move.serch
                                

                            
                    # =================================================
                    # CREATE PICKING BRANCH (JIKA TIDAK ADA ACTIVE PICKING)
                    # =================================================
                    else:
                        print("\n" + ">" * 80 + "\nCREATE PICKING BRANCH\n" + ">" * 80)
                        
                        # Pastikan field mandatory location_id & location_dest_id terisi di level picking & move lines
                        new_picking_vals = {
                            'picking_type_id': picking_type.id,
                            'location_id': picking_type.default_location_src_id.id,
                            'location_dest_id': default_dest_location,
                            'partner_id': partner.id,
                            'scheduled_date': shipment.ship_date,
                            'origin': shipment_number,
                            'note': shipment.note,
                            'adt_receipt_nbr': shipment.shipment_nbr,
                            'adt_partner_ref': shipment.customer,
                            'adt_status': shipment.status,
                            'adt_trans_type': shipment.shipment_type,
                            'adt_external_id': shipment.acumatica_id,
                        }
                        new_picking = Picking.create(new_picking_vals)
                        print(f"SUCCESS CREATING NEW PICKING: {new_picking.name} (ID: {new_picking.id})")

                        print(f"Gi ID : {shipment.id}")

                        
                        new_move_id = shipment_header.search([
                            ('gi_id', '=', shipment.id)
                        ])

                        new_move = shipment_line.search([
                            ('shipment_id', '=', new_move_id.id)
                        ])
                        print(f"Shipment line to create: {new_move}")

                        for item in new_move:
                            # code = item.inventoryid
                            Product = self._find_product(item, picking_type.default_location_src_id.id)
                            product = Product['product']

                            new_move_vals = {
                                'company_id' : warehouse.id,
                                'product_id' : Product.id,
                                'product_uom' : Product.produtc_tmpl_id.id ,
                                'location_id' : picking_type.default_location_src_id.id,
                                'location_dest_id' : picking_type.default_location_dest_id.id,
                                'partner_id' : partner.id,
                                'picking_id' : new_picking.id,
                                'picking_type_id' : picking_type.id,
                                'warehouse_id' : picking_type.warehouse_id.id,
                                'name' : item.description,
                                'origin' : new_picking.origin,
                                'description_picking' : item.description,
                                'product_qty' : item.shippedqty,
                                'product_uom_qty' : item.shippedqty,
                                'date' : shipment.ship_date,
                                'date_deadline' : shipment.ship_date,
                                'adt_line_external_id' : item.acumatica_id,
                                'adt_inventory_id' : item.inventoryid,
                                'adt_po_line_number' : item.shipment,
                                'adt_uom_code' : item.uom,
                                'adt_line_note' : item.note,
                                'adt_open_qty' : item.shippedqty,
                                'adt_type' : 'Sales Order Shipmentitem.',
                                'adt_line_description' : item.description,
                            }

                            move = Move.create(new_move_vals)
                            print(f"Success create Move : {move.id}")

                    # Jika sukses melintasi semua proses di atas tanpa crash, update status staging jadi success
                    shipment.write({
                        'import_message': 'Import berhasil tanpa error'
                    })

            # =====================================================
            # MEKANISME ABORT & ERROR LOGGING (UNTUK 1 SHIPMENT)
            # =====================================================
            except Exception as e:
                # Mengambil pesan error teks
                error_msg = str(e)
                print(f"!!! ERROR DETECTED ON SHIPMENT {shipment_number}: {error_msg}")
                
                # 1. Update status staging menjadi 'failed' agar tidak di-proses ulang langsung
                shipment.write({
                    'import_message': f'Error: {error_msg}'
                })

                # 2. Buat record baru di tabel error_picking sebagai log audit
                # Sesuai instruksi Anda: "Jika ada error maka create di model error_picking"
                ErrorPicking.create({
                    'origin': shipment_number,
                    'partner': shipment.customer,
                    'api_acumatica' : 'so_shipment'
                    # 'warehouse_id': shipment.warehouse_id,
                    # 'error_reason': error_msg,
                    # Tambahkan field lain yang ada di model error_picking Anda di bawah ini
                })
                
                # Gunakan continue agar jika shipment ke-1 error, perulangan ke shipment ke-2 tetap berjalan
                continue

        return True

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
            f"AVAILABLE QTY = {available_qty} | "
            f"REQUIRED = {line.shippedqty}"
        )

        if line.shippedqty and available_qty < line.shippedqty:

            print(
                f"INSUFFICIENT STOCK | "
                f"Product={product.display_name}"
            )
            abort_picking = True

        if abort_picking:
            raise ValueError(f"Stock pada warehouse untuk product {product.display_name} Kosong")

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
        Warehouse = self.env['stock.warehouse']
        code = line

        # 1. Jalankan query SQL (Pastikan argumen dalam bentuk tuple/list)
        self.env.cr.execute("""
            SELECT id, code
            FROM stock_warehouse
            WHERE code = %s
        """, (code,))
        
        # 2. Ambil hasilnya dan simpan ke dalam variabel (Hanya panggil fetchall SEKALI)
        sql_result = self.env.cr.fetchall()
        # raise UserError('checkpoint')
        
        warehouse = False
        # 3. Jika SQL menemukan data, ambil ID dari elemen pertama
        if sql_result:
            warehouse_id = sql_result[0][0] # Mengambil angka 176 dari [(176, 'WH33-FG')]
            
            # 4. Cari menggunakan ORM berdasarkan ID yang didapat dari SQL
            # Tambahkan context active_test=False untuk berjaga-jaga jika record di-archived
            warehouse = Warehouse.sudo().with_context(active_test=False).search([('id', '=', warehouse_id)], limit=1)

        # raise UserError('Checkpoint')
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

    @api.depends('shipment_nbr')
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
        
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()





class AcumaticaSalesOrderShipmentStaging(models.Model):
    _name = 'acumatica.sales.order.shipment.staging'
    _description = 'Staging Data Shipment Receipt dari Acumatica'

    gi_id = fields.Many2one(
        'acumatica.shipment.gi.staging'
    )

    shipto_address_id = fields.Many2one(
        'acumatica.sales.order.shipment.shiptoaddress.staging'
    )

    line_ids = fields.One2many(
        'acumatica.sales.order.shipment.staging.line',
        'shipment_id'
    )

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
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('odoo_picking_id')
    def _compute_exists_in_odoo(self):
        for rec in self:
            rec.exists_in_odoo = bool(rec.odoo_picking_id)



class AcumaticaSalesOrderShipmentStagingLine(models.Model):
    _name = 'acumatica.sales.order.shipment.staging.line'
    _description = 'Staging Data Detail Shipment Receipt dari Acumatica'

    shipment_id = fields.Many2one(
        'acumatica.sales.order.shipment.staging'
    )

    allocation_ids = fields.One2many(
        'acumatica.sales.order.shipment.staging.allocation',
        'line_id'
    )

    noteid = fields.Char()    

    acumatica_id = fields.Char(string='ID', readonly=True)
    rownumber = fields.Integer(string='Row Number', readonly=True)
    note = fields.Text(string='Note', readonly=True)
    description = fields.Text(string='Description', readonly=True)
    freeitem = fields.Boolean(string='Free Item', readonly=True)
    inventoryid = fields.Char(string='Inventory ID', readonly=True)
    linenbr = fields.Integer(string='Line Number', readonly=True)
    location = fields.Char(string='Location', readonly=True)
    openorderqty = fields.Float(string='Open Order Qty', readonly=True)
    orderedqty = fields.Float(string='Ordered Qty', readonly=True)
    orderlinenbr = fields.Integer(string='Order Line Number', readonly=True)
    ordernbr = fields.Char(string='Order Number', readonly=True)
    ordertype = fields.Char(string='Order Type', readonly=True)
    shippedqty = fields.Float(string='Shipped Qty', readonly=True)
    uom = fields.Char(string='UOM', readonly=True)
    warehouseid = fields.Char(string='Warehouse ID', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')


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
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')


class AcumaticaSalesOrderShipmentShipToAddressStaging(models.Model):
    _name = 'acumatica.sales.order.shipment.shiptoaddress.staging'
    _description = 'Staging Data Ship To Address Detail Shipment Receipt dari Acumatica'

    shipment_id = fields.Many2one(
        'acumatica.sales.order.shipment.staging',
        required=True,
        ondelete='cascade'
    )

    acumatica_id = fields.Char()
    rownumber = fields.Integer()
    note = fields.Text()

    addressline1 = fields.Char(string='Address Line 1', readonly=True)
    addressline2 = fields.Char(string='Address Line 2', readonly=True)
    city = fields.Char(string='City', readonly=True)
    country = fields.Char(string='Country', readonly=True)
    countryname = fields.Char(string='Country Name', readonly=True)
    postalcode = fields.Char(string='Postal Code', readonly=True)
    state = fields.Char(string='State', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')



class AcumaticaShipmentConfig(models.Model):
    _name = 'acumatica.so.shipment.config'
    _description = 'Konfigurasi Koneksi Acumatica - Shipment Receipt'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Shipment Receipt')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.002')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
    shipment_gi_endpoint = fields.Char(required=True, default="ShipmentGI")
    shipment_gi_expand = fields.Char(required=True, default="ShipmentGIDetails")
    endpoint_name = fields.Char(required=True, default='Shipment')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], default='draft', readonly=True)

    odata_expand = fields.Char(default='Details')
    odata_select = fields.Char()
    odata_filter = fields.Char(default="Type eq 'Shipment' and Operation eq 'Receipt'")

    @property
    def api_url(self):
        return f"{self.base_url}/wms/{self.api_version}"

    @property
    def login_url(self):
        return f"{self.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.base_url}/auth/logout"

    def action_test_connection(self):
        self.ensure_one()
        try:
            session = self._do_login()
            self._do_logout(session)
            self.state = 'connected'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Koneksi Berhasil',
                    'message': f'Berhasil terhubung ke {self.base_url}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    def _do_login(self):
        self.ensure_one()

        last_error = None

        for attempt in range(3):
            try:
                session = requests.Session()

                response = session.post(
                    self.login_url,
                    json={
                        'name': self.username,
                        'password': self.password,
                        'company': self.company_code,
                    },
                    headers={'Content-Type': 'application/json'},
                    timeout=30,
                )

                if response.status_code == 204:
                    return session

                last_error = (
                    f'Login gagal (HTTP {response.status_code}): '
                    f'{response.text}'
                )

            except Exception as e:
                last_error = str(e)

            # sleep 3 detik sebelum retry berikutnya
            if attempt < 2:
                time.sleep(3)

        raise UserError(
            f'Login gagal setelah 3 kali percobaan. Detail: {last_error}'
        )

    def _do_logout(self, session):
        self.ensure_one()

        last_error = None

        for attempt in range(3):
            try:
                response = session.post(
                    self.logout_url,
                    timeout=10,
                )

                if response.ok:
                    return

                last_error = (
                    f'Logout gagal (HTTP {response.status_code}): '
                    f'{response.text}'
                )

            except requests.exceptions.RequestException as e:
                last_error = str(e)

            if attempt < 2:
                time.sleep(3)

        # biasanya logout tidak perlu menggagalkan proses utama
        _logger.warning(
            "Logout gagal setelah 3 percobaan: %s",
            last_error,
        )

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False


    def fetch_shipment_gi_data(self):
        import json
        import logging
        import traceback

        _logger = logging.getLogger(__name__)

        print("fetching shipment GI data")
        # self.env['acumatica.shipment.gi.staging'].search([]).unlink()


        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/{self.shipment_gi_endpoint}"

            params = {}
            if self.shipment_gi_expand:
                params["$expand"] = self.shipment_gi_expand

            session.headers.update({
                "Accept": "application/json",
                "Content-Type": "application/json",
            })

            response = session.put(
                endpoint,
                params=params,
                json={},
                timeout=90
            )


            if response.status_code != 200:
                raise UserError(
                    f"Gagal ambil data Shipment GI "
                    f"(HTTP {response.status_code}): {response.text}"
                )

            api_data = response.json()

            details = api_data.get("ShipmentGIDetails", [])


            shipment_gi_data = []
            shipment_numbers = []

            for item in details:
                ship_date = self._val(item, "ShipDate")
                phrase_date = dateutil_parser.parse(ship_date).replace(tzinfo=None)


                vals = {
                    "acumatica_id": item.get("id", ""),
                    "row_number": item.get("rowNumber", ""),

                    "address_id": self._val(item, "AddressID"),
                    "address_line1": self._val(item, "AddressLine1"),
                    "address_line2": self._val(item, "AddressLine2"),
                    "address_line3": self._val(item, "AddressLine3"),

                    "city": self._val(item, "City"),

                    "confirmed": self._val(item, "Confirmed"),

                    "country": self._val(item, "Country"),
                    "country_name": self._val(item, "CountryName"),

                    "customer": self._val(item, "Customer"),
                    "customer_name": self._val(item, "CustomerName"),

                    "document_only": self._val(item, "DocumentOnly"),

                    "fob_point": self._val(item, "FOBPoint"),
                    "fob_point_description": self._val(
                        item,
                        "FOBPointDescription"
                    ),

                    "hold": self._val(item, "Hold"),

                    "location": self._val(item, "Location"),
                    "location_name": self._val(item, "LocationName"),

                    "note_ship_via": self._val(item, "NoteShipVia"),

                    "order_type": self._val(item, "OrderType"),

                    "override_address": self._val(item, "OverrideAddress"),

                    "postal_code": self._val(item, "PostalCode"),

                    "ship_date": phrase_date,

                    "shipment_nbr": self._val(item, "ShipmentNbr"),

                    "shipped_quantity": self._val(item, "ShippedQuantity"),
                    "shipped_volume": self._val(item, "ShippedVolume"),
                    "shipped_weight": self._val(item, "ShippedWeight"),

                    "ship_via": self._val(item, "ShipVia"),
                    "ship_via_address": self._val(item, "ShipViaAddress"),
                    "ship_via_city": self._val(item, "ShipViaCity"),
                    "ship_via_description": self._val(
                        item,
                        "ShipViaDescription"
                    ),
                    "ship_via_phone": self._val(item, "ShipViaPhone"),
                    "ship_via_status": self._val(item, "ShipViaStatus"),

                    "site_id_description": self._val(
                        item,
                        "SiteIDDescription"
                    ),

                    "state": self._val(item, "State"),
                    "state_name": self._val(item, "StateName"),

                    "status": self._val(item, "Status"),

                    "to_warehouse_id": self._val(item, "ToWarehouseID"),

                    "shipment_type": self._val(item, "Type"),

                    "warehouse_id": self._val(item, "WarehouseID"),
                }

                shipment_numbers.append(self._val(item, "ShipmentNbr"))

                shipment_gi_data.append(vals)


            return shipment_gi_data, shipment_numbers

        except Exception as e:
            _logger.exception("Shipment GI Import Error")
            raise UserError(str(e))

        finally:
            self._do_logout(session)

    def fetch_shipment_data(
        self,
        shipment_numbers=None,
        odata_filter=None,
    ):
        self.ensure_one()

        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/{self.endpoint_name}"

            params = {}
            filters = []

            if self.odata_expand:
                params["$expand"] = self.odata_expand

            if self.odata_select:
                params["$select"] = self.odata_select

            # =====================================================
            # FILTER SHIPMENT NUMBER
            # =====================================================

            if shipment_numbers:

                shipment_filter = " or ".join([
                    f"ShipmentNbr eq '{nbr}'"
                    for nbr in shipment_numbers
                    if nbr
                ])

                if shipment_filter:
                    filters.append(f"({shipment_filter})")

            if odata_filter:
                filters.append(f"({odata_filter})")

            elif self.odata_filter:
                filters.append(f"({self.odata_filter})")

            if filters:
                params["$filter"] = " and ".join(filters)

            response = session.get(
                endpoint,
                params=params,
                timeout=90
            )

            if response.status_code != 200:
                raise UserError(
                    f"Gagal ambil Shipment "
                    f"(HTTP {response.status_code}): "
                    f"{response.text}"
                )

            raw_data = self._normalize_rows(
                response.json()
            )

            result = []

            # =====================================================
            # SHIPMENT LOOP
            # =====================================================

            for item in raw_data:

                shipment_dict = {

                    "header": {
                        "acumatica_id":item.get("id"),
                        "rownumber":item.get("rowNumber"),
                        "note":self._val(item, "note"),
                        "controlqty":self._val(item, "ControlQty"),
                        "customerid":self._val(item, "CustomerID"),
                        "description":self._val(item, "Description"),
                        "fobpoint":self._val(item, "FOBPoint"),
                        "fobpointdescription":self._val(item,"FOBPointDescription"),
                        "hold":self._val(item, "Hold"),
                        "insurance":self._val(item, "Insurance"),
                        "lastmodifieddatetime":self._parse_dt(self._val(item,"LastModifiedDateTime")),
                        "locationid":self._val(item, "LocationID"),
                        "locationname":self._val(item, "LocationName"),
                        "operation":self._val(item, "Operation"),
                        "packagecount":self._val(item, "PackageCount"),
                        "packageweight":self._val(item, "PackageWeight"),
                        "shipmentdate":self._parse_dt(self._val(item,"ShipmentDate")),
                        "shipmentnbr":self._val(item, "ShipmentNbr"),
                        "shippedqty":self._val(item, "ShippedQty"),
                        "shippedvolume":self._val(item, "ShippedVolume"),
                        "shippedweight":self._val(item, "ShippedWeight"),
                        "shippingzoneid":self._val(item, "ShippingZoneID"),
                        "shipvia":self._val(item, "ShipVia"),
                        "status":self._val(item, "Status"),
                        "towarehouseid":self._val(item, "ToWarehouseID"),
                        "type":self._val(item, "Type"),
                        "unlimitedpackages":self._val(item, "UnlimitedPackages"),
                        "warehouseid":self._val(item, "WarehouseID"),
                        "warehousename":self._val(item, "WarehouseName"),
                    },

                    "shipto_address": {},

                    "details": []
                }

                # =================================================
                # SHIP TO ADDRESS
                # =================================================

                shipping_settings = (
                    item.get("ShippingSettings")
                    or {}
                )

                shipto = (
                    shipping_settings.get(
                        "ShipToAddress"
                    )
                    or {}
                )

                if shipto:

                    shipment_dict[
                        "shipto_address"
                    ] = {
                        "addressline1":self._val(shipto,"AddressLine1"),
                        "addressline2":self._val(shipto,"AddressLine2"),
                        "city":self._val(shipto,"City"),
                        "country":self._val(shipto,"Country"),
                        "countryname":self._val(shipto,"CountryName"),
                        "postalcode":self._val(shipto,"PostalCode"),
                        "state":self._val(shipto,"State"),
                    }

                # =================================================
                # DETAILS
                # =================================================

                details = (
                    item.get("Details")
                    or []
                )

                for detail in details:

                    detail_dict = {

                        "detail": {
                            "acumatica_id": detail.get("id"),
                            "rownumber": detail.get("rowNumber"),
                            "note": self._val(detail, "note"),
                            "description": self._val(detail, "Description"),
                            "freeitem": self._val(detail, "FreeItem"),
                            "inventoryid": self._val(detail, "InventoryID"),
                            "linenbr": self._val(detail, "LineNbr"),
                            "location": self._val(detail, "Location"),
                            "openorderqty": self._val(detail, "OpenOrderQty"),
                            "orderedqty": self._val(detail, "OrderedQty"),
                            "orderlinenbr": self._val(detail, "OrderLineNbr"),
                            "ordernbr": self._val(detail, "OrderNbr"),
                            "ordertype": self._val(detail, "OrderType"),
                            "shippedqty": self._val(detail, "ShippedQty"),
                            "uom": self._val(detail, "UOM"),
                            "warehouseid": self._val(detail, "WarehouseID"),
                        },

                        "allocations": []}

                    allocations = (detail.get("Allocations")or [])

                    for alloc in allocations:

                        detail_dict[
                            "allocations"
                        ].append(
                        {
                            "acumatica_id": alloc.get("id"),
                            "rownumber": alloc.get("rowNumber"),
                            "note": self._val(alloc, "note"),
                            "description": self._val(alloc, "Description"),
                            "inventoryid": self._val(alloc, "InventoryID"),
                            "location": self._val(alloc, "Location"),
                            "quantity": self._val(alloc, "Quantity"),
                            "splitlinenbr": self._val(alloc, "SplitLineNbr"),
                            "uom": self._val(alloc, "UOM"),
                        })

                    shipment_dict["details"].append(detail_dict)

                result.append(shipment_dict)

            return result

        finally:
            self._do_logout(session)

    def create_staging_data(self, shipment_gi_data, batch_data):
        staging_shipment_gi = self.env['acumatica.shipment.gi.staging']
        staging_so_shipment= self.env['acumatica.sales.order.shipment.staging']
        staging_so_shipment_detail= self.env['acumatica.sales.order.shipment.staging.line']
        staging_so_shipment_allocation= self.env['acumatica.sales.order.shipment.staging.allocation']
        staging_so_shipment_ship_to_address= self.env['acumatica.sales.order.shipment.shiptoaddress.staging']

        # ==========================================================
        # AMBIL RECORD YANG SUDAH ADA
        # ==========================================================

        acumatica_ids = [
            vals.get('acumatica_id')
            for vals in shipment_gi_data
            if vals.get('acumatica_id')
        ]

        existing_records = staging_shipment_gi.search([
            ('acumatica_id', 'in', acumatica_ids)
        ])

        existing_map = {
            rec.acumatica_id: rec
            for rec in existing_records
        }

        created_count = 0
        updated_count = 0

        # ==========================================================
        # CREATE / UPDATE SHIPMENT GI
        # ==========================================================

        for item in shipment_gi_data:

            acumatica_id = item.get('acumatica_id')

            vals = {
                "acumatica_id": item.get('acumatica_id'),
                "row_number": item.get('row_number'),

                "address_id": item.get('address_id'),
                "address_line1": item.get('address_line1'),
                "address_line2": item.get('address_line2'),
                "address_line3": item.get('address_line3'),

                "city": item.get('city'),
                "state": item.get('state'),
                "state_name": item.get('state_name'),

                "country": item.get('country'),
                "country_name": item.get('country_name'),
                "postal_code": item.get('postal_code'),

                "customer": item.get('customer'),
                "customer_name": item.get('customer_name'),

                "confirmed": item.get('confirmed'),
                "hold": item.get('hold'),
                "document_only": item.get('document_only'),
                "override_address": item.get('override_address'),

                "fob_point": item.get('fob_point'),
                "fob_point_description": item.get('fob_point_description'),

                "location": item.get('location'),
                "location_name": item.get('location_name'),

                "note_ship_via": item.get('note_ship_via'),

                "order_type": item.get('order_type'),

                "ship_date": item.get('ship_date'),
                "shipment_nbr": item.get('shipment_nbr'),

                "shipped_quantity": item.get('shipped_quantity'),
                "shipped_volume": item.get('shipped_volume'),
                "shipped_weight": item.get('shipped_weight'),

                "ship_via": item.get('ship_via'),
                "ship_via_address": item.get('ship_via_address'),
                "ship_via_city": item.get('ship_via_city'),
                "ship_via_description": item.get('ship_via_description'),
                "ship_via_phone": item.get('ship_via_phone'),
                "ship_via_status": item.get('ship_via_status'),

                "site_id_description": item.get('site_id_description'),

                "status": item.get('status'),
                "shipment_type": item.get('shipment_type'),

                "to_warehouse_id": item.get('to_warehouse_id'),
                "warehouse_id": item.get('warehouse_id'),

                "note": item.get('note'),

                "config_id": self.id,
                "sync_date": fields.Datetime.now(),
            }

            existing = existing_map.get(acumatica_id)

            # ======================================================
            # UPDATE
            # ======================================================

            if existing:

                vals.update({
                    'import_message': 'Data staging diperbarui dari Acumatica',
                })

                existing.write(vals)

                updated_count += 1

                print(
                    f"UPDATED | "
                    f"ID={existing.id} | "
                    f"Shipment={existing.shipment_nbr} | "
                    f"Acumatica={acumatica_id}"
                )

            # ======================================================
            # CREATE
            # ======================================================

            else:

                vals.update({
                    'import_state': 'pending',
                    'import_message': 'Data baru dari Acumatica',
                })

                new_rec = staging_shipment_gi.create(vals)

                created_count += 1

                print(
                    f"CREATED | "
                    f"ID={new_rec.id} | "
                    f"Shipment={new_rec.shipment_nbr} | "
                    f"Acumatica={acumatica_id}"
                )

        # ==========================================================
        # SUMMARY
        # ==========================================================

        print(
            f"Sync Shipment GI selesai | "
            f"Created={created_count} | "
            f"Updated={updated_count}"
        )

        # ==================================================
        # SHIPMENT HEADER
        # ==================================================

        shipment_ids = [
            x["header"].get("acumatica_id")
            for x in batch_data
            if x["header"].get("acumatica_id")
        ]

        existing_shipments = staging_so_shipment.search([
            ("acumatica_id", "in", shipment_ids)
        ])

        shipment_map = {
            rec.acumatica_id: rec
            for rec in existing_shipments
        }        

        gi_map = {
            rec.shipment_nbr: rec.id
            for rec in staging_shipment_gi.search([])
        }

        for shipment in batch_data:

            shipment_vals = dict(
                shipment["header"]
            )

            shipment_nbr = shipment_vals.get(
                "shipmentnbr"
            )

            shipment_vals["gi_id"] = gi_map.get(
                shipment_nbr
            )

            shipment_vals.update({
                "config_id": self.id,
                "sync_date": fields.Datetime.now(),
            })

            existing = shipment_map.get(acumatica_id)
            for field, value in shipment_vals.items():
                print(f"{field}: {value}")

            # ======================================================
            # UPDATE
            # ======================================================

            if existing:

                shipment_vals.update({
                    'import_state': 'updated',
                    'import_message': 'Data diperbarui dari Acumatica',
                })

                existing.write(shipment_vals)
                shipment_rec = existing
                print(f"Shipment Updated: {existing.id} with row number {existing.rownumber}")
            
            else:
                shipment_rec = staging_so_shipment.create(
                    shipment_vals
                )
                print(
                    f"Shipment Created: "
                    f"{shipment_rec.id} "
                    f"{shipment_rec.shipmentnbr}"
                )



            # ==================================================
            # SHIP TO ADDRESS
            # ==================================================

            shipto_rec = False

            if shipment.get("shipto_address"):
                shipto_vals = dict(
                    shipment["shipto_address"]
                )

                shipto_vals["shipment_id"] = shipment_rec.id

                shipto_rec = staging_so_shipment_ship_to_address.create(
                    shipto_vals
                )

            # ==================================================
            # DETAILS
            # ==================================================

            for detail_data in shipment["details"]:

                detail_vals = dict(
                    detail_data["detail"]
                )

                detail_vals[
                    "shipment_id"
                ] = shipment_rec.id

                detail_rec = staging_so_shipment_detail.create(
                    detail_vals
                )

                print(
                    f"  Detail Created: "
                    f"{detail_rec.id}"
                )

                # ==============================================
                # ALLOCATIONS
                # ==============================================

                for alloc in detail_data[
                    "allocations"
                ]:

                    alloc_vals = dict(
                        alloc
                    )

                    alloc_vals[
                        "line_id"
                    ] = detail_rec.id

                    alloc_rec = staging_so_shipment_allocation.create(
                        alloc_vals
                    )

                    print(
                        f"    Allocation Created: "
                        f"{alloc_rec.id}"
                    )


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
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.so.shipment.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    


    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    # Do Import from staging
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

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
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})
