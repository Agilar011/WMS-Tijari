from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging

_logger = logging.getLogger(__name__)


class AcumaticaStockItemLine(models.Model):
    """
    Tabel staging: hasil tarikan data Stock Item dari Acumatica.
    Target model Odoo: product.template

    Mapping:
      InventoryID          → default_code              (Mandatory)
      Description          → name                      (Mandatory)
      ItemType             → type                      (Mandatory)
      ItemClass            → adt_item_class             (Mandatory, to be)
      ItemStatus           → adt_item_status            (Mandatory, to be)
      BaseUOM              → uom_id / uom_po_id         (Mandatory, lookup by name)
      ValuationMethod      → adt_valuation_method       (Mandatory, to be)
      LastModifiedDateTime → adt_last_modified_datetime (Mandatory, to be)
    """
    _name        = 'acumatica.stock.item.line'
    _description = 'Data Stock Item dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No',                    readonly=True)
    external_id            = fields.Char(string='UUID Acumatica',           readonly=True)
    inventory_id           = fields.Char(string='InventoryID',              readonly=True)
    description            = fields.Char(string='Description',              readonly=True)
    item_type              = fields.Char(string='ItemType',                 readonly=True)
    item_class             = fields.Char(string='ItemClass',                readonly=True)
    item_status            = fields.Char(string='ItemStatus',               readonly=True)
    base_uom               = fields.Char(string='BaseUOM',                  readonly=True)
    valuation_method       = fields.Char(string='ValuationMethod',          readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime',     readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message   = fields.Char(string='Keterangan',         readonly=True)
    odoo_product_id  = fields.Many2one('product.template', string='Product di Odoo', readonly=True)
    selected         = fields.Boolean(string='Pilih',           default=True)

    config_id = fields.Many2one(
        'acumatica.stock.item.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

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
            found = Product.search([('adt_external_id', '=', rec.external_id)], limit=1)
            if found:
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
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def _do_import(self):
        imported = updated = error = 0

        for line in self:
            try:
                if not line.description:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'Description (name) kosong',
                    })
                    error += 1
                    continue

                # ── Resolve UOM ─────────────────────────────
                uom = self._resolve_uom(line.base_uom)
                if not uom and line.base_uom:
                    _logger.warning(
                        "UOM '%s' tidak ditemukan di Odoo untuk item %s",
                        line.base_uom, line.inventory_id
                    )

                # ── Map ItemType → type ──────────────────────
                odoo_type = self.ITEM_TYPE_MAP.get(
                    (line.item_type or '').lower(), 'consu'
                )

                # ── Map ValuationMethod ──────────────────────
                valuation = self.VALUATION_MAP.get(line.valuation_method or '', False)

                # ── Map ItemStatus ───────────────────────────
                item_status = self.STATUS_MAP.get(line.item_status or '', False)

                vals = {
                    # Field standar Odoo
                    'name':         line.description,
                    'default_code': line.inventory_id or False,
                    'type':         odoo_type,

                    # UOM
                    'uom_id':    uom.id if uom else False,
                    'uom_po_id': uom.id if uom else False,

                    # Field custom adt_
                    'adt_external_id':            line.external_id or False,
                    'adt_item_class':             line.item_class or False,
                    'adt_item_status':            item_status or False,
                    'adt_valuation_method':       valuation or False,
                    'adt_last_modified_datetime': self._parse_dt(line.last_modified_datetime),
                }

                existing = self._find_existing_product(line)

                if existing:
                    existing.write(vals)
                    line.write({
                        'import_state':   'updated',
                        'import_message': f'Diupdate: {existing.name} (ID: {existing.id})',
                        'odoo_product_id': existing.id,
                    })
                    updated += 1
                else:
                    new_product = self.env['product.template'].create(vals)
                    line.write({
                        'import_state':   'imported',
                        'import_message': f'Dibuat: {new_product.name} (ID: {new_product.id})',
                        'odoo_product_id': new_product.id,
                    })
                    imported += 1

            except Exception as e:
                _logger.error("Error import Stock Item %s: %s", line.inventory_id, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   'Import Stock Item',
                'message': msg,
                'type':    'success' if error == 0 else 'warning',
                'sticky':  True,
            },
        }

    # ─── Misc Actions ────────────────────────────────
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
