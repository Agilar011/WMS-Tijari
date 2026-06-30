from odoo import models, fields


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

