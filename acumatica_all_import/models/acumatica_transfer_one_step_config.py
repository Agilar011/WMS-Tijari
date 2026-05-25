import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaTransferOneStepConfig(models.Model):
    _name = 'acumatica.transfer.one.step.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Receipt Import'
    _rec_name = 'name'

    name = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url = fields.Char(string='Base URL', required=True, default='http://staging.aditya.group/acumportal/entity')
    api_version = fields.Char(string='API Version', required=True, default='25.200.002')
    username = fields.Char(string='Username', required=True, default='wms')
    password = fields.Char(string='Password', required=True)
    company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
    endpoint_name = fields.Char(string='Endpoint Name', required=True, default='TransferOrder')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)
    odata_expand = fields.Char(
        string='OData Expand',
        default='Details',
        help='Contoh: Details atau Details,OtherChild'
    )
    odata_select = fields.Char(
        string='OData Select',
        help='Optional: pilih field tertentu'
    )
    odata_filter = fields.Char(
        string='OData Filter',
        default="TransferType eq '1-Step' and (Status eq 'On Hold' or Status eq 'Balanced')"
    )

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

    def _do_login(self):
        self.ensure_one()
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

    def _val(self, item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    def _normalize_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    def fetch_receipt_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
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
            if self.odata_filter:
                filters.append(f"({self.odata_filter})")
            else:
                filters.append("(TransferType eq '1-Step')")

            if filters:
                params['$filter'] = ' and '.join(filters)       

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Order (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'note': item.get('note', {}).get('value', '') or '',
                    'scheduled_date': self._val(item, 'Date'),
                    'description': self._val(item, 'Description'),
                    'from_warehouse_code': self._val(item, 'FromWarehouseID'),
                    'is_hold': self._val(item, 'Hold'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'to_warehouse_code': self._val(item, 'ToWarehouseID'),
                    'transfer_type': self._val(item, 'TransferType'),
                    'trans_type': self._val(item, 'TransType'),
                }

                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    result.append(dict(header, line_nbr='0'))
                    continue

                for detail in details:
                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    description = self._val(detail, 'Description') or self._val(detail, 'TransactionDescription')
                    warehouse_dest_code = self._val(detail, 'Warehouse') or header.get('warehouse_code')

                    result.append({
                        **header,
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'line_description': self._val(detail, 'Description'),
                        'from_location_code': self._val(detail, 'FromLocationID'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'to_location_code': self._val(detail, 'ToLocationID'),
                        'quantity': self._val(detail, 'Quantity'),
                        'uom_code': self._val(detail, 'UOM'),
                    })

            _logger.info("Berhasil ambil %s rows Transfer Order dari Acumatica", len(result))
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
