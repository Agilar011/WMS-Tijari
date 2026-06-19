# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime as fDT
from odoo.tools import float_is_zero, float_compare
import hashlib
import base64
from ast import literal_eval

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

    def button_validate(self):
        res = super().button_validate()



        for rec in self:
            print(rec.picking_type_id.operation_category)
            for line in rec.move_line_ids:
                print(f">>> Validating line {line.id} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id},Picking id: {line.picking_id.id}, Picking Type: {line.picking_id.picking_type_id.name}, Status product: {line.picking_id.picking_type_id.operation_category}, Matching Status: {line.matching}") # Cek di terminal Odoo
                line.lot_name = line.lot_id.name if line.lot_id else line.lot_name
                if not line.lot_name:
                    print(f"Missing lot: {line}")
                    raise UserError(_("Validation blocked.\n\nPlease generate lot for all lines before validating the picking."))
            # if not rec.lot_name:
            #     raise UserError(_("Validation blocked.\n\nPlease generate lot for all lines before validating the picking."))
        for picking in self:
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
                ("origin", "ilike", picking.name),
                ("picking_type_id.code", "=", "internal"),
            ])
            total_qty = sum(picking.move_ids.move_line_ids.mapped("quantity"))
            picking.write({
                'adt_total_qty': total_qty
            })

            total_qty_storage = sum(storage_pickings.move_ids.move_line_ids.mapped("quantity"))
            storage_pickings.write({
                "adt_dest_location_id": picking.adt_dest_location_id,
                "origin": picking.origin or picking.name,
                "note" : picking.note,
                'adt_total_qty': total_qty_storage
            })
            
            for l in line:
                move_line = self.env['stock.move.line'].search([
                    ("picking_id", "=", l.id),
                    ("product_id", "=", l.product_id.id),
                    ("quantity", "=", l.quantity)
                ])
                if move_line:
                    move_line.write({
                        "location_dest_id": l.allocation_storage
                    })

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

class StockMoveLine(models.Model):
    _inherit  = 'stock.move.line'
    # _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = "Stock Move Line"

    adt_dest_location_id = fields.Many2one(
        "stock.location",
        related="move_id.adt_dest_location_id",
        store=True,
        readonly=True,
    )

    lot_button = fields.Char(string="Lot Button", compute="_compute_lot_button")
    auto_input_code = fields.Boolean(string="Auto Input Code", compute="_compute_auto_input_code")

    confirmation_location_code = fields.Char(
        string='Confirmation Location Code',
        help='Scanned / input location code for confirmation.'
    )
    confirmation_lot_code = fields.Char(
        string='Confirmation Lot Code',
        help='Scanned / input lot code for confirmation.'
    )
    matching = fields.Selection([
        ('match', 'Match'),
        ('not_match', 'Not Match')
    ], string='Matching Status',
       compute='_compute_matching',
       store=True)
    matching_html = fields.Html(
        string='Matching Info',
        compute='_compute_matching_html',
        store=False)
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

    picking_code = fields.Selection(
        related='picking_id.picking_type_code',
        store=False,
    )

    @api.depends(
        'confirmation_location_code',
        'confirmation_lot_code',
        'location_id',
        'location_dest_id',
        'lot_id',
        'picking_id',
        'picking_id.picking_type_id',
        'picking_id.picking_type_id.operation_category',
    )
    def _compute_matching(self):
        print(">>> Computing matching status...") # Cek di terminal Odoo
        for line in self:
            print(f">>> Evaluating line {line.id} - Product: {line}") # Cek di terminal Odoo
            matching = ''

            picking_type = line.picking_id.picking_type_id
            operation_category = picking_type.operation_category if picking_type else False
            print(f">>> Line {line.id} - Operation Category: {operation_category}") # Cek di terminal Odoo

            # Untuk PUT → cek unique_code lokasi (aku anggap DESTINATION location)
            if operation_category == 'put':
                print(f">>> picking_type_code: {line.picking_type_id.code if line.picking_id and line.picking_id.picking_type_id else 'N/A'}") # Cek di terminal Odoo
                print(f">>> Operation Category: PUT") # Cek di terminal Odoo
                # kalau belum ada input, keep invisible
                print(f">>> Line Confirmation Location Code: {line.confirmation_location_code}") # Cek di terminal Odoo
                print(f">>> Line Confirmation Lot Code: {line.confirmation_lot_code}") # Cek di terminal Odoo
                if line.confirmation_location_code or line.confirmation_lot_code:
                    print(f">>> Confirmation Location Code: {line.confirmation_location_code}") # Cek di terminal Odoo
                    print(f">>> Confirmation Lot Code: {line.confirmation_lot_code}") #
                    dest_loc = line.location_dest_id
                    dest_code = dest_loc.unique_code if dest_loc else False
                    print(f">>> Destination Location unique code: {dest_code}") # Cek di terminal Odoo
                    print(f">>> Line Lot ID: {line.lot_id}, Lot Name: {line.lot_id.name if line.lot_id else 'N/A'}") # Cek di terminal Odoo
                    lot = line.lot_id

                    loc_ok = bool(dest_code and line.confirmation_location_code == dest_code)
                    lot_ok = bool(lot and line.confirmation_lot_code and line.confirmation_lot_code == lot.name)

                    if loc_ok and lot_ok:
                        matching = 'match'
                    else:
                        matching = 'not_match'

                    print(f">>> Location Match: {loc_ok}, Lot Match: {lot_ok}, Overall Matching Status: {matching}") # Cek di terminal Odoo

            # Untuk PACK → cek lot + unique_code (aku anggap SOURCE location)
            elif operation_category == 'delivery':
                print(f">>> picking_type_code: {line.picking_type_id.code if line.picking_id and line.picking_id.picking_type_id else 'N/A'}") # Cek di terminal Odoo
                print(f">>> Operation Category: DELIVERY") # Cek di terminal Odoo
                print(f">>> Evaluating line {line.id} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id.name if line.lot_id else 'N/A'}") # Cek di terminal Odoo
                # kalau belum ada input sama sekali, invisible
                if line.confirmation_location_code or line.confirmation_lot_code:
                    loc_code = line.location_id.unique_code if line.location_id else (line.quant_id.location_id.unique_code if line.quant_id and line.quant_id.location_id else 'N/A')
                    lot_code = line.lot_id.name if line.lot_id else (line.quant_id.lot_id.name if line.quant_id and line.quant_id.lot_id else 'N/A')
                    print(f">>> Information to match : Lot Code = {lot_code}, Location Code = {loc_code}") # Cek di terminal Odoo
                    # src_loc = line.location_id
                    # src_code = src_loc.unique_code if src_loc else False
                    # lot = line.lot_id
                    # src_code = line.quant_id.location_id.unique_code if line.quant_id.location_id else False
                    # lot = line.quant_id.lot_id.name

                    # kondisi match
                    loc_ok = bool(loc_code and line.confirmation_location_code == loc_code)
                    lot_ok = bool(lot_code and line.confirmation_lot_code == lot_code)

                    if loc_ok and lot_ok:
                        matching = 'match'
                    else:
                        matching = 'not_match'

                    print(f">>> Location Match: {loc_ok}, Lot Match: {lot_ok}, Overall Matching Status: {matching}") # Cek di terminal Odoo

            line.matching = matching

    @api.depends('matching')
    def _compute_matching_html(self):
        for line in self:
            if line.matching == 'match':
                line.matching_html = "<span style='color: green; font-weight: bold;'>MATCH</span>"
            elif line.matching == 'not_match':
                line.matching_html = "<span style='color: red; font-weight: bold;'>NOT MATCH</span>"
            else:
                line.matching_html = False

    @api.onchange('product_id')
    def _onchange_product_copy_previous_lot(self):

        if not self.move_id:
            return

        last_line = self.move_id.move_line_ids.filtered(
            lambda l: l.lot_id
        )

        if last_line:
            self.lot_id = last_line[-1].lot_id
                
    @api.onchange('quant_id')
    def _onchange_move_line_ids(self):
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

            if vals.get('confirmation_location_code'):
                line.confirmation_location_code = vals['confirmation_location_code']

            if vals.get('confirmation_lot_code'):
                line.confirmation_lot_code = vals['confirmation_lot_code']

    @api.onchange('lot_button')
    def _onchange_lot_button(self):
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
    def _tjr_is_incoming_tracked(self):
        print(f">>> Checking if line {self.id} is incoming tracked...") # Cek di terminal Odoo
        self.ensure_one()
        print(f">>> Line {self.id} - Product: {self.product_id.display_name} - Lot id {self.lot_id.name if self.lot_id else 'N/A'} - Stock Quantity: {self.quantity}") # Cek di terminal Odoo
        # Cek tipe picking dari berbagai sumber (picking_id atau dari context)
        picking_type = self.picking_id.picking_type_id or self.move_id.picking_type_id
        print(f">>> Line {self.id} - Picking Type: {picking_type.name if picking_type else 'N/A'}") # Cek di terminal Odoo
        is_incoming = picking_type.code == 'incoming' or self._context.get('default_picking_type_code') == 'incoming'
        
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

            is_incoming = self.env.context.get('default_picking_type_code') == 'incoming' or \
                          line.picking_id.picking_type_code == 'incoming' or \
                          line.picking_id.picking_type_id.code == 'incoming'
            
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
                    'confirmation_location_code': des_parent_code,
                    'confirmation_lot_code': new_lot_name,
                })
                line.confirmation_location_code = des_parent_code  # Update confirmation_location_code untuk menampilkan di UI
                line.confirmation_lot_code = new_lot_name  # Update confirmation_lot_code untuk menampilkan di UI
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
                print(f">>> chosen lot {q.lot_id.name} - Product: {line.product_id.display_name}") # Cek di terminal Odoo
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
        related="picking_id.adt_dest_location_id",
        store=True,
    )


    # lot_button = fields.Char(string="Lot Button")

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
            
    def _update_total_qty(self):
        for picking in self.mapped("picking_id"):
            picking.adt_total_qty = sum(
                picking.move_ids.mapped("quantity")
            )

    def write(self, vals):
        res = super().write(vals)

        if "quantity" in vals:
            self._update_total_qty()

        return res

