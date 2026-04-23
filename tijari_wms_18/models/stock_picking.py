from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Memberi label unik untuk menghindari warning 'Same label: Type (Acumatica)'
    adt_receipt_nbr = fields.Char(string='Receipt Nbr (Acumatica)')
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
    
    # PERBAIKAN: Beri string yang berbeda untuk masing-masing field
    adt_receipt_type = fields.Char(string='Receipt Type (Acumatica)')
    adt_trans_type = fields.Char(string='Trans Type (Acumatica)')
    
    adt_external_ref = fields.Char(string='External Ref (Acumatica)')
    adt_warehouse_code = fields.Char(string='Warehouse (Acumatica)')
    adt_external_id = fields.Char(string='UUID Header Acumatica')
