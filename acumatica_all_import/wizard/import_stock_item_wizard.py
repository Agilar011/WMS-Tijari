from odoo import models, fields
from odoo.exceptions import UserError
import requests
import time
import logging

_logger = logging.getLogger(__name__)


class ImportStockItemWizard(models.TransientModel):
    _name        = 'import.stock.item.wizard'
    _description = 'Wizard Import Stock Item dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Batch Size', default=100)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    fetch_skip = fields.Integer(string='Mulai dari Data ke-', default=0)
    total_target = fields.Integer(string='Total Data Diambil', help='Kosongkan untuk ambil semua data')
    skip_size = fields.Integer(string='Skip Size', default=0, help='Jumlah data yang dilewati sebelum memulai import.')
    state = fields.Selection(selection=[('draft','Siap'),('fetched','Data Sudah Ditarik'),('done','Selesai')], default='draft')

    total_fetched  = fields.Integer(string='Total Data Ditarik', readonly=True)
    total_new      = fields.Integer(string='Item Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get("value", "") or ""
        return value or ""

    def _extract_barcode(self, item):
        cross_references = item.get("CrossReferences") or []
        if isinstance(cross_references, dict):
            cross_references = cross_references.get("value", []) or []
        if not isinstance(cross_references, list):
            return ""

        for cross_reference in cross_references:
            if not isinstance(cross_reference, dict):
                continue
            alternate_type = self._val(cross_reference, "AlternateType")
            if (alternate_type or "").strip().lower() != "barcode":
                continue
            return self._val(cross_reference, "AlternateID")
        return ""

    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        import math

        count = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_stock_item_data(
                limit=self.batch_size,
                offset=offset,
                skip=self.fetch_skip,
            )

            if not batch_data:
                break

            count += batch_data

        self.total_fetched = count

        if not count:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.stock.item.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }
    
    def fetch_all_stock_item_data(self, batch_size=False):
        """
        Ambil semua data Stock Item dari Acumatica dengan paging $skip.

        Dipakai untuk scheduler/server-side agar tidak dibatasi fetch_limit
        milik wizard manual.
        """
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        fetch_size = batch_size or self.batch_size or 50
        if fetch_size <= 0:
            raise UserError('Batch size harus lebih besar dari 0.')

        raw_count = 0
        batch_count = 0

        _logger.info(
            "START FETCH ALL STOCK ITEM; CONFIG=%s, BATCH_SIZE=%s, FETCH_SKIP=%s",
            self.config_id.display_name,
            fetch_size,
            self.fetch_skip,
        )

        while True:
            offset = batch_count * fetch_size
            batch_data = self.fetch_stock_item_data(
                limit=fetch_size,
                offset=offset,
                skip=self.fetch_skip,
            )
            if not batch_data:
                _logger.info(
                    "STOP FETCH ALL STOCK ITEM; empty batch at OFFSET=%s, TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
                    self.fetch_skip + offset,
                    raw_count,
                    batch_count,
                )
                break

            raw_count += batch_data
            batch_count += 1
            _logger.info(
                "FETCH ALL STOCK ITEM BATCH DONE; BATCH=%s, OFFSET=%s, FETCHED=%s, RUNNING_TOTAL=%s",
                batch_count,
                self.fetch_skip + offset,
                batch_data,
                raw_count,
            )

        self.write({
            'total_fetched': raw_count,
            'state': 'fetched' if raw_count else 'draft',
        })
        _logger.info(
            "FINISH FETCH ALL STOCK ITEM; TOTAL_FETCHED=%s, TOTAL_BATCHES=%s",
            raw_count,
            batch_count,
        )
        return raw_count

    def action_fetch_all_data(self):
        self.ensure_one()
        raw_count = self.fetch_all_stock_item_data()
        if not raw_count:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'import.stock.item.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    def _check_last_modified_staging(self, item):
        Staging = self.env['acumatica.stock.item.line']
        existing = Staging.search([
            ('external_id', '=', item['external_id']),
            ('last_modified_datetime', '!=', item['last_modified_datetime']),
        ])
        if existing:
            item['import_state'] = 'staged'
            existing.write(item)

    def fetch_stock_item_data(self, limit=50, offset=0, skip=0):
        """
        Fetch data Stock Item dengan:
        - limit     = jumlah data per request
        - offset    = offset batch internal
        - skip      = starting row manual
        """

        self.ensure_one()

        session = self.config_id._do_login()

        max_retry = 3
        retry_delay = 30

        last_error = None

        try:

            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"

            real_skip = offset + skip

            _logger.info(
                'START FETCH STOCK ITEM | '
                'LIMIT=%s | OFFSET=%s | SKIP=%s | REAL SKIP=%s',
                limit,
                offset,
                skip,
                real_skip
            )
            params = {
                "$top": limit,
                "$skip": real_skip,
                "$expand": "CrossReferences",
            }

            _logger.info(
                'REQUEST INFO | '
                'ENDPOINT=%s | PARAMS=%s',
                self.config_id.api_url,
                params,
            )

            for attempt in range(1, max_retry + 1):
                try:
                    _logger.info(
                        'FETCH STOCK ITEM ATTEMPT %s/%s | '
                        'OFFSET=%s | SKIP=%s',
                        attempt,
                        max_retry,
                        offset,
                        skip
                    )
                    response = session.get(endpoint, params=params, timeout=60)

                    _logger.info(
                        'RESPONSE RECEIVED | '
                        'STATUS CODE=%d',
                        response.status_code,
                    )
                    if response.status_code != 200:
                        last_error = (
                            f'Gagal ambil data Stock Item '
                            f'(HTTP {response.status_code}): '
                            f'{response.text}'
                        )
                        _logger.error(last_error)
                        raise Exception(last_error)

                    raw_data = response.json()

                    _logger.info(
                        'TOTAL RAW DATA | '
                        'STATUS CODE=%s',
                        len(raw_data),
                    )
                    all_results = []

                    item_no = 0

                    for item in raw_data:

                        item_no += 1

                        parsed_vals = {
                            'external_id': item.get("id", "") or "",
                            'row_number': item.get("rowNumber", 0),
                            'inventory_id': self._val(item, "InventoryID"),
                            'description': self._val(item, "Description"),
                            'item_type': self._val(item, "ItemType"),
                            'item_class': self._val(item, "ItemClass"),
                            'item_status': self._val(item, "ItemStatus"),
                            'base_uom': self._val(item, "BaseUOM"),
                            'valuation_method': self._val(item, "ValuationMethod"),
                            'last_modified_datetime': self._val(item, "LastModifiedDateTime"),
                            'barcode': self._extract_barcode(item),
                        }

                        all_results.append(parsed_vals)

                        print('--------------------------------------------------')
                        print(f'ITEM NO      : {item_no}')
                        print(f'EXTERNAL ID  : {parsed_vals["external_id"]}')
                        print(f'INVENTORY ID : {parsed_vals["inventory_id"]}')
                        print(f'DESCRIPTION  : {parsed_vals["description"]}')
                        print(f'ITEM TYPE    : {parsed_vals["item_type"]}')
                        print(f'STATUS       : {parsed_vals["item_status"]}')
                        print('--------------------------------------------------')

                    _logger.info(
                        'OFFSET %s | SKIP %s | '
                        'REAL SKIP %s | LIMIT %s | '
                        'TOTAL STOCK ITEM: %s',
                        offset,
                        skip,
                        real_skip,
                        limit,
                        len(all_results)
                    )

                    Product = self.env['product.template']
                    Staging = self.env['acumatica.stock.item.line']

                    query = """
                        INSERT INTO acumatica_stock_item_line (
                            config_id,
                            row_number,
                            external_id,
                            inventory_id,
                            description,
                            item_type,
                            item_class,
                            item_status,
                            barcode,
                            base_uom,
                            valuation_method,
                            last_modified_datetime,
                            import_state,
                            import_message,
                            odoo_product_id,
                            sync_date
                        ) 
                        VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s,
                            %s, %s, %s
                        )
                    """

                    product_by_inventory = {
                        p.adt_external_id: p.id
                        for p in Product.search([
                            ('adt_external_id', '!=', False)
                        ])
                    }

                    staging_by_inventory = {
                        p.external_id: p.id
                        for p in Staging.search([
                            ('external_id', '!=', False)
                        ])
                    }

                    params_list = []
                    for item in all_results:
                        existing_staging = False
                        if item['external_id']:
                            existing_staging = staging_by_inventory.get((item['external_id']))
                        if existing_staging:
                            self._check_last_modified_staging(item)
                            continue
                        
                        existing_product = False
                        if not existing_staging and item['external_id']:
                            existing_product = product_by_inventory.get((item['external_id']))

                        msg = 'Data sudah ada' if existing_product else ''
                        state = 'staged'


                        params_list.append((
                            self.config_id.id,
                            item['row_number'],
                            item['external_id'],
                            item['inventory_id'],
                            item['description'],
                            item['item_type'],
                            item['item_class'],
                            item['item_status'],
                            item['barcode'],
                            item['base_uom'],
                            item['valuation_method'],
                            item['last_modified_datetime'],
                            state,
                            msg,
                            existing_product or None,
                            fields.Datetime.now(),
                        ))

                    self.env.cr.executemany(query, params_list)
                    return len(all_results)

                except requests.exceptions.ConnectionError as e:

                    last_error = (
                        f'Tidak bisa terhubung ke server: '
                        f'{self.base_url}'
                    )

                    _logger.error(last_error)

                except requests.exceptions.Timeout as e:

                    last_error = (
                        'Timeout saat ambil data Stock Item '
                        'dari Acumatica.'
                    )
                    _logger.error(last_error)

                except Exception as e:

                    last_error = str(e)

                    _logger.info(
                        'UNKNOWN FETCH ERROR=%s',
                        last_error,
                    )

                    _logger.exception(e)

                if attempt < max_retry:

                    _logger.warning(
                        'FETCH STOCK ITEM FAILED - RETRY IN %s SECONDS '
                        '(attempt %s/%s)',
                        retry_delay,
                        attempt,
                        max_retry
                    )

                    time.sleep(retry_delay)

            _logger.error(
                'ALL FETCH STOCK ITEM RETRY FAILED: %s',
                last_error
            )

            raise UserError(last_error)

        finally:

            _logger.info(
                'LOGOUT SESSION ACUMATICA'
            )
            self.config_id._do_logout(session)

            self.config_id.last_sync = fields.Datetime.now()


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

    def action_import_all_pending(self):
        self.ensure_one()

        Line = self.env['acumatica.stock.item.line']

        domain = [
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
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
            ('import_state', '=', 'staged'),
        ], limit=BATCH_SIZE)

        if not lines:
            raise UserError('Tidak ada data pending untuk diimport.')
        
        _logger.info("Menemukan %s record pending untuk diimport.", len(lines))
        total_before = self.env['acumatica.stock.item.line'].search_count([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
        ])

        count_to_import = round(total_before / BATCH_SIZE)

        for i in range(count_to_import + 1):
            _logger.info("Memulai batch import ke-%s dari %s...", i + 1, count_to_import + 1)
            lines._do_import()

            # 🔥 penting: commit biar tidak nge-hang
            self.env.cr.commit()

        total_after = self.env['acumatica.stock.item.line'].search_count([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'staged'),
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
