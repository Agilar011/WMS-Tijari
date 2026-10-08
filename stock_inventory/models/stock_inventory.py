from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression

import logging
_logger = logging.getLogger(__name__)


class InventoryAdjustmentsGroup(models.Model):
    _name = "stock.inventory"
    _description = "Inventory Adjustment Group"
    _order = "date desc, id desc"
    _inherit = [ "mail.thread", "approval.mixin"]

    name = fields.Char(
        required=True,
        default="Inventory",
        string="Inventory Reference",
        readonly=True,
    )

    date = fields.Datetime(
        default=lambda self: fields.Datetime.now(),
        readonly=True,
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        readonly=True,
        index=True,
        default=lambda self: self.env.company,
        required=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("wait_approval", "Waiting for Approval"),
            ("approved", "Approved"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )

    owner_id = fields.Many2one(
        "res.partner",
        "Owner",
        help="This is the owner of the inventory adjustment",
        readonly=True,
    )

    location_ids = fields.Many2many(
        "stock.location",
        string="Locations",
        domain="[('usage', '=', 'internal'), "
        "'|', ('company_id', '=', company_id), ('company_id', '=', False)]",
        readonly=True,
    )

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Warehouse'
    )

    product_selection = fields.Selection(
        [
            ("all", "All Products"),
            ("manual", "Manual Selection"),
            ("category", "Product Category"),
            ("one", "One Product"),
            ("lot", "Lot/Serial Number"),
        ],
        default="all",
        required=True,
        readonly=True,
    )

    product_ids = fields.Many2many(
        "product.product",
        string="Products",
        domain="['|', ('company_id', '=', company_id), ('company_id', '=', False)]",
        readonly=True,
    )

    stock_quant_ids = fields.Many2many(
        "stock.quant",
        string="Inventory Adjustment",
        domain="['|', ('company_id', '=', company_id), ('company_id', '=', False)]",
        readonly=True,
    )

    category_id = fields.Many2one(
        "product.category",
        string="Product Category",
        readonly=True,
    )

    lot_ids = fields.Many2many(
        "stock.lot",
        string="Lot/Serial Numbers",
        domain="['|', ('company_id', '=', company_id), ('company_id', '=', False)]",
        readonly=True,
    )

    stock_move_ids = fields.One2many(
        "stock.move.line",
        "inventory_adjustment_id",
        string="Inventory Adjustments Done",
        readonly=True,
    )

    count_stock_quants = fields.Integer(
        compute="_compute_count_stock_quants", string="# Adjustments"
    )

    count_stock_quants_string = fields.Char(
        compute="_compute_count_stock_quants", string="Adjustments"
    )

    count_stock_moves = fields.Integer(
        compute="_compute_count_stock_moves", string="Stock Moves Lines"
    )
    action_state_to_cancel_allowed = fields.Boolean(
        compute="_compute_action_state_to_cancel_allowed"
    )

    exclude_sublocation = fields.Boolean(
        help="If enabled, it will only take into account "
        "the locations selected, and not their children."
    )

    responsible_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned to",
        readonly=True,
        help="Specific responsible of Inventory Adjustment.",
    )

    products_under_review_ids = fields.Many2many(
        comodel_name="product.product",
        compute="_compute_products_under_review_ids",
        search="_search_products_under_review_ids",
        string="Products Under Review",
        relation="stock_inventory_product_review_rel",
    )

    acumatica_ref_doc = fields.Char('Acumatica Ref Document')
    
    approval_type_id = fields.Many2one(
        "approval.type",
        string="Approval Type",
        domain=lambda self: self._get_approval_domain(),
    )

    @api.model
    def _get_approval_domain(self):
        return [
            (
                "approval_model_id.model",
                "=",
                self._name,
            )
        ]

    def _search_products_under_review_ids(self, operator, value):
        quants = self.env["stock.quant"].search(
            [("to_do", "=", True), ("product_id", operator, value)]
        )
        inventories = quants.mapped("stock_inventory_ids")
        return [("id", "in", inventories.ids), ("state", "=", "in_progress")]

    @api.depends("stock_quant_ids", "stock_quant_ids.to_do", "state")
    def _compute_products_under_review_ids(self):
        for record in self:
            if record.state == "in_progress":
                products = record.stock_quant_ids.filtered(
                    lambda quant: quant.to_do
                ).mapped("product_id")
                record.products_under_review_ids = (
                    [(6, 0, products.ids)] if products else [(5, 0, 0)]
                )
            else:
                record.products_under_review_ids = [(5, 0, 0)]

    @api.depends("stock_quant_ids")
    def _compute_count_stock_quants(self):
        for rec in self:
            current_inventory_id = rec.id
            quants = rec.stock_quant_ids
            quants_to_do = quants.filtered(lambda q: q.to_do)
            quants_pending_to_review = [
                q
                for q in quants_to_do
                if q.current_inventory_id.id == current_inventory_id
            ]
            count_pending_to_review = len(quants_pending_to_review)
            rec.count_stock_quants = len(quants)
            rec.count_stock_quants_string = (
                f"{count_pending_to_review} / {rec.count_stock_quants}"
            )

    @api.depends("stock_move_ids")
    def _compute_count_stock_moves(self):
        group_fname = "inventory_adjustment_id"
        group_data = self.env["stock.move.line"].read_group(
            [
                (group_fname, "in", self.ids),
            ],
            [group_fname],
            [group_fname],
        )
        data_by_adj_id = {
            row[group_fname][0]: row.get(f"{group_fname}_count", 0)
            for row in group_data
        }
        for rec in self:
            rec.count_stock_moves = data_by_adj_id.get(rec.id, 0)

    def _compute_action_state_to_cancel_allowed(self):
        for rec in self:
            rec.action_state_to_cancel_allowed = rec.state == "draft"

    def _get_quants(self, locations):
        self.ensure_one()
        domain = []
        base_domain = self._get_base_domain(locations)
        if self.product_selection == "all":
            domain = self._get_domain_all_quants(base_domain)
        elif self.product_selection == "manual":
            domain = self._get_domain_manual_quants(base_domain)
        elif self.product_selection == "one":
            domain = self._get_domain_one_quant(base_domain)
        elif self.product_selection == "lot":
            domain = self._get_domain_lot_quants(base_domain)
        elif self.product_selection == "category":
            domain = self._get_domain_category_quants(base_domain)
        return self.env["stock.quant"].search(domain)

    def _get_base_domain(self, locations):
        return (
            [
                ("location_id", "in", locations.mapped("id")),
            ]
            if self.exclude_sublocation
            else [
                ("location_id", "child_of", locations.child_internal_location_ids.ids),
            ]
        )

    def _get_domain_all_quants(self, base_domain):
        return base_domain

    def _get_domain_manual_quants(self, base_domain):
        self.ensure_one()
        return expression.AND(
            [base_domain, [("product_id", "in", self.product_ids.ids)]]
        )

    def _get_domain_one_quant(self, base_domain):
        self.ensure_one()
        return expression.AND(
            [
                base_domain,
                [
                    ("product_id", "in", self.product_ids.ids),
                ],
            ]
        )

    def _get_domain_lot_quants(self, base_domain):
        self.ensure_one()
        return expression.AND(
            [
                base_domain,
                [
                    ("product_id", "in", self.product_ids.ids),
                    ("lot_id", "in", self.lot_ids.ids),
                ],
            ]
        )

    def _get_domain_category_quants(self, base_domain):
        self.ensure_one()
        return expression.AND(
            [
                base_domain,
                [
                    "|",
                    ("product_id.categ_id", "=", self.category_id.id),
                    ("product_id.categ_id", "in", self.category_id.child_id.ids),
                ],
            ]
        )

    def refresh_stock_quant_ids(self):
        for rec in self:
            rec.stock_quant_ids = rec._get_quants(rec.location_ids)

    def _get_quant_joined_names(self, quants, field):
        return ", ".join(quants.mapped(f"{field}.display_name"))

    def action_state_to_in_progress(self):
        self.ensure_one()
        search_filter = [
            (
                "location_id",
                "child_of" if not self.exclude_sublocation else "in",
                self.location_ids.ids,
            ),
            ("to_do", "=", True),
        ]

        if self.product_ids:
            search_filter.append(("product_id", "in", self.product_ids.ids))
            error_field = "product_id"
            error_message = self.env._(
                "There are active adjustments for the requested products: %(names)s. "
                "Blocking adjustments: %(blocking_names)s"
            )
        else:
            error_field = "location_id"
            error_message = self.env._(
                "There's already an Adjustment in Process "
                "using one requested Location: %(names)s. "
                "Blocking adjustments: %(blocking_names)s"
            )

        quants = self.env["stock.quant"].search(search_filter)
        if quants:
            inventory_ids = self.env["stock.inventory"].search(
                [("stock_quant_ids", "in", quants.ids), ("state", "=", "in_progress")]
            )
            if inventory_ids:
                blocking_names = ", ".join(inventory_ids.mapped("name"))
                names = self._get_quant_joined_names(quants, error_field)
                raise ValidationError(
                    error_message % {"names": names, "blocking_names": blocking_names}
                )

        quants = self._get_quants(self.location_ids)
        self.write(
            {
                # "state": "in_progress",
                "stock_quant_ids": [(6, 0, quants.ids)],
            }
        )
        quants.write(
            {
                "to_do": True,
                "user_id": self.responsible_id,
                "inventory_date": self.date,
                "current_inventory_id": self.id,
            }
        )
        self.action_submit_approval()
        self.state = "in_progress"
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_state_to_wait_approval(self):
        self.ensure_one()
        self._check_inventory_adjustments_is_set()
        self.state = "wait_approval"

    def action_state_to_done(self):
        self.ensure_one()
        self._check_inventory_adjustments_is_set()

        stock_quant_ids = self.stock_quant_ids.filtered(
            lambda q: q.inventory_quantity 
            and q.inventory_diff_quantity != 0
        )

        adjustment_date = fields.Datetime.to_datetime(self.date).strftime("%m%d%y")

        for quant in stock_quant_ids:
            if (
                quant.product_id.tracking == "lot"
                and not quant.lot_id
            ):
                
                lot_name = "{}-{}-{}".format(
                    quant.product_id.default_code,
                    adjustment_date,
                    self.acumatica_ref_doc,
                )

                lot = self.env["stock.lot"].create({
                    "name": lot_name,
                    "product_id": quant.product_id.id,
                    "company_id": quant.company_id.id,
                })

                quant.write({
                    "lot_id": lot.id,
                })

            quant.action_apply_inventory()

        self.state = "done"
        self.stock_quant_ids.filtered(
            lambda q: q.current_inventory_id.id == self.id
        ).update(
            {
                "to_do": False,
                "user_id": False,
                "inventory_date": False,
                "current_inventory_id": False,
            }
        )
        return {
                    "type": "ir.actions.client",
                    "tag": "reload",
                }

    def action_auto_state_to_done(self):
        self.ensure_one()
        if not any(self.stock_quant_ids.filtered(lambda sq: sq.to_do)):
            self.action_state_to_done()
        return

    def action_state_to_draft(self):
        self.ensure_one()

        quants = self.stock_quant_ids.filtered(
            lambda q: q.current_inventory_id.id == self.id
        )

        for quant in quants:
            quant.inventory_quantity = quant.quantity

            quant.write({
                "to_do": False,
                "user_id": False,
                "inventory_date": False,
                "current_inventory_id": False,
            })

        self.write({
            "state": "draft",
            "stock_quant_ids": False,
        })

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_state_to_cancel(self):
        self.ensure_one()
        self._check_action_state_to_cancel()
        self.write(
            {
                "state": "cancel",
            }
        )

    def _check_inventory_adjustments_is_set(self):
        for rec in self:
            adjusted_stock_quant_ids = rec.stock_quant_ids.filtered(lambda q: q.inventory_diff_quantity != 0)
            if not adjusted_stock_quant_ids:
                raise UserError(
                    self.env._(
                        "You cannot do this action because there are no adjustments made."
                    )
                )

    def _check_action_state_to_cancel(self):
        for rec in self:
            if not rec.action_state_to_cancel_allowed:
                raise UserError(
                    self.env._(
                        "You can't cancel this inventory %(display_name)s.",
                        display_name=rec.display_name,
                    )
                )

    def action_view_inventory_adjustment(self):
        self.ensure_one()

        result = self.env["stock.quant"].action_view_inventory()
        
        allowed_locations = (
            self.location_ids
            | self.location_ids.child_internal_location_ids
        )
        
        context = result.get("context", {})
        context.update({
            "search_default_to_do": 1,
            "inventory_id": self.id,
            "inventory_location_ids": allowed_locations.ids,
            "default_to_do": True,
            "default_current_inventory_id": self.id,
            "default_location_id": allowed_locations.ids[0] or False,
        })

        result.update({
            "domain": [
                ("current_inventory_id", "=", self.id),
            ],
            "search_view_id": self.env.ref(
                "stock.quant_search_view"
            ).id,
            "context": context,
        })

        return result

    def action_view_stock_moves(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "stock_inventory.action_view_stock_move_line_inventory_tree"
        )
        result["domain"] = [("inventory_adjustment_id", "=", self.id)]
        result["context"] = {}
        return result

    def _check_inventory_in_progress_not_override(self):
        for rec in self:
            if rec.state == "in_progress":
                location_condition = [
                    (
                        "location_ids",
                        "child_of" if not rec.exclude_sublocation else "in",
                        rec.location_ids.ids,
                    )
                ]
                if rec.product_ids:
                    product_condition = [
                        ("state", "=", "in_progress"),
                        ("id", "!=", rec.id),
                        ("product_ids", "in", rec.product_ids.ids),
                    ] + location_condition
                    inventories = self.search(product_condition)
                else:
                    inventories = self.search(
                        [("state", "=", "in_progress"), ("id", "!=", rec.id)]
                        + location_condition
                    )
                for inventory in inventories:
                    if any(
                        i in inventory.location_ids.ids for i in rec.location_ids.ids
                    ):
                        raise ValidationError(
                            self.env._(
                                "Cannot have more than one in-progress inventory "
                                "adjustment affecting the same location or product "
                                "at the same time."
                            )
                        )

    @api.constrains("product_selection", "product_ids")
    def _check_one_product_in_product_selection(self):
        for rec in self:
            if len(rec.product_ids) > 1:
                if rec.product_selection == "one":
                    raise ValidationError(
                        self.env._(
                            "When 'Product Selection: One Product' is selected"
                            " you are only able to add one product."
                        )
                    )
                elif rec.product_selection == "lot":
                    raise ValidationError(
                        self.env._(
                            "When 'Product Selection: Lot Serial Number' is selected"
                            " you are only able to add one product."
                        )
                    )

    def _approval_approved(self):
        self.ensure_one()

        if not self.acumatica_ref_doc:
            raise UserError("Acumatica Ref Document tidak boleh kosong.")
        
        self.state = "approved"

    def _approval_rejected(self):
        self.ensure_one()
        self.state = "cancel"

    def unlink(self):
        for adjustment in self:
            if adjustment.state != "draft":
                raise UserError(
                    self.env._(
                        "You can only delete inventory adjustments groups in"
                        " draft state."
                    )
                )
        return super().unlink()
