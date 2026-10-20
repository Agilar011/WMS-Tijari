from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def get_user_roots(self):
        roots = super().get_user_roots()
        if (
            self.env.user.has_group("tijari_wms_18.group_operator")
            and not self.env.user.has_group("base.group_system")
        ):
            inventory_root = self.env.ref("stock.menu_stock_root", raise_if_not_found=False)
            if inventory_root:
                return roots & inventory_root

        # The WMS matrix does not grant standalone Purchase, Invoicing, or
        # Manufacturing app access to warehouse roles. Their WMS operation
        # menus remain available under Inventory where the matrix permits it.
        restricted_wms_groups = (
            "tijari_wms_18.group_warehouse_manager",
            "tijari_wms_18.group_warehouse_head",
            "tijari_wms_18.group_warehouse_admin",
            "tijari_wms_18.group_operator",
            "tijari_wms_18.group_accounting_stock",
        )
        if (
            any(self.env.user.has_group(group) for group in restricted_wms_groups)
            and not self.env.user.has_group("tijari_wms_18.group_it_staff")
            and not self.env.user.has_group("base.group_system")
        ):
            hidden_root_xmlids = [
                "purchase.menu_purchase_root",
                "account.menu_finance",
                "mrp.menu_mrp_root",
            ]
            if self.env.user.has_group("tijari_wms_18.group_accounting_stock"):
                hidden_root_xmlids.extend([
                    "approval_base.menu_approval_root",
                    "hr.menu_hr_root",
                    "contacts.menu_contacts",
                    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root",
                    "base.menu_management",
                ])
            hidden_roots = self.env['ir.ui.menu']
            for xmlid in hidden_root_xmlids:
                menu = self.env.ref(xmlid, raise_if_not_found=False)
                if menu:
                    hidden_roots |= menu
            return roots - hidden_roots

        # Keep the Employees application limited to IT Staff and system admins.
        if (
            not self.env.user.has_group("tijari_wms_18.group_it_staff")
            and not self.env.user.has_group("base.group_system")
        ):
            employees_root = self.env.ref("hr.menu_hr_root", raise_if_not_found=False)
            if employees_root:
                roots -= employees_root

        return roots
