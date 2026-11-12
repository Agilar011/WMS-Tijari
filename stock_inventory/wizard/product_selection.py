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
    product_selection = fields.Selection(
        related="inventory_id.product_selection",
        readonly=True,
    )
    state = fields.Selection(
        related="inventory_id.state",
        readonly=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
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
        product_ids = (
            self.product_id.ids
            if self.product_selection in ("one", "lot")
            else self.product_ids.ids
        )
        self.inventory_id.write({"product_ids": [(6, 0, product_ids)]})
        return {"type": "ir.actions.act_window_close"}
