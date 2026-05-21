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
        'acumatica.shipvia.config',
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
    total_fetched  = fields.Integer(string='Total Data Ditarik',       readonly=True)
    total_new      = fields.Integer(string='ShipVia Baru',              readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip      = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    # ─── Step 1: Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama dari config ini
        self.env['acumatica.shipvia.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # Teruskan parameter limit dan skip ke fungsi fetch
        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.config_id.fetch_shipvia_data(
                limit=self.batch_size,
                offset=offset,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)


        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        new_count = existing_count = 0
        lines_to_create = []

        for item in raw_list:
            # UUID-first lookup
            Partner  = self.env['res.partner']
            existing = Partner.browse()
            if item['external_id']:
                existing = Partner.search([
                    ('adt_external_id', '=', item['external_id'])
                ], limit=1)
            if not existing and item['carrier_id']:
                existing = Partner.search([
                    ('company_registry', '=', item['carrier_id'])
                ], limit=1)

            if existing:
                existing_count += 1
                msg = f'Sudah ada → akan diupdate: {existing.name}'
            else:
                new_count += 1
                msg = ''

            lines_to_create.append({
                'config_id':               self.config_id.id,
                'external_id':             item['external_id'],
                'note':                    item['note'],
                'address':                 item['address'],
                'carrier_id':              item['carrier_id'], 
                'city':                    item['city'],
                'description':             item['description'],
                'note_id':                 item['note_id'],
                'phone':                   item['phone'],
                'import_state':            'pending',
                'import_message':          msg,
                'odoo_partner_id':         existing.id if existing else False,
                'selected':                True,
                'sync_date':               fields.Datetime.now(),
            })

        self.env['acumatica.shipvia.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

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
            ('selected',     '=', True),
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
