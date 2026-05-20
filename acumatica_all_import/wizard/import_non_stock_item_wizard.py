from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportNonStockItemWizard(models.TransientModel):
    _name        = 'import.non.stock.item.wizard'
    _description = 'Wizard Import Non-Stock Item dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.non.stock.item.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    state       = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    total_fetched  = fields.Integer(string='Total Data Ditarik',        readonly=True)
    total_new      = fields.Integer(string='Item Baru',                 readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        self.env['acumatica.non.stock.item.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        for i in range(loop_count):
            offset = i * self.batch_size
            batch_data = self.config_id.fetch_non_stock_item_data(limit=self.batch_size, offset=offset)
            if not batch_data:
                break
            raw_list.extend(batch_data)
        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        new_count = existing_count = 0
        lines_to_create = []
        Product = self.env['product.template']

        for item in raw_list:
            existing = Product.browse()
            if item['external_id']:
                existing = Product.search([
                    ('adt_external_id', '=', item['external_id'])
                ], limit=1)
            if not existing and item['inventory_id']:
                existing = Product.search([
                    ('default_code', '=', item['inventory_id'])
                ], limit=1)

            if existing:
                existing_count += 1
                msg = f'Sudah ada → akan diupdate: {existing.name}'
            else:
                new_count += 1
                msg = ''

            lines_to_create.append({
                'config_id':             self.config_id.id,
                'row_number':            item['row_number'],
                'external_id':           item['external_id'],
                'inventory_id':          item['inventory_id'],
                'description':           item['description'],
                'item_type':             item['item_type'],
                'item_class':            item['item_class'],
                'item_status':           item['item_status'],
                'base_unit':             item['base_unit'],
                'purchase_unit':         item['purchase_unit'],
                'sales_unit':            item['sales_unit'],
                'is_a_kit':              item['is_a_kit'],
                'is_kit':                item['is_kit'],
                'note_id':               item['note_id'],
                'posting_class':         item['posting_class'],
                'note':                  item['note'],
                'last_modified_datetime': item['last_modified_datetime'],
                'price_class':           item['price_class'],
                'volume':                item['volume'],
                'volume_uom':            item['volume_uom'],
                'weight':                item['weight'],
                'weight_uom':            item['weight_uom'],
                'import_state':          'pending',
                'import_message':        msg,
                'odoo_product_id':       existing.id if existing else False,
                'selected':              True,
                'sync_date':             fields.Datetime.now(),
            })

        self.env['acumatica.non.stock.item.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.non.stock.item.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Data Non-Stock Item dari Acumatica',
            'res_model': 'acumatica.non.stock.item.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
            'context':   {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.non.stock.item.line'].search([
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
            'name':      'Hasil Import Non-Stock Item',
            'res_model': 'acumatica.non.stock.item.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
        }
