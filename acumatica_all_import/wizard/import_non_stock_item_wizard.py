from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ImportNonStockItemWizard(models.TransientModel):
    _name = 'import.non.stock.item.wizard'
    _description = 'Wizard Import Non-Stock Item dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0)
    state = fields.Selection([
        ('draft',   'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done',    'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Data Ditarik', readonly=True)
    total_new = fields.Integer(string='Item Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError('Pilih konfigurasi API terlebih dahulu.')

        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size) if self.fetch_limit else 0
        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_non_stock_item_data(limit=self.batch_size, offset=offset)
            if not batch_data:
                break

            raw_list += batch_data

        self.total_fetched = raw_list
        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        # new_count = existing_count = 0
        # lines_to_create = []
        # Product = self.env['product.template']

        # for item in raw_list:
        #     existing = Product.browse()
        #     if item['external_id']:
        #         existing = Product.search([
        #             ('adt_external_id', '=', item['external_id'])
        #         ], limit=1)
        #     if not existing and item['inventory_id']:
        #         existing = Product.search([
        #             ('default_code', '=', item['inventory_id'])
        #         ], limit=1)

        #     if existing:
        #         existing_count += 1
        #         msg = f'Sudah ada → akan diupdate: {existing.name}'
        #     else:
        #         new_count += 1
        #         msg = ''

        #     lines_to_create.append({
        #         'config_id':             self.config_id.id,
        #         'row_number':            item['row_number'],
        #         'external_id':           item['external_id'],
        #         'inventory_id':          item['inventory_id'],
        #         'description':           item['description'],
        #         'item_type':             item['item_type'],
        #         'item_class':            item['item_class'],
        #         'item_status':           item['item_status'],
        #         'base_unit':             item['base_unit'],
        #         'purchase_unit':         item['purchase_unit'],
        #         'sales_unit':            item['sales_unit'],
        #         'is_a_kit':              item['is_a_kit'],
        #         'is_kit':                item['is_kit'],
        #         'note_id':               item['note_id'],
        #         'posting_class':         item['posting_class'],
        #         'note':                  item['note'],
        #         'last_modified_datetime': item['last_modified_datetime'],
        #         'price_class':           item['price_class'],
        #         'volume':                item['volume'],
        #         'volume_uom':            item['volume_uom'],
        #         'weight':                item['weight'],
        #         'weight_uom':            item['weight_uom'],
        #         'import_state':          'pending',
        #         'import_message':        msg,
        #         'odoo_product_id':       existing.id if existing else False,
        #         'selected':              True,
        #         'sync_date':             fields.Datetime.now(),
        #     })

        # self.env['acumatica.non.stock.item.line'].create(lines_to_create)

        # self.write({
        #     'state':          'fetched',
        #     'total_fetched':  len(raw_list),
        #     'total_new':      new_count,
        #     'total_existing': existing_count,
        # })

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

    def fetch_non_stock_item_data(self, limit=50, offset=0):
        """
        Ambil data Non-Stock Item dari Acumatica API.
        Endpoint: GET /NonStockItem?$top={limit}
        """
        self.ensure_one()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {"$top": limit, "$skip": offset}
            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Non-Stock Item (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records Non-Stock Item dari Acumatica", len(raw_data))

            def val(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "") or ""
                return ""

            def bval(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return bool(v.get("value", False))
                return False

            def fval(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    try:
                        return float(v.get("value", 0) or 0)
                    except (ValueError, TypeError):
                        return 0.0
                return 0.0

            result = []
            for item in raw_data:
                result.append({
                    'external_id': item.get("id", "") or "",
                    'row_number': item.get("rowNumber", 0),
                    # Mandatory
                    'inventory_id': val(item,  "InventoryID"),
                    'description': val(item,  "Description"),
                    'item_type': val(item,  "ItemType"),
                    'item_class': val(item,  "ItemClass"),
                    'item_status': val(item,  "ItemStatus"),
                    'base_unit': val(item,  "BaseUnit"),
                    'purchase_unit': val(item,  "PurchaseUnit"),
                    'sales_unit': val(item,  "SalesUnit"),
                    'is_a_kit': bval(item, "IsAKit"),
                    'is_kit': bval(item, "IsKit"),
                    'note_id': val(item,  "NoteID"),
                    'posting_class': val(item,  "PostingClass"),
                    'note': item.get("note", {}).get("value", "") or "",
                    # Optional
                    'last_modified_datetime': val(item,  "LastModifiedDateTime"),
                    'price_class': val(item,  "PriceClass"),
                    'volume': fval(item, "Volume"),
                    'volume_uom': val(item,  "VolumeUOM"),
                    'weight': fval(item, "Weight"),
                    'weight_uom': val(item,  "WeightUOM"),
                })
    
            Product = self.env['product.template']
            query = """
                INSERT INTO acumatica_non_stock_item_line (
                    config_id,
                    row_number,
                    external_id,
                    inventory_id,
                    description,
                    item_type,
                    item_class,
                    item_status,
                    base_unit,
                    purchase_unit,
                    sales_unit,
                    is_a_kit,
                    is_kit,
                    note_id,
                    posting_class,
                    note,
                    last_modified_datetime,
                    price_class,
                    volume,
                    volume_uom,
                    weight,
                    weight_uom,
                    import_state,
                    import_message,
                    odoo_product_id,
                    selected,
                    sync_date
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
            """

            for item in result:
                staging_line = False
                staging_domain = []

                if item['external_id']:
                    staging_domain = [('external_id', '=', item['external_id'])]

                if staging_domain:
                    staging_line = self.env['acumatica.non.stock.item.line'].search(
                        staging_domain,
                        limit=1,
                    )
                    if staging_line:
                        continue

                existing = False
                if item['external_id']:
                    existing = Product.search([
                        ('adt_external_id', '=', item['external_id'])
                    ], limit=1)

                msg = 'Data sudah ada' if existing else ''
                state = 'pending'

                params = (
                    self.config_id.id,
                    item['row_number'],
                    item['external_id'],
                    item['inventory_id'],
                    item['description'],
                    item['item_type'],
                    item['item_class'],
                    item['item_status'],
                    item['base_unit'],
                    item['purchase_unit'],
                    item['sales_unit'],
                    item['is_a_kit'],
                    item['is_kit'],
                    item['note_id'],
                    item['posting_class'],
                    item['note'],
                    item['last_modified_datetime'],
                    item['price_class'],
                    item['volume'],
                    item['volume_uom'],
                    item['weight'],
                    item['weight_uom'],
                    state,
                    msg,
                    existing.id if existing else None,
                    True,
                    fields.Datetime.now(),
                )
                self.env.cr.execute(query, params)

            self.env['acumatica.non.stock.item.line']._invalidate_cache()
            return len(result)

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()
