from odoo import models, fields
from odoo.exceptions import UserError
import logging
import time
from datetime import datetime
import requests

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
        'acumatica.config',
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

    state = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    # Summary setelah fetch
    total_fetched = fields.Integer(string='Total Data Ditarik', readonly=True)

    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')


    # ───  Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        import math

        raw_count = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        params = []
        if self.start_date and self.end_date:
            params.append(f"LastModifiedDateTime ge datetimeoffset'{self.start_date}' and LastModifiedDateTime le datetimeoffset'{self.end_date}'")

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_customer_data(limit=self.batch_size, skip=offset, odata_filter=params if params else False)
            if not batch_data:
                break

            raw_count += batch_data

        self.total_fetched = raw_count
        if not raw_count:
            raise UserError('Tidak ada data dari API')

    # ────── Buka List Staging ───────────────────
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

    # ─── Import Semua Pending ────────────────────────
    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.customer.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
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

    def _check_last_modified_staging(self, item):
        Staging = self.env['acumatica.customer.line']
        existing = Staging.search([
            ('b_account_id', '=', item['b_account_id']),
            ('customer_id', '=', item['customer_id']),
            ('last_modified_datetime', '!=', item['last_modified_datetime']),
        ])
        if existing:
            item['import_state'] = 'pending'
            existing.write(item)

    def fetch_customer_data(self, limit=50, skip=0, odata_filter=False):
        """
        Ambil data Customer dari Acumatica API.
        Endpoint: /Customer?$top={limit}&$skip={skip}
        Return: list of dict sesuai mapping
        """

        self.ensure_one()

        session = self.config_id._do_login()
        max_retry = 3
        retry_delay = 30
        last_error = None
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            # ==============================================
            # PARAMS
            # ==============================================
            params = {
                "$top": limit,
                "$skip": skip
            }
            if odata_filter:
                params['$filter'] = ' and '.join(odata_filter)

            _logger.info(
                "START FETCH CUSTOMER; " \
                "ENDPOINT %s, LIMIT %d, SKIP %d, PARAMS %s",
                endpoint,
                limit,
                skip,
                params
            )
            # ==============================================
            # RETRY LOOP
            # ==============================================
            for attempt in range(1, max_retry + 1):
                try:
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

                    _logger.info(
                        'API RESPONSE; ' \
                        'STATUS CODE %s, REQUEST URL %s',
                        response.status_code,
                        response.url,
                    )

                    if response.status_code != 200:

                        last_error = (
                            f'Gagal ambil data Customer '
                            f'(HTTP {response.status_code}): '
                            f'{response.text}'
                        )

                        _logger.error(last_error)

                        raise Exception(last_error)

                    # ==========================================
                    # SUCCESS
                    # ==========================================
                    raw_data = response.json()

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

                        _logger.info(
                            'PARSE CUSTOMER #%s; ' \
                            'CUSTOMER ID : %s; ' \
                            'CUSTOMER NAME : %s; ' \
                            'STATUS : %s; ' \
                            'WAREHOUSE : %s; ' \
                            'TAX ID : %s; ',
                            index,
                            vals["customer_id"],
                            vals["customer_name"],
                            vals["status"],
                            vals["warehouse_id"],
                            vals["tax_registration_id"]
                        )

                        result.append(vals)

                    _logger.info(
                        'API RESPONSE' \
                        'TOTAL PARSED CUSTOMER %s',
                        len(result)
                    )


                    # bikin sql script buat create acumatica.customer.line
                    Partner = self.env['res.partner']
                    Staging = self.env['acumatica.customer.line']
                    query = """
                        INSERT INTO acumatica_customer_line
                        (
                            config_id,
                            row_number,
                            external_id,
                            customer_id,
                            b_account_id,
                            customer_name,
                            status,
                            warehouse_id,
                            shipping_zone_id,
                            fob_point,
                            customer_class,
                            tax_registration_id,
                            last_modified_datetime,
                            note_id,
                            note,
                            location_name,
                            import_state,
                            import_message,
                            odoo_partner_id,
                            sync_date
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """
                    partner_by_baccount = {
                        p.adt_b_account_id: p.id
                        for p in Partner.search([
                            ('adt_b_account_id', '!=', False)
                        ])
                    }

                    partner_by_customer = {
                        p.company_registry: p.id
                        for p in Partner.search([
                            ('company_registry', '!=', False)
                        ])
                    }
                    staging_by_baccount = {
                        p.b_account_id: p.id
                        for p in Staging.search([
                            ('b_account_id', '!=', False)
                        ])
                    }

                    staging_by_customer = {
                        p.customer_id: p.id
                        for p in Staging.search([
                            ('customer_id', '!=', False)
                        ])
                    }
                    params_list = []
                    for item in result:
                        existing_staging = False
                        if item['b_account_id']:
                            existing_staging = staging_by_baccount.get(item['b_account_id'])

                        elif item['customer_id']:
                            existing_staging = staging_by_customer.get(item['customer_id'])

                        if existing_staging:
                            self._check_last_modified_staging(item)
                            continue

                        existing_partner = False
                        if existing_staging:
                            existing_partner = partner_by_baccount.get(item['b_account_id'])

                        if not existing_partner and existing_staging:
                            existing_partner = partner_by_customer.get(item['customer_id'])

                        msg = 'Data sudah ada' if existing_partner else ''
                        state = 'pending'

                        params_list.append((
                            self.config_id.id,
                            item['row_number'],
                            item['external_id'],
                            item['customer_id'],
                            item['b_account_id'],
                            item['customer_name'],
                            item['status'],
                            item['warehouse_id'],
                            item['shipping_zone_id'],
                            item['fob_point'],
                            item['customer_class'],
                            item['tax_registration_id'],
                            item['last_modified_datetime'],
                            item['note_id'],
                            item['note'],
                            item['location_name'],
                            state,
                            msg,
                            existing_partner or None,
                            fields.Datetime.now(),
                        ))

                    self.env.cr.executemany(query, params_list)
                    return len(result)
                # ==============================================
                # CONNECTION ERROR
                # ==============================================
                except requests.exceptions.ConnectionError as e:

                    last_error = (
                        f'Tidak bisa terhubung ke server: '
                        f'{self.config_id.base_url}'
                    )

                    _logger.info(
                        'CONNECTION ERROR; ' \
                        '%s',
                        '%s',
                        last_error,
                        str(e)
                    )

                    _logger.error(last_error)

                # ==============================================
                # TIMEOUT ERROR
                # ==============================================
                except requests.exceptions.Timeout as e:

                    last_error = (
                        'Timeout saat ambil data Customer '
                        'dari Acumatica.'
                    )

                    _logger.info(
                        'TIMEOUT ERROR' \
                        '%s',
                        '%s',
                        last_error,
                        str(e)
                    )

                    _logger.error(last_error)

                # ==============================================
                # UNKNOWN ERROR
                # ==============================================
                except Exception as e:

                    last_error = str(e)

                    _logger.info(
                        'UNKNOWN FETCH ERROR' \
                        '%s',
                        last_error,
                    )

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

            self.config_id._do_logout(session)

            self.config_id.last_sync = fields.Datetime.now()
