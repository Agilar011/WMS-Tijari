from odoo import models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _visible_menu_ids(self, debug=False):
        visible_menu_ids = super()._visible_menu_ids(debug=debug)

        guest_group = self.env.ref(
            "tijari_auth_oauth.group_guest",
            raise_if_not_found=False,
        )

        # Kalau bukan Guest, jangan diubah
        if not guest_group or guest_group not in self.env.user.groups_id:
            return visible_menu_ids

        allowed_menu_xmlids = [
            "mail.menu_root_discuss",
            "contacts.menu_contacts",
            "spreadsheet_dashboard.spreadsheet_dashboard_menu_root",
        ]

        allowed_menu_ids = set()

        for xmlid in allowed_menu_xmlids:
            menu = self.env.ref(
                xmlid,
                raise_if_not_found=False,
            )

            if menu:
                # Masukkan menu utama
                allowed_menu_ids.add(menu.id)

                # Masukkan parent-parent-nya kalau ada
                parent = menu.parent_id

                while parent:
                    allowed_menu_ids.add(parent.id)
                    parent = parent.parent_id

        return visible_menu_ids & allowed_menu_ids