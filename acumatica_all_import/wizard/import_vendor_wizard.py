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
    total_new = fields.Integer(string='Vendor Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    # ─── Step 1: Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama dari config ini
        # self.env['acumatica.vendor.line'].search([
        #     ('config_id', '=', self.config_id.id)
        # ]).unlink()

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

        Partner = self.env['res.partner']
        Staging = self.env['acumatica.vendor.line']

        new_count = existing_count = 0
        query = """
            INSERT INTO acumatica_vendor_line
            (
                config_id,
                row_number,
                external_id,
                vendor_id,
                vendor_name,
                location_name,
                status,
                lead_time_days,
                fob_point,
                last_modified_date_time,
                note,
                vendor_class,
                account_ref,
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

        for item in raw_list:
            staging_domain = []
            if item['external_id'] and item['vendor_id']:
                staging_domain = ['|', ('external_id', '=', item['external_id']), ('vendor_id', '=', item['vendor_id'])]
            elif item['external_id']:
                staging_domain = [('external_id', '=', item['external_id'])]
            elif item['vendor_id']:
                staging_domain = [('vendor_id', '=', item['vendor_id'])]

            if staging_domain and Staging.search(staging_domain, limit=1):
                continue

            existing = False
            if item['vendor_id']:
                existing = Partner.search([
                    ('company_registry', '=', item['vendor_id'])
                ], limit=1)

            if existing:
                existing_count += 1
                msg = 'Data sudah ada'
            else:
                new_count += 1
                msg = ''

            params = (
                self.config_id.id,
                item['row_number'],
                item['external_id'],
                item['vendor_id'],
                item['vendor_name'],
                item['location_name'],
                item['status'],
                item['lead_time_days'],
                item['fob_point'],
                item['last_modified_date_time'],
                item['note'],
                item['vendor_class'],
                item['account_ref'],
                'pending',
                msg,
                existing.id if existing else None,
                True,
                fields.Datetime.now(),
            )
            self.env.cr.execute(query, params)

        self.env['acumatica.vendor.line']._invalidate_cache()

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.vendor.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

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
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            
            # Menambahkan $top dan $skip untuk pagination
            params = {
                "$top": limit,
                "$skip": skip,
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
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    # ─── Step 2a: Buka List Staging ──────────────────
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

    # ─── Step 2b: Import Semua Pending ───────────────
    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.vendor.line'].search([
            ('config_id',    '=', self.config_id.id),
            ('import_state', '=', 'pending'),
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
