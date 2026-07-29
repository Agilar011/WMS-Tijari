import requests
import json
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AcumaticaConfig(models.Model):
    _name = 'acumatica.config'
    _description = 'Konfigurasi Koneksi Acumatica WMS API'
    _rec_name = 'name'

    name = fields.Char(
        string='Nama Konfigurasi',
        required=True,
        default='Acumatica WMS',
    )
    base_url = fields.Char(
        string='Base URL',
        required=True,
        default='http://staging.aditya.group/acumportal/entity',
        help='Contoh: http://your-server/acumportal/entity',
    )
    api_version = fields.Char(
        string='API Version',
        required=True,
        default='25.200.002',
    )
    username = fields.Char(
        string='Username',
        required=True,
        default='wms',
    )
    password = fields.Char(
        string='Password',
        required=True,
    )
    company_code = fields.Char(
        string='Company Code',
        required=True,
        default='asgjkt',
    )
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)

    odata_expand = fields.Char(
        string='OData Expand',
        help='Contoh: Details atau Details,OtherChild'
    )
    odata_select = fields.Char(
        string='OData Select',
        help='Optional: pilih field tertentu'
    )
    odata_filter = fields.Char(
        string='OData Filter',
    )
    endpoint_name = fields.Char(
        string='Endpoint Name',
        required=True,
        help='Dipakai untuk transaksi yang butuh endpoint Acumatica spesifik.',
    )
    is_default = fields.Boolean(
        string='Default',
        default=False,
        help='Dipakai sebagai config bawaan untuk tipe import yang sama.',
    )
    config_type = fields.Selection(
        selection=[
            ('po_receipt', 'PO Receipt'),
            ('so_transfer', 'SO Transfer'),
            ('receipt_external', 'Receipt External'),
            ('receipt_change_item', 'Receipt Change Item'),
            ('inventory_received', 'Inventory Receipt'),
            ('toko_pegang_do', 'Toko Pegang DO'),
            ('shipment_so', 'Shipment SO Return'),
            ('so_shipment', 'SO Shipment'),
            ('transfer_shipment', 'Transfer Shipment'),
            ('issue_change_item', 'Issue Change Item'),
            ('inventory_issue', 'Inventory Issue'),
            ('issue_po_return', 'Issue PO Return'),
            ('transfer_one_step', 'Transfer One Step'),
            ('transfer_two_step', 'Transfer Two Step'),
            ('kit_assembly', 'Kit Assembly'),

            ('customer', 'Customer'),
            ('customer_location', 'Customer Location'),
            ('shipvia', 'Ship Via'),
            ('warehouse', 'Warehouse'),
            ('stock_item', 'Stock Item'),
            ('non_stock_item', 'Non Stock Item'),
            ('uom', 'Unit of Measure'),
            ('vendor', 'Vendor'),
            ('inventory_stock', 'Inventory Stock'),
            ('invoice_consignment', 'Invoice Consignment'),
            ('inventory_issue_toko_pegang_do', 'Inventory Issue Toko Pegang DO'),
            ('vendor_return_direct_transfer', 'Vendor Return Direct Transfer'),
            ('vendor_return_document_direct_transfer', 'Vendor Return Document Direct Transfer'),
            ('credit_memo_consignment', 'Credit Memo Consignment'),
            ('inventory_receipt_transfer_wh_in', 'Inventory Receipt : Transfer In'),

        ], string='Config Type', required=True, default='uom',
    )

    @api.model
    def _get_default_config_for_type(self, config_type):
        if not config_type:
            return self.browse()

        default_config = self.search([
            ('config_type', '=', config_type),
            ('is_default', '=', True),
            ('active', '=', True),
        ], limit=1)
        if default_config:
            if config_type == 'kit_assembly':
                default_config._ensure_kit_assembly_defaults()
            return default_config

        fallback_config = self.search([
            ('config_type', '=', config_type),
            ('active', '=', True),
        ], limit=1)
        if fallback_config:
            if config_type == 'kit_assembly':
                fallback_config._ensure_kit_assembly_defaults()
            return fallback_config

        if config_type == 'kit_assembly':
            return self._create_default_kit_assembly_config()

        return self.browse()

    @api.model
    def _normalize_inventory_receive_type(self, value):
        if not value:
            return 'inventory_receive'
        return str(value).strip().lower().replace('-', '_').replace(' ', '_')

    def _resolve_inventory_receive_picking_type(self, transfer_type=False, warehouse_code=False, document_only=False):
        self.ensure_one()
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        type_key = self._normalize_inventory_receive_type(transfer_type)
        domain_by_type = {
            'toko_pegang_do': [('code', '=', 'incoming')],
            'transfer_in': [('code', '=', 'internal')],
            'change_item': [('code', '=', 'incoming')],
            'inventory_receive': [('code', '=', 'incoming')],
            'inventory_received': [('code', '=', 'incoming')],
            'inventory_receipt': [('code', '=', 'incoming')],
        }

        picking_type_domain = domain_by_type.get(type_key)
        if picking_type_domain:
            domain = list(picking_type_domain) + [('is_default_api', '=', True)]
            if warehouse_code:
                location = Location.search([('code', '=', warehouse_code)], limit=1)
                if location and location.odoo_building_id:
                    domain.append(('warehouse_id', '=', location.odoo_building_id.id))
            picking_type = PickingType.search(domain, limit=1)
            if picking_type:
                return picking_type

            picking_type = PickingType.search(
                list(picking_type_domain) + [('is_default_api', '=', True)],
                limit=1,
            )
            if picking_type:
                return picking_type

        if document_only and type_key != 'transfer_in':
            return PickingType.resolve_document_only_picking_type(
                api_acumatica='inventory_received',
                document_only=document_only,
                warehouse_code=warehouse_code,
            )
        return PickingType.browse()

    @api.model
    def _create_default_kit_assembly_config(self):
        source = self.search([('active', '=', True)], limit=1)
        vals = {
            'name': 'Acumatica Kit Assembly - Default',
            'base_url': source.base_url or 'http://staging.aditya.group/acumportal/entity',
            'api_version': source.api_version or '25.200.002',
            'username': source.username or 'wms',
            'password': source.password or 'WMSAditya@2026',
            'company_code': source.company_code or 'asgjkt',
            'config_type': 'kit_assembly',
            'endpoint_name': 'KitAssembly',
            'odata_expand': 'StockComponents',
            'is_default': True,
            'active': True,
            'state': 'draft',
        }
        return self.create(vals)

    def _ensure_kit_assembly_defaults(self):
        for record in self.filtered(lambda config: config.config_type == 'kit_assembly'):
            vals = {}
            if not record.endpoint_name:
                vals['endpoint_name'] = 'KitAssembly'
            if not record.odata_expand:
                vals['odata_expand'] = 'StockComponents'
            if vals:
                record.write(vals)
        return self

    def _sync_default_flag(self):
        for record in self.filtered(lambda config: config.is_default and config.config_type):
            siblings = self.search([
                ('id', '!=', record.id),
                ('config_type', '=', record.config_type),
                ('is_default', '=', True),
            ])
            if siblings:
                siblings.write({'is_default': False})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_default_flag()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'is_default' in vals or 'config_type' in vals:
            self._sync_default_flag()
        return result

    # ─── Computed URLs ───────────────────────────────
    @property
    def api_url(self):
        return f"{self.base_url}/wms/{self.api_version}"

    @property
    def login_url(self):
        return f"{self.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.base_url}/auth/logout"

    # ─── Test Koneksi ────────────────────────────────
    def action_test_connection(self):
        self.ensure_one()
        try:
            session = self._do_login()
            if session:
                self._do_logout(session)
                self.state = 'connected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Koneksi Berhasil!',
                        'message': f'Berhasil terhubung ke Acumatica ({self.base_url})',
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    # ─── Login helper ────────────────────────────────
    def _do_login(self):
        self.ensure_one()
        credentials = {
            "name": self.username,
            "password": self.password,
            "company": self.company_code,
        }
        try:
            session = requests.Session()
            response = session.post(
                self.login_url,
                json=credentials,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code == 204:
                _logger.info("Acumatica login berhasil untuk user: %s", self.username)
                return session
            else:
                raise UserError(
                    f'Login gagal (HTTP {response.status_code}): {response.text}'
                )
        except requests.exceptions.ConnectionError:
            raise UserError(f'Tidak bisa terhubung ke server: {self.base_url}')
        except requests.exceptions.Timeout:
            raise UserError('Koneksi timeout. Periksa URL server.')

    # ─── Logout helper ───────────────────────────────
    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass  # Logout gagal tidak masalah

    # ─── Fetch UoM dari API ──────────────────────────
    def fetch_uom_data(self, limit=500, offset=0):
        print('get uom data')
        """
        Ambil data Units of Measure dari Acumatica API.
        Return: list of dict { unit_id, description, external_id }
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/UnitsOfMeasure"
            params = {"$top": limit, "$skip": offset}

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data UoM (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records UoM dari Acumatica", len(raw_data))

            result = []
            for item in raw_data:
                result.append({
                    'unit_id':     item.get("UnitID", {}).get("value", "") or "",
                    'description': item.get("Description", {}).get("value", "") or "",
                    'external_id': item.get("id", "") or "",
                    'row_number':  item.get("rowNumber", 0),
                })

            return result

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

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
        self.ensure_one()
        endpoint_name = self.endpoint_name or 'KitAssembly'
        expand = self.odata_expand or 'StockComponents'
        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/{endpoint_name}"
            params = {
                '$top': limit,
                '$skip': offset,
            }
            if expand:
                params['$expand'] = expand
            if self.odata_select:
                params['$select'] = self.odata_select
            if self.odata_filter:
                params['$filter'] = self.odata_filter

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Kit Assembly (HTTP {response.status_code}): {response.text}'
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

                assembly = self.env['acumatica.kit.assembly'].create(header)

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
                        'assembly_id': assembly.id,
                    }
                    self.env['acumatica.kit.assembly.component'].create(component_data)
                    result.append({**header, **component_data})

            _logger.info(
                'Berhasil ambil %s rows Kit Assembly dari Acumatica (skip=%s, top=%s)',
                len(result), offset, limit,
            )
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
