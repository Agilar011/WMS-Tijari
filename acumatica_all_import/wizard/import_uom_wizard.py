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
        self.env['acumatica.uom.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / 200) if self.fetch_limit else 0
        for i in range(loop_count):
            offset = i * 200
            batch_data = self.config_id.fetch_uom_data(limit=200, offset=offset)
            if not batch_data:
                break
            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        # Hitung yang sudah ada di Odoo
        new_count      = 0
        existing_count = 0

        lines_to_create = []
        for item in raw_list:
            existing = self.env['uom.uom'].search([
                ('name', '=ilike', item['description'])
            ], limit=1)

            lines_to_create.append({
                'config_id':   self.config_id.id,
                'row_number':  item['row_number'],
                'unit_id':     item['unit_id'],
                'description': item['description'],
                'external_id': item['external_id'],
                'import_state': 'skipped' if existing else 'pending',
                'import_message': f'Sudah ada: {existing.name}' if existing else '',
                'odoo_uom_id': existing.id if existing else False,
                'selected':    not bool(existing),
                'sync_date':   fields.Datetime.now(),
            })

            if existing:
                existing_count += 1
            else:
                new_count += 1

        self.env['acumatica.uom.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

        # Reload wizard (supaya user bisa lihat summary & lanjut)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.uom.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

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
                'search_default_pending': 1,
            },
        }

    # ─── Step 3: Import Semua yang Pending ───────────
    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.uom.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
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
