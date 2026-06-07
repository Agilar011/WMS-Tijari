from odoo import models, fields, api
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

    def fetch_kit_assembly_data(self, limit=100, offset=0):
        """Fetch 1 page Kit Assembly dari Acumatica (paging via $top/$skip)."""
        self.ensure_one()
        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/KitAssembly"
            print(f"Fetching Kit Assembly data from {endpoint} with limit={limit} and offset={offset}...")
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
                    'external_id': item.get('id', '') or '',
                    'row_number': item.get('rowNumber', 0) or 0,
                    'description': self._val(item, 'Description'),
                    'inventory_id': self._val(item, 'InventoryID'),
                    'last_modified_datetime': self._val(item, 'LastModifiedDateTime'),
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

                stock_components = item.get('StockComponents') or []
                if isinstance(stock_components, dict):
                    stock_components = stock_components.get('value', []) or []
                if not isinstance(stock_components, list):
                    stock_components = []

                if not stock_components:
                    result.append(dict(header, line_nbr='0'))
                    continue

                for component in stock_components:
                    line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
                    result.append({
                        **header,
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
                    })

            _logger.info(
                'Berhasil ambil %s rows Kit Assembly dari Acumatica (skip=%s, top=%s)',
                len(result), offset, limit,
            )
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

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
        'acumatica.kit.assembly.config',
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
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def _do_import(self):
        print("Starting import process...")
        Picking = self.env['stock.picking']
        Bom = self.env['mrp.bom']
        BomLine = self.env['mrp.bom.line']


        imported = 0
        updated = 0
        error = 0

        # proses per reference number
        for reference_nbr in self.mapped('reference_nbr'):
            print(f"Processing ReferenceNbr: {reference_nbr}")
            reference_lines = self.filtered(
                lambda l: l.reference_nbr == reference_nbr and l.import_state == 'pending'
            )
            if not reference_lines:
                continue

            first = reference_lines[0]

            try:
                product = self._find_existing_product(first)
                print(f"Found product for InventoryID {first.inventory_id}: {product.id if product else 'None'}")
                if not product:
                    raise UserError(
                        f'Product tidak ditemukan untuk InventoryID: '
                        f'{first.inventory_id or "-"}'
                    )
                warehouse = self._find_warehouse(first)
                print(f"Found warehouse for code {first.warehouse_code}: {warehouse.id if warehouse else 'None'}")
                if not warehouse:
                    raise UserError(
                        f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}'
                    )

                dest_location = self._find_destination_location(first, warehouse)
                print(f"Found destination location for code {first.location_dest_code or first.header_location_code or '-'}: {dest_location.id if dest_location else 'None'}")
                if not dest_location:
                    raise UserError(
                        f'Location tujuan tidak ditemukan untuk code: '
                        f'{first.location_dest_code or first.header_location_code or "-"}'
                    )

                origin = reference_nbr or False
                print(f"Determined origin for picking: {origin}")

                uom = self._resolve_uom(first.uom)
                print(f"Resolved UOM for '{first.uom}': {uom.id if uom else 'None'}")

                vals = {
                    # row_number = fields.Integer(string='No', readonly=True)
                    # inventory_id = fields.Char(string='InventoryID', readonly=True)
                    # location = fields.Char(string='Location', readonly=True)
                    # requested_on = fields.Char(string='RequestedOn', readonly=True)
                    # revision = fields.Char(string='Revision', readonly=True)
                    # status = fields.Char(string='Status', readonly=True)
                    # type = fields.Char(string='Type', readonly=True)
                    # warehouse = fields.Char(string='Warehouse', readonly=True)
    

                    # Field standar Odoo
                    'name':first.description,
                    # 'quantity': float(first.quantity) if first.quantity else 0.0,
                    # 'code': first.reference_nbr or False,

                    # UOM
                    # 'uom_id': uom.id if uom else False,

                    # Field custom adt_
                    # 'adt_external_id': first.external_id or False,
                    # 'adt_reason_code': first.reason_code or False,
                    # 'adt_post_period': first.post_period or False,
                    # 'adt_location': first.location or False,
                    # 'adt_requested_on': first.requested_on or False,
                    # 'adt_revision': first.revision or False,
                    # 'adt_status': first.status or False,
                    # 'adt_warehouse': first.warehouse or False,
                    # 'adt_acumatica_write_date': self._parse_dt(first.last_modified_datetime),
                    'origin': origin,

                    # field custom, kalau ada di model
                }
                picking = Picking.search([('origin', '=', reference_nbr)], limit=1)
                print(f"Existing Receipt with origin {reference_nbr}: {picking.id if picking else 'None'}")
                if picking:
                    if picking.state in ('done', 'cancel'):
                        raise UserError(f'Receipt {picking.origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    print(f"Created new Receipt with origin {reference_nbr}: {picking.id}")
                    action_state = 'imported'
                    imported += 1


                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Bom._fields}

                # pakai origin buat dedup
                # bom = Bom.search([('origin', '=', origin)], limit=1)
                # print(f"Existing BOM with origin {origin}: {bom.id if bom else 'None'}")

                # if bom:
                #     if bom.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                #         raise UserError(
                #             f'Kit Assembly dengan Reference No {reference_nbr} sudah ada di Odoo dengan state '
                #             f'{bom.state}, tidak bisa diupdate.'
                #         )
                #     bom.write(vals)
                #     action_state = 'updated'
                #     updated += 1
                # else:
                #     bom = Bom.create(vals)
                #     action_state = 'imported'
                #     imported += 1

                print(f"Processed ReferenceNbr: {reference_nbr}")

                for line in reference_lines:
                    print(f"Processing line {line} for ReferenceNbr {reference_nbr}...")
                    try:
                        product = self._find_existing_product(line)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.inventory_id or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        # qty = self._parse_float(line.product_uom_qty)

                        # dedup move
                        # move_domain = [('bom_id', '=', bom.id)]
                        # if 'adt_line_external_id' in BomLine._fields and line.line_external_id:
                        #     move_domain.append(('adt_line_external_id', '=', line.line_external_id))
                        # else:
                        #     move_domain += [
                        #         ('product_id', '=', product.id),
                        #         ('product_uom_qty', '=', qty),
                        #     ]

                        # existing_move = BomLine.search(move_domain, limit=1)
                        # if existing_move:
                        #     line.write({
                        #         'import_state': action_state,
                        #         'import_message': f'Skip duplicate: {bom.name}',
                        #         # 'odoo_bom_id': bom.id,
                        #     })
                        #     continue

                        # bom_line_vals = {
                        #     'bom_id': bom.id,
                        #     'product_id': product.id,
                        #     'product_qty': qty,
                        #     'product_uom_id': uom.id if uom else product.uom_id.id,

                        #     'adt_line_external_id': line.line_external_id or False,
                        #     'adt_line_note': line.line_note or False,
                        #     'adt_line_inventory_id': line.line_inventory_id or False,
                        #     'adt_line_nbr': line.line_nbr or False,
                        #     'adt_line_component_qty': line.line_component_qty or False,
                        #     'line_location_id': line.line_location_id or False,
                        #     'adt_line_quantity': line.line_quantity or False,
                        #     'adt_line_reason_code': line.line_reason_code or False,
                        #     'adt_stock_inventory_id': line.stock_inventory_id or False,
                        #     'adt_uom_code': line.uom_code or False,
                        # }

                        # # filter field yang ada di stock.move
                        # bom_line_vals = {k: v for k, v in bom_line_vals.items() if k in BomLine._fields}

                        # BomLine.create(bom_line_vals)
                        # picking = Picking.search([('origin', '=', line.receipt_nbr)], limit=1)
                        # print(f"Existing Receipt with origin {line.receipt_nbr}: {picking.id if picking else 'None'}")
                        # if picking:
                        #     if picking.state in ('done', 'cancel'):
                        #         raise UserError(f'Receipt {picking.origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                        #     picking.write(vals)
                        #     action_state = 'updated'
                        #     updated += 1
                        # else:
                        #     picking = Picking.create(vals)
                        #     action_state = 'imported'
                        #     imported += 1

                        line.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {bom.name}',
                            'odoo_bom_id': bom.id,
                        })

                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        line.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            # 'odoo_bom_id': bom.id if bom else False,
                        })
                        error += 1

            except Exception as e:
                _logger.exception("Error import receipt %s", reference_nbr)
                reference_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                error += len(reference_lines)

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
