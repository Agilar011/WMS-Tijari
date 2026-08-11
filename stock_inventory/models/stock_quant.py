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

    def _apply_inventory(self):
        res = super()._apply_inventory()
        record_moves = self.env["stock.move.line"]
        adjustments_to_process = self.env["stock.inventory"]

        for rec in self.filtered("current_inventory_id"):
            adjustment = rec.current_inventory_id
            moves = record_moves.search(
                [
                    ("product_id", "=", rec.product_id.id),
                    ("lot_id", "=", rec.lot_id.id),
                    "|",
                    ("location_id", "=", rec.location_id.id),
                    ("location_dest_id", "=", rec.location_id.id),
                ],
                order="create_date asc",
            ).filtered(
                lambda x, rec=rec: not x.company_id.id
                or not rec.company_id.id
                or rec.company_id.id == x.company_id.id
            )
            if len(moves) == 0:
                raise ValueError(self.env._("No move lines have been created"))
            move = moves[len(moves) - 1]
            adjustment.stock_move_ids |= move
            reference = move.reference
            if adjustment.name and move.reference:
                reference = adjustment.name + ": " + move.reference
            elif adjustment.name:
                reference = adjustment.name
            move.write(
                {
                    "inventory_adjustment_id": adjustment.id,
                    "reference": reference,
                }
            )
            rec.to_do = False
            rec.current_inventory_id = False
            adjustments_to_process |= adjustment

        if adjustments_to_process and self.env.company.stock_inventory_auto_complete:
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
