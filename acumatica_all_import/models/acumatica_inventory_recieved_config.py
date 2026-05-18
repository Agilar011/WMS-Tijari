import logging
import requests

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaInventoryRecievedConfig(models.Model):
    _name = 'acumatica.inventory.recieved.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Recieved'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Inventory Recieved')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.001')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
    endpoint_name = fields.Char(required=True, default='InventoryReceipt')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], default='draft', readonly=True)

    odata_expand = fields.Char(default='Details')
    odata_select = fields.Char()
    odata_filter = fields.Char(default="TransType eq 'Inventory Receive'")

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

    def fetch_inventory_recieved_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
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
            if reference_nbr:
                filters.append(f"ReferenceNbr eq '{reference_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            # if self.odata_filter:
            #     filters.append(f"({self.odata_filter})")
            if odata_filter:
                filters.append(f"({odata_filter})")
            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(f'Gagal fetch data (HTTP {response.status_code}): {response.text}')

            rows = self._normalize_rows(response.json())
            result = []
            row_number = 1
            for header in rows:
                details = self._normalize_rows(header.get('Details') or header.get('details') or [])
                if not details:
                    details = [{}]
                for detail in details:
                    result.append({
                        'row_number': row_number,
                        'external_id': self._val(header, 'id') or header.get('id') or '',
                        'line_external_id': self._val(detail, 'id') or detail.get('id') or '',
                        'reference_nbr': self._val(header, 'ReferenceNbr'),
                        'scheduled_date': self._val(header, 'Date'),
                        'description': self._val(detail, 'Description') or self._val(header, 'Description'),
                        'header_description': self._val(header, 'Description'),
                        'actual_qty': str(self._val(header, 'ControlQty')),
                        'is_hold': str(self._val(header, 'Hold')),
                        'acumatica_write_date': self._val(header, 'LastModifiedDateTime'),
                        'post_period': str(self._val(header, 'PostPeriod')),
                        'status': self._val(header, 'Status'),
                        'total_qty': str(self._val(header, 'TotalQty')),
                        'warehouse_code': self._val(header, 'ToWarehouseID'),
                        'transfer_type': self._val(header, 'TransType'),
                        'note': self._val(header, 'note'),
                        'line_note': self._val(detail, 'note'),
                        'location_code': self._val(detail, 'Location'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(self._val(detail, 'LineNbr')),
                        'product_uom_qty': str(self._val(detail, 'Qty')),
                        'detail_warehouse_code': self._val(detail, 'WarehouseID'),
                        'uom_code': self._val(detail, 'UOM'),
                    })
                    row_number += 1
            self.last_sync = fields.Datetime.now()
            return result
        finally:
            self._do_logout(session)
