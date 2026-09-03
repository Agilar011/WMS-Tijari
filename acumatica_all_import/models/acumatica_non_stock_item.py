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
    row_number             = fields.Integer(string='No',                    readonly=True)
    external_id            = fields.Char(string='UUID Acumatica',           readonly=True)

    # Mandatory
    inventory_id           = fields.Char(string='InventoryID',              readonly=True)
    description            = fields.Char(string='Description',              readonly=True)
    item_type              = fields.Char(string='ItemType',                 readonly=True)
    item_class             = fields.Char(string='ItemClass',                readonly=True)
    item_status            = fields.Char(string='ItemStatus',               readonly=True)
    base_unit              = fields.Char(string='BaseUnit',                 readonly=True)
    purchase_unit          = fields.Char(string='PurchaseUnit',             readonly=True)
    sales_unit             = fields.Char(string='SalesUnit',                readonly=True)
    is_a_kit               = fields.Boolean(string='IsAKit',                readonly=True)
    is_kit                 = fields.Boolean(string='IsKit',                 readonly=True)
    note_id                = fields.Char(string='NoteID',                   readonly=True)
    posting_class          = fields.Char(string='PostingClass',             readonly=True)
    note                   = fields.Text(string='Note',                     readonly=True)

    # Optional
    last_modified_datetime = fields.Char(string='LastModifiedDateTime',     readonly=True)
    price_class            = fields.Char(string='PriceClass',               readonly=True)
    volume                 = fields.Float(string='Volume',                  readonly=True)
    volume_uom             = fields.Char(string='VolumeUOM',                readonly=True)
    weight                 = fields.Float(string='Weight',                  readonly=True)
    weight_uom             = fields.Char(string='WeightUOM',                readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message  = fields.Char(string='Keterangan',          readonly=True)
    odoo_product_id = fields.Many2one('product.template', string='Product di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

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
        if rec.inventory_id:
            found = Product.search([('default_code', '=', rec.inventory_id)], limit=1)
            if found:
                return found
        return Product.browse()

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

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
                'data_type': self._name,
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

            # Normalisasi nilai
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
            'imported': '✅ Import Berhasil',
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

        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
    
    def _do_import(self):
        imported = updated = error = 0

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
                    changed_fields = line._get_changed_fields(
                        existing,
                        vals,
                    )       
                    existing.write(vals)

                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Diupdate: {existing.name} (ID: {existing.id})',
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

                    line.write({
                        'import_state':    'imported',
                        'import_message':  f'Dibuat: {new_product.name} (ID: {new_product.id})',
                        'odoo_product_id': new_product.id,
                    })

                    line._handle_acumatica_error()

                    line._log_import_result(
                        'imported',
                        f'Data {new_product.display_name} berhasil dibuat.',
                        new_product,
                        False
                    )
                    imported += 1
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

        msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   'Import Non-Stock Item',
                'message': msg,
                'type':    'success' if error == 0 else 'warning',
                'sticky':  True,
            },
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'pending',
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
