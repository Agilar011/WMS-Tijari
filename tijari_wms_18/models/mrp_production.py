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
    catatan = fields.Text(string="Transaction Notes")
    desc_note = fields.Char('Description Note')

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

    def action_confirm(self):
        res = super().action_confirm()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })
        
        return res

    def action_confirm(self):
        res = super().action_confirm()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })

        return res

    def button_mark_done(self):
        for production in self:
            unfinished_moves = production.move_raw_ids.filtered(
                lambda move: move.status_mo_check != 'finished'
            )

            if unfinished_moves:
                details = "\n".join(
                    f"- {move.product_id.display_name}: {move.status_mo_check or 'Belum ada status'}"
                    for move in unfinished_moves
                )

                raise UserError(
                    "Tidak dapat menyelesaikan Manufacturing Order.\n\n"
                    "Raw Materials berikut belum memiliki status 'Finished':\n"
                    f"{details}"
                )

            if (
                production.product_id.tracking in ("lot", "serial")
                and not production.lot_producing_id
            ):
                production.action_generate_serial()

            for move in production.move_raw_ids:
                for line in move.move_line_ids:
                    confirmation_quantity = line.mo_confirmation_quantity

                    line.quantity_shadow = line.quantity
                    line.quantity = confirmation_quantity

        res = super().button_mark_done()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })
        
        return res

    def action_print_hasil_manufacturing(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/hasil_manufacturing?id=' + str(self.id)
        action['target'] = 'new'
        return action
