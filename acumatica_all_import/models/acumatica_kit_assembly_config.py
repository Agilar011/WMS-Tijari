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
        default='http://34.101.103.239/acumportal/entity',
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

    def fetch_kit_assembly_data(self, batch_size=100, start_skip=0, target_total=None):
        """
        Fetch data Kit Assembly dengan:
        - batch_size  = jumlah data per request
        - start_skip  = titik awal data
        - target_total = total data yang ingin diambil (None = ambil semua)
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/KitAssembly"

            all_results = []
            current_skip = start_skip

            while True:
                # =========================
                # STOP JIKA TARGET TERCAPAI
                # =========================
                if target_total and len(all_results) >= target_total:
                    break

                # tentukan batch size aktual
                current_batch_size = batch_size
                if target_total:
                    remaining = target_total - len(all_results)
                    current_batch_size = min(batch_size, remaining)

                params = {
                    "$top": current_batch_size,
                    "$skip": current_skip,
                }

                response = session.get(endpoint, params=params, timeout=60)

                if response.status_code != 200:
                    raise UserError(
                        f'Gagal ambil data Kit Assembly '
                        f'(HTTP {response.status_code}): {response.text}'
                    )

                raw_data = response.json()

                if not raw_data:
                    _logger.info("Data API habis.")
                    break

                _logger.info(
                    "Fetch KitAssembly batch: %d records (skip=%d, top=%d)",
                    len(raw_data), current_skip, current_batch_size
                )

                # =========================
                # HELPER
                # =========================
                def val(item, key):
                    v = item.get(key, {})
                    if isinstance(v, dict):
                        return v.get("value", "") or ""
                    return ""

                # =========================
                # PARSE
                # =========================
                for item in raw_data:
                    header = {
                        'external_id':item.get("id", "") or "",
                        'row_number': item.get("rowNumber", 0),
                        'description': val(item, "Description"),
                        'inventory_id': val(item, "InventoryID"),
                        'last_modified_datetime': val(item, "LastModifiedDateTime"),
                        'location': val(item, "Location"),
                        'post_period': val(item, "PostPeriod"),
                        'quantity': val(item, "Qty"),
                        'reason_code':val(item, "ReasonCode"),
                        'reference_nbr':val(item, "ReferenceNbr"),
                        'requested_on':val(item, "RequestedOn"),
                        'revision':val(item, "Revision"),
                        'status':val(item, "Status"),
                        'type':val(item, "Type"),
                        'uom': val(item, "UOM"),
                        'warehouse': val(item, "Warehouse"),
                    }
                stock_components = item.get('StockComponents') or []
                if isinstance(stock_components, dict):
                    stock_components = stock_components.get('value', []) or []
                if not isinstance(stock_components, list):
                    stock_components = []

                if not stock_components:
                    all_results.append(dict(header, line_nbr='0'))
                    continue

                for component in stock_components:
                    line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0

                    all_results.append({
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

                batch_count = len(raw_data)
                current_skip += batch_count

                # stop kalau data API habis
                if batch_count < current_batch_size:
                    _logger.info("Batch terakhir, data habis.")
                    break

            _logger.info("TOTAL KIT ASSEMBLY TERAMBIL: %d", len(all_results))

            return all_results

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()