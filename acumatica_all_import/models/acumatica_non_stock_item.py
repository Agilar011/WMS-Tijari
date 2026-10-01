from odoo import models, fields
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from markupsafe import Markup, escape
import logging

_logger = logging.getLogger(__name__)


class AcumaticaNonStockItemLine(models.Model):
    """
    Tabel staging: hasil tarikan data Non-Stock Item dari Acumatica.
    Target model Odoo: product.template

    Mapping:
      note                 → adt_note                  (Mandatory, to be)
      BaseUnit             → adt_base_unit              (Mandatory, to be)
      Description          → name                       (Mandatory)
      InventoryID          → default_code               (Mandatory)
      IsAKit               → adt_is_a_kit               (Mandatory)
      IsKit                → adt_is_kit                 (Mandatory)
      ItemClass            → adt_item_class              (Mandatory, to be)
      ItemStatus           → adt_item_status             (Mandatory, to be)
      ItemType             → adt_item_type               (Mandatory, to be)
      LastModifiedDateTime → adt_last_modified_datetime  (Optional, to be)
      NoteID               → adt_note_id                (Mandatory, to be)
      PostingClass         → adt_posting_class           (Mandatory, to be)
      PriceClass           → adt_price_class             (to be)
      PurchaseUnit         → adt_purchase_unit           (Mandatory, to be)
      SalesUnit            → adt_sales_unit              (Mandatory, to be)
      Volume               → volume                      (Optional)
      VolumeUOM            → adt_volume_uom              (Optional)
      Weight               → weight                      (Optional)
      WeightUOM            → adt_weight_uom              (Optional)

    Catatan type Odoo:
      Non-Stock Item → 'service' (tidak ada inventory tracking)
    """
    _name        = 'acumatica.non.stock.item.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Non-Stock Item dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No')
    external_id            = fields.Char(string='UUID Acumatica')

    # Mandatory
    inventory_id           = fields.Char(string='InventoryID')
    description            = fields.Char(string='Description')
    item_type              = fields.Char(string='ItemType')
    item_class             = fields.Char(string='ItemClass')
    item_status            = fields.Char(string='ItemStatus')
    base_unit              = fields.Char(string='BaseUnit')
    purchase_unit          = fields.Char(string='PurchaseUnit')
    sales_unit             = fields.Char(string='SalesUnit')
    is_a_kit               = fields.Boolean(string='IsAKit')
    is_kit                 = fields.Boolean(string='IsKit')
    note_id                = fields.Char(string='NoteID')
    posting_class          = fields.Char(string='PostingClass')
    note                   = fields.Text(string='Note')

    # Optional
    last_modified_datetime = fields.Char(string='LastModifiedDateTime')
    price_class            = fields.Char(string='PriceClass')
    volume                 = fields.Float(string='Volume')
    volume_uom             = fields.Char(string='VolumeUOM')
    weight                 = fields.Float(string='Weight')
    weight_uom             = fields.Char(string='WeightUOM')

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged')

    import_message  = fields.Char(string='Generation Message')
    odoo_product_id = fields.Many2one('product.template', string='Document Reference')
    selected = fields.Boolean(string='Pilih', default=True)
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        ondelete='set null',
    )
    sync_date = fields.Datetime(string='Tanggal Sync')

    # ItemStatus Acumatica → adt_item_status selection
    STATUS_MAP = {
        'Active':      'Active',
        'Inactive':    'Inactive',
        'ToDelete':    'ToDelete',
        'NoSales':     'NoSales',
        'NoPurchases': 'NoPurchases',
        'NoRequest':   'NoRequest',
    }
#debug function

    # def _debug_product_vals(self, title, vals):
    #     print("\n" + "=" * 100)
    #     print(title)
    #     print("=" * 100)

    #     for key, value in sorted(vals.items()):
    #         print(f"{key:<35}: {value}")

    #     print("=" * 100 + "\n")
        
    # ─── Helpers ─────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False


    def _find_existing_product(self, rec):
        """Cari product.template by UUID dulu, fallback by default_code (InventoryID)."""
        Product = self.env['product.template']
        if rec.external_id:
            found = Product.search([('adt_external_id', '=', rec.external_id)], limit=1)
            if found:
                found.type = 'consu'
                return found
        # if rec.inventory_id:
        #     found = Product.with_context(
        #         active_test=False
        #     ).search([('default_code', '=', rec.inventory_id)], limit=1)
        #     if found:
        #         return found
        return Product.browse()

    def _sync_sku_history(self, product, old_sku=False, new_sku=False):
        """Sinkronkan SKU Non-Stock Item ke product.sku.history."""
        self.ensure_one()
        new_sku = (new_sku or '').strip()
        old_sku = (old_sku or '').strip()
        if not product or not new_sku:
            return

        # SKU history is maintained by this importer; keep direct user access
        # read-only while allowing the controlled synchronization to proceed.
        SkuHistory = self.env['product.sku.history'].sudo()
        current_history = SkuHistory.search([
            ('product_tmpl_id', '=', product.id),
            ('is_current', '=', True),
        ])

        # SKU sama dan history sudah ada: tidak membuat duplikasi.
        if old_sku == new_sku and current_history.filtered(lambda h: h.sku == new_sku):
            return

        if current_history:
            current_history.write({
                'date_end': fields.Datetime.now(),
                'is_current': False,
            })

        SkuHistory.create({
            'product_tmpl_id': product.id,
            'sku': new_sku,
            'date_start': fields.Datetime.now(),
            'is_current': True,
        })

    def _sync_product_variant(self, product, vals):
        """Sinkronkan field variant yang didefinisikan di product.product."""
        variant = product.product_variant_id or product.product_variant_ids[:1]
        if not variant:
            return

        variant_fields = (
            'default_code',
            'adt_external_id',
            'adt_note',
            'adt_base_unit',
            'adt_is_a_kit',
            'adt_is_kit',
            'adt_note_id',
            'adt_posting_class',
            'adt_price_class',
            'adt_purchase_unit',
            'adt_sales_unit',
            'adt_volume_uom',
            'adt_weight_uom',
        )
        variant.write({
            field: vals[field]
            for field in variant_fields
            if field in vals
        })

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

    def _handle_acumatica_error(self, err_msg=False):
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
                'name': f'NonStockItem-{self.id}',
                'data_type': 'acumatica.non.stock.item.line',
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
        created = updated = error = 0
        total = len(self)

        print(f'[MASTER IMPORT][Non-Stock Item] START total={total}', flush=True)

        for line in self:
            try:
                if not line.description:
                    err_msg = 'Description (name) kosong'
                    line.write({
                        'import_state':   'error',
                        'import_message': err_msg,
                    })

                    line._handle_acumatica_error(err_msg)

                    line._log_import_result(
                        'error',
                        f'Gagal mengimpor data: {err_msg}',
                        False,
                        False
                    )
                    error += 1
                    continue

                item_status = self.STATUS_MAP.get(line.item_status or '', False)

                vals = {
                    # ── Field standar Odoo ──────────────────
                    'name': line.description,
                    'default_code': line.inventory_id or False,
                    'type':         'consu',
                    'is_storable': True,
                    'tracking' : 'lot',
                    'volume':       line.volume or 0.0,
                    'weight':       line.weight or 0.0,

                    # ── Field custom adt_ ───────────────────
                    'adt_external_id': line.external_id or False,
                    'adt_product_type': 'non_stock_item',
                    'adt_note': line.note or False,
                    'adt_base_unit':  line.base_unit or False,
                    'adt_is_a_kit': line.is_a_kit,
                    'adt_is_kit':  line.is_kit,
                    'adt_item_class': line.item_class or False,
                    'adt_item_status': item_status or False,
                    'adt_item_type':  line.item_type or False,
                    'adt_acumatica_write_date': self._parse_dt(line.last_modified_datetime),
                    'adt_note_id': line.note_id or False,
                    'adt_posting_class': line.posting_class or False,
                    'adt_price_class': line.price_class or False,
                    'adt_purchase_unit': line.purchase_unit or False,
                    'adt_sales_unit': line.sales_unit or False,
                    'adt_volume_uom': line.volume_uom or False,
                    'adt_weight_uom': line.weight_uom or False,
                }

                existing = self._find_existing_product(line)

                if existing:
                    old_sku = existing.default_code or False
                    changed_fields = line._get_changed_fields(
                        existing,
                        vals,
                    )       
                    existing.write(vals)
                    self._sync_product_variant(existing, vals)
                    line._sync_sku_history(
                        existing,
                        old_sku=old_sku,
                        new_sku=line.inventory_id,
                    )

                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Updated: {existing.name} (ID: {existing.id})',
                        'odoo_product_id': existing.id,
                    })

                    line._log_import_result(
                        'updated',
                        f'Data {existing.display_name} berhasil diperbarui.',
                        existing,
                        changed_fields,
                    )
                    updated += 1
                    # for item in existing:


                else:
                    new_product = self.env['product.template'].create(vals)
                    line._sync_sku_history(
                        new_product,
                        new_sku=line.inventory_id,
                    )

                    line.write({
                        'import_state':    'created',
                        'import_message':  f'Dibuat: {new_product.name} (ID: {new_product.id})',
                        'odoo_product_id': new_product.id,
                    })

                    line._handle_acumatica_error()

                    line._log_import_result(
                        'created',
                        f'Data {new_product.display_name} berhasil dibuat.',
                        new_product,
                        False
                    )
                    created += 1
                    # for item in new_product:



            except Exception as e:
                _logger.error("Error import Non-Stock Item %s: %s", line.inventory_id, str(e))

                err_msg = str(e)[:200]
                line.write({
                    'import_state':   'error',
                    'import_message': err_msg,
                })
                line._handle_acumatica_error(err_msg)

                line._log_import_result(
                    'error',
                    f'Gagal mengimpor data: {err_msg}',
                    False,
                    False,
                )
                error += 1

        msg = f'Import selesai: {created} dibuat, {updated} diupdate, {error} error.'
        print(
            f'[MASTER IMPORT][Non-Stock Item] FINISH total={total} '
            f'created={created} updated={updated} error={error}',
            flush=True,
        )
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag':  'display_notification',
        #     'params': {
        #         'title':   'Import Non-Stock Item',
        #         'message': msg,
        #         'type':    'success' if error == 0 else 'warning',
        #         'sticky':  True,
        #     },
        # }

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
