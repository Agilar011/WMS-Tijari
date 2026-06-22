import logging
import requests

from odoo import fields, models
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

    def fetch_transfer_shipment_data(self, limit=50, offset=0, shipment_nbr=False, last_modified_from=False, odata_filter=False):
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
            if shipment_nbr:
                filters.append(f"ShipmentNbr eq '{shipment_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            if odata_filter:
                filters.append(f"({odata_filter})")
            elif self.odata_filter:
                filters.append(f"({self.odata_filter})")

            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Shipment (HTTP {response.status_code}): {response.text}')

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
                    'is_hold': self._val(item, 'Hold'),
                    'is_insurance': self._val(item, 'Insurance'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'LocationID'),
                    'operation': self._val(item, 'Operation'),
                    'package_count': self._val(item, 'PackageCount'),
                    'package_weight': self._val(item, 'PackageWeight'),
                    'is_picked': self._val(item, 'Picked'),
                    'scheduled_date': self._val(item, 'ShipmentDate'),
                    'shipment_nbr': self._val(item, 'ShipmentNbr'),
                    'shipped_qty': self._val(item, 'ShippedQty'),
                    'shipped_volume': self._val(item, 'ShippedVolume'),
                    'shipped_weight': self._val(item, 'ShippedWeight'),
                    'shipping_terms': self._val(item, 'ShippingTerms'),
                    'shipping_zone': self._val(item, 'ShippingZoneID'),
                    'ship_via': self._val(item, 'ShipVia'),
                    'status': self._val(item, 'Status'),
                    'warehouse_dest_code': self._val(item, 'ToWarehouseID'),
                    'shipment_type': self._val(item, 'Type'),
                    'warehouse_code': self._val(item, 'WarehouseID'),
                    'is_unlimited_packages': self._val(item, 'UnlimitedPackages'),
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
                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    result.append({
                        **header,
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'line_row_number': detail.get('rowNumber') or '',
                        'line_description': self._val(detail, 'Description'),
                        'is_free_item': self._val(detail, 'FreeItem'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'location_dest_code': self._val(detail, 'LocationID'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'order_line_number': self._val(detail, 'OrderLineNbr'),
                        'order_number': self._val(detail, 'OrderNbr'),
                        'order_type': self._val(detail, 'OrderType'),
                        'original_qty': self._val(detail, 'OriginalQty'),
                        'product_uom_qty': self._val(detail, 'ShippedQty'),
                        'uom_code': self._val(detail, 'UOM'),
                        'line_warehouse_code': self._val(detail, 'WarehouseID'),
                    })

            return result
        except Exception:
            raise
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
