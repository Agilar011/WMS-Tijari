# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime as fDT
from odoo.tools import float_is_zero, float_compare
from odoo.modules.module import get_module_resource
import hashlib
import base64
from ast import literal_eval
from odoo.tools.misc import OrderedSet
import os
import psycopg2
from PIL import Image
import qrcode
import io
from collections import defaultdict

import logging
_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def action_view_stock_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_move_line_action")
        action['domain'] = [
            '|',
                ('location_id.warehouse_id', '=', self.location_id.warehouse_id.id),
                ('location_dest_id.warehouse_id', '=', self.location_id.warehouse_id.id),
            ('lot_id', '=', self.lot_id.id),
            # '|',
            #     ('package_id', '=', self.package_id.id),
            #     ('result_package_id', '=', self.package_id.id),
        ]
        action['context'] = literal_eval(action.get('context'))
        action['context']['search_default_product_id'] = self.product_id.id
        return action

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    adt_receipt_nbr = fields.Char(string='Receipt Nbr (Acumatica)', index=True)
    adt_vendor_code = fields.Char(string='VendorID (Acumatica)')
    adt_partner_ref = fields.Char(string='Vendor Ref (Acumatica)')
    adt_branch_warehouse = fields.Char(string='Branch (Acumatica)')
    adt_actual_qty = fields.Float(string='Control Qty (Acumatica)')
    adt_is_hold = fields.Boolean(string='Hold (Acumatica)')
    adt_inventory_ref = fields.Char(string='Inventory Ref Nbr (Acumatica)')
    adt_acumatica_write_date = fields.Datetime(string='Last Modified (Acumatica)')
    adt_header_location_code = fields.Char(string='Header Location (Acumatica)')
    adt_post_period = fields.Char(string='Post Period (Acumatica)')
    adt_status = fields.Char(string='Status (Acumatica)')
    adt_total_qty = fields.Float(string='Total Qty (Acumatica)')
    adt_type = fields.Char(string='Type (Acumatica)')
    adt_external_ref = fields.Char(string='External Ref (Acumatica)')
    adt_warehouse_code = fields.Char(string='Warehouse (Acumatica)')
    adt_external_id = fields.Char(string='UUID Header Acumatica', index=True)
    operation_category = fields.Selection(related='picking_type_id.operation_category', string='Operation Category', store=True, readonly=True)
    adt_destination_location_address = fields.Char(string='Destination Address')

    qr_code_image = fields.Binary(string='Sign')

    # # def action_print_lot_number_line(self):
    # #     action = {}
    # #     action['type'] = 'ir.actions.act_url'
    # #     action['url'] = '/print/lot_number_move_line?id=' + str(self.id)
    # #     action['target'] = 'new'
    # #     return action

    # def action_print_lot_number_line(self):
    #     self.ensure_one()

    #     lot_names = list(set(
    #         self.move_ids_without_package.mapped('lot_ids.name')
    #     ))

    #     if not lot_names:
    #         return {
    #             'type': 'ir.actions.client',
    #             'tag': 'display_notification',
    #             'params': {
    #                 'title': 'Peringatan',
    #                 'message': 'Lot Number belum tersedia.',
    #                 'type': 'warning',
    #                 'sticky': False,
    #             }
    #         }

    #     self.create_qrcode_name()

    #     ids = ",".join(map(str, self.ids))

    #     return {
    #         'type': 'ir.actions.act_url',
    #         'url': '/print/lot_number_move_line?ids=%s' % ids,
    #         'target': 'new',
    #     }

    # def create_qrcode_name(self):
    #     for rec in self:
    #         lot_names = list(set(
    #             rec.move_ids_without_package.mapped('lot_ids.name')
    #         ))

    #         text = ', '.join(filter(None, lot_names))

    #         if text:
    #             rec.qr_code_image = rec.create_qrcode(text)

    # def create_qrcode(self, text):
    #     logo_path = os.path.abspath(
    #         os.path.join(os.path.dirname(__file__), '../static/src/img/logo-company.png')
    #     )

    #     logo = Image.open(logo_path)

    #     basewidth = 80
    #     wpercent = basewidth / float(logo.size[0])
    #     hsize = int(float(logo.size[1]) * wpercent)

    #     logo = logo.resize((basewidth, hsize))

    #     qr = qrcode.QRCode(
    #         error_correction=qrcode.constants.ERROR_CORRECT_H
    #     )

    #     qr.add_data(text)
    #     qr.make(fit=True)

    #     img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    #     img = img.resize((300, 300))

    #     pos = (
    #         (img.size[0] - logo.size[0]) // 2,
    #         (img.size[1] - logo.size[1]) // 2
    #     )

    #     img.paste(logo, pos)

    #     buffer = io.BytesIO()
    #     img.save(buffer, format="PNG")

    #     return base64.b64encode(buffer.getvalue()).decode()

    def _sync_adt_quantities_from_moves(self):
        for picking in self:
            picking.update({
                'adt_total_qty': sum(picking.move_ids.mapped('product_uom_qty')),
                'adt_actual_qty': sum(picking.move_ids.mapped('quantity')),
            })

    def button_validate(self):
        res = super().button_validate()

        for rec in self:
            print(rec.picking_type_id.operation_category)
            for line in rec.move_line_ids:
                print(f">>> Validating line {line.id} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id},Picking id: {line.picking_id.id}, Picking Type: {line.picking_id.picking_type_id.name}, Status product: {line.picking_id.picking_type_id.operation_category}, Matching Status: {line.matching}") # Cek di terminal Odoo
                line.lot_name = line.lot_id.name if line.lot_id else line.lot_name
                if not line.lot_name:
                    print(f"Missing lot: {line}")
                    raise UserError(_("Validation blocked.\n Lot not Found Please generate lot for all lines before validating the picking."))
                
        for picking in self:
            if picking.picking_type_id.name not in ('Pick', 'Receipt'):
                print("Run validate all except pick and receipt")
                # Lakukan perulangan untuk setiap stock.move yang ada di dalam picking
                for move in picking.move_ids:
                    # Jika move memiliki move_line_ids, lakukan update massal di level DB
                    for line in move.move_line_ids:
                        loc_code = str(line.location_id.unique_code or '').strip()
                        product_code = str(line.lot_id.name or '').strip()

                        line.confirmation_location_code = loc_code
                        line.confirmation_lot_code = product_code
                        line.matching = 'match'
                
            picking._check_validate_requirements()
            operation_category = picking.picking_type_id.operation_category
            print(f">>> Validating picking {picking.id} - Picking Type: {picking.picking_type_id.name}, Operation Category: {operation_category}") # Cek di terminal Odoo

            # Hanya enforce untuk PUT dan DELIVERY
            if operation_category in ['put', 'delivery']:
                for line in picking.move_line_ids:
                    # Jika belum dicek (invisible), tidak dianggap ok
                    print(f">>> Checking line {line.matching} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id.name if line.lot_id else 'N/A'}") # Cek di terminal Odoo
                    # line.matching = 'match'
                    print(f">>> Matching status for line {line.id}: {line.matching}") # Cek di terminal Odoo
                    if line.matching != 'match':
                        raise UserError(_(
                            "Validation blocked.\n\n"
                            "Line:\n"
                            f"- Product: {line.product_id.display_name}\n"
                            f"- Qty: {line.quantity or line.product_uom_qty}\n\n"
                            "Status: ❌ NOT MATCH\n\n"
                            "Silakan pastikan scan location dan/atau lot sudah benar."
                        ))
            pickings = self.env["stock.picking"].search([])
            if picking.picking_type_id.code != "incoming":
                continue

            storage_pickings = self.env["stock.picking"].search([
                ("origin", "ilike", picking.origin or picking.name),
                ("picking_type_id.code", "=", "internal"),
            ], limit=1)
            total_qty = sum(picking.move_ids.move_line_ids.mapped("quantity"))
            picking.write({
                'adt_total_qty': total_qty
            })

            storage_pickings.write({
                "adt_dest_location_id": picking.adt_dest_location_id,
                "adt_type": picking.adt_type,
                "note" : picking.note,
            })
            # for ml in picking.move_line_ids:
                # if not ml.allocation_storage:
                #     raise ValidationError(f'Isi Allocation Storage di line product {ml.product_id.name}.')
                # move_line = self.env['stock.move.line'].search([
                #     ("picking_id", "=", storage_pickings.id),
                #     ("product_id", "=", ml.product_id.id),
                #     ("quantity", "=", ml.quantity)
                # ])
                # if move_line:
                #     move_line.location_dest_id = ml.allocation_storage.id

            # Lot = self.env['stock.lot']
            # for lot_name in set(picking.move_line_ids.mapped('lot_name')):
            #     qty = sum(
            #         picking.move_line_ids.filtered(lambda l: l.lot_name == lot_name).mapped('quantity')
            #     )
            #     lot = Lot.search([('name', '=', lot_name)], limit=1)
            #     if lot:
            #         lot.product_qty = qty

            for storage in storage_pickings:
                for storage_move in storage.move_ids:
                    receipt_move = picking.move_ids.filtered(
                        lambda m: m.product_id == storage_move.product_id
                    )[:1]

                    if receipt_move:
                        storage_move.write({
                            "product_note": receipt_move.product_note,
                        })

            for move in picking.move_ids:
                if move.quantity > move.product_uom_qty:
                    total_qty = sum(line.mapped("quantity"))
                    raise UserError(
                        _(
                            "Product: %s\n"
                            "Lot: %s\n"
                            "Total QTY: %s\n"
                            "Demand: %s\n\n"
                            "Quantity exceeds demand."
                        ) % (
                            move.product_id.display_name,
                            line.lot_id.name or "-",
                            move.quantity,
                            move.product_uom_qty,
                        )
                    )

        return res

    def _check_validate_requirements(self):
        self.ensure_one()

        active_moves = self.move_ids.filtered(
            lambda move: move.state != "cancel"
        )

        unpicked_moves = active_moves.filtered(
            lambda move: not move.picked
        )

        unmatched_move_lines = active_moves.move_line_ids.filtered(
            lambda line: line.matching != "match"
        )

        error_messages = []

        if unpicked_moves:
            products = "\n".join(
                f"- {move.product_id.display_name}"
                for move in unpicked_moves
            )

            error_messages.append(
                _(
                    "Semua product harus dalam kondisi picked.\n"
                    "Move yang belum picked:\n%s"
                )
                % products
            )

        if unmatched_move_lines:
            lines = "\n".join(
                "- %s | Lot/Serial: %s | Matching: %s"
                % (
                    line.product_id.display_name,
                    line.lot_id.name or line.lot_name or "-",
                    dict(line._fields["matching"].selection).get(
                        line.matching,
                        line.matching or "-"
                    ),
                )
                for line in unmatched_move_lines
            )

            error_messages.append(
                _(
                    "Semua product harus memiliki status matching "
                    "'Match'.\n"
                    "Move line yang belum match:\n%s"
                )
                % lines
            )

        if error_messages:
            raise UserError("\n\n".join(error_messages))

    def action_print_warehouse_receipt(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/warehouse_receipt?id=' + str(self.id)
        action['target'] = 'new'
        return action

    def do_print_picking(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/warehouse_receipt?id=' + str(self.id)
        action['target'] = 'new'
        return action

    def action_confirm(self):
        res = super().action_confirm()
        self._adt_apply_dest_location_to_move_lines()
        return res

    def action_assign(self):
        res = super().action_assign()
        self._adt_apply_dest_location_to_move_lines()
        return res

    def _adt_apply_dest_location_to_move_lines(self):
        for picking in self:
            if not picking.adt_dest_location_id:
                continue

            for move in picking.move_ids_without_package:
                final_dest_location = move._adt_get_final_dest_location()
                if not final_dest_location:
                    continue

                move.location_dest_id = picking.adt_dest_location_id

                if move.move_line_ids:
                    move.move_line_ids.write({
                        'location_dest_id': final_dest_location.id,
                    })


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    operation_category = fields.Selection([
        ('put', 'Put'), 
        ('pack', 'Pack'), 
        ('internal', 'Internal Transfer'), 
        ('receive', 'Receive'), 
        ('delivery', 'Delivery'), 
        ('others', 'Others')
    ], string='Operation Category', required=False, default='others') 

    is_default_api = fields.Boolean(string="Default Picking Type For API")

    # def get_action_picking_tree_draft(self):
    #     self.ensure_one()

    #     action = self._get_action("stock.stock_picking_action_picking_type")

    #     ctx = action.get("context", {})
    #     if isinstance(ctx, str):
    #         from odoo.tools.safe_eval import safe_eval
    #         ctx = safe_eval(ctx)

    #     ctx.update({
    #         "search_default_draft": 1,
    #     })

    #     action["context"] = ctx

    #     return action


class StockLocation(models.Model):
    _inherit = 'stock.location'

    sequence = fields.Boolean(string='Sequence', default=False, help='Indicates if the location uses sequence for operations')
    unique_code = fields.Char(string='Unique Code', help='A unique code for the location')
    is_location_mapping = fields.Boolean(string="Parent Mapping Location")

    def generate_unique_code(self):
        for location in self:
            if not location.unique_code:
                raw = f"{location.id}-{location.create_date}".encode("utf-8")
                hash_str = base64.b32encode(hashlib.sha256(raw).digest())[:8].decode()
                location.unique_code = f"LOC-{hash_str}"


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
    difference_quantity = fields.Float(
        string='Difference Quantity',
        compute='_compute_difference_quantity',
        store=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves.mapped('picking_id')._sync_adt_quantities_from_moves()
        return moves

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

    @api.depends('product_uom_qty', 'quantity')
    def _compute_difference_quantity(self):
        for move in self:
            difference = move.product_uom_qty - move.quantity
            move.difference_quantity = difference if difference > 0 else 0.0


    # lot_button = fields.Char(string="Lot Button")

    def action_validate_lot(self):
        for move in self:
            for line in move.move_line_ids:
                if not line.lot_id:
                    raise ValidationError("Lot kosong, Silahkan generate lot terlebih dahulu")
                line.matching_lot_id = line.lot_id.id or False
                line.matching_loc_dest_id = line.location_dest_id.id or False
                line.confirmation_lot_code = line.lot_id.name or False
                line.confirmation_location_code = line.location_dest_id.unique_code or False

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


class StockLot(models.Model):
    _inherit = 'stock.lot'

    qr_code_image = fields.Binary(string='Sign')

    def action_print_lot_number(self):
        self.ensure_one()
        self.create_qrcode_name()
        return {
            'type': 'ir.actions.act_url',
            'url': '/print/lot_number?id=%s' % self.id,
            'target': 'new',
        }

    def create_qrcode_name(self):
        for record in self:
            if record.name:
                qr = record.create_qrcode(record.name)
                record.write({
                    'qr_code_image': qr
                })

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
