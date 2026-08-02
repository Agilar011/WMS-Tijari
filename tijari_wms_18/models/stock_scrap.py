from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

class WMSStockScrap(models.Model):
    _inherit = 'stock.scrap'

    scrap_line_ids = fields.One2many(
        "stock.scrap.line",
        "scrap_id",
        string="Scrap Lines",
        copy=False,
    )

    picking_id = fields.Many2one(
        "stock.picking",
        string="Receipt",
        readonly=True,
        copy=False,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("done", "Done"),
        ],
        default="draft",
        string="Status",
        copy=False,
        tracking=True
    )

    availability_state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("available", "Available"),
            ("insufficient", "Insufficient"),
        ],
        default="waiting",
        string="Stock Availability",
        copy=False,
        tracking=True
    )

    last_availability_check = fields.Datetime(
        string="Last Availability Check",
        readonly=True,
        copy=False,
    )        

    def action_validate(self):

        self.ensure_one()

        if self.state == "done":
            raise UserError(_("Scrap has already been validated."))

        if not self.scrap_line_ids:
            raise UserError(_("No scrap lines found."))

        if self.availability_state != "available":
            raise UserError(_("Some products do not have sufficient stock."))
 
        if self.name == _("New"):
            self.name = (
                self.env["ir.sequence"]
                .next_by_code("stock.scrap")
                or _("New")
            )

        for line in self.scrap_line_ids:

            available = self.env["stock.quant"]._get_available_quantity(
                line.product_id,
                line.location_id,
            )
    
            if float_compare(
                available,
                line.demand_qty,
                precision_rounding=line.product_uom_id.rounding,
            ) < 0:
                raise UserError(_(
                    "%s no longer has enough stock. Please check availability again."
                ) % line.product_id.display_name)
        
            move = self.env["stock.move"].create(
                self._prepare_scrap_move_values(line)
            )

            move.with_context(
                is_scrap=True
            )._action_done()


            line.write({
                "move_id": move.id,
                "scrapped_qty": line.demand_qty,
                "availability_state": "available",
            })

        self.write({
            "state": "done",
            "date_done": fields.Datetime.now(),
        })

    def action_done(self):
        self.ensure_one()
        if self.name == _("New"):
            self.name = (
                self.env["ir.sequence"]
                .next_by_code("stock.scrap")
                or _("New")
            )
        for line in self.scrap_line_ids:
            move = line.move_id
            move.with_context(
                is_scrap=True
            )._action_done()

    def action_check_availability(self):
        self.ensure_one()

        if self.state == "done":
            raise UserError(_("Scrap already validated."))

        all_available = True

        for line in self.scrap_line_ids:
            self._check_line_availability(line)

            if line.availability_state != "available":
                all_available = False

        self.availability_state = (
            "available"
            if all_available
            else "insufficient"
        )

        self.last_availability_check = fields.Datetime.now()

        if self.availability_state == "available":
            self.state = "ready"
        else:
            self.state = "draft"

        return True

    def _prepare_base_move_values(self):
        self.ensure_one()

        return {
            "name": self.name,
            "origin": self.origin or self.picking_id.name or self.name,
            "company_id": self.company_id.id,
            "state": "draft",
            "scrapped": True,
            "scrap_id": self.id,
            "picked": True,
            "picking_id": self.picking_id.id,
            "location_dest_id": self.scrap_location_id.id,
        }

    def _prepare_scrap_move_values(self, line):
        vals = self._prepare_base_move_values()

        vals.update({
            "product_id": line.product_id.id,
            "product_uom": line.product_uom_id.id,
            "product_uom_qty": line.demand_qty,
            "location_id": line.location_id.id,
            "move_line_ids": [(0, 0, {
                "product_id": line.product_id.id,
                "product_uom_id": line.product_uom_id.id,
                "quantity": line.demand_qty,
                "location_id": line.location_id.id,
                "location_dest_id": self.scrap_location_id.id,
            })],
        })

        return vals
    
    def _check_line_availability(self, line):
        move = line.move_id


        available_qty = self.env["stock.quant"]._get_available_quantity(
            line.product_id,
            line.location_id,
        )

        line.available_qty = available_qty

        if float_compare(
            available_qty,
            line.demand_qty,
            precision_rounding=line.product_uom_id.rounding,
        ) >= 0:
            line.availability_state = "available"
        else:
            line.availability_state = "insufficient"

class StockScrapLine(models.Model):
    _name = "stock.scrap.line"
    _description = "Stock Scrap Line"
    _order = "id"

    scrap_id = fields.Many2one(
        "stock.scrap",
        required=True,
        ondelete="cascade",
    )

    name = fields.Char(string='Description')

    company_id = fields.Many2one(
        related="scrap_id.company_id",
        store=True,
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        required=True,
        readonly=True,
    )

    product_uom_id = fields.Many2one(
        "uom.uom",
        readonly=True,
        string="Unit"
    )

    demand_qty = fields.Float(
        string="Demand Qty",
        digits="Product Unit of Measure",
        readonly=True,
    )

    available_qty = fields.Float(
        string="Available Qty",
        digits="Product Unit of Measure",
        copy=False,
        readonly=True,
    )

    scrapped_qty = fields.Float(
        string="Scrapped Qty",
        digits="Product Unit of Measure",
        copy=False,
        readonly=True,
    )

    availability_state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("available", "Available"),
            ("insufficient", "Insufficient"),
        ],
        default="waiting",
        string="Status",
        copy=False,
        tracking=True
    )      

    move_id = fields.Many2one(
        "stock.move",
        copy=False,
        readonly=True,
    )  

    # move_line_ids = fields.One2many(
    #     related="move_id.move_line_ids",
    #     readonly=True,
    # )

    move_state = fields.Selection(
        related="move_id.state",
        store=True,
        readonly=True,
    )

    location_id = fields.Many2one(
        "stock.location",
        readonly=True,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        readonly=True,
    )

    receipt_move_id = fields.Many2one(
        "stock.move",
        string="Receipt Move",
        readonly=True,
    )

    def action_show_details(self):
        self.ensure_one()
        return self.move_id.action_show_details()

class ScrapStockPicking(models.Model):
    _inherit = 'stock.picking'
    _description = 'ScrapStockPicking'

    scrap_ids = fields.One2many(
        "stock.scrap",
        "picking_id",
        string="Scraps",
    )

    show_generate_scrap = fields.Boolean(
        compute="_compute_show_generate_scrap"
    )

    @api.depends(
        "state",
        "adt_type",
        "scrap_ids",
        # "picking_type_id.operation_category",
    )
    def _compute_show_generate_scrap(self):
        for rec in self:
            rec.show_generate_scrap = (
                rec.state == "done"
                and rec.adt_type == "Disposal"
                # and rec.picking_type_id.operation_category == "receive"
                and not rec.scrap_ids
            )

    def action_generate_scrap(self):
        self.ensure_one()

        if not self.location_dest_id:
            raise UserError(_("Destination Location is required."))

        if self.state != "done":
            raise UserError(_("Only completed receipts can generate Scrap."))
        
        # if self.scrap_ids:
        #     raise UserError(_("Scrap has already been generated."))

        moves = self.move_ids.filtered(
            lambda m: m.state == "done"
            and m.quantity > 0
        )

        if not moves:
            raise UserError(_(
                "No available stock moves to generate Scrap."
            ))

        first_move = moves[0]

        scrap_location = self.env["stock.location"].search([
            ("scrap_location", "=", True),
            ("company_id", "in", [False, self.company_id.id]),
        ], limit=1)

        if not scrap_location:
            raise UserError(_("No Scrap Location configured."))

        scrap_lines = [
            (0,0, self._prepare_scrap_line_vals(move)) 
            for move in moves
        ]

        scrap = self.env["stock.scrap"].create({
            "origin": self.name,
            "company_id": self.company_id.id,
            "picking_id": self.id,
            "location_id": self.location_dest_id.id,
            "scrap_location_id": scrap_location.id,
            # dummy
            "product_id": first_move.product_id.id,
            "product_uom_id": first_move.product_uom.id,
            "scrap_qty": first_move.quantity,
            "scrap_line_ids": scrap_lines,
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.scrap",
            "view_mode": "form",
            "res_id": scrap.id,
        }

    def _prepare_scrap_line_vals(self, move):
            return {
                "receipt_move_id": move.id,
                "product_id": move.product_id.id,
                "product_uom_id": move.product_uom.id,
                "demand_qty": move.quantity,
                "location_id": move.location_dest_id.id,
                "name": move.description_picking 
                        or move.product_id.display_name,   
            }