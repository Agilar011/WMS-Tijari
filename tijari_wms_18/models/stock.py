# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime as fDT
from odoo.tools import float_is_zero, float_compare
import hashlib
import base64
from ast import literal_eval

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

    def button_validate(self):
        for picking in self:
            operation_category = picking.picking_type_id.operation_category

            # Hanya enforce untuk PUT dan DELIVERY
            if operation_category in ['put', 'delivery']:
                for line in picking.move_line_ids:
                    # Jika belum dicek (invisible), tidak dianggap ok
                    if line.matching != 'match':
                        raise UserError(_(
                            "Validation blocked.\n\n"
                            "Line:\n"
                            f"- Product: {line.product_id.display_name}\n"
                            f"- Qty: {line.quantity or line.product_uom_qty}\n\n"
                            "Status: ❌ NOT MATCH\n\n"
                            "Silakan pastikan scan location dan/atau lot sudah benar."
                        ))

        return super().button_validate()

class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    operation_category = fields.Selection([('put', 'Put'), ('pack', 'Pack'), ('internal', 'Internal Transfer'), ('receive', 'Receive'), ('delivery', 'Delivery'), ('others', 'Others')], string='Operation Category', required=True, help='Indicates whether this operation type is for putting away or picking goods.')


class StockLocation(models.Model):
    _inherit = 'stock.location'

    sequence = fields.Boolean(string='Sequence', default=False, help='Indicates if the location uses sequence for operations')
    unique_code = fields.Char(string='Unique Code', help='A unique code for the location')

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
    
    lot_button = fields.Char(string="Lot Button", compute="_compute_lot_button")

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
        for line in self:
            matching = ''

            picking_type = line.picking_id.picking_type_id
            operation_category = picking_type.operation_category if picking_type else False

            # Untuk PUT → cek unique_code lokasi (aku anggap DESTINATION location)
            if operation_category == 'put':
                # kalau belum ada input, keep invisible
                if line.confirmation_location_code or line.confirmation_lot_code:
                    dest_loc = line.location_dest_id
                    dest_code = dest_loc.unique_code if dest_loc else False
                    lot = line.lot_id

                    loc_ok = bool(dest_code and line.confirmation_location_code == dest_code)
                    lot_ok = bool(lot and line.confirmation_lot_code and line.confirmation_lot_code == lot.name)

                    if loc_ok and lot_ok:
                        matching = 'match'
                    else:
                        matching = 'not_match'

            # Untuk PACK → cek lot + unique_code (aku anggap SOURCE location)
            elif operation_category == 'delivery':
                # kalau belum ada input sama sekali, invisible
                if line.confirmation_location_code or line.confirmation_lot_code:
                    src_loc = line.location_id
                    src_code = src_loc.unique_code if src_loc else False
                    lot = line.lot_id

                    # kondisi match
                    loc_ok = bool(src_code and line.confirmation_location_code == src_code)
                    lot_ok = bool(lot and line.confirmation_lot_code and line.confirmation_lot_code == lot.name)

                    if loc_ok and lot_ok:
                        matching = 'match'
                    else:
                        matching = 'not_match'

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

    @api.onchange('lot_button')
    def _onchange_lot_button(self):
        for line in self:
            if line.lot_button:
                # Jalankan logika generate/pick lot
                vals = line.action_generate_or_pick_lot()
                if vals.get('lot_id'):
                    line.lot_id = vals['lot_id']
                if vals.get('lot_name'):
                    line.lot_name = vals['lot_name']
                line.lot_button = False

    def _compute_lot_button(self):
        # field dummy, tidak dipakai
        for rec in self:
            rec.lot_button = " "

    # ---------- Helpers ----------
    def _tjr_is_incoming_tracked(self):
        self.ensure_one()
        return (
            self.picking_id
            and self.picking_id.picking_type_code == 'incoming'
            and self.product_id
            and self.product_id.tracking != 'none'
        )

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
            if not line.product_id or line.product_id.tracking == 'none':
                # tidak perlu lot
                continue

            # === Incoming: generate lot_name ===
            if line._tjr_is_incoming_tracked():
                new_name = line._tjr_build_lot_name()
                # biarkan Odoo membuat lot saat validasi jika lot_id kosong
                line.write({'lot_id': False, 'lot_name': new_name})
                continue

            # === Outgoing/Internal: pilih lot via FIFO ===
            if not line.location_id:
                raise UserError(_("Source Location is empty on the move line."))

            # Berapa kuantitas yang mau di-assign?
            # - Jika qty_done sudah diisi, pakai itu.
            # - Jika kosong: untuk serial -> 1; untuk lot -> sisa qty di line (product_uom_qty/demand).
            uom_line = line.product_uom_id or line.product_id.uom_id
            qty_needed_line_uom = line.quantity
            if not qty_needed_line_uom:
                if line.product_id.tracking == 'serial':
                    qty_needed_line_uom = 1.0
                else:
                    qty_needed_line_uom = line.product_uom_qty or line.qty_reserved or 0.0
                    if not qty_needed_line_uom:
                        qty_needed_line_uom = 1.0  # fallback

            # konversi ke UoM produk (base) untuk hitung available quant
            qty_needed_base = uom_line._compute_quantity(qty_needed_line_uom, line.product_id.uom_id, rounding_method='HALF-UP')

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
                avail = Quant._get_available_quantity(
                    product=line.product_id,
                    location=q.location_id,
                    lot_id=q.lot_id,
                    package_id=q.package_id or None,
                    owner_id=q.owner_id or None,
                    strict=True,
                )
                if avail <= 0:
                    continue

                if avail >= qty_needed_base or line.product_id.tracking == 'serial':
                    # gunakan lot ini
                    updates = {'lot_id': q.lot_id.id, 'lot_name': False}
                    # Kalau qty_done 0, isi qty_done minimal 1 untuk serial, atau min(avail, qty_needed)
                    if not line.quantity:
                        if line.product_id.tracking == 'serial':
                            qty_to_write = 1.0
                        else:
                            # convert avail (base) ke uom line
                            qty_to_write = line.product_id.uom_id._compute_quantity(
                                min(avail, qty_needed_base),
                                uom_line,
                                rounding_method='HALF-UP'
                            )
                        updates['quantity'] = qty_to_write
                    line.write(updates)
                    chosen = True
                    break

            if not chosen:
                # Tidak ada lot yg cukup → pilih lot tertua yang punya sedikit stok (sebagai hint)
                partial = next((q for q in quants if Quant._get_available_quantity(
                    line.product_id, q.location_id, lot_id=q.lot_id,
                    package_id=q.package_id or None, owner_id=q.owner_id or None, strict=True) > 0), None)
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
