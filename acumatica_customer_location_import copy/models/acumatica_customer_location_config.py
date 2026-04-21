import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaCustomerLocationConfig(models.Model):
    _name        = 'acumatica.customer.location.config'
    _description = 'Konfigurasi Koneksi Acumatica - Customer Location Import'
    _rec_name    = 'name'

    name         = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url     = fields.Char(
        string='Base URL', required=True,
        default='http://34.101.103.239/acumportal/entity',
    )
    api_version  = fields.Char(string='API Version', required=True, default='25.200.001')
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

    def fetch_customer_location_data(self, batch_size=100, start_skip=0, target_total=None):
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/CustomerLocation"

            all_results = []
            current_skip = start_skip

            while True:
                # =========================
                # STOP JIKA TARGET TERCAPAI
                # =========================
                if target_total and len(all_results) >= target_total:
                    break

                # hitung batch yg akan diambil
                current_batch_size = batch_size
                if target_total:
                    remaining = target_total - len(all_results)
                    current_batch_size = min(batch_size, remaining)

                params = {
                    "$expand": "LocationContact/Address",
                    "$top": current_batch_size,
                    "$skip": current_skip,
                }

                response = session.get(endpoint, params=params, timeout=60)

                if response.status_code != 200:
                    raise UserError(
                        f'Gagal ambil data Customer Location '
                        f'(HTTP {response.status_code}): {response.text}'
                    )

                raw_data = response.json()

                if not raw_data:
                    _logger.info("Data API habis.")
                    break

                _logger.info(
                    "Fetch batch: %d records (skip=%d, top=%d)",
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

                def bval(item, key):
                    v = item.get(key, {})
                    if isinstance(v, dict):
                        return bool(v.get("value", False))
                    return False

                def ival(item, key):
                    v = item.get(key, {})
                    if isinstance(v, dict):
                        try:
                            return int(v.get("value", 0) or 0)
                        except:
                            return 0
                    return 0

                # =========================
                # PARSE
                # =========================
                for item in raw_data:
                    contact = item.get("LocationContact", {}) or {}
                    address = contact.get("Address", {}) or {}

                    def aval(key):
                        v = address.get(key, {})
                        if isinstance(v, dict):
                            return v.get("value", "") or ""
                        return ""

                    all_results.append({
                        'external_id':          item.get("id", "") or "",
                        'row_number':           item.get("rowNumber", 0),
                        'note':                 item.get("note", {}).get("value", "") or "",
                        'customer':             val(item, "Customer"),
                        'location_id_acumatica': val(item, "LocationID"),
                        'location_name':        val(item, "LocationName"),
                        'is_active':            bval(item, "Active"),
                        'address_override':     bval(item, "AddressOverride"),
                        'fob_point':            val(item, "FOBPoint"),
                        'shipping_branch':      val(item, "ShippingBranch"),
                        'status':               val(item, "Status"),
                        'warehouse':            val(item, "Warehouse"),
                        'is_default':           bval(item, "Default"),
                        'usage_type':           val(item, "EntityUsageType"),
                        'ext_ref_number':       val(item, "ExtRefNbr"),
                        'fed_ex_ground_collect': bval(item, "FedExGroundCollect"),
                        'insurance':            bval(item, "Insurance"),
                        'lead_time_days':       ival(item, "LeadTimeDays"),
                        'note_id':              val(item, "NoteID"),
                        'order_priority':       ival(item, "OrderPriority"),
                        'shipping_zone':        val(item, "ShippingZone"),
                        'ship_via':             val(item, "ShipVia"),
                        'created_datetime':     val(item, "CreatedDateTime"),
                        'last_modified_datetime': val(item, "LastModifiedDateTime"),
                        'address_line1':        aval("AddressLine1"),
                        'city':                 aval("City"),
                        'postal_code':          aval("PostalCode"),
                        'state_code':           aval("State"),
                        'country_code':         aval("Country"),
                    })

                batch_count = len(raw_data)
                current_skip += batch_count

                # stop kalau API habis
                if batch_count < current_batch_size:
                    _logger.info("Batch terakhir, data habis.")
                    break

            _logger.info("TOTAL FINAL: %d records", len(all_results))

            return all_results

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()