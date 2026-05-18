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
    _name        = 'import.vendor.wizard'
    _description = 'Wizard Import Vendor dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.vendor.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=50,
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
    total_fetched  = fields.Integer(string='Total Data Ditarik',       readonly=True)
    total_new      = fields.Integer(string='Vendor Baru',              readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    # ─── Step 1: Tarik Data ──────────────────────────
    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama dari config ini
        self.env['acumatica.vendor.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # Teruskan parameter limit dan skip ke fungsi fetch
        raw_list = self.config_id.fetch_vendor_data(
            limit=self.fetch_limit, 
            skip=self.fetch_skip
        )

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
            if not existing and item['vendor_id']:
                existing = Partner.search([
                    ('company_registry', '=', item['vendor_id'])
                ], limit=1)

            if existing:
                existing_count += 1
                msg = f'Sudah ada → akan diupdate: {existing.name}'
            else:
                new_count += 1
                msg = ''

            lines_to_create.append({
                'config_id':               self.config_id.id,
                'row_number':              item['row_number'],
                'external_id':             item['external_id'],
                'vendor_id':               item['vendor_id'],
                'vendor_name':             item['vendor_name'],
                'location_name':           item['location_name'],
                'status':                  item['status'],
                'lead_time_days':          item['lead_time_days'],
                'fob_point':               item['fob_point'],
                'last_modified_date_time': item['last_modified_date_time'],
                'note':                    item['note'],
                'vendor_class':            item['vendor_class'],
                'import_state':            'pending',
                'import_message':          msg,
                'odoo_partner_id':         existing.id if existing else False,
                'selected':                True,
                'sync_date':               fields.Datetime.now(),
            })

        self.env['acumatica.vendor.line'].create(lines_to_create)

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
