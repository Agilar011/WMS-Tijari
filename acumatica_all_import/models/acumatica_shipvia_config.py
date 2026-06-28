# import requests
# import logging

# from odoo import models, fields
# from odoo.exceptions import UserError

# _logger = logging.getLogger(__name__)


# class AcumaticaShipViaConfig(models.Model):
#     _name        = 'acumatica.shipvia.config'
#     _description = 'Konfigurasi Koneksi Acumatica - ShipVia Import'
#     _rec_name    = 'name'

#     name         = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
#     base_url     = fields.Char(
#         string='Base URL', required=True,
#         default='http://staging.aditya.group/acumportal/entity',
#     )
#     api_version  = fields.Char(string='API Version', required=True, default='25.200.002')
#     username     = fields.Char(string='Username', required=True, default='wms')
#     password     = fields.Char(string='Password', required=True)
#     company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
#     active       = fields.Boolean(default=True)
#     last_sync    = fields.Datetime(string='Terakhir Sync', readonly=True)
#     state        = fields.Selection([
#         ('draft',     'Belum Ditest'),
#         ('connected', 'Terhubung'),
#         ('error',     'Error'),
#     ], string='Status', default='draft', readonly=True)

#     # ─── Computed URLs ───────────────────────────────
#     @property
#     def api_url(self):
#         return f"{self.base_url}/wms/{self.api_version}"

#     @property
#     def login_url(self):
#         return f"{self.base_url}/auth/login"

#     @property
#     def logout_url(self):
#         return f"{self.base_url}/auth/logout"

#     # ─── Test Koneksi ────────────────────────────────
#     def action_test_connection(self):
#         self.ensure_one()
#         try:
#             session = self._do_login()
#             self._do_logout(session)
#             self.state = 'connected'
#             return {
#                 'type': 'ir.actions.client',
#                 'tag':  'display_notification',
#                 'params': {
#                     'title':   'Koneksi Berhasil!',
#                     'message': f'Berhasil terhubung ke Acumatica ({self.base_url})',
#                     'type':    'success',
#                     'sticky':  False,
#                 },
#             }
#         except Exception as e:
#             self.state = 'error'
#             raise UserError(f'Koneksi gagal: {str(e)}')

#     # ─── Login / Logout helpers ──────────────────────
#     def _do_login(self):
#         self.ensure_one()
#         try:
#             session  = requests.Session()
#             response = session.post(
#                 self.login_url,
#                 json={
#                     "name":     self.username,
#                     "password": self.password,
#                     "company":  self.company_code,
#                 },
#                 headers={"Content-Type": "application/json"},
#                 timeout=30,
#             )
#             if response.status_code == 204:
#                 return session
#             raise UserError(f'Login gagal (HTTP {response.status_code}): {response.text}')
#         except requests.exceptions.ConnectionError:
#             raise UserError(f'Tidak bisa terhubung ke server: {self.base_url}')
#         except requests.exceptions.Timeout:
#             raise UserError('Koneksi timeout. Periksa URL server.')

#     def _do_logout(self, session):
#         try:
#             session.post(self.logout_url, timeout=10)
#         except Exception:
#             pass

#     # ─── Fetch ShipVia dari API ───────────────────────
#     def fetch_shipvia_data(self, limit=50, offset=0):
#         """
#         Ambil data ShipVia dari Acumatica API.
#         Endpoint: GET /ShipVia?$top={limit}&$skip={skip}

#         Field yang diambil (sesuai mapping):
#           note                  → internal_notes
#           Address               → street
#           CarrierID             → carrier_code
#           City                  → city
#           Description           → name
#           NoteID                → note_id
#           phone                 → phone

#         Return: list of dict
#         """
#         self.ensure_one()
#         session = self._do_login()

#         try:
#             endpoint = f"{self.api_url}/ShipVia"
            
#             # Menambahkan $top dan $skip untuk pagination
#             params = {
#                 "$top": limit,
#                 "$skip": offset
#             }
            
#             response = session.get(endpoint, params=params, timeout=60)

#             if response.status_code != 200:
#                 raise UserError(
#                     f'Gagal ambil data ShipVia (HTTP {response.status_code}): {response.text}'
#                 )

#             raw_data = response.json()
#             _logger.info(
#                 "Berhasil ambil %d records ShipVia (Skip: %d) dari Acumatica", 
#                 len(raw_data), offset
#             )

#             def val(item, key):
#                 """Ambil .value dari response Acumatica, return '' jika kosong/None."""
#                 v = item.get(key, {})
#                 if isinstance(v, dict):
#                     return v.get("value", "") or ""
#                 return ""

#             def ival(item, key):
#                 """Integer value, return 0 jika kosong."""
#                 v = item.get(key, {})
#                 if isinstance(v, dict):
#                     raw = v.get("value", 0)
#                     try:
#                         return int(raw) if raw != "" else 0
#                     except (ValueError, TypeError):
#                         return 0
#                 return 0

#             result = []
#             for item in raw_data:
#                 result.append({
#                     'external_id':             item.get("id", "") or "",
#                     'note':                    item.get("note", {}).get("value", "") or "",
#                     'address':                 val(item,  "Address"),
#                     'carrier_id':              val(item,  "CarrierID"),
#                     'city':                    val(item,  "City"),
#                     'description':             val(item,  "Description"),
#                     'note_id':                 val(item,  "NoteID"),
#                     'phone':                   val(item, "Phone"),
#                 })

#             return result

#         finally:
#             self._do_logout(session)
#             self.last_sync = fields.Datetime.now()
