from odoo import fields, models
from odoo.exceptions import UserError


class InventoryProductSelectionWizard(models.TransientModel):
    _name = "stock.inventory.product.selection.wizard"
    _description = "Inventory Adjustment Product Selection"

    inventory_id = fields.Many2one(
        "stock.inventory",
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related="inventory_id.company_id",
        readonly=True,
    )
    state = fields.Selection(
        related="inventory_id.state",
        readonly=True,
    )
    product_ids = fields.Many2many(
        "product.product",
        string="Products",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

    def action_apply(self):
        self.ensure_one()
        if self.inventory_id.state != "draft":
            raise UserError(self.env._("Products can only be changed while the adjustment is in draft."))
        self.inventory_id.write({"product_ids": [(6, 0, self.product_ids.ids)]})
        return {"type": "ir.actions.act_window_close"}
