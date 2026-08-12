from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

class WMSMRPProduction(models.Model):
    _inherit = "mrp.production"
    _description = "WMSMRPProduction"

    # def action_confirm(self, merge=True, merge_into=False):
    #     print("\n" + "=" * 80)
    #     print("========== STOCK MOVE _ACTION_CONFIRM ==========")

    #     for move in self:
    #         print(
    #             f"""
    #                 MOVE ID             : {move.id}
    #                 PRODUCT             : {move.product_id.display_name}
    #                 STATE BEFORE        : {move.state}
    #                 RAW MO              : {move.raw_material_production_id.id}
    #                 PRODUCTION          : {move.production_id.id}
    #                 CREATED PRODUCTION  : {move.created_production_id.id}
    #                 PICKING             : {move.picking_id.id}
    #                 PICKING TYPE        : {move.picking_type_id.display_name}
    #                 PICKING TYPE ID     : {move.picking_type_id.id}
    #                 GROUP               : {move.group_id.id}
    #                 SOURCE              : {move.location_id.display_name}
    #                 DEST                : {move.location_dest_id.display_name}
    #                 PROCURE METHOD      : {move.procure_method}
    #                 RULE                : {move.rule_id.id}
    #                 SHOULD BE ASSIGNED  : {move._should_be_assigned()}
    #                 """
    #         )

    #     res = super()._action_confirm(
    #         merge=merge,
    #         merge_into=merge_into,
    #     )

    #     print("\n========== AFTER STOCK MOVE _ACTION_CONFIRM ==========")

    #     for move in self:
    
    #         print(
    #             f"""
    #                 MOVE ID             : {move.id}
    #                 RAW MO              : {move.raw_material_production_id.id}
    #                 PROCURE METHOD      : {move.procure_method}
    #                 STATE AFTER         : {move.state}
    #                 PICKING             : {move.picking_id.id}
    #                 PICKING NAME        : {move.picking_id.name}
    #                 RULE                : {move.rule_id.id}
    #                 RULE NAME           : {move.rule_id.name}
    #                 "RULE ACTION        : {move.rule_id.action}
    #                 "RULE PROCURE METHOD: {move.rule_id.procure_method}
    #                 "PICKING TYPE       : {move.picking_type_id.id, move.picking_type_id.name}
    #                 "SOURCE             : {move.location_id.display_name}
    #                 "DEST               : {move.location_dest_id.display_name}
    #                 "GROUP              : {move.group_id.id}
    #             """
    #         )
    #     raise ValidationError("STOP")
    #     return res

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