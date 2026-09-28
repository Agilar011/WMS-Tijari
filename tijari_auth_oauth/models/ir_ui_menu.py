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
            allowed_menu_ids = set()

            # Discuss
            discuss_menu = self.env.ref(
                "mail.menu_root",
                raise_if_not_found=False,
            )
            if discuss_menu:
                allowed_menu_ids.update(
                    self.search([
                        ("id", "child_of", discuss_menu.id),
                    ]).ids
                )

            # Dashboard
            dashboard_menu = self.env.ref(
                "board.menu_root",
                raise_if_not_found=False,
            )
            if dashboard_menu:
                allowed_menu_ids.update(
                    self.search([
                        ("id", "child_of", dashboard_menu.id),
                    ]).ids
                )

            return allowed_menu_ids

        return visible_menu_ids