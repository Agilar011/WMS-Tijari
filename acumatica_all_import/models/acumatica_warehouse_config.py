import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaWarehouseConfig(models.Model):
    _name = 'acumatica.warehouse.config'
    _description = 'Konfigurasi Koneksi Acumatica - Warehouse Import'
    _rec_name = 'name'

    name         = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url     = fields.Char(string='Base URL', required=True,
                               default='http://staging.aditya.group/acumportal/entity')
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
                json={"name": self.username, "password": self.password, "company": self.company_code},
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

    def fetch_warehouse_data(self, limit=50, offset=0):
        """
        Fetch Warehouse + Locations dari Acumatica.
        Endpoint: /Warehouse?$expand=Locations&$top={limit}
        Return: list of dict warehouse, masing-masing punya key 'locations' (list)
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/Warehouse"
            params   = {"$expand": "Locations", "$top": limit, "$skip": offset}

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Warehouse (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records Warehouse dari Acumatica", len(raw_data))

            def val(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "") or ""
                return ""

            def bval(item, key):
                """Boolean value"""
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", False)
                return False

            result = []
            for item in raw_data:
                # ── Parse locations (detail) ──
                locations = []
                for loc in item.get("Locations", []):
                    locations.append({
                        'external_id':  loc.get("id", "") or "",
                        'row_number':   loc.get("rowNumber", 0),
                        'active':       bval(loc, "Active"),
                        'description':  val(loc, "Description"),
                        'location_id':  val(loc, "LocationID"),
                        'note':         loc.get("note", {}).get("value", "") or "",
                    })

                result.append({
                    # Header
                    'external_id':           item.get("id", "") or "",
                    'building_id':           val(item, "BuildingID"),
                    'row_number':            item.get("rowNumber", 0),
                    'note':                  item.get("note", {}).get("value", "") or "",
                    'active':                bval(item, "Active"),
                    'description':           val(item, "Description"),
                    'drop_ship_location_id': val(item, "DropShipLocationID"),
                    'last_modified_dt':      val(item, "LastModifiedDateTime"),
                    'receiving_location_id': val(item, "ReceivingLocationID"),
                    'rma_location_id':       val(item, "RMALocationID"),
                    'shipping_location_id':  val(item, "ShippingLocationID"),
                    'warehouse_id':          val(item, "WarehouseID"),
                    # Detail
                    'locations':             locations,
                })

            return result

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
