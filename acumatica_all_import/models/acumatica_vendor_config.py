import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaVendorConfig(models.Model):
    _name        = 'acumatica.vendor.config'
    _description = 'Konfigurasi Koneksi Acumatica - Vendor Import'
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

    # ─── Login / Logout helpers ──────────────────────
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

    # ─── Fetch Vendor dari API ───────────────────────
    def fetch_vendor_data(self, limit=50, skip=0):
        """
        Ambil data Vendor dari Acumatica API.
        Endpoint: GET /Vendor?$top={limit}&$skip={skip}

        Field yang diambil (sesuai mapping):
          note                  → internal_notes
          FOBPoint              → adt_fob_point
          LastModifiedDateTime  → adt_last_modified_date_time
          LeadTimedays          → sale_delay
          LocationName          → name
          Status                → adt_state
          VendorClass           → adt_class
          VendorID              → company_registry
          VendorName            → complete_name / name

        Return: list of dict
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/Vendor"
            
            # Menambahkan $top dan $skip untuk pagination
            params = {
                "$top": limit,
                "$skip": skip
            }
            
            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Vendor (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info(
                "Berhasil ambil %d records Vendor (Skip: %d) dari Acumatica", 
                len(raw_data), skip
            )

            def val(item, key):
                """Ambil .value dari response Acumatica, return '' jika kosong/None."""
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "") or ""
                return ""

            def ival(item, key):
                """Integer value, return 0 jika kosong."""
                v = item.get(key, {})
                if isinstance(v, dict):
                    raw = v.get("value", 0)
                    try:
                        return int(raw) if raw != "" else 0
                    except (ValueError, TypeError):
                        return 0
                return 0

            result = []
            for item in raw_data:
                result.append({
                    'external_id':             item.get("id", "") or "",
                    'row_number':              item.get("rowNumber", 0),
                    # Mandatory
                    'note':                    item.get("note", {}).get("value", "") or "",
                    'account_ref':             val(item,  "AccountRef"),
                    'b_account_ref':           val(item,  "BAccountRef"),
                    'vendor_id':               val(item,  "VendorID"),
                    'vendor_name':             val(item,  "VendorName"),
                    'fob_point':               val(item,  "FOBPoint"),
                    'last_modified_date_time': val(item,  "LastModifiedDateTime"),
                    'lead_time_days':          ival(item, "LeadTimedays"),
                    'location_name':           val(item,  "LocationName"),
                    'status':                  val(item,  "Status"),
                    # Optional
                    'vendor_class':            val(item,  "VendorClass"),
                })

            return result

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
