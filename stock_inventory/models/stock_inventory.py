from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression

import logging
from time import perf_counter

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

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        compute="_compute_product_id",
        inverse="_inverse_product_id",
        domain="['|', ('company_id', '=', company_id), ('company_id', '=', False)]",
    )

    product_count = fields.Integer(
        string="Products",
        compute="_compute_product_count",
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

    @api.depends("product_ids")
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_ids)

    @api.depends("product_ids")
    def _compute_product_id(self):
        for rec in self:
            rec.product_id = rec.product_ids[:1] if len(rec.product_ids) == 1 else False

    def _inverse_product_id(self):
        for rec in self:
            rec.product_ids = [(6, 0, rec.product_id.ids)]

    def action_open_product_selection(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Products"),
            "res_model": "stock.inventory.product.selection.wizard",
            "view_mode": "form",
            "views": [(
                self.env.ref(
                    "stock_inventory.view_inventory_product_selection_wizard_form"
                ).id,
                "form",
            )],
            "target": "new",
            "context": {
                "default_inventory_id": self.id,
                "default_product_ids": [(6, 0, self.product_ids.ids)],
                "default_product_id": self.product_ids[:1].id,
            },
        }

    def _get_quant_joined_names(self, quants, field):
        return ", ".join(quants.mapped(f"{field}.display_name"))

    def action_state_to_in_progress(self):
        self.ensure_one()
        if not self.env.context.get("skip_inventory_operation_queue"):
            return self._queue_inventory_operation("begin")
        if self.product_selection in ("manual", "one", "lot") and not self.product_ids:
            raise UserError(
                self.env._("Select at least one product before beginning this adjustment.")
            )
        started_at = perf_counter()
        _logger.info(
            "Inventory adjustment begin id=%s name=%s phase=start "
            "locations=%s product_selection=%s product_count=%s exclude_sublocation=%s",
            self.id,
            self.name,
            len(self.location_ids),
            self.product_selection,
            len(self.product_ids),
            self.exclude_sublocation,
        )
        phase_started = perf_counter()
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
        blocking_count = 0
        if quants:
            inventory_ids = self.env["stock.inventory"].search(
                [("stock_quant_ids", "in", quants.ids), ("state", "=", "in_progress")]
            )
            blocking_count = len(inventory_ids)
            if inventory_ids:
                blocking_names = ", ".join(inventory_ids.mapped("name"))
                names = self._get_quant_joined_names(quants, error_field)
                raise ValidationError(
                    error_message % {"names": names, "blocking_names": blocking_names}
                )
        _logger.info(
            "Inventory adjustment begin id=%s phase=check_conflicts elapsed=%.3fs "
            "quant_count=%s blocking_adjustments=%s",
            self.id,
            perf_counter() - phase_started,
            len(quants),
            blocking_count,
        )

        phase_started = perf_counter()
        quants = self._get_quants(self.location_ids)
        self.write(
            {
                # "state": "in_progress",
                "stock_quant_ids": [(6, 0, quants.ids)],
            }
        )
        # A new adjustment starts with no counted values. Odoo keeps the
        # counted quantity separately from the on-hand quantity, and the
        # inventory_quantity_set flag distinguishes an explicit count of 0
        # from a quant that has not been counted yet.
        quants.action_clear_inventory_quantity()
        quants.write(
            {
                "to_do": True,
                "user_id": self.responsible_id,
                "inventory_date": self.date,
                "current_inventory_id": self.id,
            }
        )
        _logger.info(
            "Inventory adjustment begin id=%s phase=load_and_assign_quants "
            "elapsed=%.3fs quant_count=%s",
            self.id,
            perf_counter() - phase_started,
            len(quants),
        )

        phase_started = perf_counter()
        self.action_submit_approval()
        self.state = "in_progress"
        _logger.info(
            "Inventory adjustment begin id=%s name=%s phase=approval_and_state "
            "elapsed=%.3fs",
            self.id,
            self.name,
            perf_counter() - phase_started,
        )
        _logger.info(
            "Inventory adjustment begin id=%s name=%s phase=complete total=%.3fs",
            self.id,
            self.name,
            perf_counter() - started_at,
        )
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_state_to_wait_approval(self):
        self.ensure_one()
        self._check_inventory_adjustments_is_set()
        self.state = "wait_approval"

    def _check_inventory_adjustments_doc(self):
        self.ensure_one()
        Staging = self.env['acumatica.inventory.adjustment.staging'].sudo()
        staging_lines = Staging.search([
            ('ref_nbr', '=', self.acumatica_ref_doc),
        ]) if self.acumatica_ref_doc else Staging.browse()

        if not staging_lines:
            raise UserError((
                'Data Inventory Adjustment dengan Reference Number %s tidak ditemukan di staging.'
            ) % (self.acumatica_ref_doc or '-'))
        if staging_lines.filtered('is_used'):
            raise UserError((
                'Data Inventory Adjustment dengan Reference Number %s sudah pernah digunakan.'
            ) % self.acumatica_ref_doc)

        staging_lines.write({'is_used': True})

    def action_state_to_done(self):
        self.ensure_one()
        if not self.env.context.get("skip_inventory_operation_queue"):
            return self._queue_inventory_operation("apply")
        started_at = perf_counter()
        _logger.info(
            "Inventory adjustment apply id=%s name=%s phase=start",
            self.id,
            self.name,
        )

        phase_started = perf_counter()
        self._check_inventory_adjustments_is_set()
        self._check_inventory_adjustments_doc()

        stock_quant_ids = self.stock_quant_ids.filtered(
            lambda quant: (
                quant.inventory_quantity_set
                and quant.inventory_diff_quantity != 0
            )
        )
        quants_to_clear = self.stock_quant_ids.filtered(
            lambda quant: quant.current_inventory_id == self
        )

        outdated_quants = stock_quant_ids.filtered("is_outdated")
        if outdated_quants:
            names = ", ".join(outdated_quants.mapped("product_id.display_name"))
            raise UserError(self.env._(
                "Some counted stock changed after the count and cannot be applied. "
                "Recount these products first: %(products)s",
                products=names,
            ))
        _logger.info(
            "Inventory adjustment apply id=%s phase=validate elapsed=%.3fs "
            "quant_count=%s quant_to_clear=%s",
            self.id,
            perf_counter() - phase_started,
            len(stock_quant_ids),
            len(quants_to_clear),
        )

        phase_started = perf_counter()
        adjustment_date = fields.Datetime.to_datetime(self.date).strftime("%m%d%y")

        # Build lot names up front and fetch any matching lots in one query.
        # Quants for the same product/company (including different locations)
        # must share one lot during this adjustment.
        lotless_quants = stock_quant_ids.filtered(lambda quant: not quant.lot_id)
        lot_name_by_quant_id = {
            quant.id: "{}-{}-{}".format(
                quant.product_id.default_code,
                adjustment_date,
                self.acumatica_ref_doc,
            )
            for quant in lotless_quants
        }
        lots_by_key = {}
        inventory_company_id = self.company_id.id
        if lotless_quants:
            existing_lots = self.env["stock.lot"].search(
                [
                    ("product_id", "in", lotless_quants.product_id.ids),
                    ("name", "in", list(set(lot_name_by_quant_id.values()))),
                    ("company_id", "in", [inventory_company_id, False]),
                ],
                order="company_id desc, id",
            )
            for lot in existing_lots:
                key = (lot.product_id.id, lot.name, lot.company_id.id)
                lots_by_key.setdefault(key, lot)
        _logger.info(
            "Inventory adjustment apply id=%s phase=lot_lookup elapsed=%.3fs "
            "lotless_quants=%s existing_lots=%s",
            self.id,
            perf_counter() - phase_started,
            len(lotless_quants),
            len(lots_by_key),
        )

        # Collect missing lots by product/name first. Multiple location quants
        # for the same product share a single lot for this adjustment.
        phase_started = perf_counter()
        missing_lot_vals = {}
        for quant in lotless_quants:
            lot_name = lot_name_by_quant_id[quant.id]
            lot_key = (quant.product_id.id, lot_name, inventory_company_id)
            shared_lot_key = (quant.product_id.id, lot_name, False)
            if not lots_by_key.get(lot_key) and not lots_by_key.get(shared_lot_key):
                missing_lot_vals.setdefault(lot_key, {
                    "name": lot_name,
                    "product_id": quant.product_id.id,
                    "company_id": inventory_company_id,
                })

        _logger.info(
            "Inventory adjustment apply id=%s phase=resolve_lots elapsed=%.3fs "
            "lotless_quants=%s existing_lots=%s missing_lots=%s",
            self.id,
            perf_counter() - phase_started,
            len(lotless_quants),
            len(lots_by_key),
            len(missing_lot_vals),
        )

        phase_started = perf_counter()
        if missing_lot_vals:
            created_lots = self.env["stock.lot"].create(list(missing_lot_vals.values()))
            for lot in created_lots:
                lots_by_key[(lot.product_id.id, lot.name, lot.company_id.id)] = lot
        _logger.info(
            "Inventory adjustment apply id=%s phase=create_lots elapsed=%.3fs "
            "created_lots=%s",
            self.id,
            perf_counter() - phase_started,
            len(missing_lot_vals),
        )

        quant_ids_by_lot = {}
        for quant in lotless_quants:
            lot_name = lot_name_by_quant_id[quant.id]
            lot_key = (quant.product_id.id, lot_name, inventory_company_id)
            shared_lot_key = (quant.product_id.id, lot_name, False)
            lot = lots_by_key.get(lot_key) or lots_by_key.get(shared_lot_key)
            if lot:
                quant_ids_by_lot.setdefault(lot.id, []).append(quant.id)

        phase_started = perf_counter()
        Quant = self.env["stock.quant"]
        for lot_id, quant_ids in quant_ids_by_lot.items():
            Quant.browse(quant_ids).write({"lot_id": lot_id})
        _logger.info(
            "Inventory adjustment apply id=%s phase=assign_lots elapsed=%.3fs "
            "quant_count=%s lot_count=%s",
            self.id,
            perf_counter() - phase_started,
            len(lotless_quants),
            len(quant_ids_by_lot),
        )

        phase_started = perf_counter()
        result = stock_quant_ids.with_context(
            set_inventory_quantity_auto_apply=True,
            skip_stock_inventory_auto_complete=True,
        ).action_apply_inventory()
        if result:
            raise UserError(self.env._(
                "Odoo could not apply the inventory adjustment for %(product)s.",
                product=stock_quant_ids[:1].product_id.display_name,
            ))
        _logger.info(
            "Inventory adjustment apply id=%s phase=apply_moves elapsed=%.3fs "
            "quant_count=%s",
            self.id,
            perf_counter() - phase_started,
            len(stock_quant_ids),
        )

        phase_started = perf_counter()
        remaining_quants = stock_quant_ids.filtered(
            lambda quant: quant.inventory_diff_quantity != 0
        )
        if remaining_quants:
            names = ", ".join(remaining_quants.mapped("product_id.display_name"))
            raise UserError(self.env._(
                "Some inventory differences remain unapplied: %(products)s",
                products=names,
            ))

        # Inventory adjustment moves are completed immediately by Odoo.
        # Remove stale links left by earlier matching logic that could attach
        # an unrelated or still-open move line to this adjustment.
        invalid_move_lines = self.stock_move_ids.filtered(
            lambda line: line.state != "done" or not line.move_id.is_inventory
        )
        invalid_move_lines.write({"inventory_adjustment_id": False})

        self.state = "done"
        quants_to_clear.write({
            "to_do": False,
            "user_id": False,
            "inventory_date": False,
            "current_inventory_id": False,
        })
        _logger.info(
            "Inventory adjustment apply id=%s phase=verify_and_cleanup elapsed=%.3fs "
            "invalid_move_lines=%s cleared_quants=%s",
            self.id,
            perf_counter() - phase_started,
            len(invalid_move_lines),
            len(quants_to_clear),
        )
        _logger.info(
            "Inventory adjustment apply id=%s name=%s phase=complete total=%.3fs",
            self.id,
            self.name,
            perf_counter() - started_at,
        )
        return {
                    "type": "ir.actions.client",
                    "tag": "reload",
                }

    def action_auto_state_to_done(self):
        self.ensure_one()
        if not any(self.stock_quant_ids.filtered(lambda sq: sq.to_do)):
            pending_counted_quants = self.stock_quant_ids.filtered(
                lambda quant: (
                    quant.inventory_quantity_set
                    and quant.inventory_diff_quantity != 0
                )
            )
            if pending_counted_quants:
                self.with_context(skip_inventory_operation_queue=True).action_state_to_done()
            elif self.state == "approved" and self.count_stock_moves:
                self.state = "done"
                self.stock_quant_ids.filtered(
                    lambda quant: quant.current_inventory_id == self
                ).write({
                    "to_do": False,
                    "user_id": False,
                    "inventory_date": False,
                    "current_inventory_id": False,
                })
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
            adjusted_stock_quant_ids = rec.stock_quant_ids.filtered(
                lambda quant: (
                    quant.inventory_quantity_set
                    and quant.inventory_diff_quantity != 0
                )
            )
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
            "inventory_company_id": self.company_id.id,
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
