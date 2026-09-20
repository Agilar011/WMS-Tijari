from odoo import api, fields, models

class ResUsers(models.Model):
    _inherit = 'res.users'

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Default Warehouse'
    )

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Allowed Warehouses'
    )

    def _tijari_operator_forbidden_group_xmlids(self):
        return [
            "base.group_allow_export",
            "base.group_multi_company",
            "base.group_no_one",
            "base.group_partner_manager",
            "product.group_product_manager",
            "account.group_account_invoice",
            "sales_team.group_sale_salesman",
            "sales_team.group_sale_manager",
            "sale_management.group_sale_order_template",
            "purchase.group_purchase_user",
            "purchase.group_purchase_manager",
            "purchase.group_send_reminder",
            "mrp.group_mrp_user",
            "mrp.group_mrp_manager",
            "stock.group_stock_manager",
            "mail.group_mail_canned_response_admin",
        ]

    def _tijari_cleanup_operator_groups(self):
        if self.env.context.get("tijari_skip_operator_cleanup"):
            return

        operator_group = self.env.ref("tijari_wms_18.group_operator", raise_if_not_found=False)
        if not operator_group:
            return

        forbidden_groups = self.env["res.groups"]
        for xmlid in self._tijari_operator_forbidden_group_xmlids():
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                forbidden_groups |= group

        operator_users = self.filtered(lambda user: operator_group in user.groups_id)
        if operator_users and forbidden_groups:
            operator_users.with_context(tijari_skip_operator_cleanup=True).write({
                "groups_id": [(3, group.id) for group in forbidden_groups],
            })

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._tijari_cleanup_operator_groups()
        return users

    def write(self, vals):
        result = super().write(vals)
        if "groups_id" in vals:
            self._tijari_cleanup_operator_groups()
        return result


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _tijari_ensure_operator_group_xmlid(self):
        module = "tijari_wms_18"
        xmlid_name = "group_operator"
        category = self.env.ref("base.module_category_inventory_inventory")
        IrModelData = self.env["ir.model.data"].sudo()

        xmlid = IrModelData.search([
            ("module", "=", module),
            ("name", "=", xmlid_name),
        ], limit=1)
        if xmlid and xmlid.model == "res.groups" and self.browse(xmlid.res_id).exists():
            self.browse(xmlid.res_id).sudo().write({
                "name": "Warehouse Operator",
                "implied_ids": [(4, self.env.ref("stock.group_stock_user").id)],
            })
            self.env["res.users"].sudo().search([
                ("groups_id", "in", [xmlid.res_id]),
            ])._tijari_cleanup_operator_groups()
            return True
        if xmlid:
            xmlid.unlink()

        group = self.sudo().search([
            ("category_id", "=", category.id),
            ("name", "in", ["Warehouse Operator", "Operator"]),
        ], order="id", limit=1)
        if not group:
            group = self.sudo().create({
                "name": "Warehouse Operator",
                "category_id": category.id,
            })
        group.write({
            "name": "Warehouse Operator",
            "implied_ids": [(4, self.env.ref("stock.group_stock_user").id)],
        })

        IrModelData.create({
            "module": module,
            "name": xmlid_name,
            "model": "res.groups",
            "res_id": group.id,
            "noupdate": True,
        })
        self.env["res.users"].sudo().search([
            ("groups_id", "in", [group.id]),
        ])._tijari_cleanup_operator_groups()
        return True
