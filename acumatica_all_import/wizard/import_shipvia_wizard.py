from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportShipviaWizard(models.TransientModel):
    """
    Wizard 2-step import ShipVia dari Acumatica:
      Step 1. Pilih config, limit & skip → Tarik Data (fetch ke staging)
      Step 2. Preview ringkasan → Import Semua atau Lihat & Pilih manual
    """
    _name        = 'import.shipvia.wizard'
    _description = 'Wizard Import ShipVia dari Acumatica'

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
    state = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    # Summary setelah fetch
    total_fetched  = fields.Integer(string='Total Data Ditarik', readonly=True)
    total_new      = fields.Integer(string='ShipVia Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip      = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    # ─── Step 1: Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama dari config ini
        # self.env['acumatica.shipvia.line'].search([
        #     ('config_id', '=', self.config_id.id)
        # ]).unlink()

        # Teruskan parameter limit dan skip ke fungsi fetch
        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_shipvia_data(
                limit=self.batch_size,
                offset=offset,
            )

            if not batch_data:
                break

            raw_list += batch_data

        self.total_fetched = raw_list

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.shipvia.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    # ─── Step 2a: Buka List Staging ──────────────────
    def action_view_staging(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Data ShipVia dari Acumatica',
            'res_model': 'acumatica.shipvia.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
            'context':   {'default_config_id': self.config_id.id},
        }

    # ─── Step 2b: Import Semua Pending ───────────────
    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.shipvia.line'].search([
            ('config_id',    '=', self.config_id.id),
            ('import_state', '=', 'pending'),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        lines._do_import()
        self.state = 'done'

        return {
            'type':      'ir.actions.act_window',
            'name':      'Hasil Import ShipVia',
            'res_model': 'acumatica.shipvia.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
        }

    def fetch_shipvia_data(self, limit=50, offset=0):
        """
        Ambil data ShipVia dari Acumatica API.
        Endpoint: GET /ShipVia?$top={limit}&$skip={skip}

        Field yang diambil (sesuai mapping):
          note                  → internal_notes
          Address               → street
          CarrierID             → carrier_code
          City                  → city
          Description           → name
          NoteID                → note_id
          phone                 → phone

        Return: list of dict
        """
        self.ensure_one()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            
            # Menambahkan $top dan $skip untuk pagination
            params = {
                "$top": limit,
                "$skip": offset
            }
            
            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data ShipVia (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info(
                "Berhasil ambil %d records ShipVia (Skip: %d) dari Acumatica", 
                len(raw_data), offset
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
            for row_number, item in enumerate(raw_data, start=1):
                result.append({
                    'external_id': item.get("id", "") or "",
                    'row_number': item.get("rowNumber", row_number) or row_number,
                    'note': item.get("note", {}).get("value", "") or "",
                    'address': val(item, "Address"),
                    'carrier_id': val(item, "CarrierID"),
                    'city': val(item, "City"),
                    'description': val(item, "Description"),
                    'note_id': val(item, "NoteID"),
                    'phone': val(item, "Phone"),
                })
            Partner = self.env['res.partner']
            Staging = self.env['acumatica.shipvia.line']
            new_count = existing_count = 0

            query = """
                INSERT INTO acumatica_shipvia_line
                (
                    config_id,
                    row_number,
                    external_id,
                    note,
                    address,
                    carrier_id,
                    city,
                    description,
                    note_id,
                    phone,
                    import_state,
                    import_message,
                    odoo_partner_id,
                    sync_date
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
            """

            for item in result:
                staging_domain = []
                if item['external_id'] and item['carrier_id']:
                    staging_domain = ['|', ('external_id', '=', item['external_id']), ('carrier_id', '=', item['carrier_id'])]
                elif item['external_id']:
                    staging_domain = [('external_id', '=', item['external_id'])]
                elif item['carrier_id']:
                    staging_domain = [('carrier_id', '=', item['carrier_id'])]

                if staging_domain and Staging.search(staging_domain, limit=1):
                    continue

                existing = False
                if item['carrier_id']:
                    existing = Partner.search([
                        ('company_registry', '=', item['carrier_id'])
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
                    item['note'],
                    item['address'],
                    item['carrier_id'],
                    item['city'],
                    item['description'],
                    item['note_id'],
                    item['phone'],
                    'pending',
                    msg,
                    existing.id if existing else None,
                    fields.Datetime.now()
                )

                self.env.cr.execute(query, params)
                self.env['acumatica.shipvia.line']._invalidate_cache()

            return len(result)


        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()
