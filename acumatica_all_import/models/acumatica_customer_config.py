import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaCustomerConfig(models.Model):
    _name = 'acumatica.customer.config'
    _description = 'Konfigurasi Koneksi Acumatica - Customer Import'
    _rec_name = 'name'

    name = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url = fields.Char(
        string='Base URL', required=True,
        default='http://34.101.103',
    )
    api_version = fields.Char(string='API Version', required=True, default='25.200.001')
    username    = fields.Char(string='Username', required=True, default='wms')
    password    = fields.Char(string='Password', required=True)
    company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
    active      = fields.Boolean(default=True)
    last_sync   = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft',     'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error',     'Error'),
    ], string='Status', default='draft', readonly=True)

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

    # ─── Logout helper ───────────────────────────────
    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass

    # ─── Fetch Customer dari API ─────────────────────
    def fetch_customer_data(self, limit=50, skip=0):
        """
        Ambil data Customer dari Acumatica API.
        Endpoint: /Customer?$top={limit}&$skip={skip}
        Return: list of dict sesuai mapping
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/Customer"
            
            # Menambahkan parameter $top dan $skip untuk pagination
            params = {
                "$top": limit,
                "$skip": skip
            }

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Customer (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info(
                "Berhasil ambil %d records Customer (Skip: %d) dari Acumatica", 
                len(raw_data), skip
            )

            def val(item, key):
                """Helper ambil .value dari dict Acumatica, return '' jika kosong/None"""
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "") or ""
                return ""

            result = []
            for item in raw_data:
                result.append({
                    'external_id':            item.get("id", "") or "",
                    'row_number':             item.get("rowNumber", 0),
                    # Field yang diimport ke res.partner
                    'customer_id':            val(item, "CustomerID"),
                    'b_account_id':           str(val(item, "BAccountID")) if val(item, "BAccountID") else "",
                    'customer_name':          val(item, "CustomerName"),
                    'customer_class':         val(item, "CustomerClass"),
                    'status':                 val(item, "Status"),
                    'currency_id':            val(item, "CurrencyID"),
                    'warehouse_id':           val(item, "WarehouseID"),
                    'shipping_zone_id':       val(item, "ShippingZoneID"),
                    'fob_point':              val(item, "FOBPoint"),
                    'created_datetime':       val(item, "CreatedDateTime"),
                    'last_modified_datetime': val(item, "LastModifiedDateTime"),
                    'note_id':                val(item, "NoteID"),
                    'note':                   item.get("note", {}).get("value", "") or "",
                    'location_name':          val(item, "LocationName"),
                })

            return result

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
