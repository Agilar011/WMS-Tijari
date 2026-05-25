import requests
import logging
import time

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaStockItemConfig(models.Model):
    _name        = 'acumatica.stock.item.config'
    _description = 'Konfigurasi Koneksi Acumatica - Stock Item Import'
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

        max_retry = 3
        retry_delay = 30

        last_error = None

        for attempt in range(1, max_retry + 1):

            try:

                print('==================================================')
                print(f'LOGIN ACUMATICA ATTEMPT {attempt}/{max_retry}')
                print(f'LOGIN URL   : {self.login_url}')
                print(f'USERNAME    : {self.username}')
                print(f'COMPANY     : {self.company_code}')
                print('==================================================')

                _logger.info(
                    'LOGIN ACUMATICA ATTEMPT %s/%s',
                    attempt,
                    max_retry
                )

                session = requests.Session()

                response = session.post(
                    self.login_url,
                    json={
                        "name":     self.username,
                        "password": self.password,
                        "company":  self.company_code,
                    },
                    headers={
                        "Content-Type": "application/json"
                    },
                    timeout=30,
                )

                print('=============== LOGIN RESPONSE ===================')
                print(f'STATUS CODE : {response.status_code}')
                print(f'RESPONSE    : {response.text}')
                print('==================================================')

                if response.status_code == 204:

                    print('LOGIN SUCCESS')
                    print('==================================================')

                    _logger.info('LOGIN SUCCESS')

                    return session

                last_error = (
                    f'Login gagal '
                    f'(HTTP {response.status_code}): {response.text}'
                )

                print('LOGIN FAILED')
                print(last_error)

                _logger.error(last_error)

            except requests.exceptions.ConnectionError as e:

                last_error = (
                    f'Tidak bisa terhubung ke server: {self.base_url}'
                )

                print('==================================================')
                print('CONNECTION ERROR')
                print(last_error)
                print(str(e))
                print('==================================================')

                _logger.error(last_error)

            except requests.exceptions.Timeout as e:

                last_error = 'Koneksi timeout. Periksa URL server.'

                print('==================================================')
                print('TIMEOUT ERROR')
                print(last_error)
                print(str(e))
                print('==================================================')

                _logger.error(last_error)

            except Exception as e:

                last_error = str(e)

                print('==================================================')
                print('UNKNOWN LOGIN ERROR')
                print(last_error)
                print('==================================================')

                _logger.exception(e)

            # ==============================================
            # RETRY
            # ==============================================
            if attempt < max_retry:

                print('==================================================')
                print(
                    f'LOGIN GAGAL - RETRY LAGI DALAM '
                    f'{retry_delay} DETIK'
                )
                print(f'NEXT ATTEMPT : {attempt + 1}')
                print('==================================================')

                _logger.warning(
                    'LOGIN FAILED - RETRY IN %s SECONDS '
                    '(attempt %s/%s)',
                    retry_delay,
                    attempt,
                    max_retry
                )

                time.sleep(retry_delay)

        # ==================================================
        # FINAL FAILED
        # ==================================================
        print('==================================================')
        print('SEMUA LOGIN RETRY GAGAL')
        print(f'LAST ERROR : {last_error}')
        print('==================================================')

        _logger.error(
            'ALL LOGIN RETRY FAILED: %s',
            last_error
        )

        raise UserError(last_error)

    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass

    def fetch_stock_item_data(self, limit=50, offset=0):
        """
        Fetch data Stock Item dengan:
        - limit  = jumlah data per request
        - offset  = titik awal data
        - target_total = total data yang ingin diambil (None = ambil semua)
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/StockItem"

            all_results = []
            params = {"$top": limit, "$skip": offset}

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Stock Item '
                    f'(HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()

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
                all_results.append({
                    'external_id':            item.get("id", "") or "",
                    'row_number':             item.get("rowNumber", 0),
                    'inventory_id':           val(item, "InventoryID"),
                    'description':            val(item, "Description"),
                    'item_type':              val(item, "ItemType"),
                    'item_class':             val(item, "ItemClass"),
                    'item_status':            val(item, "ItemStatus"),
                    'base_uom':               val(item, "BaseUOM"),
                    'valuation_method':       val(item, "ValuationMethod"),
                    'last_modified_datetime': val(item, "LastModifiedDateTime"),
                })

            _logger.info("TOTAL STOCK ITEM TERAMBIL: %d", len(all_results))

            return all_results

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()