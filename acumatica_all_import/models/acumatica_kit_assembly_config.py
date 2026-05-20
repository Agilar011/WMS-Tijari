import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

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
        try:
            session  = requests.Session()
            response = session.post(
                self.login_url,
                json={
                    "name":     self.username,
                    "password": self.password,
                    "company":  self.company_code,
                },
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code == 204:
                return session
            raise UserError(f'Login gagal (HTTP {response.status_code}): {response.text}')
        except requests.exceptions.ConnectionError:
            raise UserError(f'Tidak bisa terhubung ke server: {self.base_url}')
        except requests.exceptions.Timeout:
            raise UserError('Koneksi timeout. Periksa URL server.')

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

    def fetch_kit_assembly_data(self, limit=100, offset=0):
        """Fetch 1 page Kit Assembly dari Acumatica (paging via $top/$skip)."""
        self.ensure_one()
        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/KitAssembly"
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
