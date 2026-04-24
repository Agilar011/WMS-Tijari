import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaNonStockItemConfig(models.Model):
    _name        = 'acumatica.non.stock.item.config'
    _description = 'Konfigurasi Koneksi Acumatica - Non-Stock Item Import'
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

    def fetch_non_stock_item_data(self, limit=50):
        """
        Ambil data Non-Stock Item dari Acumatica API.
        Endpoint: GET /NonStockItem?$top={limit}
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/NonStockItem"
            params   = {"$top": limit}
            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Non-Stock Item (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records Non-Stock Item dari Acumatica", len(raw_data))

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

            def fval(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    try:
                        return float(v.get("value", 0) or 0)
                    except (ValueError, TypeError):
                        return 0.0
                return 0.0

            result = []
            for item in raw_data:
                result.append({
                    'external_id':            item.get("id", "") or "",
                    'row_number':             item.get("rowNumber", 0),
                    # Mandatory
                    'inventory_id':           val(item,  "InventoryID"),
                    'description':            val(item,  "Description"),
                    'item_type':              val(item,  "ItemType"),
                    'item_class':             val(item,  "ItemClass"),
                    'item_status':            val(item,  "ItemStatus"),
                    'base_unit':              val(item,  "BaseUnit"),
                    'purchase_unit':          val(item,  "PurchaseUnit"),
                    'sales_unit':             val(item,  "SalesUnit"),
                    'is_a_kit':               bval(item, "IsAKit"),
                    'is_kit':                 bval(item, "IsKit"),
                    'note_id':                val(item,  "NoteID"),
                    'posting_class':          val(item,  "PostingClass"),
                    'note':                   item.get("note", {}).get("value", "") or "",
                    # Optional
                    'last_modified_datetime': val(item,  "LastModifiedDateTime"),
                    'price_class':            val(item,  "PriceClass"),
                    'volume':                 fval(item, "Volume"),
                    'volume_uom':             val(item,  "VolumeUOM"),
                    'weight':                 fval(item, "Weight"),
                    'weight_uom':             val(item,  "WeightUOM"),
                })

            return result

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()
