from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def get_user_roots(self):
        roots = super().get_user_roots()
        if self.env.user.has_group("tijari_wms_18.group_operator"):
            inventory_root = self.env.ref("stock.menu_stock_root", raise_if_not_found=False)
            if inventory_root:
                return roots & inventory_root
        return roots
