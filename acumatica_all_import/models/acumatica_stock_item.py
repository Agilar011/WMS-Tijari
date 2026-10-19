from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from markupsafe import Markup, escape
import logging
import json

_logger = logging.getLogger(__name__)


class AcumaticaStockItemLine(models.Model):
    """
    Tabel staging: hasil tarikan data Stock Item dari Acumatica.
    Target model Odoo: product.template

    Mapping:
      InventoryID          → default_code              (Mandatory)
      CrossReferences      → barcode                   (Optional, AlternateType=barcode)
      Description          → name                      (Mandatory)
      ItemType             → type                      (Mandatory)
      ItemClass            → adt_item_class             (Mandatory, to be)
      ItemStatus           → adt_item_status            (Mandatory, to be)
      BaseUOM              → uom_id / uom_po_id         (Mandatory, lookup by name)
      ValuationMethod      → adt_valuation_method       (Mandatory, to be)
      LastModifiedDateTime → adt_acumatica_write_date (Mandatory, to be)
    """
    _name        = 'acumatica.stock.item.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Stock Item dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No')
    external_id            = fields.Char(string='UUID Acumatica')
    inventory_id           = fields.Char(string='InventoryID')
    description            = fields.Char(string='Description')
    barcode                = fields.Char(string='Barcode')
    item_type              = fields.Char(string='ItemType')
    item_class             = fields.Char(string='ItemClass')
    item_status            = fields.Char(string='ItemStatus')
    base_uom               = fields.Char(string='BaseUOM')
    valuation_method       = fields.Char(string='ValuationMethod')
    last_modified_datetime = fields.Char(string='LastModifiedDateTime')

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged')

    import_message = fields.Char(string='Generation Message')
    odoo_product_id  = fields.Many2one('product.template', string='Document Reference')
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        ondelete='set null',
    )
    sync_date = fields.Datetime(string='Tanggal Sync')

    # ─── Helpers ─────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    # ItemType Acumatica → type Odoo
    # 'consu' = storable/consumable (Odoo 17/18 pakai 'consu' untuk goods)
    ITEM_TYPE_MAP = {
        'finished good': 'consu',
        'component':     'consu',
        'non-stock':     'consu',
        'service':       'service',
        'labor':         'service',
        'charge':        'service',
    }

    # ValuationMethod Acumatica → adt_valuation_method selection
    VALUATION_MAP = {
        'FIFO':     'FIFO',
        'Average':  'Average',
        'Standard': 'Standard',
        'Specific': 'Specific',
    }

    # ItemStatus Acumatica → adt_item_status selection
    STATUS_MAP = {
        'Active':       'Active',
        'Inactive':     'Inactive',
        'ToDelete':     'ToDelete',
        'NoSales':      'NoSales',
        'NoPurchases':  'NoPurchases',
        'NoRequest':    'NoRequest',
    }

    def _resolve_uom(self, uom_name):
        """
        Lookup uom.uom by name (case-insensitive).
        UOM sudah diimport sebelumnya ke uom.uom.
        Return: uom.uom record atau browse() jika tidak ditemukan.
        """
        if not uom_name:
            return self.env['uom.uom'].browse()
        uom = self.env['uom.uom'].search([('name', '=ilike', uom_name)], limit=1)
        return uom

    def _find_existing_product(self, rec):
        """Cari product.template by UUID dulu, fallback by default_code (InventoryID)."""
        Product = self.env['product.template']
        if rec.external_id:
            query = "SELECT id FROM product_template WHERE adt_external_id = %s"
            self.env.cr.execute(query, (rec.external_id,))     
            data = self.env.cr.fetchone()  
            if data:
                return True
            # found = Product.search([('adt_external_id', '=', rec.external_id)], limit=1)
            # if found:
            #     return found
        return False

    def _create_product_and_sku_history(self, line):
        query_product = """
            INSERT INTO product_template (name, categ_id, default_code, type, uom_id, uom_po_id, adt_external_id, adt_item_class, adt_item_status, adt_status, adt_valuation_method, adt_acumatica_write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """
        params_product = (
            json.dumps({"en_US": line.description}),
            1,  # Default category (Uncategorized)
            line.inventory_id or False,
            self.ITEM_TYPE_MAP.get((line.item_type or '').lower(), 'consu'),
            self._resolve_uom(line.base_uom).id if line.base_uom else None,
            self._resolve_uom(line.base_uom).id if line.base_uom else None,
            line.external_id or False,
            line.item_class or False,
            self.STATUS_MAP.get(line.item_status or '', False),
            line.item_status or False,
            self.VALUATION_MAP.get(line.valuation_method or '', False),
            self._parse_dt(line.last_modified_datetime),
        )
        self.env.cr.execute(query_product, params_product)
        product_id = self.env.cr.fetchone()[0]
        # if line.barcode:
        #     self.env['product.template'].browse(product_id).write({'barcode': line.barcode})
        query_staging = """
            UPDATE acumatica_stock_item_line
            SET import_state = %s, 
            import_message = %s, 
            odoo_product_id = %s
            WHERE id = %s
        """                    
        params_staging = (
            'created',
            f'Dibuat: {line.name} (ID: {product_id})',
            product_id,
            line.id
        )
        self.env.cr.execute(query_staging, params_staging)
        query_sku = """
            INSERT INTO product_sku_history (product_tmpl_id, sku, date_start, is_current)
            VALUES (%s, %s, %s, %s)
        """
        params_sku = (
            product_id,
            line.inventory_id,
            fields.Datetime.now(),
            True
        )
        self.env.cr.execute(query_sku, params_sku)

    def _update_product_and_sku_history(self, existing, line):
        # Jika Terjadi Perubahan Data, Update Product
        query_product = """
            UPDATE product_template
            SET name = %s,
                type = %s,
                uom_id = %s,
                uom_po_id = %s,
                adt_external_id = %s,
                adt_item_class = %s,
                adt_item_status = %s,
                adt_status = %s,
                adt_valuation_method = %s,
                adt_acumatica_write_date = %s
            WHERE adt_external_id = %s and adt_acumatica_write_date != %s RETURNING id, default_code
        """
        params_product = (
            json.dumps({"en_US": line.description}),
            # line.inventory_id,
            self.ITEM_TYPE_MAP.get((line.item_type or '').lower(), 'consu'),
            self._resolve_uom(line.base_uom).id if line.base_uom else None,
            self._resolve_uom(line.base_uom).id if line.base_uom else None,
            line.external_id,
            line.item_class,
            self.STATUS_MAP.get(line.item_status or '', False),
            line.item_status,
            self.VALUATION_MAP.get(line.valuation_method or '', False),
            self._parse_dt(line.last_modified_datetime),
            line.external_id,
            line._parse_dt(line.last_modified_datetime)
        )
        self.env.cr.execute(query_product, params_product)
        result = self.env.cr.fetchone()
        # if result:
            # Barcode kosong dari staging berarti barcode di Acumatica sudah
            # dihapus, jadi barcode product juga harus dikosongkan.
            # self.env['product.template'].browse(result[0]).write({
            #     'barcode': line.barcode or False,
            # })
        if not result:
            # Tidak ada perubahan data, skip update
            query_staging = """
                UPDATE acumatica_stock_item_line
                SET 
                    import_state = %s, 
                    import_message = %s
                WHERE id = %s
            """                    
            params_staging = (
                'updated',
                f'Tidak ada perubahan data → tetap pakai: {line.description}',
                line.id
            )
            self.env.cr.execute(query_staging, params_staging)
            return

        product_id = result[0]
        old_sku = result[1]

        query_staging = """
            UPDATE acumatica_stock_item_line
            SET import_state = %s, 
            import_message = %s, 
            odoo_product_id = %s
            WHERE id = %s
        """                    
        params_staging = (
            'updated',
            f'Updated: {line.description} (ID: {product_id})',
            product_id,
            line.id
        )
        self.env.cr.execute(query_staging, params_staging)

        # Jika SKU berubah, update product_sku_history dan update SKU di product.template
        if old_sku != line.inventory_id:
            query_sku_end = """
                UPDATE product_sku_history
                SET date_end = %s, is_current = False
                WHERE product_tmpl_id = %s AND is_current = True
            """
            params_sku_end = (
                fields.Datetime.now(),
                product_id,
            )
            self.env.cr.execute(query_sku_end, params_sku_end)

            query_product_sku_new = """
                UPDATE product_template
                SET default_code = %s
                WHERE id = %s
            """
            params_product_sku_new = (
                line.inventory_id,
                product_id,
            )
            self.env.cr.execute(query_product_sku_new, params_product_sku_new)

            query_sku_new = """
                INSERT INTO product_sku_history (product_tmpl_id, sku, date_start, is_current)
                VALUES (%s, %s, %s, %s)
            """
            params_sku_new = (
                product_id,
                line.inventory_id,
                fields.Datetime.now(),
                True
            )
            self.env.cr.execute(query_sku_new, params_sku_new)

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    # def _do_import(self):
    #     created = updated = error = 0

    #     for line in self:
    #         try:
    #             if not line.description:
    #                 line.write({
    #                     'import_state':   'error',
    #                     'import_message': 'Description (name) kosong',
    #                 })
    #                 error += 1
    #                 continue

    #             # ── Resolve UOM ─────────────────────────────
    #             uom = self._resolve_uom(line.base_uom)
    #             if not uom and line.base_uom:
    #                 _logger.warning(
    #                     "UOM '%s' tidak ditemukan di Odoo untuk item %s",
    #                     line.base_uom, line.inventory_id
    #                 )

    #             # ── Map ItemType → type ──────────────────────
    #             odoo_type = self.ITEM_TYPE_MAP.get((line.item_type or '').lower(), 'consu')
    #             valuation = self.VALUATION_MAP.get(line.valuation_method or '', False)
    #             item_status = self.STATUS_MAP.get(line.item_status or '', False)

    #             vals = {
    #                 # Field standar Odoo
    #                 'name':         line.description,
    #                 'default_code': line.inventory_id or False,
    #                 'type':         odoo_type,

    #                 # UOM
    #                 'uom_id':    uom.id if uom else False,
    #                 'uom_po_id': uom.id if uom else False,

    #                 # Field custom adt_
    #                 'adt_external_id': line.external_id or False,
    #                 'adt_item_class': line.item_class or False,
    #                 'adt_item_status': item_status or False,
    #                 'adt_valuation_method': valuation or False,
    #                 'adt_last_modified_datetime': self._parse_dt(line.last_modified_datetime),
    #             }

    #             existing = self._find_existing_product(line)
    #             SkuHistory = self.env['product.sku.history']

    #             if not existing:
    #                 # new_product = self.env['product.template'].create(vals)
    #                 # line.write({
    #                 #     'import_state':   'created',
    #                 #     'import_message': f'Dibuat: {new_product.name} (ID: {new_product.id})',
    #                 #     'odoo_product_id': new_product.id,
    #                 # })
    #                 # created += 1
    #                 # self.env['product.sku.history'].create({
    #                 #     'product_tmpl_id': new_product.id,
    #                 #     'sku': new_product.default_code,
    #                 #     'date_start': fields.Datetime.now(),
    #                 #     'is_current': True,
    #                 # })
    #                 self._create_product_and_sku_history(line)
    #                 created += 1
    #                 print(f"DATA BERHASIL DIBUAT NIH - ID {line.inventory_id}")
    #             else:
    #                 # if existing.adt_last_modified_datetime != self._parse_dt(line.last_modified_datetime):
    #                 #     if existing.default_code != line.inventory_id:
    #                 #         SkuHistory.search([
    #                 #             ('product_tmpl_id', '=', existing.id),
    #                 #             ('date_end', '=', False),
    #                 #         ]).write({'date_end': fields.Datetime.now(), 'is_current': False})
    #                 #         # Create a new SKU history record for the old SKU
    #                 #         SkuHistory.create({
    #                 #             'product_tmpl_id': existing.id,
    #                 #             'sku': existing.default_code,
    #                 #             'date_start': fields.Datetime.now(),
    #                 #             'is_current': True,
    #                 #         })
    #                 #         existing.message_post(body=f"SKU berubah dari {existing.default_code} menjadi {line.inventory_id} karena data di Acumatica berubah. Last Modified: {line.last_modified_datetime}")
    #                 #     existing.write(vals)
    #                 #     existing.message_post(body=f"Stock Item berhasil diupdate karena data di Acumatica berubah. Last Modified: {line.last_modified_datetime}")
    #                 #     line.write({
    #                 #         'import_state':   'updated',
    #                 #         'import_message': f'Updated: {existing.name} (ID: {existing.id})',
    #                 #         'odoo_product_id': existing.id,
    #                 #     })
    #                 #     updated += 1
    #                 self._update_product_and_sku_history(existing, line)
    #                 updated += 1
    #                 print(f"DATA BERHASIL DIUPDATE NIH - ID {line.inventory_id}")
                
    #             # if existing:
    #             #     if existing and existing.default_code != line.inventory_id:

    #             #         SkuHistory.search([
    #             #             ('product_tmpl_id', '=', existing.id),
    #             #             ('date_end', '=', False),
    #             #         ]).write({'date_end': fields.Datetime.now(), 'is_current': False})
    #             #         # Create a new SKU history record for the old SKU
    #             #         SkuHistory.create({
    #             #             'product_tmpl_id': existing.id,
    #             #             'sku': existing.default_code,
    #             #             'date_start': fields.Datetime.now(),
    #             #             'is_current': True,
    #             #         })
    #             #     existing.write(vals)
    #             #     line.write({
    #             #         'import_state':   'updated',
    #             #         'import_message': f'Updated: {existing.name} (ID: {existing.id})',
    #             #         'odoo_product_id': existing.id,
    #             #     })
    #             #     updated += 1
    #             # else:
    #             #     # buat juga log sku baru untuk log perubahan sku di masa depan
    #             #     new_product = self.env['product.template'].create(vals)
    #             #     line.write({
    #             #         'import_state':   'created',
    #             #         'import_message': f'Dibuat: {new_product.name} (ID: {new_product.id})',
    #             #         'odoo_product_id': new_product.id,
    #             #     })
    #             #     created += 1
    #             #     self.env['product.sku.history'].create({
    #             #         'product_tmpl_id': new_product.id,
    #             #         'sku': new_product.default_code,
    #             #         'date_start': fields.Datetime.now(),
    #             #         'is_current': True,
    #             #     })

    #         except Exception as e:
    #             _logger.error("Error import Stock Item %s: %s", line.inventory_id, str(e))
    #             line.write({
    #                 'import_state':   'error',
    #                 'import_message': str(e)[:200],
    #             })
    #             error += 1

    #     msg = f'Import selesai: {created} dibuat, {updated} diupdate, {error} error.'
    #     return {
    #         'type': 'ir.actions.client',
    #         'tag':  'display_notification',
    #         'params': {
    #             'title':   'Import Stock Item',
    #             'message': msg,
    #             'type':    'success' if error == 0 else 'warning',
    #             'sticky':  True,
    #         },
    #     }


    def _handle_acumatica_error(self, err_msg=False):
        # Setelah rollback, cache ORM bisa masih menyimpan Many2one ke error
        # record yang juga ikut ter-rollback. Baca ulang record dan relasinya
        # sebelum mengakses field agar error handler tidak menimpa error asli.
        self = self.exists()
        if not self:
            return
        self.invalidate_recordset(['acumatica_err_id'])
        AcumaticaError = self.env['acumatica.error.master']
        acumatica_err_id = self.acumatica_err_id
        if not err_msg:
            if acumatica_err_id:
                acumatica_err_id.import_state = 'solved'
                return
            return

        state = 'error'
        if not acumatica_err_id:
            acumatica_err_id = AcumaticaError.create({
                'name': f'StockItem-{self.id}',
                'data_type': 'stock_item',
                'import_state': state,
                'data_id': self.id,
                'error_msg': err_msg
            })
            self.acumatica_err_id = acumatica_err_id
            
        acumatica_err_id.error_msg = err_msg
        acumatica_err_id.import_state = state

    def _get_changed_fields(self, record, vals):
        changed_fields = []

        for field_name, new_value in vals.items():
            field = record._fields.get(field_name)

            if not field:
                continue

            old_value = record[field_name]

            if field.type == 'many2one':
                old_value = old_value.id if old_value else False
                
            old_value = old_value or False
            new_value = new_value or False

            if old_value != new_value:
                changed_fields.append({
                    'field_name': field_name,
                    'field_label': field.string,
                    'old_value': old_value,
                    'new_value': new_value,
                })

        return changed_fields
    
    def _log_import_result(
        self,
        state,
        message,
        record=False,
        changed_fields=None,
    ):
        # A failed savepoint/rollback can leave a stale browse record. There
        # is nothing to post when the staging row no longer exists.
        self = self.exists()
        if not self:
            return
        titles = {
            'created': '✅ Import Berhasil',
            'updated': '🔄 Data Diperbarui',
            'error': '❌ Import Gagal',
        }

        body = Markup("""
            <p>
                <strong>{}</strong>
            </p>
            <p>{}</p>
        """).format(
            titles.get(state, 'Import Log'),
            message,
        )

        if changed_fields:
            body += Markup("""
                <p><strong>Perubahan:</strong></p>
                <ul>
            """)

            for change in changed_fields:
                old_value = change['old_value'] or '-'
                new_value = change['new_value'] or '-'

                body += Markup("""
                    <li>
                        <strong>{}</strong>:
                        {} → {}
                    </li>
                """).format(
                    escape(change['field_label']),
                    escape(str(old_value)),
                    escape(str(new_value)),
                )

            body += Markup("</ul>")

        if record:
            body += Markup("""
                <p>
                    Record Odoo:
                    <a href="#"
                    data-oe-model="{}"
                    data-oe-id="{}">
                        {}
                    </a>
                </p>
            """).format(
                escape(record._name),
                record.id,
                escape(record.display_name),
            )

        self.with_context(
            mail_create_nosubscribe=True,
            mail_post_autofollow=False,
        ).message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
    
    def _do_import(self):

        from odoo.tools import split_every

        BATCH_SIZE = 1000
        total = len(self)
        created = 0
        updated = 0
        error = 0
        ctx = {
            'tracking_disable': True,
            'mail_create_nolog': True,
            'mail_notrack': True,
            'mail_create_nosubscribe': True,
        }
        Product = self.env['product.template'].with_context(**ctx)
        ProductVariant = self.env['product.product'].with_context(**ctx)

        print(
            f'[MASTER IMPORT][Stock Item] START total={total} batch_size={BATCH_SIZE}',
            flush=True,
        )

        # =====================================================
        # CACHE UOM
        # =====================================================

        uom_map = {}
        all_uoms = self.env['uom.uom'].search([])
        for uom in all_uoms:
            uom_map[(uom.name or '').lower()] = uom.id

        # =====================================================
        # CACHE EXISTING PRODUCTS
        # =====================================================

        # Cari existing product berdasarkan external_id (UUID Acumatica) di acumatica_stock_item_line
        external_ids = [
            line.external_id
            for line in self
            if line.external_id
        ]
        existing_map = {}
        # Jika ada external_id, ambil data product_template yang matching dengan external_id
        if external_ids:
            self.env.cr.execute("""
                SELECT id, adt_external_id, default_code
                FROM product_template
                WHERE adt_external_id IN %s
            """, [tuple(external_ids)])
            # Buat mapping dari external_id ke product_template id dan default_code
            for row in self.env.cr.fetchall():
                existing_map[row[1]] = {
                    'id': row[0],
                    'default_code': row[2],
                }

        # =====================================================
        # PROCESS PER CHUNK
        # =====================================================

        # Proses data per chunk untuk menghindari memory error jika datanya sangat besar
        for chunk in split_every(BATCH_SIZE, self):
            chunk_ids = [line.id for line in chunk]
            print(
                f'[MASTER IMPORT][Stock Item] BATCH start={chunk_ids[0] if chunk_ids else "-"} '
                f'end={chunk_ids[-1] if chunk_ids else "-"} count={len(chunk)}',
                flush=True,
            )
            try:
                
                create_vals = []
                update_params = []
                barcode_updates = []
                variant_updates = []
                sku_insert_params = []
                staging_success = []
                staging_error = []

                # =============================================
                # PREPARE
                # =============================================

                for line in chunk:
                    try:
                        # Cek kalo description (name) kosong, langsung tandai error dan skip proses import untuk line ini
                        if not line.description:

                            err_msg = 'Description kosong'
                            staging_error.append((
                                'error',
                                err_msg,
                                line.id
                            ))

                            line._handle_acumatica_error(err_msg)

                            line._log_import_result(
                                'error',
                                f'Gagal mengimpor data: {err_msg}',
                                False,
                                False
                            )
                            error += 1
                            continue

                        uom_id = uom_map.get(
                            (line.base_uom or '').lower()
                        )

                        # Cari existing product berdasarkan external_id (UUID Acumatica) yang sudah dicache sebelumnya
                        existing = existing_map.get(
                            line.external_id
                        )

                        # =====================================
                        # CREATE
                        # =====================================
                        vals = {
                            'name': line.description,
                            'adt_product_type': 'stock_item',
                            'is_storable': True,
                            'tracking' : 'lot',
                            'default_code': line.inventory_id or False,
                            # 'barcode': line.barcode or False,
                            'type': self.ITEM_TYPE_MAP.get(
                                (line.item_type or '').lower(),
                                'consu'
                            ),
                            'categ_id': 1,
                            'uom_id': uom_id,
                            'uom_po_id': uom_id,
                            'adt_external_id': line.external_id or False,
                            'adt_item_class': line.item_class or False,
                            'adt_item_status': self.STATUS_MAP.get(
                                line.item_status or '',
                                False
                            ),
                            'adt_status': line.item_status,
                            'adt_valuation_method': self.VALUATION_MAP.get(
                                line.valuation_method or '',
                                False
                            ),
                            'adt_acumatica_write_date':
                                self._parse_dt(
                                    line.last_modified_datetime
                                ),

                            # helper temporary
                            '_line_id': line.id,
                        }
                        
                        # Buat data baru jika tidak ditemukan existing product dengan external_id yang sama.
                        if not existing:

                            # Tambahkan data baru ke list create_vals untuk nanti di-bulk create dengan ORM
                            create_vals.append(vals)

                        # =====================================
                        # UPDATE
                        # =====================================

                        # Kalo ada product dengan external_id yang sama, tapi data di Acumatica lebih baru daripada data di Odoo, maka update datanya.
                        else:
                            # Tambahkan data update ke list update_params untuk nanti di-bulk update dengan SQL
                            update_params.append((
                                json.dumps({
                                    "en_US": line.description
                                }),
                                self.ITEM_TYPE_MAP.get(
                                    (line.item_type or '').lower(),
                                    'consu'
                                ),
                                uom_id,
                                uom_id,
                                line.item_class or False,
                                self.STATUS_MAP.get(
                                    line.item_status or '',
                                    False
                                ),
                                line.item_status,
                                self.VALUATION_MAP.get(
                                    line.valuation_method or '',
                                    False
                                ),
                                self._parse_dt(
                                    line.last_modified_datetime
                                ),
                                existing['id']
                            ))
                            # Nilai kosong bukan berarti "skip": itu snapshot
                            # terbaru dari Acumatica dan harus menghapus barcode
                            # lama pada product.
                            barcode_updates.append((existing['id'], line.barcode or False))
                            # InventoryID dan barcode juga merupakan data
                            # variant. Jangan hanya mengubah template karena
                            # product.product menyimpan nilai operasionalnya.
                            variant_updates.append((
                                existing['id'],
                                line.inventory_id or False,
                                # line.barcode or False,
                                line.external_id or False,
                            ))

                            # SKU changed
                            if existing['default_code'] != line.inventory_id:
                                
                                # Tutup SKU history lama dengan date_end dan is_current = False
                                self.env.cr.execute("""
                                    UPDATE product_sku_history
                                    SET date_end = NOW(),
                                        is_current = FALSE
                                    WHERE product_tmpl_id = %s
                                    AND is_current = TRUE
                                """, [existing['id']])

                                # Tambahkan data SKU baru ke list sku_insert_params untuk nanti di-bulk insert dengan SQL
                                sku_insert_params.append((
                                    existing['id'],
                                    line.inventory_id,
                                    fields.Datetime.now(),
                                    True
                                ))

                                # Update SKU di product_template
                                self.env.cr.execute("""
                                    UPDATE product_template
                                    SET default_code = %s
                                    WHERE id = %s
                                """, (
                                    line.inventory_id,
                                    existing['id']
                                ))

                            # Tambahkan data sukses update ke list staging_success untuk nanti di-bulk update status di staging dengan SQL
                            staging_success.append((
                                'updated',
                                f'Updated: {line.description}',
                                existing['id'],
                                line.id
                            ))

                            existing = Product.browse(existing['id'])
                            changed_fields = line._get_changed_fields(
                                existing,
                                vals,
                            )

                            line._log_import_result(
                                'updated',
                                f'Data {existing.display_name} berhasil diperbarui.',
                                existing,
                                changed_fields,
                            )

                            updated += 1

                    except Exception as e:

                        err_msg = str(e)[:200]
                        staging_error.append((
                            'error',
                            err_msg,
                            line.id
                        ))

                        line._handle_acumatica_error(err_msg)

                        line._log_import_result(
                            'error',
                            f'Gagal mengimpor data: {err_msg}',
                            False,
                            False
                        )
                        error += 1

                # =============================================
                # BULK CREATE ORM
                # =============================================

                # Buat per-line dengan savepoint. Satu barcode duplikat tidak
                # boleh membatalkan seluruh batch stock item.
                if create_vals:
                    clean_vals = []
                    for vals in create_vals:
                        line_id = vals.pop('_line_id')
                        clean_vals.append((line_id, vals))

                    for line_id, vals in clean_vals:
                        try:
                            with self.env.cr.savepoint():
                                product = Product.create(vals)

                            staging_success.append((
                                'created',
                                f'Created: {product.name}',
                                product.id,
                                line_id,
                            ))

                            acu_product = self.env[
                                'acumatica.stock.item.line'
                            ].browse(line_id).exists()
                            acu_product._handle_acumatica_error()
                            try:
                                acu_product._log_import_result(
                                    'created',
                                    f'Data {product.display_name} berhasil dibuat.',
                                    product,
                                    False
                                )
                            except Exception:
                                _logger.exception(
                                    "Failed to create chatter log for stock item line %s",
                                    acu_product.id,
                                )

                            sku_insert_params.append((
                                product.id,
                                product.default_code,
                                fields.Datetime.now(),
                                True,
                            ))
                            created += 1
                        except Exception as create_error:
                            err_msg = str(create_error)[:200]
                            staging_error.append((
                                'error',
                                err_msg,
                                line_id,
                            ))
                            acu_product = self.env[
                                'acumatica.stock.item.line'
                            ].browse(line_id).exists()
                            acu_product._handle_acumatica_error(err_msg)
                            acu_product._log_import_result(
                                'error',
                                f'Gagal mengimpor data: {err_msg}',
                                False,
                                False,
                            )
                            error += 1

                # =============================================
                # BULK SQL UPDATE PRODUCT
                # =============================================

                if update_params:

                    self.env.cr.executemany("""
                        UPDATE product_template
                        SET name = %s,
                            type = %s,
                            uom_id = %s,
                            uom_po_id = %s,
                            adt_item_class = %s,
                            adt_item_status = %s,
                            adt_status = %s,
                            adt_valuation_method = %s,
                            adt_acumatica_write_date = %s
                        WHERE id = %s
                    """, update_params)

                # product.template.barcode is a computed/inverse field in
                # Odoo 18; it has no column on product_template. Use ORM so
                # the inverse writes the barcode to the product variant.
                for product_id, barcode in barcode_updates:
                    Product.browse(product_id).write({'barcode': barcode})

                # Sinkronkan variant secara eksplisit. Stock Item selalu
                # dibuat sebagai satu variant; fallback ke variant pertama
                # menjaga flow tetap aman untuk template lama yang memiliki
                # lebih dari satu variant.
                for product_id, default_code, external_id in variant_updates:
                    template = Product.browse(product_id)
                    variant = template.product_variant_id
                    if not variant:
                        variant = template.product_variant_ids[:1]
                    if variant:
                        ProductVariant.browse(variant.id).write({
                            'default_code': default_code,
                            'barcode': barcode,
                            'adt_external_id': external_id,
                        })

                # =============================================
                # BULK SKU HISTORY
                # =============================================

                if sku_insert_params:

                    self.env.cr.executemany("""
                        INSERT INTO product_sku_history (
                            product_tmpl_id,
                            sku,
                            date_start,
                            is_current
                        )
                        VALUES (%s, %s, %s, %s)
                    """, sku_insert_params)

                # =============================================
                # BULK STAGING SUCCESS
                # =============================================

                if staging_success:
                    staging_model = self.env[
                        'acumatica.stock.item.line'
                    ].with_context(tracking_disable=True, mail_notrack=True)
                    for state, message, product_id, line_id in staging_success:
                        staging_model.browse(line_id).write({
                            'import_state': state,
                            'import_message': message,
                            'odoo_product_id': product_id,
                        })

                    # Verify status using the ORM after the write. Product
                    # updates and staging status are separate operations; do
                    # not let the import summary claim success if this part
                    # did not persist.
                    refreshed = staging_model.browse(
                        [item[3] for item in staging_success]
                    )
                    refreshed.invalidate_recordset([
                        'import_state', 'import_message', 'odoo_product_id',
                    ])
                    missing_status = refreshed.filtered(
                        lambda line: line.import_state not in ('created', 'updated')
                    )
                    if missing_status:
                        raise UserError(
                            'Status staging Stock Item tidak tersimpan untuk: %s'
                            % ', '.join(missing_status.mapped('inventory_id'))
                        )

                # =============================================
                # BULK STAGING ERROR
                # =============================================

                if staging_error:

                    self.env.cr.executemany("""
                        UPDATE acumatica_stock_item_line
                        SET import_state = %s,
                            import_message = %s
                        WHERE id = %s
                    """, staging_error)

                # =============================================
                # COMMIT PER BATCH
                # =============================================

                self.env.cr.commit()

                self.env.clear()

            except Exception as e:

                self.env.cr.rollback()

                _logger.exception("IMPORT ERROR: %s", str(e))

                for line_id in chunk_ids:
                    err_msg = str(e)[:200]
                    self.env.cr.execute("""
                        UPDATE acumatica_stock_item_line
                        SET import_state = 'error',
                            import_message = %s
                        WHERE id = %s
                    """, (
                        err_msg,
                        line_id
                    ))

                    acu_product = self.env[
                        'acumatica.stock.item.line'
                    ].browse(line_id).exists()
                    acu_product._handle_acumatica_error(err_msg)
                    acu_product._log_import_result(
                        'error',
                        f'Gagal mengimpor data: {err_msg}',
                        False,
                        False
                    )

                self.env.cr.commit()

        msg = f'Import selesai: {created} dibuat, {updated} diupdate, {error} error.'
        print(
            f'[MASTER IMPORT][Stock Item] FINISH total={total} '
            f'created={created} updated={updated} error={error}',
            flush=True,
        )
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Stock Item',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'warning',
        #         'sticky': True,
        #     },
        # }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'staged',
            'import_message': False,
        })

    def action_open_product(self):
        self.ensure_one()
        if not self.odoo_product_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id':    self.odoo_product_id.id,
            'view_mode': 'form',
        }
    
