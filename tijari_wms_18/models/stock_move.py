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