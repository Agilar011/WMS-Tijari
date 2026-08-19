
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
import logging
_logger = logging.getLogger(__name__)

class StockMoveLine(models.Model):
    _inherit  = 'stock.move.line'
    _description = "Stock Move Line"
    # Bisa dihapus sebelum golive
    adt_dest_location_id = fields.Many2one(
        "stock.location",
        related="move_id.adt_dest_location_id",
        store=True,
        readonly=True,
    )

    adt_dest_location = fields.Char(
        string="Mapped Location",
        related="move_id.adt_dest_location",
        store=True,
        readonly=True,
    )

    lot_button = fields.Char(string="Lot Button", compute="_compute_lot_button")
    auto_input_code = fields.Boolean(string="Auto Input Code")

    confirmation_location_code = fields.Char(
        string='Confirmation Location Code',
        help='Scanned / input location code for confirmation.',
        store=True
    )
    confirmation_lot_code = fields.Char(
        string='Confirmation Lot Code',
        help='Scanned / input lot code for confirmation.',
        store=True
    )
    # matching = fields.Selection([
    #     ('match', 'Match'),
    #     ('not_match', 'Not Match')
    # ], string='Matching Status',
    #    store=True)

    matching = fields.Selection(
        [
            ('match', 'Match'),
            ('not_match', 'Not Match')
        ],
        store=True,
    )
    putaway_status = fields.Selection(
        [
            ('finished', 'Finished'),
            ('unfinished', 'Unfinished')
        ],
        string='Putaway Status',
        default='unfinished',
    )

    picker_status = fields.Selection(
        [
            ('finished', 'Finished'),
            ('unfinished', 'Unfinished')
        ],
        string='Picker Status',
        default='unfinished',
    )
    location_putaway_id = fields.Many2one(
        "stock.location",
        string="Putaway Location",
    )

    operation_category = fields.Selection(related='picking_id.picking_type_id.operation_category', string='Operation Category', store=True, readonly=True)

    allocation_storage = fields.Many2one(
        "stock.location",
        string="Allocation Storage",
    )

    allocation_id = fields.Char(string='Allocation ID')
    allocation_note = fields.Text(string='Allocation Note')
    allocation_Description = fields.Text(string='Allocation Description')
    allocation_InventoryID = fields.Char(string='Allocation Inventory ID')
    allocation_LocationID = fields.Char(string='Allocation Location ID')
    allocation_Quantity = fields.Float(string='Allocation Quantity')
    allocation_SplitLineNbr = fields.Integer(string='Allocation Split Line Number')
    allocation_UOM = fields.Char(string='Allocation UOM')
    confirmation_quantity = fields.Float(string='Confirmation Qty')

    picking_code = fields.Selection(
        related='picking_id.picking_type_code',
        store=False,
    )

    origin = fields.Char(
        related='picking_id.origin',
        string='Source Document',
        readonly=True,
        store=False,
    )
    matching_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Confirm Lot",
        domain="[('id', 'in', allowed_matching_lot_ids)]",
        store=True
    )
    matching_loc_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Confirm Location",
        domain="[('id', 'child_of', adt_dest_location_id)]",
        store=True
    )
    allowed_matching_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        string="Allowed Matching Lots",
        compute="_compute_allowed_matching_lot_ids",
    )

    unfiltered_dest = fields.Boolean(
        string="Unfiltered Destination",
        default=False,
    )

    source_location_id = fields.Many2one(
        "stock.location",
        string="Source Location",
        domain="[('id', 'child_of', location_id)]",
    )

    product_lot_id = fields.Many2one(
        "stock.lot",
        string="Lot",
        domain="[('id', 'in', temp_lot_ids)]",
    )

    selected_quant_id = fields.Many2one(
        "stock.quant",
        string="Selected Quant",
        domain="[('id', 'in', temp_quant_ids)]",
        readonly=True,
    )

    temp_quant_ids = fields.Many2many(
        "stock.quant",
        string="Temporary Quants",
        compute="_compute_temp_quant_ids",
        store=False,
    )
    temp_lot_ids = fields.Many2many(
        "stock.lot",
        string="Temporary Lots",
        compute="_compute_temp_quant_ids",
        store=False,
    )

    available_lot_ids = fields.Many2many(
        "stock.lot",
        compute="_compute_available_quant_fields",
    )

    available_location_ids = fields.Many2many(
        "stock.location",
        compute="_compute_available_quant_fields",
    )

    picking_type_name = fields.Char(
        related="move_id.picking_type_name",
        store=False,
    )
   
    allowed_lot_ids = fields.Many2many(
        "stock.lot",
        string="Allowed Lots",
        compute="_compute_allowed_lot_ids",
    )

    second_matching = fields.Char(string="Status")

    adt_owner_id = fields.Many2one(
        "res.partner",
        related="move_id.owner_id",
        store=True,
        readonly=True,
    )

    @api.depends(
        "move_id",
        "move_id.move_line_ids.lot_id",
    )

    def _compute_allowed_lot_ids(self):
        print('def _compute_allowed_lot_ids')
        for line in self:
            if not line.move_id:
                line.allowed_lot_ids = False
                continue

            lots = line.move_id.move_line_ids.mapped("lot_id")
            line.allowed_lot_ids = lots
            

    @api.depends(
        "picking_id.move_line_ids.lot_id",
        "picking_id.move_ids.move_line_ids.lot_id",
    )
    def _compute_allowed_matching_lot_ids(self):
        for line in self:
            line.allowed_matching_lot_ids = line.picking_id.move_line_ids.mapped("lot_id") or line.move_id.move_line_ids.mapped("lot_id")

    def _get_owner_quant_domain(self):
        self.ensure_one()
        domain = [
            ("product_id", "=", self.product_id.id),
            ("location_id", "child_of", self.source_location_id.id),
            ("quantity", ">", 0),
            ("lot_id", "!=", False),
        ]
        if self.move_id.picking_id.adt_type == 'Toko Pegang DO' and self.move_id.owner_id:
            domain.append(("owner_id", "=", self.move_id.owner_id.id))
        return domain

    @api.depends("product_id", "source_location_id", "move_id.owner_id", "move_id.picking_id.adt_type")
    def _compute_temp_quant_ids(self):
        print('def _compute_temp_quant_ids(self):')
        for line in self:
            if line.move_id.transaction_type == 'outbound' and line.move_id.picking_type_name == 'Pack':
                print('Auto matching source_location_id and product_lot_id in Pack transaction')
                print(line.location_id.id)
                print(line.lot_id.id)
                line.source_location_id = line.location_id
                line.product_lot_id = line.lot_id.id
                line.lot_name = line.lot_id.name

        # _logger.info("Running Onchange on pick type: %s", self.picking_type_name)
        Quant = self.env["stock.quant"]

        for line in self:

            line.temp_quant_ids = False
            line.temp_lot_ids = False

            if not line.product_id or not line.source_location_id:
                continue

            domain = line._get_owner_quant_domain()

            # ===========================
            # TAMBAHAN UNTUK TOKO PEGANG DO
            # ===========================
            print(line.move_id.picking_id.adt_type)
            if line.move_id.picking_id.adt_type == 'Toko Pegang DO' and line.move_id.owner_id:
                print(f"Running domain with owner : {line.move_id.owner_id.name} ")
            # ===========================

            quants = Quant.search(domain)

            line.temp_quant_ids = [(6, 0, quants.ids)]
            line.temp_lot_ids = [(6, 0, quants.mapped("lot_id").ids)]

            for item in line.temp_quant_ids:
                print(f"Quant domained: {item.lot_id.name}")

            print(f"Quant domain: {line.temp_quant_ids}")

    @api.onchange("lot_id", "location_id")
    def _onchange_quant_fields(self):

        return self._refresh_quant()

    @api.onchange("product_id", "source_location_id")
    def _onchange_source_location(self):
        print('def _onchange_source_location(self)')
        print(f"Search product: {self.product_id.name} in loc: {self.source_location_id.name}")
        self.product_lot_id = False
        self.selected_quant_id = False
        # self.quant_id = False

        if not self.product_id or not self.source_location_id:
            return {
                "domain": {
                    "product_lot_id": [("id", "=", False)]
                }
            }

        quants = self.env["stock.quant"].search(self._get_owner_quant_domain())

        lot_ids = quants.mapped("lot_id").ids
        print(f"Lot found: {lot_ids}")

        return {
            "domain": {
                "product_lot_id": [("id", "in", lot_ids)]
            }
        }
    
    @api.onchange("product_lot_id")
    def _onchange_product_lot(self):
        print('def _onchange_product_lot(self)')
        self.selected_quant_id = False
        # self.quant_id = False

        if not (
            self.product_id
            and self.source_location_id
            and self.product_lot_id
        ):
            return

        quant = self.env["stock.quant"].search(
            self._get_owner_quant_domain() + [("lot_id", "=", self.product_lot_id.id)],
            order="quantity desc",
            limit=1,
        )
        print(f"Quant found: {quant}")

        self.selected_quant_id = quant
        self.quant_id = quant

    @api.model_create_multi
    def create(self, vals_list):
        move_lines = super().create(vals_list)
        move_lines.mapped('picking_id')._sync_adt_quantities_from_moves()
        # if not move_lines.parent_location_id:
        #     move_lines.parent_location_id = move_lines.adt_dest_location_id
        # if not move_lines.parent_location_id:
        #     for line in move_lines:
        #         line.parent_location_id = line.adt_dest_location_id

        return move_lines
        

    def write(self, vals):
        pickings = self.mapped('picking_id')
        res = super().write(vals)
        pickings |= self.mapped('picking_id')

        if {'quantity', 'move_id', 'picking_id'} & set(vals):
            pickings._sync_adt_quantities_from_moves()

        # matching_inputs = {
        #     'matching_lot_id', 'matching_loc_dest_id',
        #     'source_location_id', 'product_lot_id',
        #     'location_id', 'location_dest_id', 'lot_id',
        # }
        # if not self.env.context.get('skip_matching_sync') and matching_inputs & set(vals):
        #     for line in self:
        #         matching = line._get_matching_status() if not line.move_id.is_manufacturing else line._get_matching_status_mo()
        #         status_vals = {'matching': matching}
        #         if line.picking_id.picking_type_id.name in ('Pick', 'Pick Internal', 'Internal Transfers') or line.move_id.is_manufacturing:
        #             status_vals['second_matching'] = (
        #                 'Match' if matching == 'match' else 'Not Match'
        #             )
                
        #         if any(line[field] != value for field, value in status_vals.items()):
        #               line.with_context(skip_matching_sync=True).write(status_vals)
        
        self._update_move_picked()

        return res

    def unlink(self):
        pickings = self.mapped('picking_id')
        res = super().unlink()
        pickings._sync_adt_quantities_from_moves()
        return res

    # @api.onchange('confirmation_lot_code', 'confirmation_location_code', 'matching', 'auto_input_code')
    # def _compute_matching(self):
    #     print(">>> Computing matching status...") # Cek di terminal Odoo
    #     for line in self:
    #         picking_type = line.picking_id.picking_type_id

    #         # 1. Validasi awal: pastikan input user tidak kosong atau hanya berisi spasi
    #         conf_loc = str(line.confirmation_location_code or '').strip()
    #         conf_lot = str(line.confirmation_lot_code or '').strip()

    #         loc_ok = False
    #         lot_ok = False
            
    #         if not conf_loc or not conf_lot:
    #             line.matching = 'not_match'
    #             continue
            
    #         if picking_type and picking_type.name in ('Pick'):
    #             print('run validate code for pick')
    #             loc_code = str(line.location_id.unique_code or '').strip()
    #             product_code = str(line.lot_id.name or '').strip()

    #             loc_ok = bool(loc_code and conf_loc.lower() == loc_code.lower())
    #             lot_ok = bool(product_code and conf_lot.lower() == product_code.lower())

    #         if picking_type and picking_type.name in ('Receipts'):
    #             print('run validate code for receipt')
    #             loc_code = str(line.location_dest_id.unique_code or '').strip()
    #             product_code = str(line.lot_id.name or '').strip()

    #             loc_ok = bool(loc_code and conf_loc.lower() == loc_code.lower())
    #             lot_ok = bool(product_code and conf_lot.lower() == product_code.lower())


    #         if not picking_type or picking_type.name not in ('Pick', 'Pack', 'Receipts'):
    #             raise ValueError('validation is not config yet')

    #         line.matching = 'match'

    #         # # Untuk PACK → cek lot + unique_code (aku anggap SOURCE location)
    #         # elif operation_category == 'delivery':
    #         #     print(f">>> picking_type_code: {line.picking_type_id.code if line.picking_id and line.picking_id.picking_type_id else 'N/A'}") # Cek di terminal Odoo
    #         #     print(f">>> Operation Category: DELIVERY") # Cek di terminal Odoo
    #         #     print(f">>> Evaluating line {line.id} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id.name if line.lot_id else 'N/A'}") # Cek di terminal Odoo
    #         #     # kalau belum ada input sama sekali, invisible
    #         #     if line.confirmation_location_code or line.confirmation_lot_code:
    #         #         loc_code = line.location_id.unique_code if line.location_id else (line.quant_id.location_id.unique_code if line.quant_id and line.quant_id.location_id else 'N/A')
    #         #         lot_code = line.lot_id.name if line.lot_id else (line.quant_id.lot_id.name if line.quant_id and line.quant_id.lot_id else 'N/A')
    #         #         print(f">>> Information to match : Lot Code = {lot_code}, Location Code = {loc_code}") # Cek di terminal Odoo
    #         #         # src_loc = line.location_id
    #         #         # src_code = src_loc.unique_code if src_loc else False
    #         #         # lot = line.lot_id
    #         #         # src_code = line.quant_id.location_id.unique_code if line.quant_id.location_id else False
    #         #         # lot = line.quant_id.lot_id.name

    #         #         # kondisi match
    #         #         loc_ok = bool(loc_code and line.confirmation_location_code == loc_code)
    #         #         lot_ok = bool(lot_code and line.confirmation_lot_code == lot_code)

    #         #         if loc_ok and lot_ok:
    #         #             matching = 'match'
    #         #         else:
    #         #             matching = 'not_match'

    #         #         print(f">>> Location Match: {loc_ok}, Lot Match: {lot_ok}, Overall Matching Status: {matching}") # Cek di terminal Odoo

    #         # if line.matching_lot_id.id == line.lot_id.id and line.matching_loc_dest_id.id == line.location_dest_id.id:
    #         #     matching = 'match'

    #         # line.matching = matching


    @api.onchange('product_id')
    def _onchange_product_copy_previous_lot(self):
        _logger.info('def _onchange_product_copy_previous_lot(self)')

        for line in self:
            if not line.move_id:
                continue

            previous_lines = line.move_id.move_line_ids.filtered(
                lambda l: l != line
            )
            last_lot_line = previous_lines.filtered(lambda l: l.lot_id)

            if last_lot_line:
                line.lot_id = last_lot_line[-1].lot_id

            if not line.env.context.get('copy_previous_picker_location'):
                continue

            last_location_line = previous_lines.filtered(
                lambda l: l.location_id or l.location_dest_id or l.source_location_id
            )
            if not last_location_line:
                continue

            previous_line = last_location_line[-1]
            if previous_line.location_id:
                line.location_id = previous_line.location_id
            if previous_line.location_dest_id:
                line.location_dest_id = previous_line.location_dest_id
            if previous_line.source_location_id:
                line.source_location_id = previous_line.source_location_id
                
    @api.onchange('quant_id')
    def _onchange_move_line_ids(self):
        print('def _onchange_move_line_ids(self)')
        for line in self:
            if line.quant_id:
                print(f">>> Onchange move_line_ids: quant_id changed for line {line.id}, new quant_id: {line.quant_id.id}, lot_id: {line.quant_id.lot_id.name if line.quant_id.lot_id else 'N/A'}") # Cek di terminal Odoo
                # line.lot_id = line.quant_id.lot_id.name if line.quant_id.lot_id else line.lot_name
                line.lot_name = line.quant_id.lot_id.name if line.quant_id.lot_id else line.lot_name
                print(f">>> changed lot_name: {line.lot_name}") # Cek di terminal Odoo
            if not line.lot_name and line.lot_id:
                print(f">>> Onchange move_line_ids: setting lot_name for line {line.id} based on lot_id {line.lot_id.name}") # Cek di terminal Odoo
                line.lot_name = line.lot_id.name

            
    @api.onchange('auto_input_code')
    def _compute_auto_input_code(self):
        print('def _compute_auto_input_code(self)')
        for line in self:
            if line.auto_input_code:
                print(f">>> Auto input code triggered for line {line.id}") # Cek di terminal Odoo
                line.matching = 'match'
                sml = self.env['stock.move.line'].browse(line._origin.id)
                sml.write({'matching': 'match'})


    def action_generate_selected_lot(self):
        for line in self:
            line.generate_lot()

        return True
        
    def generate_lot(self):
        for line in self:
            print(f"BEFORE product={line.product_id.display_name} move={line.move_id.product_id.display_name}")

            vals = line.action_generate_or_pick_lot()

            print(f"AFTER product={line.product_id.display_name} move={line.move_id.product_id.display_name}")

            if vals.get('lot_id'):
                line.lot_id = vals['lot_id']

            if vals.get('lot_name'):
                line.lot_name = vals['lot_name']

            # if vals.get('confirmation_location_code'):
            #     line.confirmation_location_code = vals['confirmation_location_code']

            # if vals.get('confirmation_lot_code'):
            #     line.confirmation_lot_code = vals['confirmation_lot_code']

    @api.onchange('lot_button')
    def _onchange_lot_button(self):
        print('def _onchange_lot_button(self)')
        print(">>> TOMBOL GENERATE LOT DIKLIK!") # Cek di terminal Odoo
        for line in self:
            if line.lot_button:
                vals = line.action_generate_or_pick_lot()
                print(f">>> Values returned from action_generate_or_pick_lot: {vals}") # Cek di terminal Odoo
                print(f">>> Line confirmation_location_code after generate/pick: {line.confirmation_location_code}") # Cek di terminal Odoo
                print(f">>> Line confirmation_lot_code after generate/pick: {line.confirmation_lot_code}") # Cek di terminal Odoo
                print(f">>> Line operation_category: {line.operation_category}") # Cek di terminal Odoo
                print(f">>> Lot ID assigned: {line.lot_id}") # Cek di terminal Odoo
                print(f">>> Lot Name assigned: {line.lot_name}") # Cek di terminal Odoo
                print(f">>> Confirmation Location Code assigned: {line.confirmation_location_code}") # Cek di terminal Odoo
                print(f">>> Confirmation Lot Code assigned: {line.confirmation_lot_code}") # Cek di terminal Odoo

                if vals.get('lot_id'):
                    line.lot_id = vals['lot_id']
                    print(f">>> Lot ID assigned: {line.lot_id}") # Cek di terminal Odoo
                if vals.get('lot_name'):
                    line.lot_name = vals['lot_name']
                    print(f">>> Lot Name assigned: {line.lot_name}") # Cek di terminal Odoo
                if vals.get('confirmation_location_code'):
                    line.confirmation_location_code = vals['confirmation_location_code']
                    print(f">>> Confirmation Location Code assigned: {line.confirmation_location_code}") # Cek di terminal Odoo
                if vals.get('confirmation_lot_code'):
                    line.confirmation_lot_code = vals['confirmation_lot_code']
                    print(f">>> Confirmation Lot Code assigned: {line.confirmation_lot_code}") # Cek di terminal Odoo
                line.lot_button = False



    def _compute_lot_button(self):
        # field dummy, tidak dipakai
        for rec in self:
            rec.lot_button = " "

    # ---------- Helpers ----------

    def _get_base_quant_domain(self):
            self.ensure_one()
    
            domain = [
                ("product_id", "=", self.product_id.id),
                ("location_id", "child_of", self.adt_dest_location_id.id),
                ("quantity", ">", 0),
                ("lot_id", "!=", False),
            ]
    
            if (
                self.move_id.picking_id.adt_type == "Toko Pegang DO"
                and self.move_id.owner_id
            ):
                domain.append(
                    ("owner_id", "=", self.move_id.owner_id.id)
                )
    
            return domain
    
    @api.depends(
        "product_id",
        "source_location_id",
        "lot_id",
        "location_id",
    )
    def _compute_available_quant_fields(self):

        Quant = self.env["stock.quant"]

        for line in self:

            line.available_lot_ids = False
            line.available_location_ids = False

            if (
                not line.product_id
                or not line.location_id
            ):
                continue

            # ----------------------------------
            # Available Lots
            # ----------------------------------

            lot_domain = line._get_base_quant_domain()

            lots = Quant.search(lot_domain).mapped("lot_id")

            line.available_lot_ids = [(6, 0, lots.ids)]

            # ----------------------------------
            # Available Locations
            # ----------------------------------
            
            Location = self.env['stock.location']
            # location_domain = line._get_base_quant_domain()

            locations = Location.search(
                [('id', 'child_of', line.adt_dest_location_id.id)]
            )

            line.available_location_ids = [
                (6, 0, locations.ids)
            ]

    def _refresh_quant(self):
        self.ensure_one()

        Quant = self.env['stock.quant']
        quants = self._get_base_quant_domain()
        available_lots = Quant.search(quants).mapped("lot_id")
        available_locations = self.env['stock.location'].search(
            [('id', 'child_of', self.adt_dest_location_id.id)]
        )

        # ------------------------------------------------------
        # Sync Quant
        # ------------------------------------------------------

        self.quant_id = False

        if self.lot_id and self.location_id:

            quant = self.env["stock.quant"].search([
                ("product_id", "=", self.product_id.id),
                ("lot_id", "=", self.lot_id.id),
                ("location_id", "=", self.location_id.id),
                ("quantity", ">", 0),
            ], limit=1)

            self.quant_id = quant

        return {
            "domain": {
                "lot_id": [
                    ("id", "in", available_lots.ids)
                ],
                "location_id": [
                    ("id", "in", available_locations.ids)
                ],
            }
        }

    def _tjr_is_incoming_tracked(self):
        print(f">>> Checking if line {self.id} is incoming tracked...") # Cek di terminal Odoo
        self.ensure_one()
        print(f">>> Line {self.id} - Product: {self.product_id.display_name} - Lot id {self.lot_id.name if self.lot_id else 'N/A'} - Stock Quantity: {self.quantity}") # Cek di terminal Odoo
        # Cek tipe picking dari berbagai sumber (picking_id atau dari context)
        picking_type = self.picking_id.picking_type_id or self.move_id.picking_type_id
        print(f">>> Line {self.id} - Picking Type: {picking_type.name if picking_type else 'N/A'}") # Cek di terminal Odoo
        is_internal_transfer_receipt = (
            self.picking_id
            and 'internal_transfer_leg' in self.picking_id._fields
            and self.picking_id.internal_transfer_leg == 'receipt'
        )
        is_incoming = (
            picking_type.code == 'incoming'
            or self._context.get('default_picking_type_code') == 'incoming'
            or picking_type.name in ('Receipts', 'Receipt Internal')
            or is_internal_transfer_receipt
        )
        
        return (
            is_incoming
            and self.product_id
            and self.product_id.tracking != 'none'
        )

    # def _tjr_is_incoming_tracked(self):
    #     self.ensure_one()
    #     return (
    #         self.picking_id
    #         and self.picking_id.picking_type_code == 'incoming'
    #         and self.product_id
    #         and self.product_id.tracking != 'none'
    #     )

    def _tjr_is_outgoing_or_internal_tracked(self):
        self.ensure_one()
        return (
            self.picking_id
            and self.picking_id.picking_type_code in ('outgoing', 'internal')
            and self.product_id
            and self.product_id.tracking != 'none'
        )

    def _tjr_get_po_number(self):
        self.ensure_one()
        po = self.move_id.purchase_line_id.order_id if self.move_id and self.move_id.purchase_line_id else False
        return po.name if po else (self.picking_id.origin or self.picking_id.name or 'PO')

    def _tjr_build_lot_name(self):
        self.ensure_one()
        # Ambil nomor PO
        po_number = self._tjr_get_po_number()

        # Ambil ID purchase line jika ada, fallback ke stock move line id
        po_line_id = (
            self.move_id.purchase_line_id.id
            if self.move_id and self.move_id.purchase_line_id
            else self.id
        )

        # Ambil nomor sequence unik
        seq = self.env['ir.sequence'].next_by_code('tijari.lot.serial') \
            or fields.Datetime.now().strftime('%Y%m%d%H%M%S')

        return f"{po_number} - {po_line_id} - {seq}"

    # ---------- Main button ----------
    def action_generate_or_pick_lot(self):
        """
        Incoming (receipt): generate lot_name (lot_id=False).
        Outgoing/Internal : pick FIFO lot_id from stock.quant (source location).
        Fields lot_id & lot_name dibuat readonly di view; perubahan via tombol ini.
        """

        Quant = self.env['stock.quant']
        for line in self:

            is_incoming = line._tjr_is_incoming_tracked()
            
            # print(f">>> Is Incoming: {is_incoming}") # Cek di terminal Odoo

            if is_incoming:
                kode_supplier = self.picking_id.partner_id.company_registry or (self.picking_id.partner_id.ref if self.picking_id.partner_id and self.picking_id.partner_id.ref else False)
                print(f">>> Kode Supplier: {kode_supplier}") # Cek di terminal Odoo
                if not kode_supplier:
                    kode_supplier = "SUPP"  # Fallback jika supplier tidak memiliki kode

                # 2. Ambil TANGGAL MASUK (Format: MMDDYY)
                # Odoo menyimpan waktu dalam UTC, kita ambil tanggal hari ini
                tanggal_masuk = fields.Date.today().strftime('%m%d%y')
                print(f">>> Tanggal Masuk: {tanggal_masuk}") # Cek di terminal Odoo

                # 3. Ambil KODE WAREHOUSE Tujuan
                # Mengambil warehouse dari destinasi lokasi penerimaan
                des_parent_code = self.location_dest_id.location_id.name if self.location_dest_id and self.location_dest_id.location_id else False
                print(f">>> Lokasi Tujuan: {des_parent_code}") # Cek di terminal Odoo

                warehouse = line.picking_id.picking_type_id.warehouse_id
                kode_warehouse = des_parent_code or (warehouse.code if warehouse else False)
                if not kode_warehouse:
                    kode_warehouse = "WH"  # Fallback jika gudang tidak teridentifikasi

                # 4. Ambil SEQUENCE (Berdasarkan jumlah lot yang dibuat hari ini)
                # Mencari lot dengan awalan yang sama untuk menghitung urutan
                kode_product = line.product_id.default_code or f"PROD{line.product_id.id}"
                source_document = line.picking_id.origin or f"PICK{line.picking_id.id}"
                prefix = f"{source_document}-{tanggal_masuk}-{kode_product}"

                # lot_count = self.env['stock.lot'].search_count([
                #     ('name', '=like', f"{prefix}%"),
                #     ('product_id', '=', line.product_id.id)
                # ])

                # KOMPOSISI AKHIR LOT
                new_lot_name = f"{prefix}"
                
                # Masukkan ke dalam UI menggunakan update
                print(f">>> Line Confirmation Location Code before update: {line.confirmation_location_code}") # Cek di terminal Odoo
                print(f">>> Line Confirmation Lot Code before update: {line.confirmation_lot_code}") # Cek di terminal Odoo
                line.update({
                    'lot_id': False,
                    # 'confirmation_location_code': des_parent_code,
                    # 'confirmation_lot_code': new_lot_name,
                })
                # line.confirmation_location_code = des_parent_code  # Update confirmation_location_code untuk menampilkan di UI
                # line.confirmation_lot_code = new_lot_name  # Update confirmation_lot_code untuk menampilkan di UI
                line.lot_name = new_lot_name  # Update lot_name untuk menampilkan di UI

                print(f">>> Line Confirmation Location Code after update: {line.confirmation_location_code}") # Cek di terminal Odoo
                print(f">>> Line Confirmation Lot Code after update: {line.confirmation_lot_code}")
                
                print(f">>> SUCCESS: Generated lot name -> {new_lot_name}")
                lot_data = {
                    'name': line.lot_name,               # Nomor Lot
                    'product_id': line.product_id.id,              # ID Produk
                    'product_uom_id': line.product_id.uom_id.id,           # ID Satuan Unit
                    'company_id': False,           # [NULL] di Odoo diwakili False
                    'location_id': line.location_id.id,              # Lokasi awal/default (opsional tergantung versi)
                    'ref': False,                  # Internal Reference [NULL]
                    'note': False,                 # Catatan [NULL]
                }
                search_lot = self.env['stock.lot'].search([('name', '=', line.lot_name)])
                lot_exist = search_lot
                if not search_lot:
                    new_lot = line.env['stock.lot'].create(lot_data)
                    lot_exist = new_lot
                    # search_lot

                
                line.lot_id = lot_exist.id
                print(f">>> Created new lot with ID: {lot_exist.id} and Name: {lot_exist.name}") # Cek di terminal Odoo
                line.update({
                    'lot_id': lot_exist.id,
                })
                print(f">>> Lot ID assigned: {line.lot_id}") # Cek di terminal Odoo

                continue

            # === Incoming: generate lot_name ===
            if line._tjr_is_incoming_tracked():
                print(">>> Detected incoming tracked product. Generating lot name...") # Cek di terminal Odoo
                new_name = line._tjr_build_lot_name()
                # biarkan Odoo membuat lot saat validasi jika lot_id kosong
                line.update({
                    'lot_id': False,
                    'lot_name': new_name,
                })
                print(f">>> Generated lot name: {new_name}")

                # line.write({'lot_id': False, 'lot_name': new_name})
                continue

            # === Outgoing/Internal: pilih lot via FIFO ===
            if not line.location_id:
                raise UserError(_("Source Location is empty on the move line."))

            # Berapa kuantitas yang mau di-assign?
            # - Jika qty_done sudah diisi, pakai itu.
            # - Jika kosong: untuk serial -> 1; untuk lot -> sisa qty di line (product_uom_qty/demand).
            uom_line = line.product_uom_id or line.product_id.uom_id
            qty_needed_line_uom = line.quantity
            print(f">>> Initial quantity needed (line UoM): {qty_needed_line_uom}") # Cek di terminal Odoo
            # print(f">>> Product Tracking: {line.product_id.tracking}") # Cek di terminal Odoo   
            if not qty_needed_line_uom:
                print(">>> Quantity needed is zero, calculating fallback...") # Cek di terminal Odoo
                if line.product_id.tracking == 'serial':
                    qty_needed_line_uom = 1.0
                else:
                    qty_needed_line_uom = line.quantity or line.qty_reserved or 0.0
                    if not qty_needed_line_uom:
                        qty_needed_line_uom = 1.0  # fallback

            # konversi ke UoM produk (base) untuk hitung available quant
            qty_needed_base = uom_line._compute_quantity(qty_needed_line_uom, line.product_id.uom_id, rounding_method='HALF-UP')
            print(f">>> Quantity needed (product UoM): {qty_needed_base}") # Cek di terminal Odoo

            # Ambil quants dengan lot yang punya stok available > 0 di lokasi sumber (FIFO)
            domain = [
                ('product_id', '=', line.product_id.id),
                ('location_id', 'child_of', line.location_id.id),
                ('lot_id', '!=', False),
                ('quantity', '>', 0),
            ]
            if line.owner_id:
                domain.append(('owner_id', '=', line.owner_id.id))
            if line.package_id:
                domain.append(('package_id', '=', line.package_id.id))

            quants = Quant.search(domain, order='in_date asc, id asc')

            chosen = False
            for q in quants:
                # hitung available di lokasi quant (strict ke lokasi quant)
                print(f"Product ID - {line.product_id.id}, Location ID - {q.location_id.id}, Lot ID - {q.lot_id.id if q.lot_id else 'N/A'}, Package ID - {q.package_id.id if q.package_id else 'N/A'}, Owner ID - {q.owner_id.id if q.owner_id else 'N/A'}") # Cek di terminal Odoo
                avail = Quant._get_available_quantity(
                    line.product_id,
                    q.location_id,
                    lot_id=q.lot_id,
                    package_id=q.package_id or None,
                    owner_id=q.owner_id or None,
                    strict=True,
                )
                print(f">>> Evaluating quant {q.id} - Lot: {q.lot_id.name if q.lot_id else 'N/A'} - Available Qty: {avail}") # Cek di terminal Odoo                
                if avail <= 0:
                    continue

                if avail >= qty_needed_base or line.product_id.tracking == 'serial':
                    # gunakan lot ini
                    # updates = {'lot_id': q.lot_id.id, 'lot_name': False}
                    print(f">>> Using lot: {q.lot_id.name}") # Cek di terminal Odoo
                    line.lot_id = q.lot_id
                    line.lot_name = False

                    # Kalau qty_done 0, isi qty_done minimal 1 untuk serial, atau min(avail, qty_needed)
                    if not line.quantity:
                        print(f">>> Line quantity before assignment: {line.quantity}") # Cek di terminal Odoo
                        print(f">>> Calculating quantity to assign for line {line.id}") # Cek di terminal Odoo
                        if line.product_id.tracking == 'serial':
                            # qty_to_write = 1.0
                            line.quantity = 1.0
                        else:
                            # convert avail (base) ke uom line
                            # qty_to_write = line.product_id.uom_id._compute_quantity(
                            #     min(avail, qty_needed_base),
                            #     uom_line,
                            #     rounding_method='HALF-UP'
                            # )
                            line.quantity = line.product_id.uom_id._compute_quantity(
                                min(avail, qty_needed_base),
                                uom_line)
                            print(f">>> Assigned quantity: {line.quantity} {uom_line.name}") # Cek di terminal Odoo
                    #     updates['qty_done'] = qty_to_write
                    # line.write(updates)
                    chosen = True
                    break
                      
            if not chosen:
                print(f">>> chosen {chosen}") # Cek di terminal Odoo
                # print(f">>> chosen lot {q.lot_id.name} - Product: {line.product_id.display_name}") # Cek di terminal Odoo
                # Tidak ada lot yg cukup → pilih lot tertua yang punya sedikit stok (sebagai hint)
                partial = next((q for q in quants if Quant._get_available_quantity(
                    line.product_id, q.location_id, lot_id=q.lot_id,
                    package_id=q.package_id or None, owner_id=q.owner_id or None, strict=True) > 0), None)
                print(f">>> No sufficient lot found for line {line.id}. Partial suggestion: {partial.lot_id.name if partial else 'None'}") # Cek di terminal Odoo
                if partial:
                    line.write({'lot_id': partial.lot_id.id, 'lot_name': False})
                    # quantity bila kosong isi seminimal mungkin agar user sadar (1 untuk serial, else 0)
                    if not line.quantity and line.product_id.tracking == 'serial':
                        line.quantity = 1.0
                else:
                    raise UserError(_("No available lots found for product %s in %s.") % (line.product_id.display_name, line.location_id.display_name))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Done'),
                'message': _('Lot generated for receipts or picked by FIFO for issues/transfers.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_prepare_scan_lot(self):
        self.ensure_one()
        if not self.lot_id:
            raise ValidationError("Lot kosong, Silahkan generate lot terlebih dahulu")
        return {
            'type': 'ir.actions.client',
            'tag': 'adt_scan_qr_to_move_line_field',
            'params': {
                'field_name': 'confirmation_lot_code',
                'move_line_id': self.id,
                'title': _('Scan Lot QR Code'),
            },
        }

    def action_prepare_scan_location(self):
        self.ensure_one()
        if not self.lot_id:
            raise ValidationError("Lot kosong, Silahkan generate lot terlebih dahulu")
        return {
            'type': 'ir.actions.client',
            'tag': 'adt_scan_qr_to_move_line_field',
            'params': {
                'field_name': 'confirmation_location_code',
                'move_line_id': self.id,
                'title': _('Scan Location QR Code'),
            },
        }

    @api.onchange('matching')
    def _onchange_matching(self):
        for line in self:
            line._update_move_picked()

    def action_apply_scanned_field(self, field_name, scanned_code):
        allowed_fields = {
            'confirmation_lot_code',
            'confirmation_location_code',
            'matching_lot_id',
            'matching_loc_dest_id',
        }
        if field_name not in allowed_fields:
            raise ValidationError(_("Field scan tidak valid."))

        result = {}
        for line in self:
            picking_type_name = line.picking_type_name
            vals = {}
            if field_name in ('confirmation_lot_code', 'matching_lot_id'):
                lot = line._find_lot_by_scan_code(scanned_code)
                if not lot:
                    raise ValidationError(_("Barcode tidak terdaftar."))
                if field_name == 'confirmation_lot_code':
                    vals['confirmation_lot_code'] = scanned_code
                vals['matching_lot_id'] = lot.id
            elif field_name in ('confirmation_location_code', 'matching_loc_dest_id'):
                location = line._find_loc_by_scan_code(scanned_code)
                if not location:
                    raise ValidationError(_("Barcode tidak terdaftar."))
                if field_name == 'confirmation_location_code':
                    vals['confirmation_location_code'] = scanned_code
                if picking_type_name in ['Receipts', 'Receipt Internal'] and field_name == 'confirmation_location_code':
                    vals['location_putaway_id'] = location.id
                    vals['location_dest_id'] = location.id
                else:
                    vals['matching_loc_dest_id'] = location.id

            line.write(vals)

            matching_labels = dict(line._fields['matching'].selection)
            status_labels = dict(line._fields['putaway_status'].selection)
            result = {
                'id': line.id,
                field_name: scanned_code
                # 'matching': line.matching,
                # 'matching_label': matching_labels.get(line.matching, line.matching or ''),
                # 'matching_lot_id': [
                #     line.matching_lot_id.id,
                #     line.matching_lot_id.display_name,
                # ] if line.matching_lot_id else False,
            }

            if picking_type_name in ['Receipts', 'Receipt Internal']:
                result['putaway_status'] = line.putaway_status
                result['putaway_status_label'] = status_labels.get(line.putaway_status, line.putaway_status or '')
                result['location_putaway_id'] = [
                    line.location_putaway_id.id,
                    line.location_putaway_id.name,
                ] if line.location_putaway_id else False
                result['location_dest_id'] = [
                    line.location_dest_id.id,
                    line.location_dest_id.name,
                ] if line.location_dest_id else False
            else:
                result['matching'] = line.matching
                result['matching_label'] = matching_labels.get(line.matching, line.matching or '')
                result['matching_lot_id'] = [
                    line.matching_lot_id.id,
                    line.matching_lot_id.display_name,
                ] if line.matching_lot_id else False
                result['matching_loc_dest_id'] = [
                    line.matching_loc_dest_id.id,
                    line.matching_loc_dest_id.display_name,
                ] if line.matching_loc_dest_id else False

        return result

    def action_mark_putaway_finished(self):
        if not self.location_putaway_id and self.confirmation_quantity == 0:
            raise ValidationError(_("Location putaway dan Quantity tidak boleh kosong, silahkan input location putaway dan quantity terlebih dahulu"))
        if self.confirmation_quantity == 0:
            raise ValidationError(_("Quantity tidak boleh 0, silahkan input quantity terlebih dahulu"))
        if not self.location_putaway_id:
            raise ValidationError(_("Location putaway tidak boleh kosong, silahkan input location putaway terlebih dahulu"))
        if self.confirmation_quantity > self.quantity:
            raise ValidationError(_("Stored Qty tidak boleh lebih besar dari Picked Qty, silahkan input quantity yang sesuai"))
        if self.confirmation_quantity < self.quantity:
            raise ValidationError(_("Stored Qty tidak boleh kurang dari Picked Qty, silahkan input quantity yang sesuai"))
        self.write({'putaway_status': 'finished'})
        return True

    def action_mark_putaway_unfinished(self):
        self.write({'putaway_status': 'unfinished'})
        return True


    def action_mark_picker_finished(self):
        if not self.lot_id:
            raise ValidationError(_("Lot kosong, silahkan generate lot terlebih dahulu"))
        if self.quantity == 0:
            raise ValidationError(_("Quantity tidak boleh 0, silahkan input quantity terlebih dahulu"))
        self.write({'picker_status': 'finished'})
        return True


    @api.onchange('location_putaway_id')
    def _onchange_location_putaway_id(self):
        for line in self:

            if line.location_putaway_id:
                line.location_dest_id = line.location_putaway_id.id

    @api.onchange('confirmation_location_code')
    def _onchange_confirmation_location_code(self):
        print('def _onchange_confirmation_location_code(self)')
        for wizard in self:

            location = wizard._find_loc_by_scan_code(wizard.confirmation_location_code)
            if not wizard.confirmation_location_code or not location:
                wizard.matching_loc_dest_id = False
                wizard.matching = 'not_match'


            wizard.matching_loc_dest_id = location.id

    def _find_lot_by_scan_code(self, lot_code):
        Lot = self.env['stock.lot']
        lot_code = (lot_code or '').strip()
        if not lot_code:
            return Lot.browse()

        return Lot.search([('name', '=', lot_code)], limit=1)

    @api.onchange('confirmation_lot_code')
    def _onchange_confirmation_lot_code(self):
        print('def _onchange_confirmation_lot_code(self)')
        for wizard in self:

            lot = wizard._find_lot_by_scan_code(wizard.confirmation_lot_code)
            if not lot:
                wizard.matching_lot_id = False
                wizard.matching = 'not_match'

            wizard.matching_lot_id = lot.id
    def _find_loc_by_scan_code(self, location_code):
        Loc = self.env['stock.location']
        location_code = (location_code or '').strip()
        if not location_code:
            return Loc.browse()

        search_fields = ['unique_code', 'barcode', 'complete_name', 'name']
        for field_name in search_fields:
            if field_name not in Loc._fields:
                continue
            loc = Loc.search([(field_name, '=', location_code)], limit=1)
            if loc:
                return loc

        return Loc.browse()

    # @api.onchange('matching_lot_id', 'matching_loc_dest_id')
    # def _onchange_update_matching_status(self):
    #     for line in self:
    #         if not line.matching_lot_id or not line.matching_loc_dest_id:
    #             continue

    #         lot_match = line.matching_lot_id.id == line.lot_id.id
    #         location_match = line.matching_loc_dest_id.id == line.location_dest_id.id

    #         line.matching = 'match' if lot_match and location_match else 'not_match'

    def _update_move_picked(self):
        for move in self.mapped('move_id'):

            # Matching hanya berlaku untuk stock move yang
            # merupakan bagian dari picking.
            # if not move.picking_id:
            #     continue

            # Return picking tidak melalui proses matching WMS.
            if move.picking_id.return_id:
                move.picked = True
                continue
            
            move.picked = bool(
                move.move_line_ids
                and all(
                    line.matching == 'match'
                    for line in move.move_line_ids
                )
            )

    def _get_matching_status(self):
        """Return the matching result using the reference fields for each operation."""
        self.ensure_one()
        picking_name = self.picking_id.picking_type_id.name
        if not self.matching_lot_id or not self.matching_loc_dest_id:
            return 'not_match'

        if picking_name in ('Pick', 'Pick Internal', 'Pick Components', 'Internal Transfers'):
            expected_location = self.source_location_id or self.location_id
            expected_lot = self.product_lot_id or self.lot_id
        elif picking_name in ('Receipts', 'Receipt Internal'):
            expected_location = self.location_dest_id
            expected_lot = self.lot_id
        else:
            return 'not_match'

        return (
            'match'
            if expected_location == self.matching_loc_dest_id
            and expected_lot == self.matching_lot_id
            else 'not_match'
        )

    #ONLY LOT CONFIRMATION
    def _get_matching_status_mo(self):
            """Return the matching result using the reference fields for each operation."""
            self.ensure_one()
            if not self.matching_lot_id:
                return 'not_match'
    
            expected_lot = self.lot_id
            
            return (
                'match'
                if expected_lot == self.matching_lot_id
                else 'not_match'
            )
    

    @api.onchange('confirmation_quantity', 'auto_input_code', 'matching_lot_id', 'matching_loc_dest_id')
    def _compute_matching(self):
        for line in self:
            if line.picking_id:
                if line.picking_id.picking_type_id.name in ('Pick', 'Pick Internal', 'Pick Components', 'Internal Transfers'):
                    line.matching = line._get_matching_status()
                    line.second_matching = (
                        'Match' if line.matching == 'match' else 'Not Match'
                    )
                elif line.picking_id.picking_type_id.name in ('Internal Transfers') and line.matching == 'match':
                    line.matching = line._get_matching_status()
                    line.picker_status = 'finished'
                elif line.picking_id.picking_type_id.name in ('Receipt Internal'):
                    line.matching = line._get_matching_status_mo()
                    line.second_matching = (
                        'Match' if line.matching == 'match' else 'Not Match'
                                    )
            elif line.move_id.raw_material_production_id:
                line.matching = line._get_matching_status_mo()
                line.second_matching = (
                    'Match' if line.matching == 'match' else 'Not Match'
                )
                
                
            
    @api.onchange('auto_input_code')
    def _compute_auto_input_code(self):
        print('def _compute_auto_input_code(self)')
        print(f"Self: {self}")
        for line in self:
            picking_name = line.move_id.picking_id.picking_type_id.name
            print(f"validate stock move line with picking type name: {picking_name}")

            if picking_name and picking_name in ( 'Pick', 'Pick Components', 'Pick Internal'):
                loc_code = str(line.location_id.unique_code or '').strip()
                product_code = str(line.lot_id.name or '').strip()

                line.confirmation_location_code = loc_code
                line.confirmation_lot_code = product_code
                line.matching_lot_id = line.product_lot_id.id
                line.matching_loc_dest_id = line.source_location_id.id
                line.matching = 'match'
                line.second_matching = 'Match'

            if picking_name and picking_name == 'Receipt':
                loc_code = str(line.location_dest_id.unique_code or '').strip()
                product_code = str(line.lot_id.name or '').strip()

                line.confirmation_location_code = loc_code
                line.confirmation_lot_code = product_code
                line.matching = 'match'
            #     # loc_ok = bool(loc_code and conf_loc.lower() == loc_code.lower())
            #     # lot_ok = bool(product_code and conf_lot.lower() == product_code.lower())
                
                

            # if line.auto_input_code:
            #     print(f">>> Auto input code triggered for line {line.id}") # Cek di terminal Odoo
            #     line.matching = 'match'
            #     sml = self.env['stock.move.line'].browse(line._origin.id)
            #     sml.write({'matching': 'match'})
