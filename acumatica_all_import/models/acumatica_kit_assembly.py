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

        try:
            return datetime.fromisoformat(value)
        except Exception:
            return False
        
    def fetch_kit_assembly_data(self, limit=100, offset=0):
        """Fetch 1 page Kit Assembly dari Acumatica (paging via $top/$skip)."""
        # print("==========================================================================================")
        # print("ACTION: Fetch data from Acumatica")
        # print("==========================================================================================")

        self.ensure_one()
        session = self._do_login()
        staging_header = self.env['acumatica.kit.assembly']
        staging_line = self.env['acumatica.kit.assembly.component']
        try:
            endpoint = f"{self.api_url}/KitAssembly"
            # print(f"Fetching Kit Assembly data from {endpoint} with limit={limit} and offset={offset}...")
            params = {'$top': limit, '$skip': offset, '$expand': 'StockComponents'}

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Kit Assembly '
                    f'(HTTP {response.status_code}): {response.text}'
                )

            raw_data = self._normalize_rows(response.json())
            result = []

            for item in raw_data:
                header = {
                    'name': self._val(item, 'ReferenceNbr'),
                    'external_id': item.get('id', '') or '',
                    'row_number': item.get('rowNumber', 0) or 0,
                    'description': self._val(item, 'Description'),
                    'inventory_id': self._val(item, 'InventoryID'),
                    'last_modified_datetime': self._parse_datetime(
                        item.get('LastModifiedDateTime')
                    ),
                    'location': self._val(item, 'Location'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'quantity': self._val(item, 'Qty'),
                    'reason_code': self._val(item, 'ReasonCode'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'requested_on': self._val(item, 'RequestedOn'),
                    'revision': self._val(item, 'Revision'),
                    'status': self._val(item, 'Status'),
                    'type': self._val(item, 'Type'),
                    'uom': self._val(item, 'UOM'),
                    'warehouse': self._val(item, 'Warehouse'),
                }

                # === PRINT DATA HEADER ===
                # print("==========================================================================================")
                # print("HEADER DATA:")
                # for h_key, h_val in header.items():
                    # print(f"{h_key:<25} : {h_val}")

                assembly = self.env['acumatica.kit.assembly'].create(header)  # Simpan header ke staging untuk referensi, bisa dihapus jika tidak perlu
                print(f"Created staging header record with ID {assembly.id} for ReferenceNbr {header['reference_nbr']}")

                stock_components = item.get('StockComponents') or []
                if isinstance(stock_components, dict):
                    stock_components = stock_components.get('value', []) or []
                if not isinstance(stock_components, list):
                    stock_components = []

                if not stock_components:
                    # print("-- (No Components Available)") # Info jika component kosong
                    result.append(dict(header, line_nbr='0'))
                    # print("==========================================================================================")
                    continue

                # === PRINT DATA COMPONENT ===
                # print("COMPONENTS:")
                for component in stock_components:
                    line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
                    
                    # Buat dictionary component data untuk mempermudah perulangan print
                    component_data = {
                        'line_external_id': component.get('id', '') or '',
                        'line_note': component.get('note', {}).get('value', '') or '',
                        'line_inventory_id': self._val(component, 'InventoryID'),
                        'line_component_qty': self._val(component, 'ComponentQty'),
                        'line_nbr': str(line_nbr),
                        'line_location_id': self._val(component, 'LocationID'),
                        'line_quantity': self._val(component, 'Qty'),
                        'line_reason_code': self._val(component, 'ReasonCode'),
                        'stock_inventory_id': self._val(component, 'StockInventoryID'),
                        'line_uom': self._val(component, 'UOM'),
                        'assembly_id': assembly.id,  # Simpan component dengan relasi ke header yang sudah dibuat, bisa dihapus jika tidak perlu
                    }
                    
                    # Print setiap field di dalam component ini dengan awalan '--'
                    # print("  ----------------------------------------")
                    # for c_key, c_val in component_data.items():
                        # print(f"  -- {c_key:<25} : {c_val}")

                    assembly_line = self.env['acumatica.kit.assembly.component'].create(component_data)  # Simpan component ke staging, bisa dihapus jika tidak perlu
                    # print(f"  Created staging component record with ID {assembly_line.id} for LineNbr {component_data['line_nbr']} under ReferenceNbr {header['reference_nbr']}")
                    
                    # Tetap masukkan ke hasil akhir Odoo wizard Anda
                    result.append({**header, **component_data})
                
                # print("==========================================================================================")


            # for item in raw_data:
            #     header = {
            #         'external_id': item.get('id', '') or '',
            #         'row_number': item.get('rowNumber', 0) or 0,
            #         'description': self._val(item, 'Description'),
            #         'inventory_id': self._val(item, 'InventoryID'),
            #         'last_modified_datetime': self._val(item, 'LastModifiedDateTime'),
            #         'location': self._val(item, 'Location'),
            #         'post_period': self._val(item, 'PostPeriod'),
            #         'quantity': self._val(item, 'Qty'),
            #         'reason_code': self._val(item, 'ReasonCode'),
            #         'reference_nbr': self._val(item, 'ReferenceNbr'),
            #         'requested_on': self._val(item, 'RequestedOn'),
            #         'revision': self._val(item, 'Revision'),
            #         'status': self._val(item, 'Status'),
            #         'type': self._val(item, 'Type'),
            #         'uom': self._val(item, 'UOM'),
            #         'warehouse': self._val(item, 'Warehouse'),


            #     }

            #     stock_components = item.get('StockComponents') or []
            #     if isinstance(stock_components, dict):
            #         stock_components = stock_components.get('value', []) or []
            #     if not isinstance(stock_components, list):
            #         stock_components = []

            #     if not stock_components:
            #         result.append(dict(header, line_nbr='0'))
            #         continue

            #     for component in stock_components:
            #         line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
            #         result.append({
            #             **header,
            #             'line_external_id': component.get('id', '') or '',
            #             'line_note': component.get('note', {}).get('value', '') or '',
            #             'line_inventory_id': self._val(component, 'InventoryID'),
            #             'line_component_qty': self._val(component, 'ComponentQty'),
            #             'line_nbr': str(line_nbr),
            #             'line_location_id': self._val(component, 'LocationID'),
            #             'line_quantity': self._val(component, 'Qty'),
            #             'line_reason_code': self._val(component, 'ReasonCode'),
            #             'stock_inventory_id': self._val(component, 'StockInventoryID'),
            #             'line_uom': self._val(component, 'UOM'),
            #         })

            
            _logger.info(
                'Berhasil ambil %s rows Kit Assembly dari Acumatica (skip=%s, top=%s)',
                len(result), offset, limit,
            )
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

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

    _sql_constraints = [
        (
            'reference_nbr_unique',
            'unique(reference_nbr)',
            'Reference Number must be unique.'
        )
    ]

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
        manufacturing = self.env['mrp.production']
        PickingType = self.env['stock.picking.type']
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']
        warehouse = self.env['stock.warehouse']
        mapping_location = self.env['stock.location.acumatica']
        header_reference = self.env['acumatica.kit.assembly']
        component_reference = self.env['acumatica.kit.assembly.component']
        stock_picking = self.env['stock.picking']
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

            processed_product = self.env['product.template'].search([
                    ('default_code', '=', header.inventory_id),
                ], limit=1)
            print(f"Processed product : {processed_product.name}")


            vals = {
                'product_tmpl_id' : processed_product.id,
                'product_qty' : header.quantity,
                'code' : header.name,
                'type' : 'phantom',
                'product_uom_id' : processed_product.uom_id.id,

            }

            boms = self.env['mrp.bom'].search([('code', '=', reference_nbr)], limit=1)

            if boms:
                Bom = boms
            if not boms:
                Bom = Bom.create(vals)

            print(Bom)
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
                    'product_id' : component.id,
                    'product_qty' : item.line_quantity,
                    'product_uom_id' : component.uom_id.id,
                    'bom_id' : Bom.id
                }
                BomsLine = self.env['mrp.bom.line'].search([('bom_id', '=', Bom.id)])
                if BomsLine:
                    BomLine = BomsLine

                if not BomsLine:
                    BomLine = BomLine.create(vals)
                    
                print(BomLine)

                vals = {}
            

        picking_type = PickingType.search([
            ('code', '=', 'mrp_operation'),
        ], limit=1)

        if picking_type:
            print(f"Found picking type for code 'mrp_operation': {picking_type.id}")

        if not picking_type:
            raise UserError('Picking type receipt/incoming tidak ditemukan.')
        
        kit_assembly_warehouse = mapping_location.search([('code', '=', header.warehouse)], limit=1)
        print(kit_assembly_warehouse)

        company_id = kit_assembly_warehouse.odoo_building_id.id
        print(f"Determined company for warehouse mapping: {kit_assembly_warehouse.odoo_building_id.id if kit_assembly_warehouse and kit_assembly_warehouse.odoo_building_id else 'None'}")

        product_id = self.env['product.product'].search([
                ('product_tmpl_id', '=', processed_product.id),
            ], limit=1)
        
        print(product_id)

        
        vals = {
                'product_id': product_id.id,
                'product_uom_id': processed_product.uom_id.id,
                'picking_type_id': picking_type.id,  # Replace with actual picking type ID if needed
                'location_src_id': (
                    kit_assembly_warehouse.odoo_location_id.id
                    if kit_assembly_warehouse and kit_assembly_warehouse.odoo_location_id
                    else False
                ),

                'location_dest_id': (
                    kit_assembly_warehouse.odoo_location_id.id
                    if kit_assembly_warehouse and kit_assembly_warehouse.odoo_location_id
                    else False
                ),
                'bom_id' : Bom.id,
                'location_final_id': False,  # Replace with actual final location ID if needed
                'user_id': self.env.uid,
                'company_id': company_id, #ambil dari company aditya
                'procurement_group_id': False,
                'orderpoint_id': False,
                'production_location_id': False,
                'create_uid': False,
                'write_uid': False,
                'name': False,
                'priority': False,
                'origin': header.name,
                'product_qty': header.quantity,
                'qty_producing': header.quantity,
                'date_deadline': False,
                'date_start': fields.Datetime.now(),
                'date_finished': False,
                'create_date': fields.Datetime.now(),
                'write_date': fields.Datetime.now(),
                'product_uom_qty': False,
            }
        
        manufacturing_check = self.env['mrp.production'].search([('origin', '=', header.name)])
        if manufacturing_check:
            print("Create MO Skipped")
        if not manufacturing_check:
            if kit_assembly_warehouse.odoo_location_id.id:
                manufacturing = manufacturing.create(vals)
                print(f"Created : {manufacturing}")
                
            if not kit_assembly_warehouse.odoo_location_id.id:
                print('created skipped cause location not found')


# Block Kode Generate 1-Step Transfer Pemindahan barang dari penyimpanan ke Assembly Line
        operation_type = self.env['stock.picking.type'].search([('code', '=', 'internal'), ('operation_category', '=', 'internal')], limit=1)

        total_moving_qty = 0 

        component = component_reference.search([('assembly_id', '=', header.id)])
        for item in component:
            total_moving_qty += item.line_quantity

        vals = {
            'picking_type_id' : operation_type.id,
            'location_id' : operation_type.default_location_src_id.id,
            'location_dest_id' : operation_type.default_location_dest_id.id,
            'scheduled_date' : fields.Datetime.now(),
            'origin' : header.name,
            'adt_type' : "1-Step",
            'adt_total_qty' : total_moving_qty,
        }
        if operation_type.default_location_dest_id.usage == 'customer':
            raise UserError('Location tujuan customer hanya boleh dipakai oleh SO Shipment.')

        if manufacturing_check:
            print("Create MO Skipped")
        if not manufacturing_check:
            if kit_assembly_warehouse.odoo_location_id.id:
                # stock_picking = self.env['stock.picking']
                stock_picking = stock_picking.create(vals)
                print(stock_picking.name)
                
            if not kit_assembly_warehouse.odoo_location_id.id:
                print('created skipped cause location not found')

        for item in component:
            component = self.env['product.template'].search(
                [('default_code', '=', item.stock_inventory_id)],
                limit=1
            )
            
            vals = {
                    'name' : stock_picking.name,
                    'product_id' : component.id,
                    'product_uom_qty' : item.line_quantity,
                    'product_uom' : component.uom_id.id,
                    'picking_id' : stock_picking.id
                }

            if manufacturing_check:
                print("Create MO Skipped")
            if not manufacturing_check:
                if kit_assembly_warehouse.odoo_location_id.id:
                    stock_move = self.env['stock.move']
                    stock_move = stock_move.create(vals)
                    
                if not kit_assembly_warehouse.odoo_location_id.id:
                    print('created skipped cause location not found')

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
