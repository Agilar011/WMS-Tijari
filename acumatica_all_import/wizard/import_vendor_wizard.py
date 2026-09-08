from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportVendorWizard(models.TransientModel):
    """
    Wizard 2-step import Vendor dari Acumatica:
      Step 1. Pilih config, limit & skip → Tarik Data (fetch ke staging)
      Step 2. Preview ringkasan → Import Semua atau Lihat & Pilih manual
    """
    _name = 'import.vendor.wizard'
    _description = 'Wizard Import Vendor dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=50,
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

    # ─── Step 1: Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_vendor_data(limit=self.batch_size, skip=offset)
            if not batch_data:
                break
            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.vendor.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    def _get_vendor_odata_filters(self):
        self.ensure_one()
        params = []
        if self.start_date and self.end_date:
            params.append(f"LastModifiedDateTime ge datetimeoffset'{self.start_date}' and LastModifiedDateTime le datetimeoffset'{self.end_date}'")
        return params

    def fetch_all_vendor_data(self, batch_size=False):
        """
        Ambil semua data Vendor dari Acumatica dengan paging $skip.

        Dipakai untuk scheduler/server-side agar tidak dibatasi fetch_limit
        milik wizard manual.
        """
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        fetch_size = batch_size or self.batch_size or 50
        if fetch_size <= 0:
            raise UserError('Batch size harus lebih besar dari 0.')

        raw_count = 0
        batch_count = 0
        params = self._get_vendor_odata_filters()

        _logger.info(
            "START FETCH ALL VENDOR; CONFIG=%s, BATCH_SIZE=%s, FETCH_SKIP=%s, FILTERS=%s",
            self.config_id.display_name,
            fetch_size,
            self.fetch_skip,
            params or '-',
        )

        while True:
            offset = self.fetch_skip + (batch_count * fetch_size)
            batch_data = self.fetch_vendor_data(
                limit=fetch_size,
                skip=offset,
                odata_filter=params if params else False,
            )
            if not batch_data:
                _logger.info(
                    "STOP FETCH ALL VENDOR; empty batch at OFFSET=%s, TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
                    offset,
                    raw_count,
                    batch_count,
                )
                break

            fetched_count = len(batch_data)
            raw_count += fetched_count
            batch_count += 1
            _logger.info(
                "FETCH ALL VENDOR BATCH DONE; BATCH=%s, OFFSET=%s, FETCHED=%s, RUNNING_TOTAL=%s",
                batch_count,
                offset,
                fetched_count,
                raw_count,
            )

        self.write({
            'total_fetched': raw_count,
            'state': 'fetched' if raw_count else 'draft',
        })
        _logger.info(
            "FINISH FETCH ALL VENDOR; TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
            raw_count,
            batch_count,
        )
        return raw_count

    def action_fetch_all_data(self):
        self.ensure_one()
        raw_count = self.fetch_all_vendor_data()
        if not raw_count:
            raise UserError('Tidak ada data dari API')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.vendor.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _check_last_modified_staging(self, item):
        Staging = self.env['acumatica.vendor.line']
        existing = Staging.search([
            ('vendor_id', '=', item['vendor_id']),
            ('last_modified_datetime', '!=', item['last_modified_datetime']),
        ])
        if existing:
            item['import_state'] = 'staged'
            existing.write(item)

    def fetch_vendor_data(self, limit=50, skip=0, odata_filter=False):
        """
        Ambil data Vendor dari Acumatica API.
        Endpoint: GET /Vendor?$top={limit}&$skip={skip}

        Field yang diambil (sesuai mapping):
          note                  → internal_notes
          FOBPoint              → adt_fob_point
          LastModifiedDateTime  → last_modified_datetime
          LeadTimedays          → sale_delay
          LocationName          → name
          Status                → adt_state
          VendorClass           → adt_class
          VendorID              → company_registry
          VendorName            → complete_name / name

        Return: list of dict
        """
        self.ensure_one()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            
            # Menambahkan $top dan $skip untuk pagination
            params = {
                "$top": limit,
                "$skip": skip,
            }
            if odata_filter:
                params['$filter'] = ' and '.join(odata_filter)

            
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
                    'b_account_id':           val(item,  "BAccountID"),
                    'fob_point':               val(item,  "FOBPoint"),
                    'last_modified_datetime': val(item,  "LastModifiedDateTime"),
                    'lead_time_days':          ival(item, "LeadTimedays"),
                    'location_name':           val(item,  "LocationName"),
                    'status':                  val(item,  "Status"),
                    'vendor_id':               val(item,  "VendorID"),
                    'vendor_name':             val(item,  "VendorName"),
                    # Optional
                    'vendor_class':            val(item,  "VendorClass"),
                })

            Partner = self.env['res.partner']
            Staging = self.env['acumatica.vendor.line']

            query = """
                INSERT INTO acumatica_vendor_line
                (
                    config_id,
                    external_id,
                    row_number,
                    note,
                    account_ref,
                    b_account_id,
                    fob_point,
                    last_modified_datetime,
                    lead_time_days,
                    location_name,
                    status,
                    vendor_id,
                    vendor_name,
                    import_state,
                    import_message,
                    odoo_partner_id,
                    selected,
                    sync_date
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """

            staging_by_vendor = {
                p.vendor_id: p.id
                for p in Staging.search([
                    ('vendor_id', '!=', False)
                ])
            }

            partner_by_vendor = {
                p.adt_vendor_id: p.id
                for p in Partner.search([
                    ('adt_vendor_id', '!=', False)
                ])
            }

            params_list = []
            for item in result:
                existing_staging = False
                if item['vendor_id']:
                    existing_staging = staging_by_vendor.get(item['vendor_id'])

                if existing_staging:
                    self._check_last_modified_staging(item)
                    continue

                existing_partner = False
                if existing_staging:
                    existing_partner = partner_by_vendor.get(item['vendor_id'])

                msg = 'Data sudah ada' if existing_partner else ''
                state = 'staged'

                params_list.append((
                    self.config_id.id,
                    item['external_id'],
                    item['row_number'],
                    item['note'],
                    item['account_ref'],
                    item['b_account_id'],
                    item['fob_point'],
                    item['last_modified_datetime'],
                    item['lead_time_days'],
                    item['location_name'],
                    item['status'],
                    item['vendor_id'],
                    item['vendor_name'],
                    state,
                    msg,
                    existing_partner or None,
                    True,
                    fields.Datetime.now(),
                ))

            self.env.cr.executemany(query, params_list)
            print(self.env.cr.rowcount)
            return result

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Data Vendor dari Acumatica',
            'res_model': 'acumatica.vendor.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
            'context':   {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.vendor.line'].search([
            ('config_id',    '=', self.config_id.id),
            ('import_state', '=', 'staged'),
            ('selected',     '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        lines._do_import()
        self.state = 'done'

        return {
            'type':      'ir.actions.act_window',
            'name':      'Hasil Import Vendor',
            'res_model': 'acumatica.vendor.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
        }
