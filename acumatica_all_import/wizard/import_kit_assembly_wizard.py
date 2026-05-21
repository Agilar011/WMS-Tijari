from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportKitAssemblyWizard(models.TransientModel):
    _name        = 'import.kit.assembly.wizard'
    _description = 'Wizard Import Kit Assembly dari Acumatica'

    # =========================
    # INPUT
    # =========================
    config_id = fields.Many2one(
        'acumatica.kit.assembly.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )

    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=5000)
    batch_size = fields.Integer(string='Batch Size untuk Fetch', default=100)

    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0)

    total_target = fields.Integer(
        string='Total Data Diambil',
        help='Kosongkan untuk ambil semua data'
    )

    # =========================
    # STATE
    # =========================
    state = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    # =========================
    # SUMMARY
    # =========================
    total_fetched  = fields.Integer(string='Total Data Ditarik', readonly=True)
    total_new      = fields.Integer(string='Item Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    # =========================
    # FETCH
    # =========================
    def action_fetch_data(self):
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # cleanup staging
        self.env['acumatica.kit.assembly.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # =========================
        # FETCH (AUTO LOOP)
        # =========================
        import math

        effective_total = self.total_target or self.fetch_limit
        if effective_total <= 0:
            raise UserError('Maks Data Ditarik harus lebih besar dari 0.')
        if self.batch_size <= 0:
            raise UserError('Batch Size untuk Fetch harus lebih besar dari 0.')

        raw_list = []
        loop_count = math.ceil(effective_total / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.config_id.fetch_kit_assembly_data(
                limit=self.batch_size,
                offset=offset,
            )
            if not batch_data:
                break
            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Bom = self.env['mrp.bom']

        new_count = existing_count = 0
        lines_to_create = []

        for item in raw_list:
            reference_nbr = item.get('reference_nbr') or ''
            existing_bom = Bom.browse()
            if reference_nbr:
                existing_bom = Bom.search([('code', '=', reference_nbr)], limit=1)

            if existing_bom:
                existing_count += 1
                msg = f'Sudah ada → akan diupdate: {existing_bom.display_name}'
            else:
                new_count += 1
                msg = ''

            lines_to_create.append({
                'config_id': self.config_id.id,

                # Header fields
                'row_number': item.get('row_number') or 0,
                'external_id': item.get('external_id') or '',
                'inventory_id': item.get('inventory_id') or '',
                'description': item.get('description') or '',
                'last_modified_datetime': item.get('last_modified_datetime') or '',
                'location': item.get('location') or '',
                'post_period': item.get('post_period') or '',
                'quantity': item.get('quantity') or '',
                'reason_code': item.get('reason_code') or '',
                'reference_nbr': reference_nbr,
                'requested_on': item.get('requested_on') or '',
                'revision': item.get('revision') or '',
                'status': item.get('status') or '',
                'type': item.get('type') or '',
                'uom': item.get('uom') or '',
                'warehouse': item.get('warehouse') or '',

                # Line fields
                'line_external_id': item.get('line_external_id') or '',
                'line_note': item.get('line_note') or '',
                'line_inventory_id': item.get('line_inventory_id') or '',
                'line_component_qty': item.get('line_component_qty') or '',
                'line_nbr': item.get('line_nbr') or '',
                'line_location_id': item.get('line_location_id') or '',
                'line_quantity': item.get('line_quantity') or '',
                'line_reason_code': item.get('line_reason_code') or '',
                'stock_inventory_id': item.get('stock_inventory_id') or '',
                'line_uom': item.get('line_uom') or '',

                # Import flags
                'import_state': 'pending',
                'import_message': msg,
                'odoo_bom_id': existing_bom.id if existing_bom else False,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })

        self.env['acumatica.kit.assembly.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.kit.assembly.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    # =========================
    # VIEW STAGING
    # =========================
    def action_view_staging(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Data Kit Assembly dari Acumatica',
            'res_model': 'acumatica.kit.assembly.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
            'context':   {'default_config_id': self.config_id.id},
        }

    # =========================
    # IMPORT
    # =========================
    def action_import_all_pending(self):
        self.ensure_one()

        Line = self.env['acumatica.kit.assembly.line']

        domain = [
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ]

        total = Line.search_count(domain)

        if not total:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')

        _logger.info("IMPORT ALL START: total=%s", total)

        batch_size = 1000
        processed = 0

        while True:
            lines = Line.search(domain, limit=batch_size)

            if not lines:
                break

            _logger.info(
                "PROCESSING BATCH: %s records (processed=%s/%s)",
                len(lines), processed, total
            )

            # Import batch
            lines._do_import()

            # Commit biar tidak numpuk di memory & tidak freeze
            self.env.cr.commit()

            processed += len(lines)

            _logger.info(
                "BATCH DONE: processed=%s/%s",
                processed, total
            )

        _logger.info("IMPORT ALL DONE: total processed=%s", processed)

        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import Kit Assembly',
            'res_model': 'acumatica.kit.assembly.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
        
    def action_import_batch(self):
        self.ensure_one()
        Line = self.env['acumatica.kit.assembly.line']

        domain = [
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ]

        lines = Line.search(domain, limit=1000)
        if not lines:
            raise UserError('Tidak ada data pending untuk diimport.')

        lines._do_import()
        self.env.cr.commit()

        remaining = Line.search_count(domain)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Batch Import Selesai',
                'message': f'{len(lines)} data diproses. Sisa pending: {remaining}',
                'type': 'success',
                'sticky': False,
            },
        }
