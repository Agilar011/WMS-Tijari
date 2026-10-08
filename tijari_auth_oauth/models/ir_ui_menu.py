from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _visible_menu_ids(self, debug=False):
        visible_menu_ids = super()._visible_menu_ids(debug=debug)

        guest_group = self.env.ref(
            "tijari_auth_oauth.group_guest",
            raise_if_not_found=False,
        )


        if guest_group and guest_group in self.env.user.groups_id:
            
            allowed_menu_ids = set()

            guest_root_menu = self.env.ref(
                "tijari_auth_oauth.menu_guest_root",
                raise_if_not_found=False,
            )

            if guest_root_menu:
                self.env.cr.execute("""
                    SELECT id
                    FROM ir_ui_menu
                    WHERE id = %s
                    OR parent_path LIKE %s
                """, (
                    guest_root_menu.id,
                    f"{guest_root_menu.id}/%",
                ))

                allowed_menu_ids.update(
                    row[0] for row in self.env.cr.fetchall()
                )

            return allowed_menu_ids

        return visible_menu_ids