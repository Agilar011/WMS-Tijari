from odoo import models, fields
from odoo.exceptions import UserError
import logging
import time
from datetime import datetime, time

_logger = logging.getLogger(__name__)


class ImportCustomerWizard(models.TransientModel):
    """
    Wizard 3-step import Customer dari Acumatica:
      1. Pilih config, limit & skip → Tarik Data
      2. Preview ringkasan (baru vs sudah ada)
      3. Import semua pending / atau lihat & pilih manual
    """
    _name = 'import.customer.wizard'
    _description = 'Wizard Import Customer dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.customer.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=50,
        help='Sesuai spesifikasi: default 50 data customer',
    )
    batch_size = fields.Integer(
        string='Batch Size untuk Import',
        default=20,
        help='Jumlah record yang diproses per batch saat import. Sesuaikan dengan performa server dan jumlah data. Default 20.',
    )
    # Tambahkan field skip agar user bisa memasukkan loncatan data
    fetch_skip = fields.Integer(
        string='Skip Data (Offset)',
        default=0,
        help='Jumlah data yang dilewati sebelum menarik data baru',
    )
    skip_size = fields.Integer(string='Skip Size ', default=0, required=True, help='Jumlah data yang dilewati sebelum memulai import.')

    state = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    # Summary setelah fetch
    total_fetched  = fields.Integer(string='Total Data Ditarik', readonly=True)
    total_new      = fields.Integer(string='Customer Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')


    # ─── Step 1: Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama dari config ini
        self.env['acumatica.customer.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        params = []
        if self.start_date and self.end_date:
            params.append(f"LastModifiedDateTime ge datetimeoffset'{self.start_date}' and LastModifiedDateTime le datetimeoffset'{self.end_date}'")

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.config_id.fetch_customer_data(limit=self.batch_size, skip=offset, odata_filter=params if params else False)
            if not batch_data:
                break
            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        new_count = existing_count = 0
        lines_to_create = []

        for item in raw_list:
            # Cek existing: cari by external_id dulu, lalu CustomerID
            Partner = self.env['res.partner']
            existing = False
            if item['external_id']:
                existing = Partner.search([
                    ('adt_external_id', '=', item['external_id'])
                ], limit=1)
            if not existing and item['customer_id']:
                existing = Partner.search([
                    ('company_registry', '=', item['customer_id'])
                ], limit=1)

            if existing:
                existing_count += 1
                state = 'pending'  # tetap pending agar bisa diupdate
                msg   = f'Sudah ada → akan diupdate: {existing.name}'
            else:
                new_count += 1
                state = 'pending'
                msg   = ''

            lines_to_create.append({
                'config_id':             self.config_id.id,
                'row_number':            item['row_number'],
                'external_id':           item['external_id'],
                'customer_id':           item['customer_id'],
                'b_account_id':          item['b_account_id'],
                'customer_name':         item['customer_name'],
                'customer_class':        item['customer_class'],
                'status':                item['status'],
                'warehouse_id':          item['warehouse_id'],
                'shipping_zone_id':      item['shipping_zone_id'],
                'fob_point':             item['fob_point'],
                'last_modified_datetime':item['last_modified_datetime'],
                'note_id':               item['note_id'],
                'note':                  item['note'],
                'location_name':         item['location_name'],
                'tax_registration_id':   item['tax_registration_id'],
                'import_state':          state,
                'import_message':        msg,
                'odoo_partner_id':       existing.id if existing else False,
                'selected':              True,
                'sync_date':             fields.Datetime.now(),
            })

        self.env['acumatica.customer.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

    def action_fetch_data_import_batch(self):
        print('ACTION: FETCH DATA + IMPORT BATCH')
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama dari config ini
        self.env['acumatica.customer.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        for i in range(loop_count):
            print(f'FETCH BATCH {i+1}/{loop_count} (limit={self.batch_size}, offset={self.fetch_skip + (i * self.batch_size)})')
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.config_id.fetch_customer_data(limit=self.batch_size, skip=offset)
            if not batch_data:
                break
            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        new_count = existing_count = 0
        lines_to_create = []

        for item in raw_list:
            # Cek existing: cari by external_id dulu, lalu CustomerID
            Partner = self.env['res.partner']
            existing = False
            if item['external_id']:
                existing = Partner.search([
                    ('adt_external_id', '=', item['external_id'])
                ], limit=1)
            if not existing and item['customer_id']:
                existing = Partner.search([
                    ('company_registry', '=', item['customer_id'])
                ], limit=1)

            if existing:
                existing_count += 1
                state = 'pending'  # tetap pending agar bisa diupdate
                msg   = f'Sudah ada → akan diupdate: {existing.name}'
            else:
                new_count += 1
                state = 'pending'
                msg   = ''

            lines_to_create.append({
                'config_id':             self.config_id.id,
                'row_number':            item['row_number'],
                'external_id':           item['external_id'],
                'customer_id':           item['customer_id'],
                'b_account_id':          item['b_account_id'],
                'customer_name':         item['customer_name'],
                'customer_class':        item['customer_class'],
                'status':                item['status'],
                'warehouse_id':          item['warehouse_id'],
                'shipping_zone_id':      item['shipping_zone_id'],
                'fob_point':             item['fob_point'],
                'last_modified_datetime':item['last_modified_datetime'],
                'note_id':               item['note_id'],
                'note':                  item['note'],
                'location_name':         item['location_name'],
                'tax_registration_id':   item['tax_registration_id'],
                'import_state':          state,
                'import_message':        msg,
                'odoo_partner_id':       existing.id if existing else False,
                'selected':              True,
                'sync_date':             fields.Datetime.now(),
            })

        self.env['acumatica.customer.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })


        lines = self.env['acumatica.customer.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        lines._do_import()
        self.state = 'done'



        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.customer.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ─── Step 2: Buka List Staging ───────────────────
    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Customer dari Acumatica',
            'res_model': 'acumatica.customer.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    # ─── Step 3: Import Semua Pending ────────────────
    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.customer.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        lines._do_import()
        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import Customer',
            'res_model': 'acumatica.customer.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }

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

