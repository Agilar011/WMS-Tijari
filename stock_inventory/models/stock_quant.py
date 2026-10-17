from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StockQuant(models.Model):
    _inherit = "stock.quant"

    to_do = fields.Boolean(default=False)

    stock_inventory_ids = fields.Many2many(
        "stock.inventory",
        "stock_inventory_stock_quant_rel",
        string="Stock Inventories",
        copy=False,
    )
    current_inventory_id = fields.Many2one(
        "stock.inventory",
        string="Current Inventory",
        store=True,
    )

    def _get_inventory_move_values(
        self, qty, location_id, location_dest_id, package_id=False,
        package_dest_id=False,
    ):
        vals = super()._get_inventory_move_values(
            qty,
            location_id,
            location_dest_id,
            package_id=package_id,
            package_dest_id=package_dest_id,
        )
        if self.current_inventory_id:
            for command in vals.get("move_line_ids", []):
                if command[0] == 0:
                    command[2]["inventory_adjustment_id"] = self.current_inventory_id.id
        return vals

    def _apply_inventory(self):
        adjustments_to_process = self.filtered(
            "current_inventory_id"
        ).mapped("current_inventory_id")
        res = super()._apply_inventory()
        for quant in self.filtered("current_inventory_id"):
            quant.to_do = False
            quant.current_inventory_id = False

        if (
            adjustments_to_process
            and self.env.company.stock_inventory_auto_complete
            and not self.env.context.get("skip_stock_inventory_auto_complete")
        ):
            for inventory in adjustments_to_process:
                inventory.action_auto_state_to_done()
        return res

    def action_apply_all(self):
        ctx = self.env.context
        inventory = self.env["stock.inventory"].browse(
            ctx.get("inventory_id")
        )

        if inventory.approval_state != "approved":
            raise UserError(_(
                "Inventory Adjustment must be approved before applying inventory."
            ))

        return super().action_apply_all()

    def _get_inventory_fields_write(self):
        return super()._get_inventory_fields_write() + ["to_do"]

    # def generate_lot_stock_quant(self):
    #     for quant in self:
    #         if (
    #             quant.product_id.tracking == "lot"
    #             and not quant.lot_id
    #         ):
    #             lot_name = self.env["ir.sequence"].next_by_code(
    #                 "stock.lot.inventory.adjustment"
    #             )

    #             lot = self.env["stock.lot"].create({
    #                 "name": lot_name,
    #                 "product_id": quant.product_id.id,
    #                 "company_id": quant.company_id.id,
    #             })

    #             quant.lot_id = lot.id

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        if self.env.context.get(
            "active_model", False
        ) == "stock.inventory" and self.env.context.get("active_id", False):
            self.env["stock.inventory"].browse(
                self.env.context.get("active_id")
            ).refresh_stock_quant_ids()
        return res

    @api.model
    def _get_inventory_fields_create(self):
        fields = super()._get_inventory_fields_create()

        if "current_inventory_id" not in fields:
            fields.append("current_inventory_id")

        return fields
