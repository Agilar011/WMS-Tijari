from datetime import datetime
from odoo import models, fields, api
from odoo.fields import Datetime
from odoo.exceptions import UserError

from dateutil import parser as dateutil_parser
import logging
import requests

_logger = logging.getLogger(__name__)


class AcumaticaKitAssemblyConfig(models.Model):
    _name        = 'acumatica.kit.assembly.config'
    _description = 'Konfigurasi Koneksi Acumatica - Kit Assembly Import'
    _rec_name    = 'name'

    name         = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url     = fields.Char(
        string='Base URL', required=True,
        default='http://staging.aditya.group/acumportal/entity',
    )
    api_version  = fields.Char(string='API Version', required=True, default='25.200.002')
    username     = fields.Char(string='Username', required=True, default='wms')
    password     = fields.Char(string='Password', required=True)
    company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
    active       = fields.Boolean(default=True)
    last_sync    = fields.Datetime(string='Terakhir Sync', readonly=True)
    state        = fields.Selection([
        ('draft',     'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error',     'Error'),
    ], string='Status', default='draft', readonly=True)

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
                'tag':  'display_notification',
                'params': {
                    'title':   'Koneksi Berhasil!',
                    'message': f'Berhasil terhubung ke Acumatica ({self.base_url})',
                    'type':    'success',
                    'sticky':  False,
                },
            }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    def _do_login(self):
        self.ensure_one()

        last_error = None

        for attempt in range(1, 4):
            try:
                session = requests.Session()
                response = session.post(
                    self.login_url,
                    json={
                        "name": self.username,
                        "password": self.password,
                        "company": self.company_code
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 204:
                    return session

                raise UserError(
                    f'Login gagal (HTTP {response.status_code}): {response.text}'
                )

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_error = e

                if attempt < 3:
                    time.sleep(30)

        if isinstance(last_error, requests.exceptions.ConnectionError):
            raise UserError(
                f'Tidak bisa terhubung ke server: {self.base_url} (sudah dicoba 3 kali)'
            )

        if isinstance(last_error, requests.exceptions.Timeout):
            raise UserError(
                'Koneksi timeout setelah 3 kali percobaan. Periksa URL server.'
            )

        raise UserError('Login gagal setelah 3 kali percobaan.')


    def _do_logout(self, session):
        for attempt in range(1, 4):
            try:
                response = session.post(
                    self.logout_url,
                    timeout=10
                )

                # opsional: validasi status code
                if response.status_code in (200, 204):
                    return

                if attempt < 3:
                    time.sleep(30)

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout):
                if attempt < 3:
                    time.sleep(30)

            except Exception:
                # tetap diam seperti kode asli
                return
        
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



    def _parse_datetime(self, value):
        if not value:
            return False

        if isinstance(value, datetime):
            return value

        try:
            # Support:
            # 2011-12-09T22:18:00+07:00
            # 2011-12-09T22:18:00Z
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return False        
        

class AcumaticaKitAssembly(models.Model):
    _name = 'acumatica.kit.assembly'
    _description = 'Acumatica Kit Assembly'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Reference Number',
        required=True,
        index=True,
        tracking=True,
    )

    external_id = fields.Char(
        string='External ID',
        index=True,
    )

    row_number = fields.Integer()

    description = fields.Char()

    inventory_id = fields.Char(
        string='Finished Good Inventory ID',
        index=True,
    )

    last_modified_datetime = fields.Datetime()

    location = fields.Char()

    post_period = fields.Char()

    quantity = fields.Float()

    reason_code = fields.Char()

    reference_nbr = fields.Char(
        required=True,
        index=True,
    )

    requested_on = fields.Date()

    revision = fields.Char()

    status = fields.Char()

    document_only = fields.Boolean(string='Document Only', readonly=True)

    type = fields.Char()

    uom = fields.Char()

    warehouse = fields.Char()

    import_state = fields.Selection([
        ('pending', 'Pending'),
        ('imported', 'Imported'),
        ('error', 'Error'),
    ], default='pending')

    import_message = fields.Text()

    mrp_production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        readonly=True,
    )

    component_ids = fields.One2many(
        'acumatica.kit.assembly.component',
        'assembly_id',
        string='Components',
    )

    config_id = fields.Many2one(
            'acumatica.config',
            string='Konfigurasi',
            readonly=True,
            ondelete='cascade',
        )
    _sql_constraints = [
        (
            'reference_nbr_unique',
            'unique(reference_nbr)',
            'Reference Number must be unique.'
        )
    ]

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def _do_import(self):
        print("Starting import process...")
        Manufacturing = self.env['mrp.production']
        PickingType = self.env['stock.picking.type']
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        Warehouse = self.env['stock.location.acumatica']
        mapping_location = self.env['stock.location.acumatica']
        header_reference = self.env['acumatica.kit.assembly']
        component_reference = self.env['acumatica.kit.assembly.component']
        stock_picking = self.env['stock.picking']
        Move = self.env['stock.move']
        looping_count = 0
        
        imported = 0
        updated = 0
        error = 0

        # proses per reference number
        for reference_nbr in self.mapped('reference_nbr'):
            try:
                vals = {}
                header = header_reference.search([('name', '=', reference_nbr)], limit=1)
                print(f"Header Value : {header.name}")

                warehouse = Warehouse.search([('code', '=', header.warehouse)], limit=1)
                if not warehouse:
                    print(f"Warehouse tidak ditemukan untuk: {header.warehouse}")
                    error += 1
                    continue

                processed_product = self.env['product.product'].search([
                    ('default_code', '=', header.inventory_id),
                ], limit=1)
                if not processed_product:
                    print(f"Processed product not found for: {header.inventory_id}")
                    error += 1
                    continue

                picking_type = PickingType.search([
                    ('name', '=', 'Manufacturing'),
                    ('warehouse_id', '=', warehouse.odoo_location_id.warehouse_id.id),
                ], limit=1)

                if not picking_type:
                    print("Manufacturing Picking Type tidak ditemukan.")
                    error += 1
                    continue

                vals = {
                    'name': reference_nbr,
                    'product_id': processed_product.id,
                    'product_qty': header.quantity,
                    'product_uom_id': processed_product.product_tmpl_id.uom_id.id,
                    'date_start': header.requested_on,
                    'user_id': self.env.uid,
                    'picking_type_id': picking_type.id,
                    'location_src_id': picking_type.default_location_src_id.id,
                    'location_dest_id': picking_type.default_location_dest_id.id,
                    'company_id': warehouse.odoo_location_id.warehouse_id.company_id.id,
                }

                manufacturing_check = Manufacturing.search(
                    [('origin', '=', header.name)],
                    limit=1,
                )

                if not manufacturing_check:
                    manufacturing = Manufacturing.create(vals)
                    imported += 1
                else:
                    manufacturing = manufacturing_check
                    updated += 1

                component = component_reference.search([
                    ('assembly_id', '=', header.id)
                ])

                raw_moves = []

                for item in component:
                    processed_product = self.env['product.product'].search([
                        ('default_code', '=', item.stock_inventory_id),
                    ], limit=1)

                    if not processed_product:
                        error += 1
                        continue

                    raw_moves.append((0, 0, {
                        'product_id': processed_product.id,
                        'product_uom_qty': item.line_quantity,
                        'product_uom': processed_product.product_tmpl_id.uom_id.id,
                        'location_id': picking_type.default_location_src_id.id,
                        'raw_material_production_id': manufacturing.id,
                    }))
                    
                    if raw_moves and not manufacturing_check:
                        manufacturing.write({
                            'move_raw_ids': raw_moves,
                        })

            except Exception as e:
                error += 1
                print(f"Error processing {reference_nbr}: {e}")

        total = len(self.mapped('reference_nbr'))

        msg = (
            f"Import Kit Assembly selesai.\n\n"
            f"Total Reference Number : {total}\n"
            f"Manufacturing Order dibuat : {imported}\n"
            f"Manufacturing Order sudah ada : {updated}\n"
            f"Error : {error}"
        )

        self.write({
            'import_message': msg,
            'mrp_production_id': manufacturing.id,
            'import_state': 'imported',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Kit Assembly',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_product(self):
        self.ensure_one()
        if not self.odoo_product_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id':    self.odoo_product_id.id,
            'view_mode': 'form',
        }


class AcumaticaKitAssemblyComponent(models.Model):
    _name = 'acumatica.kit.assembly.component'
    _description = 'Acumatica Kit Assembly Component'

    assembly_id = fields.Many2one(
        'acumatica.kit.assembly',
        required=True,
        ondelete='cascade',
    )

    line_external_id = fields.Char(
        required=True,
        index=True,
    )

    line_nbr = fields.Integer()

    line_note = fields.Text()

    line_inventory_id = fields.Char()

    line_component_qty = fields.Float()

    line_location_id = fields.Char()

    line_quantity = fields.Float()

    line_reason_code = fields.Char()

    stock_inventory_id = fields.Char(
        string='Component Inventory ID',
        index=True,
    )

    line_uom = fields.Char()

    product_id = fields.Many2one(
        'product.product',
        string='Matched Product',
        readonly=True,
    )

    import_message = fields.Text()    



class AcumaticaKitAssemblyLine(models.Model):
    """
    Tabel staging: hasil tarikan data Kit Assembly dari Acumatica.
    Target model Odoo: product.template

    Mapping:
      InventoryID          → default_code              (Mandatory)
      Description          → name                      (Mandatory)
      ItemType             → type                      (Mandatory)
      ItemClass            → adt_item_class             (Mandatory, to be)
      ItemStatus           → adt_item_status            (Mandatory, to be)
      BaseUOM              → uom_id / uom_po_id         (Mandatory, lookup by name)
      ValuationMethod      → adt_valuation_method       (Mandatory, to be)
      LastModifiedDateTime → adt_acumatica_write_date (Mandatory, to be)
    """
    _name        = 'acumatica.kit.assembly.line'
    _description = 'Data Kit Assembly dari Acumatica (Staging)'
    _order       = 'row_number asc'
    

    # 'external_id':item.get("id", "") or "",
    # 'row_number': item.get("rowNumber", 0),
    # 'description': val(item, "Description"),
    # 'inventory_id': val(item, "InventoryID"),
    # 'last_modified_datetime': val(item, "LastModifiedDateTime"),
    # 'location': val(item, "Location"),
    # 'post_period': val(item, "PostPeriod"),
    # 'quantity': val(item, "Qty"),
    # 'reason_code':val(item, "ReasonCode"),
    # 'reference_nbr':val(item, "ReferenceNbr"),
    # 'requested_on':val(item, "RequestedOn"),
    # 'revision':val(item, "Revision"),
    # 'status':val(item, "Status"),
    # 'type':val(item, "Type"),
    # 'uom': val(item, "UOM"),
    # 'warehouse': val(item, "Warehouse"),


    # 'line_external_id': component.get('id', '') or '',
    # 'line_note': component.get('note', {}).get('value', '') or '',
    # 'inventory_id': self._val(component, 'InventoryID'),
    # 'line_nbr': str(line_nbr),
    # 'line_location_id': self._val(component, 'LocationID'),
    # 'line_reason_code': self._val(component, 'ReasonCode'),
    # 'stock_inventory_id': self._val(component, 'StockInventoryID'),
    # 'uom_code': self._val(component, 'UOM'),

    # ─── Data mentah dari Acumatica ──────────────────
    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Acumatica', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime', readonly=True)
    location = fields.Char(string='Location', readonly=True)
    post_period = fields.Char(string='PostPeriod', readonly=True)
    quantity = fields.Char(string='Qty', readonly=True)
    reason_code = fields.Char(string='ReasonCode', readonly=True)
    reference_nbr = fields.Char(string='ReferenceNbr', readonly=True)
    requested_on = fields.Char(string='RequestedOn', readonly=True)
    revision = fields.Char(string='Revision', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    type = fields.Char(string='Type', readonly=True)
    uom = fields.Char(string='uom', readonly=True)
    warehouse = fields.Char(string='Warehouse', readonly=True)

    line_external_id = fields.Char(string='Line UUID', readonly=True)
    line_note = fields.Char(string='Line Note', readonly=True)
    line_inventory_id = fields.Char(string='Line InventoryID', readonly=True)
    line_component_qty = fields.Char(string='Line Component Qty', readonly=True)
    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    line_location_id = fields.Char(string='Line LocationID', readonly=True)
    line_quantity = fields.Char(string='Line Quantity', readonly=True)
    line_reason_code = fields.Char(string='Line ReasonCode', readonly=True)
    stock_inventory_id = fields.Char(string='Stock InventoryID', readonly=True)
    line_uom = fields.Char(string='Line UOM', readonly=True)

    RMALocationID = fields.Char(string='RMA Location ID', readonly=True)
    WarehouseID = fields.Char(string='Warehouse ID', readonly=True)
    BuildingID = fields.Char(string='Building ID', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message   = fields.Char(string='Keterangan',         readonly=True)
    odoo_product_id  = fields.Many2one('product.template', string='Product di Odoo', readonly=True)
    odoo_bom_id = fields.Many2one('mrp.bom', string='BOM di Odoo', readonly=True)
    selected         = fields.Boolean(string='Pilih',           default=True)

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)
    warehouse_code = fields.Char(string='Warehouse Code', readonly=True)
    location_dest_code = fields.Char(string='Location Dest Code', readonly=True)
    header_location_code = fields.Char(string='Header Location Code', readonly=True)    
    uom_code = fields.Char(string='UOM Code', readonly=True)
    receipt_nbr = fields.Char(string='Receipt Nbr', readonly=True)
    po_number = fields.Char(string='PO Number', readonly=True)


    # ─── Helpers ─────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    # ItemType Acumatica → type Odoo
    # 'consu' = storable/consumable (Odoo 17/18 pakai 'consu' untuk goods)
    ITEM_TYPE_MAP = {
        'finished good': 'consu',
        'component':     'consu',
        'non-stock':     'consu',
        'service':       'service',
        'labor':         'service',
        'charge':        'service',
    }

    # ValuationMethod Acumatica → adt_valuation_method selection
    VALUATION_MAP = {
        'FIFO':     'FIFO',
        'Average':  'Average',
        'Standard': 'Standard',
        'Specific': 'Specific',
    }

    # ItemStatus Acumatica → adt_item_status selection
    STATUS_MAP = {
        'Active':       'Active',
        'Inactive':     'Inactive',
        'ToDelete':     'ToDelete',
        'NoSales':      'NoSales',
        'NoPurchases':  'NoPurchases',
        'NoRequest':    'NoRequest',
    }

    def _resolve_uom(self, uom_name):
        """
        Lookup uom.uom by name (case-insensitive).
        UOM sudah diimport sebelumnya ke uom.uom.
        Return: uom.uom record atau browse() jika tidak ditemukan.
        """
        if not uom_name:
            return self.env['uom.uom'].browse()
        uom = self.env['uom.uom'].search([('name', '=ilike', uom_name)], limit=1)
        return uom

    def _find_existing_product(self, rec):
        """Cari product.template by default_code (InventoryID)."""
        Product = self.env['product.template']
        if rec.inventory_id:
            found = Product.search([('default_code', '=', rec.inventory_id)], limit=1)
            if found:
                return found
        return Product.browse()
    
    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        code = line.warehouse_code
        warehouse = False
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', code)], limit=1)
        return warehouse or Warehouse.search([], limit=1)
    
    def _find_destination_location(self, line, warehouse=False):
        Location = self.env['stock.location']
        code = line.location_dest_code or line.header_location_code
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom


    

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def _do_import(self):
        print("Starting import process...")
        Manufacturing = self.env['mrp.production']
        PickingType = self.env['stock.picking.type']
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        Warehouse = self.env['stock.warehouse']
        mapping_location = self.env['stock.location.acumatica']
        header_reference = self.env['acumatica.kit.assembly']
        component_reference = self.env['acumatica.kit.assembly.component']
        stock_picking = self.env['stock.picking']
        Move = self.env['stock.move']
        looping_count = 0
        


        imported = 0
        updated = 0
        error = 0

        # proses per reference number
        for reference_nbr in self.mapped('reference_nbr'):
            # print(f"Processing ReferenceNbr: {reference_nbr}")
            vals = {}
            header = header_reference.search([('name', '=', reference_nbr)])
            print(f"Header Value : {header.name} ")

            warehouse = Warehouse.search([('code', '=', header.warehouse)], limit=1)
            if not warehouse:
                print(f"Warehouse tidak ditemukan untuk: {header.warehouse}")

            processed_product = self.env['product.product'].search([
                    ('default_code', '=', header.inventory_id),
                ], limit=1)
            if not processed_product:
                print(f"Processed product not found for: {header.inventory_id}")

            picking_type = PickingType.search([
                ('name', '=', 'Manufacturing'),
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)

            vals = {
                'name' : reference_nbr,
                'product_id' : processed_product.id,
                'product_qty' : header.quantity,
                'product_uom_id' : processed_product.product_tmpl_id.xuom_id.id,
                'scheduled_date': header.requested_on,
                'user_id': self.env.uid,
                'picking_type_id': picking_type.id,
                'location_src_id': picking_type.default_location_id_src_id.id,
                'location_dest_id': picking_type.default_location_id_dest_id.id,
                'source' : reference_nbr,
                'company_id' : warehouse.company_id.id,
            }
            manufacturing_check = self.env['mrp.production'].search([('origin', '=', header.name)])
            if not manufacturing_check:
                manufacturing = Manufacturing.create(vals)
                print(f"Created manufacture: {manufacturing}")



            # boms = self.env['mrp.bom'].search([('code', '=', reference_nbr)], limit=1)

            # if boms:
            #     Bom = boms
            # if not boms:
            #     Bom = Bom.create(vals)

            # print(Bom)
            vals = {}

            component = component_reference.search([('assembly_id', '=', header.id)])
            print(component)

            for item in component:
                component = self.env['product.template'].search(
                    [('default_code', '=', item.stock_inventory_id)],
                    limit=1
                )
                print(component)
                

                vals = {
                    'product_id' : component.product_id.id,
                    'product_uom_qty' : item.line_quantity,
                    'product_uom_id' : component.uom_id.id,
                    'location_id' : picking_type.default_location_id_src_id.id,
                    'raw_material_production_id' : manufacturing.id,
                }

                # if not manufacturing_check:
                #     move = Move.create(vals)
                vals = {}
            

        # picking_type = PickingType.search([
        #     ('name', '=', 'Pick Components'),
        # ], limit=1)

        # if picking_type:
        #     print(f"Found picking type for code 'mrp_operation': {picking_type.id}")

        # if not picking_type:
        #     raise UserError('Picking type Manufacture tidak ditemukan.')
        
        # kit_assembly_warehouse = mapping_location.search([('code', '=', header.warehouse)], limit=1)
        # print(kit_assembly_warehouse)

        # company_id = kit_assembly_warehouse.odoo_building_id.id
        # print(f"Determined company for warehouse mapping: {kit_assembly_warehouse.odoo_building_id.id if kit_assembly_warehouse and kit_assembly_warehouse.odoo_building_id else 'None'}")

        # product_id = self.env['product.product'].search([
        #         ('product_tmpl_id', '=', processed_product.id),
        #     ], limit=1)
        
        # print(product_id)

        
        # vals = {
        #         'product_id': product_id.id,
        #         'product_uom_id': processed_product.uom_id.id,
        #         # 'picking_type_id': picking_type.id,  # Replace with actual picking type ID if needed
        #         'location_src_id': (
        #             kit_assembly_warehouse.odoo_location_id.id
        #             if kit_assembly_warehouse and kit_assembly_warehouse.odoo_location_id
        #             else False
        #         ),

        #         # 'location_dest_id': (
        #         #     kit_assembly_warehouse.odoo_location_id.id
        #         #     if kit_assembly_warehouse and kit_assembly_warehouse.odoo_location_id
        #         #     else False
        #         # ),
        #         # 'bom_id' : Bom.id,
        #         # 'location_final_id': False,  # Replace with actual final location ID if needed
        #         'user_id': self.env.uid,
        #         'company_id': company_id, #ambil dari company aditya
        #         'procurement_group_id': False,
        #         'orderpoint_id': False,
        #         'production_location_id': False,
        #         'create_uid': False,
        #         'write_uid': False,
        #         'name': False,
        #         'priority': False,
        #         'origin': header.name,
        #         'product_qty': header.quantity,
        #         'qty_producing': header.quantity,
        #         'date_deadline': False,
        #         'date_start': fields.Datetime.now(),
        #         'date_finished': False,
        #         'create_date': fields.Datetime.now(),
        #         'write_date': fields.Datetime.now(),
        #         'product_uom_qty': False,
        #     }
        
        # if manufacturing_check:
        #     print("Create MO Skipped")
        # if not manufacturing_check:
        #     if kit_assembly_warehouse.odoo_location_id.id:
        #         manufacturing = manufacturing.create(vals)
        #         print(f"Created : {manufacturing}")
                
        #     if not kit_assembly_warehouse.odoo_location_id.id:
        #         print('created skipped cause location not found')


# Block Kode Generate 1-Step Transfer Pemindahan barang dari penyimpanan ke Assembly Line
        # operation_type = self.env['stock.picking.type'].search([('code', '=', 'internal'), ('name', '=', 'Pick Components')], limit=1)

        # total_moving_qty = 0 

        # component = component_reference.search([('assembly_id', '=', header.id)])
        # for item in component:
        #     total_moving_qty += item.line_quantity

        # vals = {
        #     'picking_type_id' : operation_type.id,
        #     'location_id' : operation_type.default_location_src_id.id,
        #     'location_dest_id' : operation_type.default_location_dest_id.id,
        #     'scheduled_date' : fields.Datetime.now(),
        #     'origin' : header.name,
        #     'adt_type' : "1-Step",
        #     'adt_total_qty' : total_moving_qty,
        # }
        # if operation_type.default_location_dest_id.usage == 'customer':
        #     raise UserError('Location tujuan customer hanya boleh dipakai oleh SO Shipment.')

        # if manufacturing_check:
        #     print("Create MO Skipped")
        # if not manufacturing_check:
        #     if kit_assembly_warehouse.odoo_location_id.id:
        #         # stock_picking = self.env['stock.picking']
        #         stock_picking = stock_picking.create(vals)
        #         print(stock_picking.name)
                
        #     if not kit_assembly_warehouse.odoo_location_id.id:
        #         print('created skipped cause location not found')

        # for item in component:
        #     component = self.env['product.template'].search(
        #         [('default_code', '=', item.stock_inventory_id)],
        #         limit=1
        #     )
            
        #     vals = {
        #             'name' : stock_picking.name,
        #             'product_id' : component.id,
        #             'product_uom_qty' : item.line_quantity,
        #             'product_uom' : component.uom_id.id,
        #             'picking_id' : stock_picking.id
        #         }

        #     if manufacturing_check:
        #         print("Create MO Skipped")
        #     if not manufacturing_check:
        #         if kit_assembly_warehouse.odoo_location_id.id:
        #             stock_move = self.env['stock.move']
        #             stock_move = stock_move.create(vals)
                    
        #         if not kit_assembly_warehouse.odoo_location_id.id:
        #             print('created skipped cause location not found')

        msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Receipt',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_product(self):
        self.ensure_one()
        if not self.odoo_product_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id':    self.odoo_product_id.id,
            'view_mode': 'form',
        }
