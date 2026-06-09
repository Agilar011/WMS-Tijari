import logging
import requests

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaTransferConfig(models.Model):
    _name = 'acumatica.transfer.config'
    _description = 'Konfigurasi Koneksi Acumatica - Internal Transfer'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Internal Transfer')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.002')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
    endpoint_name = fields.Char(required=True, default='PurchaseReceipt')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], default='draft', readonly=True)

    odata_expand = fields.Char(default='Details')
    odata_select = fields.Char()
    odata_filter = fields.Char(default="Type eq 'Transfer Receipt'")

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

    def fetch_transfer_data(self, limit=50, offset=0, receipt_nbr=False, last_modified_from=False, odata_filter=False):
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
                filters.append(f"ReceiptNbr eq '{receipt_nbr}'")
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
                raise UserError(f'Gagal ambil data Transfer Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            is_found_dest_warehouse = False

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'branch_warehouse': self._val(item, 'Branch'),
                    'actual_qty': self._val(item, 'ControlQty'),
                    'scheduled_date': self._val(item, 'Date'),
                    'is_hold': self._val(item, 'Hold'),
                    'inventory_ref': self._val(item, 'InventoryRefNbr'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'Location'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'receipt_nbr': self._val(item, 'ReceiptNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'receipt_type': self._val(item, 'Type'),
                    'vendor_code': self._val(item, 'VendorID'),
                    'partner_ref': self._val(item, 'VendorRef'),
                    'warehouse_dest_code': self._val(item, 'Warehouse'),
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
                    transfer_shipment_nbr = self._val(detail, 'TransferShipmentNbr')
                    if transfer_shipment_nbr and not is_found_dest_warehouse:
                        dest_warehouse_data = self.search_dest_warehouse(transfer_shipment_nbr, session)
                        is_found_dest_warehouse = True

                    result.append({
                        **header,
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'description': description,
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'line_type': self._val(detail, 'LineType'),
                        'location_dest_code': self._val(detail, 'Location'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'po_line_number': self._val(detail, 'POLineNbr'),
                        'po_number': self._val(detail, 'POOrderNbr'),
                        'po_type': self._val(detail, 'POOrderType'),
                        'po_receipt_line_number': self._val(detail, 'POReceiptLineNbr'),
                        'po_receipt_number': self._val(detail, 'POReceiptNbr'),
                        'product_uom_qty': self._val(detail, 'ReceiptQty'),
                        'transaction_description': self._val(detail, 'TransactionDescription'),
                        'transfer_order_line_number': self._val(detail, 'TransferOrderLineNbr'),
                        'transfer_order_number': self._val(detail, 'TransferOrderNbr'),
                        'transfer_order_type': self._val(detail, 'TransferOrderType'),
                        'transfer_shipment_number': transfer_shipment_nbr,
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_code': dest_warehouse_data.get('source_warehouse') if dest_warehouse_data else None,
                    })

            _logger.info('Berhasil ambil %s rows Transfer Receipt dari Acumatica', len(result))
            self.last_sync = fields.Datetime.now()
            return result
        finally:
            self._do_logout(session)

    def search_dest_warehouse(self, transfer_nbr, session):
        self.ensure_one()
        # if not session:
        #     session = self._do_login()
        if not transfer_nbr:
            return None
        try:
            endpoint = f"{self.api_url}/Shipment"
            params = {
                '$select': 'ToWarehouseID, WarehouseID, ShipmentNbr', 
                '$filter': f"ShipmentNbr eq '{transfer_nbr}'"
            }

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Destination Warehouse (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())

            item = raw_data[0]  # misal ambil data pertama

            result = {
                'shipment_number': self._val(item, 'ShipmentNbr'),
                'dest_warehouse': self._val(item, 'ToWarehouseID'),
                'source_warehouse': self._val(item, 'WarehouseID'),
            }

            _logger.info('Berhasil ambil data Warehouse dari Transfer Shipment', len(result))
            return result
        except Exception as e:
            _logger.error('Gagal ambil data Warehouse dari Transfer Shipment: %s', str(e))
            return None