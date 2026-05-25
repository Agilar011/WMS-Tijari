from odoo import models, fields
from odoo.exceptions import UserError
import logging
import time

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
        for i in range(loop_count):
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
