from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportWarehouseWizard(models.TransientModel):
    _name = 'import.warehouse.wizard'
    _description = 'Wizard Import Warehouse dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.warehouse.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    state       = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    total_fetched        = fields.Integer(string='Total Warehouse', readonly=True)
    total_new            = fields.Integer(string='Warehouse Baru', readonly=True)
    total_existing       = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    total_locations      = fields.Integer(string='Total Locations', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # Hapus staging lama
        old_lines = self.env['acumatica.warehouse.line'].search([
            ('config_id', '=', self.config_id.id)
        ])
        old_lines.mapped('location_line_ids').unlink()
        old_lines.unlink()

        raw_list = self.config_id.fetch_warehouse_data(limit=self.fetch_limit)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        new_count = existing_count = total_loc = 0
        WH = self.env['stock.warehouse']

        for item in raw_list:
            # Cek existing warehouse
            existing = WH.browse()
            if item['external_id']:
                existing = WH.search([('adt_external_id', '=', item['external_id'])], limit=1)
            if not existing and item['warehouse_id']:
                existing = WH.search([('code', '=', item['warehouse_id'])], limit=1)

            if existing:
                existing_count += 1
            else:
                new_count += 1

            # Buat header line
            wh_line = self.env['acumatica.warehouse.line'].create({
                'config_id':             self.config_id.id,
                'row_number':            item['row_number'],
                'external_id':           item['external_id'],
                'warehouse_id':          item['warehouse_id'],
                'description':           item['description'],
                'active':                item['active'],
                'note':                  item['note'],
                'drop_ship_location_id': item['drop_ship_location_id'],
                'last_modified_dt':      item['last_modified_dt'],
                'receiving_location_id': item['receiving_location_id'],
                'rma_location_id':       item['rma_location_id'],
                'shipping_location_id':  item['shipping_location_id'],
                'import_state':          'pending',
                'import_message':        f'Sudah ada → akan diupdate: {existing.name}' if existing else '',
                'odoo_warehouse_id':     existing.id if existing else False,
                'selected':              True,
                'sync_date':             fields.Datetime.now(),
            })

            # Buat detail location lines
            loc_vals_list = []
            for loc in item.get('locations', []):
                loc_vals_list.append({
                    'warehouse_line_id': wh_line.id,
                    'row_number':        loc['row_number'],
                    'external_id':       loc['external_id'],
                    'location_id':       loc['location_id'],
                    'description':       loc['description'],
                    'active':            loc['active'],
                    'note':              loc['note'],
                    'import_state':      'pending',
                })
                total_loc += 1

            if loc_vals_list:
                self.env['acumatica.warehouse.location.line'].create(loc_vals_list)

        self.write({
            'state':           'fetched',
            'total_fetched':   len(raw_list),
            'total_new':       new_count,
            'total_existing':  existing_count,
            'total_locations': total_loc,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.warehouse.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Warehouse dari Acumatica',
            'res_model': 'acumatica.warehouse.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.warehouse.line'].search([
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
            'name': 'Hasil Import Warehouse',
            'res_model': 'acumatica.warehouse.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
