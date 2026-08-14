from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

import logging
_logger = logging.getLogger(__name__)

class WMSMRPProduction(models.Model):
    _inherit = "mrp.production"
    _description = "WMSMRPProduction"

    picking_type_name = fields.Char(
        related="picking_type_id.name",
        store=False,
    )

    def _prepare_stock_lot_values(self):
        self.ensure_one()

        sequence = self.env["ir.sequence"]

        name = sequence.next_by_code("stock.lot.manufacture")

        while name and self.env["stock.lot"].search([
            ("product_id", "=", self.product_id.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
            ("name", "=", name),
        ], limit=1):
            name = sequence.next_by_code("stock.lot.manufacture")

        if not name:
            raise UserError(
                _("Please configure the Manufacture Lot sequence.")
            )

        return {
            "product_id": self.product_id.id,
            "name": name,
        }