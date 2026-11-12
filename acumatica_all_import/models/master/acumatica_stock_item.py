from odoo import models, fields
from odoo.exceptions import UserError
from markupsafe import Markup, escape
import logging
from ...utils import acumatica_data as _data


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

        batch_size = 1000
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
        SkuHistory = self.env['product.sku.history'].with_context(**ctx)
        Staging = self.env['acumatica.stock.item.line'].with_context(
            tracking_disable=True,
            mail_notrack=True,
        )

        _logger.info(
            '[MASTER IMPORT][Stock Item] start total=%s batch_size=%s',
            total,
            batch_size,
        )

        uom_map = {
            (uom.name or '').lower(): uom.id
            for uom in self.env['uom.uom'].search([])
        }
        external_ids = list({line.external_id for line in self if line.external_id})
        existing_map = {}
        if external_ids:
            existing_products = Product.search_read(
                [('adt_external_id', 'in', external_ids)],
                ['adt_external_id', 'default_code'],
            )
            existing_map = {
                product['adt_external_id']: {
                    'id': product['id'],
                    'default_code': product['default_code'],
                }
                for product in existing_products
            }

        for chunk in split_every(batch_size, self):
            chunk_ids = [line.id for line in chunk]
            batch_created = 0
            batch_updated = 0
            batch_error = 0
            staging_success = []
            staging_error = []

            try:
                for line in chunk:
                    try:
                        if not line.description:
                            raise UserError('Description kosong')

                        uom_id = uom_map.get((line.base_uom or '').lower())
                        existing = existing_map.get(line.external_id)
                        product_vals = {
                            'name': line.description,
                            'adt_product_type': 'stock_item',
                            'is_storable': True,
                            'tracking': 'lot',
                            'default_code': line.inventory_id or False,
                            'type': self.ITEM_TYPE_MAP.get(
                                (line.item_type or '').lower(), 'consu'
                            ),
                            'categ_id': 1,
                            'uom_id': uom_id,
                            'uom_po_id': uom_id,
                            'adt_external_id': line.external_id or False,
                            'adt_item_class': line.item_class or False,
                            'adt_item_status': self.STATUS_MAP.get(
                                line.item_status or '', False
                            ),
                            'adt_status': line.item_status,
                            'adt_valuation_method': self.VALUATION_MAP.get(
                                line.valuation_method or '', False
                            ),
                            'adt_acumatica_write_date': _data.acumatica_datetime(
                                line.last_modified_datetime
                            ),
                        }

                        with self.env.cr.savepoint():
                            if not existing:
                                product = Product.create(product_vals)
                                SkuHistory.create({
                                    'product_tmpl_id': product.id,
                                    'sku': product.default_code,
                                    'date_start': fields.Datetime.now(),
                                    'is_current': True,
                                })
                                state = 'created'
                                message = f'Created: {product.display_name}'
                                changed_fields = False
                                batch_created += 1
                            else:
                                product = Product.browse(existing['id']).exists()
                                update_vals = {
                                    'name': product_vals['name'],
                                    'type': product_vals['type'],
                                    'uom_id': product_vals['uom_id'],
                                    'uom_po_id': product_vals['uom_po_id'],
                                    'adt_item_class': product_vals['adt_item_class'],
                                    'adt_item_status': product_vals['adt_item_status'],
                                    'adt_status': product_vals['adt_status'],
                                    'adt_valuation_method': product_vals['adt_valuation_method'],
                                    'adt_acumatica_write_date': product_vals['adt_acumatica_write_date'],
                                }
                                changed_fields = _data.changed_import_fields(
                                    product,
                                    update_vals,
                                )
                                product.write(update_vals)

                                variant = product.product_variant_id or product.product_variant_ids[:1]
                                if not variant:
                                    raise UserError(
                                        f'Product {product.display_name} tidak memiliki variant.'
                                    )
                                variant.write({
                                    'default_code': line.inventory_id or False,
                                    'barcode': line.barcode or False,
                                    'adt_external_id': line.external_id or False,
                                })

                                sku_changed = existing['default_code'] != line.inventory_id
                                if sku_changed:
                                    current_history = SkuHistory.search([
                                        ('product_tmpl_id', '=', product.id),
                                        ('is_current', '=', True),
                                    ])
                                    if current_history:
                                        current_history.write({
                                            'date_end': fields.Datetime.now(),
                                            'is_current': False,
                                        })
                                    SkuHistory.create({
                                        'product_tmpl_id': product.id,
                                        'sku': line.inventory_id,
                                        'date_start': fields.Datetime.now(),
                                        'is_current': True,
                                    })

                                state = 'updated'
                                message = f'Updated: {product.display_name}'
                                batch_updated += 1

                        staging_success.append((
                            state,
                            message,
                            product.id,
                            line.id,
                        ))
                        try:
                            line._handle_acumatica_error()
                        except Exception:
                            _logger.exception(
                                'Failed to clear Stock Item error state for staging line %s',
                                line.id,
                            )
                        try:
                            line._log_import_result(
                                state,
                                f'Data {product.display_name} berhasil '
                                f'{"dibuat" if state == "created" else "diperbarui"}.',
                                product,
                                changed_fields,
                            )
                        except Exception:
                            _logger.exception(
                                'Failed to create Stock Item import log for staging line %s',
                                line.id,
                            )
                    except Exception as line_error:
                        err_msg = str(line_error)[:200]
                        staging_error.append(('error', err_msg, line.id))
                        line._handle_acumatica_error(err_msg)
                        try:
                            line._log_import_result(
                                'error',
                                f'Gagal mengimpor data: {err_msg}',
                                False,
                                False,
                            )
                        except Exception:
                            _logger.exception(
                                'Failed to create Stock Item error log for staging line %s',
                                line.id,
                            )
                        batch_error += 1

                for state, message, product_id, line_id in staging_success:
                    Staging.browse(line_id).write({
                        'import_state': state,
                        'import_message': message,
                        'odoo_product_id': product_id,
                    })

                for state, message, line_id in staging_error:
                    Staging.browse(line_id).write({
                        'import_state': state,
                        'import_message': message,
                    })

                self.env.cr.commit()
                created += batch_created
                updated += batch_updated
                error += batch_error
                self.env.clear()
            except Exception as batch_exception:
                self.env.cr.rollback()
                err_msg = str(batch_exception)[:200]
                _logger.exception(
                    '[MASTER IMPORT][Stock Item] batch failed: %s',
                    batch_exception,
                )
                failed_lines = Staging.browse(chunk_ids).exists()
                failed_lines.write({
                    'import_state': 'error',
                    'import_message': err_msg,
                })
                for line in failed_lines:
                    line._handle_acumatica_error(err_msg)
                    try:
                        line._log_import_result(
                            'error',
                            f'Gagal mengimpor data: {err_msg}',
                            False,
                            False,
                        )
                    except Exception:
                        _logger.exception(
                            'Failed to create Stock Item batch error log for staging line %s',
                            line.id,
                        )
                self.env.cr.commit()
                error += len(chunk)

        _logger.info(
            '[MASTER IMPORT][Stock Item] finish total=%s created=%s updated=%s error=%s',
            total,
            created,
            updated,
            error,
        )

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
    
