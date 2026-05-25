from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockWarehouse(models.Model):
    """
    Extend stock.warehouse dengan field baru dari Acumatica.
    Semua field baru diprefix 'adt_' untuk menghindari conflict
    dengan field bawaan Odoo.

    Field standar yang sudah ada di Odoo (TIDAK perlu dibuat):
      - name  → Description
      - code  → WarehouseID

    Override:
      - code  → size limit dihapus (default Odoo max 5 char),
                karena WarehouseID Acumatica bisa lebih panjang
                contoh: WH01-BS, WH33-DCJKT, dll.
    """
    _inherit = 'stock.warehouse'

    # ── Override field code: hapus batasan size=5 bawaan Odoo ──────────────
    # Odoo default: size=5. Kita override ke None (unlimited varchar di PostgreSQL).
    code = fields.Char(
        string='Short Name',
        required=True,
        size=None,
        help='Short name used as prefix for locations and operations. '
             'Dioverride untuk mendukung WarehouseID Acumatica yang lebih dari 5 karakter.',
    )

    @api.constrains('code')
    def _check_warehouse_code_length(self):
        """Override constraint panjang kode. Max 50 karakter (longgar tapi wajar)."""
        for rec in self:
            if not rec.code:
                raise ValidationError('Short Name (code) tidak boleh kosong.')
            if len(rec.code) > 50:
                raise ValidationError(
                    f'Short Name "{rec.code}" terlalu panjang '
                    f'({len(rec.code)} karakter, maksimal 50).'
                )

    # ── Field baru dari Acumatica (prefix adt_) ─────────────────────────────
    adt_external_id           = fields.Char(string='UUID Acumatica', index=True)
    adt_note                  = fields.Text(string='Note (Acumatica)')
    adt_state                 = fields.Boolean(string='Active (Acumatica)',
                                               help='Active status dari Acumatica WMS')
    adt_drop_ship_location_id = fields.Char(string='Drop Ship Location ID')
    adt_acumatica_write_date      = fields.Datetime(string='Last Modified (Acumatica)')
    adt_receiving_location_id = fields.Char(string='Receiving Location ID')
    adt_rma_location_id       = fields.Char(string='RMA Location ID')
    adt_shipping_location_id  = fields.Char(string='Shipping Location ID')
