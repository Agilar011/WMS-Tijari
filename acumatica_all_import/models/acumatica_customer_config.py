import requests
import time

from odoo import models, fields
from odoo.exceptions import UserError

import logging
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
    api_version = fields.Char(string='API Version', required=True, default='25.200.002')
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

    # ─── Logout helper ───────────────────────────────
    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass

    # ─── Fetch Customer dari API ─────────────────────

    def fetch_customer_data(self, limit=50, skip=0, odata_filter=False):
        """
        Ambil data Customer dari Acumatica API.
        Endpoint: /Customer?$top={limit}&$skip={skip}
        Return: list of dict sesuai mapping
        """

        self.ensure_one()

        session = self._do_login()

        max_retry = 3
        retry_delay = 30

        last_error = None

        try:

            endpoint = f"{self.api_url}/Customer"

            # ==============================================
            # PARAMS
            # ==============================================
            params = {
                "$top": limit,
                "$skip": skip
            }
            if odata_filter:
                params['$filter'] = ' and '.join(odata_filter)

            print('==================================================')
            print('START FETCH CUSTOMER')
            print(f'ENDPOINT     : {endpoint}')
            print(f'LIMIT        : {limit}')
            print(f'SKIP         : {skip}')
            print(f'PARAMS       : {params}')
            print('==================================================')

            # ==============================================
            # RETRY LOOP
            # ==============================================
            for attempt in range(1, max_retry + 1):

                try:

                    print('==================================================')
                    print(
                        f'FETCH CUSTOMER ATTEMPT '
                        f'{attempt}/{max_retry}'
                    )
                    print('==================================================')

                    _logger.info(
                        'FETCH CUSTOMER ATTEMPT %s/%s | SKIP=%s | LIMIT=%s',
                        attempt,
                        max_retry,
                        skip,
                        limit
                    )

                    response = session.get(
                        endpoint,
                        params=params,
                        timeout=60
                    )

                    print('=============== API RESPONSE =====================')
                    print(f'STATUS CODE : {response.status_code}')
                    print(f'REQUEST URL : {response.url}')
                    print('==================================================')

                    if response.status_code != 200:

                        last_error = (
                            f'Gagal ambil data Customer '
                            f'(HTTP {response.status_code}): '
                            f'{response.text}'
                        )

                        print('FETCH CUSTOMER FAILED')
                        print(last_error)

                        _logger.error(last_error)

                        raise Exception(last_error)

                    # ==========================================
                    # SUCCESS
                    # ==========================================
                    raw_data = response.json()

                    print('==================================================')
                    print(
                        f'SUCCESS FETCH CUSTOMER : '
                        f'{len(raw_data)} RECORDS'
                    )
                    print(f'SKIP  : {skip}')
                    print(f'LIMIT : {limit}')
                    print('==================================================')

                    _logger.info(
                        "Berhasil ambil %d records Customer (Skip: %d) dari Acumatica",
                        len(raw_data),
                        skip
                    )

                    # ==========================================
                    # HELPER
                    # ==========================================
                    def val(item, key):
                        """
                        Helper ambil .value dari dict Acumatica,
                        return '' jika kosong/None
                        """
                        v = item.get(key, {})

                        if isinstance(v, dict):
                            return v.get("value", "") or ""

                        return ""

                    # ==========================================
                    # PARSE DATA
                    # ==========================================
                    result = []

                    for index, item in enumerate(raw_data, start=1):

                        vals = {
                            'external_id':            item.get("id", "") or "",
                            'row_number':             item.get("rowNumber", 0),

                            # Field yang diimport ke res.partner
                            'note':                   item.get("note", {}).get("value", "") or "",
                            'b_account_id':           str(val(item, "BAccountID")) if val(item, "BAccountID") else "",
                            'customer_class':         val(item, "CustomerClass"),
                            'customer_id':            val(item, "CustomerID"),
                            'customer_name':          val(item, "CustomerName"),
                            'fob_point':              val(item, "FOBPoint"),
                            'last_modified_datetime': val(item, "LastModifiedDateTime"),
                            'location_name':          val(item, "LocationName"),
                            'note_id':                val(item, "NoteID"),
                            'shipping_zone_id':       val(item, "ShippingZoneID"),
                            'status':                 val(item, "Status"),
                            'warehouse_id':           val(item, "WarehouseID"),
                            'tax_registration_id':    val(item, "TaxRegistrationID"),
                        }

                        print('--------------------------------------------------')
                        print(f'PARSE CUSTOMER #{index}')
                        print(f'CUSTOMER ID     : {vals["customer_id"]}')
                        print(f'CUSTOMER NAME   : {vals["customer_name"]}')
                        print(f'STATUS          : {vals["status"]}')
                        print(f'WAREHOUSE       : {vals["warehouse_id"]}')
                        print(f'TAX ID          : {vals["tax_registration_id"]}')
                        print('--------------------------------------------------')

                        result.append(vals)

                    print('==================================================')
                    print(f'TOTAL PARSED CUSTOMER : {len(result)}')
                    print('==================================================')

                    return result

                # ==============================================
                # CONNECTION ERROR
                # ==============================================
                except requests.exceptions.ConnectionError as e:

                    last_error = (
                        f'Tidak bisa terhubung ke server: '
                        f'{self.base_url}'
                    )

                    print('==================================================')
                    print('CONNECTION ERROR')
                    print(last_error)
                    print(str(e))
                    print('==================================================')

                    _logger.error(last_error)

                # ==============================================
                # TIMEOUT ERROR
                # ==============================================
                except requests.exceptions.Timeout as e:

                    last_error = (
                        'Timeout saat ambil data Customer '
                        'dari Acumatica.'
                    )

                    print('==================================================')
                    print('TIMEOUT ERROR')
                    print(last_error)
                    print(str(e))
                    print('==================================================')

                    _logger.error(last_error)

                # ==============================================
                # UNKNOWN ERROR
                # ==============================================
                except Exception as e:

                    last_error = str(e)

                    print('==================================================')
                    print('UNKNOWN FETCH ERROR')
                    print(last_error)
                    print('==================================================')

                    _logger.exception(e)

                # ==============================================
                # RETRY
                # ==============================================
                if attempt < max_retry:

                    print('==================================================')
                    print(
                        f'RETRY FETCH CUSTOMER '
                        f'DALAM {retry_delay} DETIK'
                    )
                    print(f'NEXT ATTEMPT : {attempt + 1}')
                    print('==================================================')

                    _logger.warning(
                        'FETCH CUSTOMER FAILED - RETRY IN %s SECONDS '
                        '(attempt %s/%s)',
                        retry_delay,
                        attempt,
                        max_retry
                    )

                    time.sleep(retry_delay)

            # ==============================================
            # FINAL FAILED
            # ==============================================
            print('==================================================')
            print('SEMUA FETCH CUSTOMER RETRY GAGAL')
            print(f'LAST ERROR : {last_error}')
            print('==================================================')

            _logger.error(
                'ALL FETCH CUSTOMER RETRY FAILED: %s',
                last_error
            )

            raise UserError(last_error)

        finally:

            print('==================================================')
            print('LOGOUT SESSION ACUMATICA')
            print('==================================================')

            self._do_logout(session)

            self.last_sync = fields.Datetime.now()
