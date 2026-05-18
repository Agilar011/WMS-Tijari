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

    fetch_limit = fields.Integer(
        string='Batch Size',
        default=100
    )

    fetch_skip = fields.Integer(
        string='Mulai dari Data ke-',
        default=0
    )

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
        raw_list = self.config_id.fetch_kit_assembly_data(
            batch_size=self.fetch_limit,
            start_skip=self.fetch_skip,
            target_total=self.total_target or None
        )

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Product = self.env['product.template']

        new_count = existing_count = 0
        lines_to_create = []

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
                'config_id':              self.config_id.id,
                'row_number':             item['row_number'],
                'external_id':            item['external_id'],
                'inventory_id':           item['inventory_id'],
                'description':            item['description'],
                'item_type':              item['item_type'],
                'item_class':             item['item_class'],
                'item_status':            item['item_status'],
                'base_uom':               item['base_uom'],
                'valuation_method':       item['valuation_method'],
                'last_modified_datetime': item['last_modified_datetime'],
                'import_state':           'pending',
                'import_message':         msg,
                'odoo_product_id':        existing.id if existing else False,
                'selected':               True,
                'sync_date':              fields.Datetime.now(),
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
        _logger.info("Memulai batch import kit assembly...")

        BATCH_SIZE = 1000
        batch_
        _;logger.info("Mencari hingga %s record pending untuk diimport...", BATCH_SIZE)

        lines = self.env['acumatica.kit.assembly.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ], limit=BATCH_SIZE)

        if not lines:
            raise UserError('Tidak ada data pending untuk diimport.')
        
        _logger.info("Menemukan %s record pending untuk diimport.", len(lines))
        total_before = self.env['acumatica.kit.assembly.line'].search_count([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])

        count_to_import = round(total_before / BATCH_SIZE)

        for i in range(count_to_import + 1):
            _logger.info("Memulai batch import ke-%s dari %s...", i + 1, count_to_import + 1)
            lines._do_import()

            # 🔥 penting: commit biar tidak nge-hang
            self.env.cr.commit()

        total_after = self.env['acumatica.kit.assembly.line'].search_count([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])

        _logger.info(
            "Import batch selesai: %s -> %s",
            total_before,
            total_after
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Batch Import Selesai',
                'message': f'{len(lines)} data diproses. Sisa: {total_after}',
                'type': 'success',
                'sticky': False,
            },
        }
