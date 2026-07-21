from odoo import api, models, fields
import base64
import os
from PIL import Image
import qrcode
import io
from odoo.exceptions import UserError, ValidationError
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
    product_note = fields.Text(string='Product Note')

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
        related="picking_id.picking_type_id.name",
        store=False,
    )

    def action_validate_lot_pick(self):
        for move in self:
            picking_type = move.picking_id.picking_type_id
            for line in move.move_line_ids:
                line._compute_auto_input_code()
                
    def action_validate_lot(self):
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
                    item.source_location_id = False
                    item.unfiltered_dest = value

                    _logger.info("parent_location_id: %s", item.parent_location_id.name)
                    _logger.info("source_location_id: %s", item.source_location_id.name if item.source_location_id else False)
                    _logger.info("unfiltered_dest: %s", item.unfiltered_dest)

                else:
                    item.parent_location_id = move.picking_id.picking_type_id.default_location_src_id.id
                    item.source_location_id = False
                    item.unfiltered_dest = value

                    _logger.info("parent_location_id: %s", item.parent_location_id.name)
                    _logger.info("source_location_id: %s", item.source_location_id.name if item.source_location_id else False)
                    _logger.info("unfiltered_dest: %s", item.unfiltered_dest)

    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()

        print("_get_new_picking_values")
        print("move:", self)
        print("move adt_type:", self.adt_type)
        print("vals before:", vals)

        vals['adt_type'] = self.adt_type

        print("vals after:", vals)

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
                line.adt_dest_location_id = line.location_id

        return res

    def _adt_get_final_dest_location(self):
        self.ensure_one()

        picking = self.picking_id
        base_dest_location = (
            picking.adt_dest_location_id
            if picking and picking.adt_dest_location_id
            else self.location_dest_id
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

            product = wizard._find_product_by_scan_code(wizard.scan_code.strip())

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

