from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportStockItemWizard(models.TransientModel):
    _name        = 'import.stock.item.wizard'
    _description = 'Wizard Import Stock Item dari Acumatica'

    # =========================
    # INPUT
    # =========================
    config_id = fields.Many2one(
        'acumatica.stock.item.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )

    fetch_limit = fields.Integer(
        string='Batch Size',
        default=100
    )
    batch_size = fields.Integer(
        string='Batch Size untuk Import',
        default=20
    )

    fetch_skip = fields.Integer(
        string='Mulai dari Data ke-',
        default=0
    )

    total_target = fields.Integer(
        string='Total Data Diambil',
        help='Kosongkan untuk ambil semua data'
    )
    skip_size = fields.Integer(
        string='Skip Size',
        default=0,
        help='Jumlah data yang dilewati sebelum memulai import.'
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
        print('true action_fetch_data called')
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # cleanup staging
        self.env['acumatica.stock.item.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # =========================
        # FETCH (AUTO LOOP)
        # =========================
        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = i * self.batch_size
            batch_data = self.config_id.fetch_stock_item_data(
                limit=self.batch_size,
                offset=offset,
                # skip = self.fetch_skip,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)


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

        self.env['acumatica.stock.item.line'].create(lines_to_create)

        self.write({
            'state':          'fetched',
            'total_fetched':  len(raw_list),
            'total_new':      new_count,
            'total_existing': existing_count,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.stock.item.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }
    
    # =========================
    # FETCH & Import Sekaligus (tanpa staging)
    # =========================
    def action_fetch_data_import_batch(self):
        print('==================================================')
        print('TRUE action_fetch_data_import_batch CALLED')
        print('==================================================')

        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        # ==================================================
        # CLEANUP STAGING
        # ==================================================
        print('==================================================')
        print('CLEANUP STAGING DATA')
        print(f'CONFIG ID : {self.config_id.id}')
        print('==================================================')

        old_lines = self.env['acumatica.stock.item.line'].search([
            ('config_id', '=', self.config_id.id)
        ])

        print(f'TOTAL OLD STAGING : {len(old_lines)}')

        old_lines.unlink()

        print('OLD STAGING REMOVED')

        # ==================================================
        # PREPARE
        # ==================================================
        import math

        Product = self.env['product.template']
        Line = self.env['acumatica.stock.item.line']

        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        print('==================================================')
        print('START FETCH + IMPORT PER BATCH')
        print(f'FETCH LIMIT    : {self.fetch_limit}')
        print(f'BATCH SIZE     : {self.batch_size}')
        print(f'SKIP SIZE      : {self.skip_size}')
        print(f'LOOP COUNT     : {loop_count}')
        print('==================================================')

        total_fetched = 0
        total_imported = 0
        total_new = 0
        total_existing = 0

        # ==================================================
        # LOOP FETCH
        # ==================================================
        for i in range(loop_count):

            offset = i * self.batch_size

            print('')
            print('##################################################')
            print(f'BATCH NUMBER : {i + 1}')
            print(f'OFFSET       : {offset}')
            print(f'LIMIT        : {self.batch_size}')
            print(f'SKIP SIZE    : {self.skip_size}')
            print('##################################################')

            # ==================================================
            # FETCH API
            # ==================================================
            batch_data = self.config_id.fetch_stock_item_data(
                limit=self.batch_size,
                offset=offset,
            )

            if not batch_data:
                print('NO MORE DATA FROM API')
                break

            print(f'TOTAL DATA FETCHED FROM API : {len(batch_data)}')

            total_fetched += len(batch_data)

            # ==================================================
            # PREPARE STAGING
            # ==================================================
            lines_to_create = []

            for item_index, item in enumerate(batch_data, start=1):

                # print('--------------------------------------------------')
                # print(f'PREPARE ITEM : {item_index}')
                # print(f'EXTERNAL ID  : {item["external_id"]}')
                # print(f'INVENTORY ID : {item["inventory_id"]}')
                # print(f'DESCRIPTION  : {item["description"]}')
                # print('--------------------------------------------------')

                existing = Product.browse()

                # ==========================================
                # CHECK EXISTING BY EXTERNAL ID
                # ==========================================
                if item['external_id']:

                    existing = Product.search([
                        ('adt_external_id', '=', item['external_id'])
                    ], limit=1)

                    # if existing:
                    #     print(
                    #         f'FOUND EXISTING PRODUCT BY EXTERNAL ID: '
                    #         f'{existing.id} - {existing.name}'
                    #     )

                # ==========================================
                # CHECK EXISTING BY DEFAULT CODE
                # ==========================================
                if not existing and item['inventory_id']:

                    existing = Product.search([
                        ('default_code', '=', item['inventory_id'])
                    ], limit=1)

                    # if existing:
                    #     print(
                    #         f'FOUND EXISTING PRODUCT BY DEFAULT CODE: '
                    #         f'{existing.id} - {existing.name}'
                    #     )

                # ==========================================
                # STATUS
                # ==========================================
                if existing:
                    total_existing += 1

                    msg = f'Sudah ada → akan diupdate: {existing.name}'

                    # print(f'EXISTING PRODUCT : {existing.name}')

                else:
                    total_new += 1

                    msg = ''

                    print('NEW PRODUCT')

                vals = {
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
                }

                lines_to_create.append(vals)

            # ==================================================
            # CREATE STAGING
            # ==================================================
            print('==================================================')
            print(f'CREATE STAGING : {len(lines_to_create)} RECORDS')
            print('==================================================')

            lines = Line.create(lines_to_create)

            print(f'STAGING CREATED : {len(lines)} RECORDS')

            # ==================================================
            # IMPORT
            # ==================================================
            print('==================================================')
            print(f'START IMPORT BATCH : {len(lines)} RECORDS')
            print('==================================================')

            try:

                lines._do_import()

                total_imported += len(lines)

                print('==================================================')
                print('IMPORT BATCH SUCCESS')
                print(f'TOTAL IMPORTED : {total_imported}')
                print('==================================================')

                # ==============================================
                # COMMIT
                # ==============================================
                print('DATABASE COMMIT')

                self.env.cr.commit()

                print('COMMIT SUCCESS')

            except Exception as e:

                print('==================================================')
                print('IMPORT BATCH FAILED')
                print(f'ERROR : {str(e)}')
                print('==================================================')

                self.env.cr.rollback()

                raise UserError(
                    f'Import batch gagal di batch {i + 1}: {str(e)}'
                )

        # ==================================================
        # FINAL WRITE
        # ==================================================
        print('==================================================')
        print('FINAL WRITE TO WIZARD')
        print('==================================================')

        self.write({
            'state':          'done',
            'total_fetched':  total_fetched,
            'total_new':      total_new,
            'total_existing': total_existing,
        })

        print('==================================================')
        print('IMPORT ALL DONE')
        print(f'TOTAL FETCHED   : {total_fetched}')
        print(f'TOTAL IMPORTED  : {total_imported}')
        print(f'TOTAL NEW       : {total_new}')
        print(f'TOTAL EXISTING  : {total_existing}')
        print('==================================================')

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.stock.item.wizard',
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
            'name':      'Data Stock Item dari Acumatica',
            'res_model': 'acumatica.stock.item.line',
            'view_mode': 'list,form',
            'domain':    [('config_id', '=', self.config_id.id)],
            'context':   {'default_config_id': self.config_id.id},
        }

    # =========================
    # IMPORT
    # =========================
    def action_import_all_pending(self):
        self.ensure_one()

        Line = self.env['acumatica.stock.item.line']

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
            'name': 'Hasil Import Stock Item',
            'res_model': 'acumatica.stock.item.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
        
    def action_import_batch(self):
        self.ensure_one()
        _logger.info("Memulai batch import stock item...")

        BATCH_SIZE = 1000
        # batch_
        # _;logger.info("Mencari hingga %s record pending untuk diimport...", BATCH_SIZE)

        lines = self.env['acumatica.stock.item.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ], limit=BATCH_SIZE)

        if not lines:
            raise UserError('Tidak ada data pending untuk diimport.')
        
        _logger.info("Menemukan %s record pending untuk diimport.", len(lines))
        total_before = self.env['acumatica.stock.item.line'].search_count([
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

        total_after = self.env['acumatica.stock.item.line'].search_count([
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
