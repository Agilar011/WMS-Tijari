from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportUomWizard(models.TransientModel):
    """
    Wizard untuk tarik data UoM dari Acumatica,
    preview hasilnya, lalu pilih mana yang diimport.
    """
    _name = 'import.uom.wizard'
    _description = 'Wizard Import UoM dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=500,
        help='Jumlah maksimal record yang diambil dari API',
    )
    batch_size = fields.Integer(
        string='Batch Size untuk Import',
        default=20,
        help='Jumlah record yang diimport sekaligus saat proses import',
    )
    state = fields.Selection([
        ('draft',    'Siap'),
        ('fetched',  'Data Sudah Ditarik'),
        ('done',     'Selesai'),
    ], default='draft')

    # Summary setelah fetch
    total_fetched  = fields.Integer(string='Total Data', readonly=True)
    total_new      = fields.Integer(string='Data Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada di Odoo', readonly=True)
    fetch_skip      = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    # ─── Step 1: Tarik Data dari API ─────────────────
    def action_fetch_data(self):
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama (dari config ini)
        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / 200) if self.fetch_limit else 0
        for i in range(loop_count):
            offset = i * 200
            batch_data = self.fetch_uom_data(limit=200, offset=offset)
            raw_list += batch_data

        self.total_fetched = raw_list

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.uom.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def fetch_all_uom_data(self, batch_size=False):
        """
        Ambil semua data UoM dari Acumatica dengan paging $skip.

        Dipakai scheduler agar tidak dibatasi fetch_limit wizard manual.
        """
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        fetch_size = batch_size or self.batch_size or 500
        if fetch_size <= 0:
            raise UserError('Batch size harus lebih besar dari 0.')

        raw_count = 0
        batch_count = 0

        _logger.info(
            "START FETCH ALL UOM; CONFIG=%s, BATCH_SIZE=%s, FETCH_SKIP=%s",
            self.config_id.display_name,
            fetch_size,
            self.fetch_skip,
        )

        while True:
            offset = self.fetch_skip + (batch_count * fetch_size)
            batch_count_result = self.fetch_uom_data(limit=fetch_size, offset=offset)
            if not batch_count_result:
                _logger.info(
                    "STOP FETCH ALL UOM; empty batch at OFFSET=%s, TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
                    offset,
                    raw_count,
                    batch_count,
                )
                break

            raw_count += batch_count_result
            batch_count += 1
            _logger.info(
                "FETCH ALL UOM BATCH DONE; BATCH=%s, OFFSET=%s, FETCHED=%s, RUNNING_TOTAL=%s",
                batch_count,
                offset,
                batch_count_result,
                raw_count,
            )

            if batch_count_result < fetch_size:
                break

        self.write({
            'total_fetched': raw_count,
            'state': 'fetched' if raw_count else 'draft',
        })
        _logger.info("FINISH FETCH ALL UOM; TOTAL_FETCHED=%s, TOTAL_BATCHES=%s", raw_count, batch_count)
        return raw_count

    def action_fetch_all_data(self):
        self.ensure_one()
        raw_count = self.fetch_all_uom_data()
        if not raw_count:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.uom.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def fetch_uom_data(self, limit=500, offset=0):
        """
        Ambil data Units of Measure dari Acumatica API.
        Return: list of dict { unit_id, description, external_id }
        """
        self.ensure_one()
        # logout -> login -> logout
        session = self.config_id._do_login()

        try:
            endpoint_name = self.config_id.endpoint_name or 'UnitsOfMeasure'
            endpoint = f"{self.config_id.api_url}/{endpoint_name}"
            params = {"$top": limit, "$skip": offset}

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data UoM (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records UoM dari Acumatica", len(raw_data))

            result = []
            for item in raw_data:
                result.append({
                    'unit_id': item.get("UnitID", {}).get("value", "") or "",
                    'description': item.get("Description", {}).get("value", "") or "",
                    'external_id': item.get("id", "") or "",
                    'row_number': item.get("rowNumber", 0),
                    'last_modified_datetime': item.get("LastModifiedDateTime", {}).get("value", "") or "",
                })

            UomLine = self.env['acumatica.uom.line']
            seen_keys = set()
            for item in result:
                external_id = item['external_id'] or False
                unit_id = item['unit_id'] or False
                key = ('external_id', external_id) if external_id else ('unit_id', unit_id)

                # Acumatica dapat mengembalikan baris yang sama dalam satu
                # batch. Jangan memproses key yang sama dua kali.
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                # UnitID adalah business key utama untuk mendeteksi update.
                existing = UomLine.browse()
                if unit_id:
                    existing = UomLine.search([
                        ('config_id', '=', self.config_id.id),
                        ('unit_id', '=', unit_id),
                    ], limit=1)
                if not existing and external_id:
                    existing = UomLine.search([
                        ('config_id', '=', self.config_id.id),
                        ('external_id', '=', external_id),
                    ], limit=1)

                vals = {
                    'config_id': self.config_id.id,
                    'row_number': item['row_number'],
                    'external_id': external_id,
                    'unit_id': unit_id,
                    'description': item['description'],
                    'last_modified_datetime': item['last_modified_datetime'],
                    'selected': True,
                    'sync_date': fields.Datetime.now(),
                }
                if existing:
                    changed = any(existing[field] != vals[field] for field in ('unit_id', 'description', 'external_id', 'row_number', 'last_modified_datetime'))
                    existing.write(vals)
                    if changed:
                        existing.write({
                            'import_state': 'staged',
                            'import_message': False,
                        })
                else:
                    vals.update({
                        'import_state': 'staged',
                        'import_message': False,
                    })
                    UomLine.create(vals)

            return len(result)


        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    # ─── Step 2: Buka List View Staging ──────────────
    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data UoM dari Acumatica',
            'res_model': 'acumatica.uom.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {
                'default_config_id': self.config_id.id,
                'search_default_staged': 1,
            },
        }

    # ─── Step 3: Import Semua yang Pending ───────────
    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.uom.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
            ('selected', '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        result = lines._do_import()
        self.state = 'done'

        # Setelah import, buka list view staging
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import UoM',
            'res_model': 'acumatica.uom.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
