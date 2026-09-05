from odoo.tools.float_utils import float_compare, float_round
from odoo import _, api, models, fields
import base64
import os
from PIL import Image
import qrcode
import io
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero
import logging

_logger = logging.getLogger(__name__)

class StockMove(models.Model):
    _inherit = 'stock.move'

    adt_line_external_id = fields.Char(string='UUID Line Acumatica', index=True)
    adt_inventory_id = fields.Char(string='InventoryID (Acumatica)')
    adt_line_nbr = fields.Char(string='Line Nbr (Acumatica)')
    adt_line_type = fields.Char(string='Line Type (Acumatica)')
    adt_open_qty = fields.Float(string='Open Qty (Acumatica)')
    adt_order_qty = fields.Float(string='Ordered Qty (Acumatica)')
    adt_po_line_number = fields.Char(string='PO Line Nbr (Acumatica)')
    adt_po_number = fields.Char(string='PO Number (Acumatica)')
    adt_po_type = fields.Char(string='PO Type (Acumatica)')
    adt_po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr (Acumatica)')
    adt_po_receipt_number = fields.Char(string='PO Receipt Number (Acumatica)')
    adt_transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr (Acumatica)')
    adt_transfer_order_number = fields.Char(string='Transfer Order Number (Acumatica)')
    adt_transfer_order_type = fields.Char(string='Transfer Order Type (Acumatica)')
    adt_transfer_shipment_number = fields.Char(string='Transfer Shipment Number (Acumatica)')
    adt_uom_code = fields.Char(string='UOM (Acumatica)')
    adt_warehouse_dest_code = fields.Char(string='Warehouse Dest (Acumatica)')
    adt_location_dest_code = fields.Char(string='Location Dest (Acumatica)')
    adt_line_note = fields.Text(string='Line Note (Acumatica)')
    adt_line_description = fields.Char(string='Line Description (Acumatica)')
    adt_to_location_code = fields.Char(string='To Location (Acumatica)')
    adt_from_location_code = fields.Char(string='From Location (Acumatica)')
    adt_quantity = fields.Float(string='Quantity (Acumatica)')
    adt_type = fields.Char(string='Type (Acumatica)')
    adt_acumatica_write_date = fields.Datetime(string='Last Modified (Acumatica)')
    allocation_id = fields.Char(string='Allocation ID')
    allocation_note = fields.Text(string='Allocation Note')
    allocation_Description = fields.Text(string='Allocation Description')
    allocation_InventoryID = fields.Char(string='Allocation Inventory ID')
    allocation_LocationID = fields.Char(string='Allocation Location ID')
    allocation_Quantity = fields.Float(string='Allocation Quantity')
    allocation_SplitLineNbr = fields.Integer(string='Allocation Split Line Number')
    allocation_UOM = fields.Char(string='Allocation UOM')
    adt_dest_location_id = fields.Many2one(
        "stock.location",
        domain="[('usage', '=', 'internal')]",
        string="Mapped Location",
    )
    product_note = fields.Text(string='Product Note')
    batch_adt_type = fields.Char(
        related='picking_id.adt_type',
        string='Tipe Transaksi',
        readonly=True,
    )
    batch_origin = fields.Char(
        related='picking_id.origin',
        string='No. Transaksi',
        readonly=True,
    )
    product_default_code = fields.Char(
        related='product_id.default_code',
        string='Product Code',
        readonly=True,
    )

    qr_code_image = fields.Binary(string='Sign')

    unfiltered_dest = fields.Boolean(
        string="Unfiltered Destination",
        default=True,
    )

    picking_type_code = fields.Selection(
        related="picking_id.picking_type_id.code",
        store=False,
    )

    picking_type_name = fields.Char(
        string="Operation Type",
        compute="_compute_get_picking_type_name",
    )

    @api.depends(
        "picking_id",
        "raw_material_production_id",
    )
    def _compute_get_picking_type_name(self):
        for rec in self:
            rec.picking_type_name = False

            if rec.picking_id:
                rec.picking_type_name = rec.picking_id.picking_type_id.name
            elif rec.raw_material_production_id:
                rec.picking_type_name = (
                    rec.raw_material_production_id.picking_type_id.name
                )

    transaction_type = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
        ('internal', 'Internal'),
    ], string='Type transaksi', readonly=True)

    
    adt_dest_location = fields.Char(
        string="Mapped Location",
        readonly=True,
    )

    # temp_float = fields.Float(string="Confirmation Quantity")
    so_confirmation_quantity = fields.Float(string="Confirmation Quantity")
    
    remaining_package_qty = fields.Float(
        compute="_compute_remaining_package_qty",
        store=True,
        string="Remaining Package Qty",
    )

    unpack_quantity = fields.Float(
        'Unpack Qty',
        readonly=True
    )

    difference_quantity = fields.Float(
        string='Difference Qty',
        compute='_compute_difference_quantity',
        store=True,
    )

    confirmation_quantity = fields.Float(
        string='Confirmation Qty',
        compute='_compute_confirmation_quantity',
        store=True,
    )

    owner_id = fields.Many2one(
            "res.partner",
            string="Owner",
            store=True,
            readonly=False,
        )

    shipped_qty = fields.Float('Shipped Qty')

    status_check = fields.Selection([
        ('finished', 'Finished'),
        ('unfinished', 'Unfinished'),
    ], string='Status', default='unfinished')

    def action_mark_check_finished(self):
        if self.so_confirmation_quantity == 0:
            raise ValidationError(_("Confirmation Quantity tidak boleh 0, silahkan input quantity terlebih dahulu"))
        
        comparison = self._validate_before_mark_finished()
        if comparison > 0:
            raise UserError("Confirmed Qty tidak boleh melebihi Remaining Package Qty")

        if comparison < 0:
            diff = self.remaining_package_qty - self.so_confirmation_quantity
            move_line = self.move_line_ids.filtered(
                lambda x: not x.result_package_id and x.quantity == self.remaining_package_qty
            )

            rounding = self.product_uom.rounding if self.product_uom else 0.01
            for line in move_line:
                comparison = float_compare(
                    line.quantity,
                    diff,
                    precision_rounding=rounding,
                )
                if comparison > 0:
                    line.quantity -= diff
                    break

        self.write({'status_check': 'finished'})
        return True

    def action_mark_check_unfinished(self):
        self.write({'status_check': 'unfinished'})
        return True

    def _validate_before_mark_finished(self):
        confirmation_quantity = self.so_confirmation_quantity
        remaining_package_qty = self.remaining_package_qty

        rounding = self.product_uom.rounding if self.product_uom else 0.01
        comparison = float_compare(
            confirmation_quantity,
            remaining_package_qty,
            precision_rounding=rounding,
        )

        if float_is_zero(
            confirmation_quantity,
            precision_rounding=rounding,
        ):
            raise UserError(f"Product {self.product_id.display_name} confirmation quantity can not be zero")

        return comparison
            

    def _update_reserved_quantity_vals(
        self,
        need,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=True,
    ):
        self.ensure_one()

        if not lot_id:
            lot_id = self.env["stock.lot"]
        if not package_id:
            package_id = self.env["stock.quant.package"]
        if not owner_id:
            owner_id = self.env["res.partner"]

        # ======================================================
        # CUSTOM : TOKO PEGANG DO
        # ======================================================
        if (
            self.picking_id.adt_type == "Toko Pegang DO"
        ):
            owner_id = self.owner_id
        # ======================================================

        quants = self.env["stock.quant"]._get_reserve_quantity(
            self.product_id,
            location_id,
            need,
            product_packaging_id=self.product_packaging_id,
            uom_id=self.product_uom,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
        )

        taken_quantity = 0
        rounding = self.env["decimal.precision"].precision_get(
            "Product Unit of Measure"
        )

        candidate_lines = {}
        for line in self.move_line_ids:
            if line.result_package_id or line.product_id.tracking == "serial":
                continue
            candidate_lines[
                (
                    line.location_id,
                    line.lot_id,
                    line.package_id,
                    line.owner_id,
                )
            ] = line

        move_line_vals = []
        grouped_quants = {}

        for quant, quantity in quants:
            key = (
                quant.location_id,
                quant.lot_id,
                quant.package_id,
                quant.owner_id,
            )

            if key not in grouped_quants:
                grouped_quants[key] = [quant, quantity]
            else:
                grouped_quants[key][1] += quantity

        for reserved_quant, quantity in grouped_quants.values():
            taken_quantity += quantity

            to_update = candidate_lines.get(
                (
                    reserved_quant.location_id,
                    reserved_quant.lot_id,
                    reserved_quant.package_id,
                    reserved_quant.owner_id,
                )
            )

            if to_update:
                uom_quantity = self.product_id.uom_id._compute_quantity(
                    quantity,
                    to_update.product_uom_id,
                    rounding_method="HALF-UP",
                )

                uom_quantity = float_round(
                    uom_quantity,
                    precision_digits=rounding,
                )

                uom_quantity_back_to_product_uom = (
                    to_update.product_uom_id._compute_quantity(
                        uom_quantity,
                        self.product_id.uom_id,
                        rounding_method="HALF-UP",
                    )
                )

            if (
                to_update
                and float_compare(
                    quantity,
                    uom_quantity_back_to_product_uom,
                    precision_digits=rounding,
                )
                == 0
            ):
                to_update.with_context(
                    reserved_quant=reserved_quant
                ).quantity += uom_quantity

            else:
                if (
                    self.product_id.tracking == "serial"
                    and (
                        self.picking_type_id.use_create_lots
                        or self.picking_type_id.use_existing_lots
                    )
                ):
                    vals_list = self._add_serial_move_line_to_vals_list(
                        reserved_quant,
                        quantity,
                    )
                    if vals_list:
                        move_line_vals += vals_list

                else:
                    move_line_vals.append(
                        self._prepare_move_line_vals(
                            quantity=quantity,
                            reserved_quant=reserved_quant,
                        )
                    )

        return move_line_vals, taken_quantity
    
    @api.depends('product_uom_qty', 'quantity', 'picking_type_name', 'confirmation_quantity')
    def _compute_difference_quantity(self):
        for move in self:
            if move.picking_type_name in ['Receipts', 'Receipt Internal']:
                total_confirmation_quantity = move.confirmation_quantity
                difference = move.product_uom_qty - total_confirmation_quantity
            elif move.picking_type_name in ['Pick', 'Pick Internal', 'Pick Components']:
                total_confirmation_quantity = move.confirmation_quantity
                difference = move.quantity - total_confirmation_quantity
            else:
                difference = move.product_uom_qty - move.quantity
            move.difference_quantity = difference if difference > 0 else 0.0



    @api.depends('move_line_ids.confirmation_quantity')
    def _compute_confirmation_quantity(self):
        for move in self:
            total_confirmation_quantity = sum(move.move_line_ids.mapped('confirmation_quantity'))
            move.confirmation_quantity = total_confirmation_quantity if total_confirmation_quantity > 0 else 0.0

    def action_generate_lot(self):
        for move in self:
            print(move.product_id)
            print(move.product_uom)
            print(move.product_id.uom_id)
            move.move_line_ids.generate_lot()

    @api.onchange("move_line_ids")
    def _onchange_move_line_ids(self):
        for move in self:
            total_qty = sum(move.move_line_ids.mapped("quantity"))

            if total_qty > move.product_uom_qty:
                return {
                    "warning": {
                        "title": _("Invalid Quantity"),
                        "message": _(
                            "The total quantity (%s) cannot exceed the demand (%s)."
                        ) % (total_qty, move.product_uom_qty),
                    }
                }

    @api.onchange('product_uom_qty', 'quantity')
    def _onchange_sync_picking_quantities(self):
        for move in self:
            picking = move.picking_id
            if not picking:
                continue

            picking._sync_adt_quantities_from_moves()


    @api.depends(
        "quantity",
        "move_line_ids.quantity",
        "move_line_ids.package_id",
    )
    def _compute_remaining_package_qty(self):
        for move in self:
            packaged_qty = sum(
                ml.quantity
                for ml in move.move_line_ids
                if ml.package_id
            )

            move.remaining_package_qty = move.quantity - packaged_qty
            
    @api.depends('move_line_ids.lot_id', 'move_line_ids.quantity')
    def _compute_lot_ids(self):
        for move in self:
            move.lot_ids = move.move_line_ids.mapped('lot_id')   

    def action_validate_lot_pick(self):
        for move in self:
            picking_type = move.picking_id.picking_type_id
            for line in move.move_line_ids:
                line._compute_auto_input_code()
                
    def action_validate_lot(self):
        print('action_validate_lot')

        for move in self:
            picking_type = move.picking_id.picking_type_id
            for line in move.move_line_ids:
                if not line.lot_id:
                    raise ValidationError("Lot kosong, Silahkan generate lot terlebih dahulu")

                if not line.location_dest_id.unique_code:
                    raise ValidationError(f"Unique Code untuk location {line.location_dest_id.name} kosong, Silahkan generate unique code terlebih dahulu")

                location = line.location_dest_id
                if picking_type.name == "Pick":
                    location = line.location_id

                line.matching_lot_id = line.lot_id.id or False
                line.matching_loc_dest_id = location.id or False
                line.confirmation_lot_code = line.lot_id.name or False
                line.confirmation_location_code = location.unique_code or False
                self._check_match_status()

    def _check_match_status(self):
        print('_check_match_status')
        for move in self.move_line_ids:
            move.matching = move._get_matching_status()

    @api.onchange('unfiltered_dest')
    def action_toggle_unfiltered_dest(self):
        _logger.info("Running Onchange 1")
        _logger.info("Running Onchange on pick type: %s", self.picking_type_name)

        for move in self:
            _logger.info("Before onchange: %s", move.unfiltered_dest)

            value = move.unfiltered_dest

            _logger.info("After onchange: %s", value)

            move.unfiltered_dest = value

            for item in move.move_line_ids:
                if move.unfiltered_dest:
                    item.parent_location_id = item.adt_dest_location_id.id
                    # item.source_location_id = False
                    item.unfiltered_dest = value

                    _logger.info("parent_location_id: %s", item.parent_location_id.name)
                    _logger.info("source_location_id: %s", item.source_location_id.name if item.source_location_id else False)
                    _logger.info("unfiltered_dest: %s", item.unfiltered_dest)

                else:
                    item.parent_location_id = move.picking_id.picking_type_id.default_location_src_id.id
                    # item.source_location_id = False
                    item.unfiltered_dest = value

                    _logger.info("parent_location_id: %s", item.parent_location_id.name)
                    _logger.info("source_location_id: %s", item.source_location_id.name if item.source_location_id else False)
                    _logger.info("unfiltered_dest: %s", item.unfiltered_dest)

    def _search_picking_for_assignation(self):
        """Always create a new picking instead of reusing an existing one."""
        self.ensure_one()
        return self.env['stock.picking']


    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        print("_get_new_picking_values")

        origin_picking = (
            self.move_orig_ids
            .mapped('picking_id')
            .filtered(lambda p: p.origin)
        )[:1]

        if origin_picking:
            vals['origin'] = origin_picking.origin

        for item in self:
            print("move:", item)
            print("move adt_type:", item.adt_type)
            print("move transaction_type:", item.transaction_type)
            print("vals before:", vals)

            vals['adt_type'] = item.adt_type
            vals['transaction_type'] = item.transaction_type

            print("vals after:", vals)

        # Carry pick/pack/do responsible + user_ids forward from the
        # predecessor transfer(s) onto this brand-new transfer, so users
        # don't have to re-enter them once the next transfer is created
        # (mirrors what StockPicking._propagate_responsible_to_next_transfers
        # does for transfers that already exist).
        predecessor_pickings = self.move_orig_ids.picking_id
        if predecessor_pickings:
            carry_over_fields = self.env['stock.picking']._get_responsible_carry_over_fields()
            for field_name in carry_over_fields:
                if field_name in vals:
                    continue
                source_ids = predecessor_pickings.mapped(field_name)
                if source_ids:
                    vals[field_name] = [(6, 0, source_ids.ids)]

        return vals

    
    def action_print_lot_number_line(self):
        self.ensure_one()

        if not self.lot_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Lot Number belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        lot_names = list({
            lot.name for lot in self.lot_ids if lot.name
        })

        if not lot_names:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Lot Number belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        self.create_qrcode_name()

        return {
            'type': 'ir.actions.act_url',
            'url': '/print/lot_number_move_line?ids=%s' % self.id,
            'target': 'new',
        }

    def create_qrcode_name(self):
        for rec in self:
            lot_names = list(set(
                rec.lot_ids.mapped('name')
            ))

            text = ', '.join(filter(None, lot_names))

            if text:
                rec.qr_code_image = rec.create_qrcode(text)

    def create_qrcode(self, text):
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../static/src/img/logo-company.png')
        )

        logo = Image.open(logo_path)

        basewidth = 80
        wpercent = basewidth / float(logo.size[0])
        hsize = int(float(logo.size[1]) * wpercent)

        logo = logo.resize((basewidth, hsize))

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H
        )

        qr.add_data(text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        img = img.resize((300, 300))

        pos = (
            (img.size[0] - logo.size[0]) // 2,
            (img.size[1] - logo.size[1]) // 2
        )

        img.paste(logo, pos)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        return base64.b64encode(buffer.getvalue()).decode()

    def action_open_move_pick(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock Move',
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'tijari_wms_18.stock_move_pick_view'
            ).id,
            'target': 'new',
        }

    # Putaway flow scoped to the current stock move. The existing picking and
    # batch Putaway flows continue to use their stock.move.line collections.
    putaway_scan_product_button = fields.Boolean(string='Scan Product')
    putaway_product_id = fields.Many2one(
        'product.product',
        string='Putaway Product',
        domain="[('id', 'in', allowed_putaway_product_ids)]",
    )
    location_putaway_id = fields.Many2one(
        'stock.location',
        string='Putaway Location',
        compute='_compute_location_putaway_id',
        inverse='_inverse_location_putaway_id',
        domain="[('id', 'child_of', adt_dest_location_id)]",
        context="{'show_location_short_name': True}",
    )
    allowed_putaway_product_ids = fields.Many2many(
        'product.product',
        string='Allowed Putaway Products',
        compute='_compute_allowed_putaway_product_ids',
    )
    putaway_move_line_ids = fields.One2many(
        'stock.move.line',
        'move_id',
        string='Putaway Move Lines',
        domain=[
            '&', '&', '&',
            ('picker_status', '=', 'finished'),
            ('quantity', '>', 0),
            ('state', '!=', 'cancel'),
            '|',
            ('lot_id', '!=', False),
            ('lot_name', '!=', False),
        ],
    )
    putaway_progress_status = fields.Selection(
        [
            ('finished', 'Finished'),
            ('unfinished', 'Unfinished'),
        ],
        string='Putaway Status',
        compute='_compute_putaway_progress_status',
    )

    def _get_putaway_base_move_lines(self):
        self.ensure_one()
        return self.move_line_ids.filtered(
            lambda line: (
                (line.lot_id or line.lot_name)
                and line.quantity > 0
                and line.picker_status == 'finished'
                and line.state != 'cancel'
            )
        )

    def _get_putaway_move_lines(self):
        self.ensure_one()
        lines = self._get_putaway_base_move_lines()
        if self.putaway_product_id:
            lines = lines.filtered(
                lambda line: line.product_id == self.putaway_product_id
            )
        return lines

    @api.depends(
        'move_line_ids',
        'move_line_ids.location_putaway_id',
        'move_line_ids.quantity',
        'move_line_ids.picker_status',
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
    )
    def _compute_location_putaway_id(self):
        for move in self:
            locations = move._get_putaway_base_move_lines().mapped('location_putaway_id')
            move.location_putaway_id = locations[:1] if len(locations) == 1 else False

    def _inverse_location_putaway_id(self):
        for move in self:
            if move.location_putaway_id:
                move._get_putaway_base_move_lines().write({
                    'location_putaway_id': move.location_putaway_id.id,
                    'location_dest_id': move.location_putaway_id.id,
                })

    @api.depends(
        'move_line_ids',
        'move_line_ids.product_id',
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
        'move_line_ids.quantity',
        'move_line_ids.picker_status',
        'move_line_ids.state',
    )
    def _compute_allowed_putaway_product_ids(self):
        for move in self:
            move.allowed_putaway_product_ids = move._get_putaway_base_move_lines().product_id

    @api.depends(
        'move_line_ids',
        'move_line_ids.quantity',
        'move_line_ids.confirmation_quantity',
        'move_line_ids.putaway_status',
        'move_line_ids.picker_status',
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
    )
    def _compute_putaway_progress_status(self):
        for move in self:
            lines = move._get_putaway_move_lines()
            move.putaway_progress_status = (
                'finished' if lines and all(line.putaway_status == 'finished' for line in lines)
                else 'unfinished'
            )

    @api.onchange('putaway_product_id')
    def _onchange_putaway_product_id(self):
        for move in self:
            if move.putaway_product_id and move.putaway_product_id not in move.allowed_putaway_product_ids:
                move.putaway_product_id = False

    def action_apply_scanned_product(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product = self.env['product.product'].search([
            '|',
            ('barcode', '=', scanned_code),
            ('default_code', '=', scanned_code),
        ], limit=1)
        if not product:
            raise ValidationError(_('Product tidak ditemukan untuk kode scan: %s') % scanned_code)

        if product not in self.allowed_putaway_product_ids:
            raise ValidationError(_('Product hasil scan tidak ada di Putaway move ini.'))

        self.putaway_product_id = product
        return {
            'product_id': product.id,
            'display_name': product.display_name,
        }

    def action_mark_putaway_finished(self):
        self.ensure_one()
        lines = self._get_putaway_base_move_lines()
        if not lines:
            raise ValidationError(_('Tidak ada Putaway line yang siap diselesaikan.'))

        if self.location_putaway_id:
            lines.write({
                'location_putaway_id': self.location_putaway_id.id,
                'location_dest_id': self.location_putaway_id.id,
            })

        for line in lines:
            line.action_mark_putaway_finished()

        return True

    def action_open_move_putaway(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Putaway'),
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'tijari_wms_18.stock_move_putaway_view'
            ).id,
            'target': 'new',
        }

    def action_add_picker_line(self):
        self.ensure_one()

        move_line = self.env['stock.move.line'].create(
            self._prepare_move_line_vals(quantity=0)
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Picker Details'),
            'res_model': 'stock.move.line',
            'res_id': move_line.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'tijari_wms_18.wizard_picker_view_mobile'
            ).id,
            'context': {
                'picker_new_line': True,
            },
            'target': 'new',
        }

    def action_open_move_lines(self):
        self.ensure_one()
        return self.action_open_move_pick()

    def action_open_note_wizard(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Product Note',
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'tijari_wms_18.stock_move_note_form_view'
            ).id,
            'target': 'new',
        }

    def _action_confirm(self, merge=True, merge_into=False):
        moves_no_merge = self.filtered(
            lambda m: m.picking_id
            and m.picking_id.adt_type == "Receipt"
        )

        moves_normal = self - moves_no_merge

        res = self.browse()

        if moves_normal:
            res |= super(StockMove, moves_normal)._action_confirm(
                merge=merge,
                merge_into=merge_into
            )

        if moves_no_merge:
            res |= super(StockMove, moves_no_merge)._action_confirm(
                merge=False,
                merge_into=False
            )

        return res

    def create(self, vals):
        res = super().create(vals)
        for line in res:
            if not line.adt_dest_location_id:
                if line.picking_id.adt_dest_location_id:
                    line.adt_dest_location_id = line.picking_id.adt_dest_location_id
                elif line.picking_id.picking_type_name in ['Pick']:
                    line.adt_dest_location_id = line.picking_id.picking_type_id.default_location_src_id
                else:
                    line.adt_dest_location_id = line.picking_id.picking_type_id.default_location_dest_id
        res.mapped('picking_id')._sync_adt_quantities_from_moves()

        return res

    def write(self, vals):
        pickings = self.mapped('picking_id')
        res = super().write(vals)
        pickings |= self.mapped('picking_id')

        if {'product_uom_qty', 'quantity', 'picking_id'} & set(vals):
            pickings._sync_adt_quantities_from_moves()

        return res

    def unlink(self):
        pickings = self.mapped('picking_id')
        res = super().unlink()
        pickings._sync_adt_quantities_from_moves()
        return res

    def _adt_get_final_dest_location(self):
        self.ensure_one()

        picking = self.picking_id
        base_dest_location = (
            picking.adt_dest_location_id
            if picking and picking.adt_dest_location_id and picking.picking_type_name not in ['Receipts', 'Receipt Internal', 'Direct Receipt']
            else self.adt_dest_location_id
        )

        if not base_dest_location:
            return False

        putaway_location = base_dest_location._get_putaway_strategy(
            self.product_id,
            quantity=self.product_uom_qty,
            packaging=self.product_packaging_id,
        )

        return putaway_location or base_dest_location


class StockMoveScanWizard(models.TransientModel):
    _name = 'stock.move.scan.wizard'
    _description = 'Stock Move Scan Wizard'

    picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Picking',
        required=True,
        readonly=True,
    )

    scan_code = fields.Char(
        string='Scan Product / QR Code',
    )

    allowed_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_product_ids',
    )

    lot_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product From Lines',
        domain="[('id', 'in', allowed_product_ids)]",
    )

    @api.depends('picking_id')
    def _compute_allowed_product_ids(self):
        for rec in self:
            rec.allowed_product_ids = rec.picking_id.move_ids.product_id

    @api.onchange('lot_product_id')
    def _onchange_lot_product_id(self):
        if self.lot_product_id:
            self.scan_code = self.lot_product_id.default_code or self.lot_product_id.barcode
        else:
            self.scan_code = ''

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        readonly=True,
    )

    move_line_ids = fields.Many2many(
        comodel_name='stock.move.line',
        string='Stock Move Lines',
    )

    @api.onchange('scan_code')
    def _onchange_scan_code(self):
        for wizard in self:
            wizard.product_id = False
            wizard.move_line_ids = False

            if not wizard.scan_code:
                continue

            scan_code = wizard.scan_code.strip()
            product = wizard._find_product_by_scan_code(scan_code)
            if not product:
                product = wizard._find_product_by_lot_scan_code(scan_code)

            if not product:
                continue

            wizard.product_id = product

            lines = wizard.picking_id.move_line_ids.filtered(
                lambda line: line.product_id == product
            )

            wizard.move_line_ids = [(6, 0, lines.ids)]

    def _find_product_by_scan_code(self, scan_code):
        Product = self.env['product.product']

        return Product.search([
            '|',
            ('barcode', '=', scan_code),
            ('default_code', '=', scan_code),
        ], limit=1)

    def _find_product_by_lot_scan_code(self, scan_code):
        self.ensure_one()
        StockLot = self.env['stock.lot']

        lots = StockLot.search([('name', '=', scan_code)])
        move_lines = self.picking_id.move_line_ids.filtered(
            lambda line: (
                (lots and line.lot_id in lots)
                or (line.lot_name and line.lot_name == scan_code)
            )
        )
        products = move_lines.product_id

        return products[:1] if len(products) == 1 else self.env['product.product']
