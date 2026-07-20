import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaTransferShipmentConfig(models.Model):
    _name = 'acumatica.transfer.shipment.config'
    _description = 'Konfigurasi Koneksi Acumatica - Transfer Shipment'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Transfer Shipment')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.002')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
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
    odata_filter = fields.Char(default="Type eq 'Transfer' and Operation eq 'Issue'")

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
        raise UserError(f'Login gagal (HTTP {response.status_code}): {response.text}')

    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass


class AcumaticaTransferShipmentLine(models.Model):
    _name = 'acumatica.transfer.shipment.line'
    _description = 'Data Transfer Shipment dari Acumatica'
    _order = 'shipment_nbr asc, id asc'

    shipment_line_ids = fields.One2many(
        'acumatica.transfer.shipment.line.product', 
        'shipment_id', 
        string='Shipment Lines'
    )

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_row_number = fields.Char(string='Row Number Detail', readonly=True)

    building_code = fields.Char(string='BuildingID', readonly=True)
    shipment_nbr = fields.Char(string='Shipment Number', readonly=True, index=True)
    partner_code = fields.Char(string='CustomerID', readonly=True)
    customer_name = fields.Char(string='Customer Name', readonly=True)
    description = fields.Char(string='Description Header', readonly=True)
    document_only = fields.Char(string='Document Only', readonly=True)
    fob_point = fields.Char(string='FOB Point', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    is_insurance = fields.Char(string='Insurance', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    header_location_code = fields.Char(string='Location Header', readonly=True)
    location_name = fields.Char(string='Location Name', readonly=True)
    operation = fields.Char(string='Operation', readonly=True)
    package_count = fields.Char(string='Package Count', readonly=True)
    package_weight = fields.Char(string='Package Weight', readonly=True)
    is_picked = fields.Char(string='Picked', readonly=True)
    scheduled_date = fields.Char(string='Shipment Date', readonly=True)
    shipped_qty = fields.Char(string='Shipped Qty Header', readonly=True)
    shipped_volume = fields.Char(string='Shipped Volume', readonly=True)
    shipped_weight = fields.Char(string='Shipped Weight', readonly=True)
    shipping_terms = fields.Char(string='Shipping Terms', readonly=True)
    shipping_zone = fields.Char(string='Shipping Zone', readonly=True)
    ship_via = fields.Char(string='Ship Via', readonly=True)
    site_id_description = fields.Char(string='Site ID Description', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    warehouse_dest_code = fields.Char(string='To Warehouse', readonly=True)
    shipment_type = fields.Char(string='Type', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    is_unlimited_packages = fields.Char(string='Unlimited Packages', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)
    note_header_id = fields.Char(string='Note Header ID', readonly=True)


    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Picking di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])

    @api.depends('shipment_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.shipment_nbr and Picking.search_count([('origin', '=', rec.shipment_nbr)]))

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    @staticmethod
    def _parse_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)
        if not product:
            product = Product.create({
                'name': line.line_description or line.inventory_id or 'Unknown Product',
                'default_code': line.inventory_id or False,
                'type': 'consu',
            })
        return product

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line.partner_code:
            partner = Partner.search([('ref', '=', line.partner_code)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.partner_code)], limit=1)
        return partner

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

    def _find_location(self, code, warehouse=False, fallback_field='lot_stock_id'):
        Location = self.env['stock.location']
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse and hasattr(warehouse, fallback_field):
            location = getattr(warehouse, fallback_field)
        return location
    
    def _find_location2(self, code):
        print("search product location")
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if code.location_dest_code:
            warehouse = Warehouse.search([('code', '=', code.location_dest_code), ('is_active', '=', True)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse


        Location = self.env['stock.location']
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse and hasattr(warehouse, fallback_field):
            location = getattr(warehouse, fallback_field)
        return location

    def _find_uom(self, line, product):
        print("search product uom")
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
            if not uom and product:
                uom = product.uom_id
            
        return uom

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

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

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = updated = error = 0
        shipment_keys = [k for k in self.mapped('shipment_nbr') if k]
        
        print(f"debug : Memulai _do_import dengan total key shipment: {len(shipment_keys)}")

        for shipment_key in shipment_keys:
            print(f"debug : [Shipment {shipment_key}] Memulai pencarian shipment_lines")
            shipment_lines = self.filtered(lambda l: l.shipment_nbr == shipment_key and l.import_state == 'pending')
            if not shipment_lines:
                print(f"debug : [Shipment {shipment_key}] Dilewati karena tidak ada lines berstatus 'pending'")
                continue
            
            first = shipment_lines[0]
            print(f"debug : [Shipment {shipment_key}] Mengambil record pertama (ID Odoo: {first.id})")
            
            try:
                first_data = first.read()[0]
                print("--- SEMUA FIELD DAN NILAI DARI FIRST ---")
                import pprint
                pprint.pprint(first_data) # pprint membuat format json lebih rapi di terminal

                print(f"debug : [Shipment {shipment_key}] Langkah 1: Mencari data warehouse (Source & Destination)")
                source_wh = self._find_warehouse_by_code(first.warehouse_code or first.line_warehouse_code)
                dest_wh = self._find_warehouse_by_code(first.warehouse_dest_code)
                
                if not source_wh:
                    print(f"debug : [Shipment {shipment_key}] ERROR: Warehouse asal tidak ditemukan")
                    raise UserError(f'Warehouse asal tidak ditemukan untuk code: {first.warehouse_code or first.line_warehouse_code or "-"}')
                print(f"debug : [Shipment {shipment_key}] Source WH: {source_wh.code} | Dest WH: {dest_wh.code if dest_wh else 'None'}")

                print(f"debug : [Shipment {shipment_key}] Langkah 2: Mencari stock.picking.type (Outgoing)")
                picking_type = first.picking_type_id
                if not picking_type:
                    print(f"debug : [Shipment {shipment_key}] ERROR: Picking type internal tidak ditemukan")
                    raise UserError('Picking type internal tidak ditemukan.')
                print(f"debug : [Shipment {shipment_key}] Picking Type ID: {picking_type.id} ({picking_type.display_name})")

                print(f"debug : [Shipment {shipment_key}] Langkah 3: Menentukan Source & Destination Location")
                src_location = self._find_location(first.header_location_code, source_wh, 'lot_stock_id') or (picking_type.default_location_src_id or source_wh.lot_stock_id)
                dest_location = False
                if dest_wh:
                    dest_location = dest_wh.lot_stock_id
                if not dest_location:
                    dest_location = self._find_location(first.warehouse_dest_code, source_wh, 'lot_stock_id')
                dest_location = dest_location or picking_type.default_location_dest_id or source_wh.lot_stock_id
                print(f"debug : [Shipment {shipment_key}] Src Loc: {src_location.display_name} | Dest Loc: {dest_location.display_name}")

                print(f"debug : [Shipment {shipment_key}] Langkah 4: Menyusun dictionary data (vals) untuk Stock Picking")
                vals = {
                    'origin': first.shipment_nbr,
                    'partner_id': self._find_partner(first).id if self._find_partner(first) else False,
                    'picking_type_id': picking_type.id,
                    'location_id': src_location.id,
                    'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,
                    'adt_type': first.shipment_type or False,
                }

                print(f"debug : [Shipment {shipment_key}] Langkah 5: Cek apakah data stock.picking sudah ada di database")
                picking = Picking.search([('origin', '=', first.shipment_nbr)], limit=1)
                if picking:
                    print(f"debug : [Shipment {shipment_key}] Data picking ditemukan (ID: {picking.id}, Name: {picking.name}), memeriksa state")
                    if picking.state in ('done', 'cancel'):
                        print(f"debug : [Shipment {shipment_key}] ERROR: Picking sudah 'done' atau 'cancel'")
                        raise UserError(f'Transfer shipment {first.shipment_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    
                    print(f"debug : [Shipment {shipment_key}] Mengupdate data picking via .write()")
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    print(f"debug : [Shipment {shipment_key}] Data picking tidak ditemukan, membuat baru via .create()")
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1
                print(f"debug : [Shipment {shipment_key}] Berhasil memproses picking: {picking.name} | Action State: {action_state}")

                print(f"debug : [Shipment {shipment_key}] Langkah 6: Mulai looping lines product (Total: {len(shipment_lines)} lines)")
                for idx, line in enumerate(shipment_lines, start=1):
                    product = self.env['acumatica.transfer.shipment.line.product'].search([('shipment_id', '=', line.id)])

                    for item in product:
                        print(f"debug : [Shipment {shipment_key}][Line {idx}] Memproses line: {item}")
                        # product = self.env['acumatica.transfer.shipment.line.product'].search([('id', '=', item)])
                        product = self._find_product(item)
                        
                        uom = self._find_uom(item, product)

                        line_dest = dest_wh.lot_stock_id if dest_wh else False

                        if not line_dest:
                            line_dest = self._find_location2(item) or dest_location

                        qty = self._parse_float(item.product_uom_qty)

                        move_vals = {
                            'name': item.line_description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': line_dest.id if line_dest else picking.location_dest_id.id,
                            'description_picking': item.line_description or False,
                         
                        }
                        created_move = Move.create(move_vals)
                        print(f"debug : [Shipment {shipment_key}] Langkah 7: Create Move Line untuk picking: {picking.id} dengan move ID: {created_move.id}")
                        # print(f"debug : [Shipment {shipment_key}][Line {idx}] Product: {product.display_name} | Qty: {qty}")


                    # print(f"Memproses product dengan id: {product.id}")
                    

                    # print(f"debug : [Shipment {shipment_key}][Line {idx}] Memeriksa apakah stock.move yang sama sudah ada")
                    # existing = Move.search([
                    #     ('picking_id', '=', picking.id),
                    #     ('product_id', '=', product.id),
                    #     ('name', '=', line.line_description or product.display_name),
                    #     ('product_uom_qty', '=', qty),
                    # ], limit=1)
                    
                    # if existing:
                    #     print(f"debug : [Shipment {shipment_key}][Line {idx}] Stock move sudah ada, skip pembuatan dan update import_state")
                    #     line.write({
                    #         'import_state': action_state,
                    #         'import_message': f'{action_state.title()}: {picking.name} (move sudah ada)',
                    #         'odoo_picking_id': picking.id,
                    #     })
                    #     continue

                    # print(f"debug : [Shipment {shipment_key}][Line {idx}] Membuat stock.move baru")
                    # # Move.create({
                    # #     'name': line.line_description or product.display_name,
                    # #     'picking_id': picking.id,
                    # #     'product_id': product.id,
                    # #     'product_uom_qty': qty,
                    # #     'product_uom': uom.id if uom else product.uom_id.id,
                    # #     'location_id': picking.location_id.id,
                    # #     'location_dest_id': line_dest.id if line_dest else picking.location_dest_id.id,
                    # #     'description_picking': line.line_description or False,
                    # # })
                    
                    print(f"debug : [Shipment {shipment_key}][Line {idx}] Sukses buat move, update import_state pada line")
                    line.write({
                        'import_state': action_state,
                        'import_message': f'{action_state.title()}: {picking.name}',
                        'odoo_picking_id': picking.id,
                    })
                    
                # raise UserError(f'Panggil Agil udah berhasil')
            
            except Exception as e:
                print(f"debug : [Shipment {shipment_key}] TERJADI EXCEPTION ERROR: {str(e)}")
                # raise UserError(f'Panggil Agil : {str(e)[:200]}')
                _logger.exception('Error import transfer shipment %s', shipment_key)
                shipment_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
                error += len(shipment_lines)

        print(f"debug : Selesai memproses _do_import. Summary -> Imported: {imported}, Updated: {updated}, Error: {error}")
        msg = f'Import selesai: {imported} transfer dibuat, {updated} transfer diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Transfer Shipment',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }


    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

class AcumaticaTransferShipmentLineProduct(models.Model):
    _name = 'acumatica.transfer.shipment.line.product'
    _description = 'Data Product dari Transfer Shipment Acumatica'
    _order = 'shipment_id asc, line_nbr asc, id asc'

    
    shipment_id = fields.Many2one(
    'acumatica.transfer.shipment.line', 
    string='Parent Shipment', 
    ondelete='cascade', 
    required=True)

    line_external_id = fields.Char(string='UUID Line', readonly=True)
    line_row_number = fields.Char(string='Line Nbr', readonly=True)
    line_nbr = fields.Char(string='Line Nbr', readonly=True)    
    line_description = fields.Char(string='Description Detail', readonly=True)
    is_free_item = fields.Char(string='Free Item', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    location_dest_code = fields.Char(string='LocationID', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    order_line_number = fields.Char(string='Order Line Nbr', readonly=True)
    order_number = fields.Char(string='Order Number', readonly=True, index=True)
    order_type = fields.Char(string='Order Type', readonly=True)
    original_qty = fields.Char(string='Original Qty', readonly=True)
    product_uom_qty = fields.Char(string='Shipped Qty Detail', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    line_warehouse_code = fields.Char(string='Warehouse Detail', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)
    line_note_id = fields.Char(string='Line Note ID', readonly=True)
    custom_json = fields.Text(string='Custom Payload', readonly=True)
