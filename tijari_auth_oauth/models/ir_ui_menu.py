from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _visible_menu_ids(self, debug=False):
        visible_menu_ids = super()._visible_menu_ids(debug=debug)

        guest_group = self.env.ref(
            "tijari_auth_oauth.group_guest",
            raise_if_not_found=False,
        )

        # Guest tidak boleh melihat menu apa pun
        if guest_group and guest_group in self.env.user.groups_id:
            return set()

        return visible_menu_ids