from odoo import api, fields, models, _

class WMSReserveParentLocation(models.TransientModel):
    _name = "wms.reserve.parent.location"
    _description = "Reserve Product From Parent Location"

    picking_id = fields.Many2one(
        "stock.picking",
        required=True,
        readonly=True,
    )

    line_ids = fields.One2many(
        "wms.reserve.parent.location.line",
        "wizard_id",
    )

class WMSReserveParentLocationLine(models.TransientModel):
    _name = "wms.reserve.parent.location.line"
    _description = "Reserve Parent Location Line"

    wizard_id = fields.Many2one(
        "wms.reserve.parent.location",
        required=True,
        ondelete="cascade",
    )

    selected = fields.Boolean(
        default=True,
    )

    move_id = fields.Many2one(
        "stock.move",
        required=True,
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        readonly=True,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        readonly=True,
    )

    current_location_id = fields.Many2one(
        "stock.location",
        readonly=True,
    )

    suggested_location_id = fields.Many2one(
        "stock.location",
        readonly=True,
    )

    available_qty = fields.Float(
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):

        res = super().default_get(fields_list)

        picking = self.env["stock.picking"].browse(
            self.env.context.get("default_picking_id")
        )

        res["picking_id"] = picking.id

        lines = []

        moves = picking.move_ids.filtered(
            lambda m:
                m.product_id.type == "product"
                and m.state in (
                    "confirmed",
                    "waiting",
                    "partially_available",
                )
                and m.reserved_availability < m.product_uom_qty
        )

        for move in moves:

            quants = move._wms_find_parent_quants()

            for quant in quants:

                available = (
                    quant.quantity
                    - quant.reserved_quantity
                )

                if available <= 0:
                    continue

                lines.append((0, 0, {

                    "move_id": move.id,

                    "product_id": move.product_id.id,

                    "lot_id": quant.lot_id.id,

                    "current_location_id": move.location_id.id,

                    "suggested_location_id": quant.location_id.id,

                    "available_qty": available,

                }))

        res["line_ids"] = lines

        return res

    def action_cancel(self):

        return {
            "type": "ir.actions.act_window_close"
        }

    def action_approve(self):

        self.ensure_one()

        for line in self.line_ids.filtered("selected"):

            move = line.move_id

            if not move.original_location_id:

                move.original_location_id = move.location_id

            move.fallback_location_id = (
                line.suggested_location_id
            )

            move.location_id = (
                line.suggested_location_id
            )

            move._action_assign()

        self.picking_id._adt_apply_dest_location_to_move_lines()

        return {
            "type": "ir.actions.act_window_close"
        }
    
        