import logging
from dateutil import parser as dateutil_parser
from docutils.nodes import note

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

import requests


class AcumaticaShipmentConfig(models.Model):
    _name = 'acumatica.shipment.config'
    _description = 'Konfigurasi Koneksi Acumatica - Shipment Receipt'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Shipment Receipt')
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

    def fetch_shipment_data(self, limit=50, offset=0, receipt_nbr=False, last_modified_from=False, odata_filter=False):
        self.ensure_one()
        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/{self.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.odata_expand:
                params['$expand'] = self.odata_expand
            if self.odata_select:
                params['$select'] = self.odata_select
            if receipt_nbr:
                filters.append(f"ShipmentNbr eq '{receipt_nbr}'")
            if odata_filter:
                filters.append(self.odata_filter)
                filters.extend(odata_filter)
            else:
                filters.append("(Type eq 'Shipment' and Operation eq 'Receipt')")

            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Shipment Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'actual_qty': self._val(item, 'ControlQty'),
                    'partner_code': self._val(item, 'CustomerID'),
                    'description': self._val(item, 'Description'),
                    'fob_point': self._val(item, 'FOBPoint'),
                    'fob_point_description': self._val(item, 'FOBPointDescription'),
                    'is_hold': self._val(item, 'Hold'),
                    'is_insurance': self._val(item, 'Insurance'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'LocationID'),
                    'header_location_name': self._val(item, 'LocationName'),
                    'operation': self._val(item, 'Operation'),
                    'package_count': self._val(item, 'PackageCount'),
                    'package_weight': self._val(item, 'PackageWeight'),
                    'is_picked': self._val(item, 'Picked'),
                    'scheduled_date': self._val(item, 'ShipmentDate'),
                    'receipt_nbr': self._val(item, 'ShipmentNbr'),
                    'shipped_qty': self._val(item, 'ShippedQty'),
                    'shipped_volume': self._val(item, 'ShippedVolume'),
                    'shipped_weight': self._val(item, 'ShippedWeight'),
                    'shipping_terms': self._val(item, 'ShippingTerms'),
                    'shipping_settings': self._val(item, 'ShippingSettings'),
                    'shipping_zone': self._val(item, 'ShippingZoneID'),
                    'ship_via': self._val(item, 'ShipVia'),
                    'status': self._val(item, 'Status'),
                    'warehouse_dest_code': self._val(item, 'ToWarehouseID'),
                    'shipment_type': self._val(item, 'Type'),
                    'unlimited_packages': self._val(item, 'UnlimitedPackages'),
                    'warehouse_code': self._val(item, 'WarehouseID'),
                    'warehouse_name': self._val(item, 'WarehouseName'),
                }

                shipment_to_address = item.get('ShipToAddress') or item.get('shipToAddress') or {}
                if shipment_to_address:
                    shipment_to_address = {
                        'shipment_to_address_line_1': self._val(shipment_to_address, 'AddressLine1'),
                        'shipment_to_address_line_2': self._val(shipment_to_address, 'AddressLine2'),
                        'shipment_to_address_city': self._val(shipment_to_address, 'City'),
                        'shipment_to_address_country': self._val(shipment_to_address, 'Country'),
                        'shipment_to_address_country': self._val(shipment_to_address, 'CountryName'),
                        'shipment_to_address_postal_code': self._val(shipment_to_address, 'PostalCode'),
                        'shipment_to_address_state': self._val(shipment_to_address, 'State'),
                    }

                details = item.get('Details') or item.get('details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    result.append(dict(header, line_nbr='0'))
                    continue

                for detail in details:
                    allocations = detail.get('Allocations') or detail.get('allocations') or []
                    allocations_container = []
                    if isinstance(allocations, dict):
                        allocations = allocations.get('value', []) or []
                    if not isinstance(allocations, list):
                        allocations = []
                    if allocations:
                        for allocation in allocations:
                            allocations_container.append({
                                'allocation_line_external_id': allocation.get('id', '') or '',
                                'allocation_acumatica_id': allocation.get('id', '') or '',
                                'allocation_acumatica_row_number': allocation.get('rowNumber') or 0,
                                'allocation_detail_note': self._val(allocation, 'note'),
                                'allocation_line_description': self._val(allocation, 'Description'),
                                'allocation_inventory_id': self._val(allocation, 'InventoryID'),
                                # 'allocation_line_nbr': str(line_nbr),
                                'allocation_location_dest_code': self._val(allocation, 'LocationID'),
                                'allocation_qty': self._val(allocation, 'Quantity'),
                                'allocation_split_line_nbr': self._val(allocation, 'SplitLineNbr'),
                                'allocation_uom_code': self._val(allocation, 'UOM'),
                            })

                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    detail_containter = {
                        'allocations': allocations_container,
                        'line_external_id': detail.get('id', '') or '',
                        'acumatica_id': detail.get('id', '') or '',
                        'acumatica_row_number': detail.get('rowNumber') or 0,
                        'detail_note': detail.get('note', {}).get('value', '') or '',
                        'line_description': self._val(detail, 'Description'),
                        'is_free_item': self._val(detail, 'FreeItem'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'acumatica_line_number': self._val(detail, 'LineNbr'),
                        'location_dest_code': self._val(detail, 'LocationID'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'order_line_number': self._val(detail, 'OrderLineNbr'),
                        'order_number': self._val(detail, 'OrderNbr'),
                        'order_type': self._val(detail, 'OrderType'),
                        'original_qty': self._val(detail, 'OriginalQty'),
                        'detail_shipped_qty': self._val(detail, 'ShippedQty'),
                        'uom_code': self._val(detail, 'UOM'),
                        'detail_warehouse_code': self._val(detail, 'WarehouseID'),
                    }
                    result.append({
                        **header,
                        **shipment_to_address,
                        **detail_containter,
                    })

            _logger.info('Berhasil ambil %s rows Shipment Receipt dari Acumatica', len(result))
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()


class AcumaticaShipmentLine(models.Model):
    _name = 'acumatica.shipment.line'
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

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.shipment.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('receipt_nbr')
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
            partner = Partner.search([('company_registry', '=', line.partner_code)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.partner_code)], limit=1)
        return partner

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if line.detail_warehouse_code:
            warehouse = Warehouse.search([('code', '=', line.detail_warehouse_code)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    
            else:
                warehouse = False
        return warehouse

    def _find_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        location = False
        if line.warehouse_code:
            location = Location.search([('code', '=', line.warehouse_code)], limit=1)
            if not location:
                location = Location.search([('name', '=', line.warehouse_code)], limit=1)
            else:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
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

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = updated = error = 0

        keys = [k for k in self.mapped('receipt_nbr') if k]
        for shipment_nbr in keys:
            receipt_lines = self.filtered(lambda l: l.receipt_nbr == shipment_nbr and l.import_state == 'pending')
            if not receipt_lines:
                continue
            first = receipt_lines[0]
            try:
                # partner = self._find_partner(first)
                partner = self._find_partner(first)
                if not partner:
                    flag = {
                        'sync_state': 'not_ready',
                        'sync_message': f'Customer dengan CustomerID {first.partner_code} tidak ditemukan di WMS.',
                    }
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    flag = {
                        'sync_state': 'not_ready',
                        'sync_message': f'Warehouse dengan code {first.warehouse_dest_code} tidak ditemukan di WMS.',
                    }
                # warehouse = self._find_warehouse(first)
                # if not warehouse:
                #     raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'incoming'),
                ], limit=1)
                if not picking_type:
                    raise UserError('Picking type receipt/incoming tidak ditemukan.')

                dest_location = self._find_location_dest(first)
                # if not dest_location:
                #     raise UserError(f'Location tujuan tidak ditemukan untuk code: {first.location_dest_code or first.header_location_code or "-"}')

                # src_location = self._find_source_location(warehouse)
                # if not src_location:
                #     raise UserError('Location sumber supplier tidak ditemukan.')

                vals = {
                    'origin': first.receipt_nbr,
                    'partner_id': partner.id if partner else False,
                    'picking_type_id': picking_type.id,
                    'adt_dest_location_id': dest_location.id if dest_location else False,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,

                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    # 'adt_location_code': first.description,

                    # NANTI BUAT INHERIT KE STOCK.PICKING BERDASARKAN FIELD YANG ADA DI BAWAH INI
                    # adt_fob_point
                    # adt_is_hold
                    # adt_is_insurance
                    # adt_operations 
                    # adt_package_count
                    # adt_package_weight
                    # adt_picked
                    # adt_shipped_qty
                    # adt_shipped_volume
                    # adt_shipped_weight
                    # adt_shipping_terms
                    # adt_shipping_zone_id
                    # adt_ship_via
                    # adt_status
                    # adt_to_warehouse_id
                    # adt_type
                    # adt_warehouse_id
                    # adt_address_line_1
                    # adt_address_line_2
                    # adt_city
                    # adt_country
                    # adt_country_name
                    # adt_postal_code
                    # adt_state

                }

                picking = Picking.search([('origin', '=', first.receipt_nbr)], limit=1)
                if picking:
                    if picking.state in ('done', 'cancel'):
                        raise UserError(f'Receipt {first.receipt_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1

                for line in receipt_lines:
                    product = self._find_product(line)
                    uom = self._find_uom(line, product)
                    line_dest = self._find_location_dest(line) or dest_location
                    qty = self._parse_float(line.detail_shipped_qty or line.order_qty or line.actual_qty)

                    existing = Move.search([
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', product.id),
                        ('name', '=', line.line_description or product.display_name),
                        ('product_uom_qty', '=', qty),
                    ], limit=1)
                    if existing:
                        line.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name} (move sudah ada)',
                            'odoo_picking_id': picking.id,
                        })
                        continue

                    Move.create({
                        'name': line.line_description or product.display_name,
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': uom.id if uom else product.uom_id.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': line_dest.id if line_dest else picking.location_dest_id.id,
                        'description_picking': line.line_description or False,
                    })
                    line.write({
                        'import_state': action_state,
                        'import_message': f'{action_state.title()}: {picking.name}',
                        'odoo_picking_id': picking.id,

                        # NANTI BUAT INHERIT KE STOCK.MOVE BERDASARKAN FIELD YANG ADA DI BAWAH INI
                        # acumatica_row_number
                        # adt_note
                        # adt_description
                        # adt_is_free_item
                        # adt_acumatica_line_number
                        # adt_order_line_number
                        # adt_order_number
                        # adt_order_type
                        # adt_original_qty
                        # adt_shipped_qty
                    })
                    # ABIS INI NGEBUAT ALLOCATION, NANTI BAKAL ADA MODELS BARU BUAT NAMPUNG DATA ALLOCATION DARI ACUMATICA
                    # id
                    # rowNumber
                    # note
                    # Description
                    # InventoryID
                    # LocationID
                    # Quantity
                    # SplitLineNbr
                    # UOM
            except Exception as e:
                _logger.exception('Error import shipment receipt %s', shipment_nbr)
                receipt_lines.write({'import_state': 'error', 'import_message': str(e)[:200]})
                error += len(receipt_lines)

        msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Shipment Receipt',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

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
