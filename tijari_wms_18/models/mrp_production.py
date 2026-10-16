from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import base64
from odoo.addons.tijari_wms_18.controllers.controllers import WmsApiController

from odoo.tools.float_utils import float_compare, float_round

import logging
_logger = logging.getLogger(__name__)

class WMSMRPProduction(models.Model):
    _inherit = "mrp.production"
    _description = "WMSMRPProduction"

    picking_type_name = fields.Char(
        related="picking_type_id.name",
        store=False,
    )
    catatan = fields.Text(string="Transaction Notes")
    desc_note = fields.Char('Description Note')
    raw_material_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_raw_material_product_ids',
    )
    raw_material_product_id = fields.Many2one('product.product', string='Product')
    raw_material_lot_ids = fields.Many2many(
        'stock.lot',
        compute='_compute_raw_material_lot_ids',
    )
    raw_material_lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial Number',
        domain="[('id', 'in', raw_material_lot_ids)]",
    )
    raw_material_scan_code = fields.Char(
        string='Scan Handheld',
        help='Bisa diisi dari scanner handheld atau diketik manual.',
    )
    raw_material_scan_button = fields.Boolean(string='Scan Handheld')
    filtered_raw_material_move_ids = fields.One2many(
        'stock.move',
        'raw_material_production_id',
        string='Filtered Raw Materials',
        compute='_compute_filtered_raw_material_move_ids',
    )

    def _get_raw_material_base_moves(self):
        self.ensure_one()
        return self.move_raw_ids.filtered(lambda move: move.state != 'cancel' and move.product_id)

    def _get_raw_material_moves(self):
        self.ensure_one()
        moves = self._get_raw_material_base_moves()
        if self.raw_material_product_id:
            moves = moves.filtered(lambda move: move.product_id == self.raw_material_product_id)
        if self.raw_material_lot_id:
            lot = self.raw_material_lot_id
            moves = moves.filtered(lambda move: (
                lot in move.lot_ids
                or lot in move.move_line_ids.lot_id
                or lot.name in move.move_line_ids.mapped('lot_name')
            ))
        return moves

    def _get_raw_material_lots(self):
        self.ensure_one()
        moves = self._get_raw_material_base_moves()
        if self.raw_material_product_id:
            moves = moves.filtered(lambda move: move.product_id == self.raw_material_product_id)
        lots = moves.lot_ids | moves.move_line_ids.lot_id
        lot_names = moves.move_line_ids.filtered(
            lambda line: line.lot_name and not line.lot_id
        ).mapped('lot_name')
        if lot_names:
            domain = [('name', 'in', lot_names)]
            if moves.product_id:
                domain.append(('product_id', 'in', moves.product_id.ids))
            lots |= self.env['stock.lot'].search(domain)
        return lots

    @api.depends('move_raw_ids', 'move_raw_ids.product_id', 'move_raw_ids.state')
    def _compute_raw_material_product_ids(self):
        for production in self:
            production.raw_material_product_ids = production._get_raw_material_base_moves().product_id

    @api.depends(
        'raw_material_product_id', 'move_raw_ids', 'move_raw_ids.lot_ids',
        'move_raw_ids.move_line_ids.lot_id', 'move_raw_ids.move_line_ids.lot_name',
    )
    def _compute_raw_material_lot_ids(self):
        for production in self:
            production.raw_material_lot_ids = production._get_raw_material_lots()

    @api.depends(
        'raw_material_product_id', 'raw_material_lot_id', 'move_raw_ids',
        'move_raw_ids.product_id', 'move_raw_ids.state', 'move_raw_ids.lot_ids',
        'move_raw_ids.move_line_ids.lot_id', 'move_raw_ids.move_line_ids.lot_name',
    )
    def _compute_filtered_raw_material_move_ids(self):
        for production in self:
            production.filtered_raw_material_move_ids = production._get_raw_material_moves()

    @api.onchange('raw_material_product_id')
    def _onchange_raw_material_product_id(self):
        for production in self:
            production.raw_material_lot_id = production._get_raw_material_lots()[:1] if production.raw_material_product_id else False

    @api.onchange('raw_material_lot_id')
    def _onchange_raw_material_lot_id(self):
        for production in self:
            if not production.raw_material_lot_id:
                production.raw_material_product_id = False
                continue
            lot = production.raw_material_lot_id
            moves = production._get_raw_material_base_moves().filtered(lambda move: (
                lot in move.lot_ids
                or lot in move.move_line_ids.lot_id
                or lot.name in move.move_line_ids.mapped('lot_name')
            ))
            production.raw_material_product_id = moves.product_id[:1]

    def _get_raw_material_scan_values(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        if not scanned_code:
            raise ValidationError(_('Kode scan tidak boleh kosong.'))

        product = self.env['product.product'].search([('barcode', '=', scanned_code)], limit=1)
        if not product:
            product = self.env['product.product'].search([('default_code', '=', scanned_code)], limit=1)
        moves = self._get_raw_material_base_moves()
        if product:
            matched_moves = moves.filtered(lambda move: move.product_id == product)
            if not matched_moves:
                raise ValidationError(_('Product hasil scan tidak ada di Raw Material Manufacturing ini.'))
            lot = (matched_moves.lot_ids | matched_moves.move_line_ids.lot_id)[:1]
            return {'raw_material_product_id': product.id, 'raw_material_lot_id': lot.id}

        lots = self.env['stock.lot'].search([('name', '=', scanned_code)])
        matched_moves = moves.filtered(lambda move: (
            (lots and bool(move.lot_ids & lots))
            or move.move_line_ids.filtered(lambda line: (
                (lots and line.lot_id in lots) or line.lot_name == scanned_code
            ))
        ))
        if not matched_moves:
            raise ValidationError(_('Kode %s tidak ditemukan sebagai Barcode, SKU, atau Lot di Raw Material Manufacturing ini.') % scanned_code)
        products = matched_moves.product_id
        if len(products) > 1:
            raise ValidationError(_('Lot hasil scan mengarah ke lebih dari satu product.'))
        return {'raw_material_product_id': products.id, 'raw_material_lot_id': lots[:1].id}

    def action_apply_scanned_picker_code(self, scanned_code):
        self.ensure_one()
        values = self._get_raw_material_scan_values(scanned_code)
        self.write(values)
        return values

    @api.onchange('raw_material_scan_code')
    def _onchange_raw_material_scan_code(self):
        for production in self:
            if production.raw_material_scan_code:
                production.update(production._get_raw_material_scan_values(production.raw_material_scan_code))
                production.raw_material_scan_code = False

    def _prepare_stock_lot_values(self):
        self.ensure_one()
        product_code = self.product_id.default_code or f"PROD{self.product_id.id}"
        document_number = self.origin or self.name
        lot_name = "%s-%s-%s" % (
            product_code,
            fields.Date.today().strftime("%m%d%y"),
            document_number,
        )

        return {
            "product_id": self.product_id.id,
            "name": lot_name,
        }

    def _set_lot_producing(self):
        self.ensure_one()
        lot_values = self._prepare_stock_lot_values()
        lot = self.env["stock.lot"].search([
            ("product_id", "=", self.product_id.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
            ("name", "=", lot_values["name"]),
        ], limit=1)
        self.lot_producing_id = lot or self.env["stock.lot"].create(lot_values)

    def action_confirm(self):
        res = super().action_confirm()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })
            production.picking_ids.filtered(
                lambda picking: picking.picking_type_name == "Pick Components"
            ).write({"adt_type": "Kit Assembly"})

        return res

    def action_assign(self):
        res = super().action_assign()

        # Keep the normal reservation flow, then leave raw-material quantity
        # entry to the warehouse operator, like the receipt flow in
        # stock.picking.action_assign().
        move_lines = self.move_raw_ids.move_line_ids.filtered(
            lambda line: line.state not in ('done', 'cancel')
        )
        if move_lines:
            move_lines.write({'quantity': 0.0})

        return res

    def button_mark_done(self):
        for production in self:
            unfinished_moves = production.move_raw_ids.filtered(
                lambda move: move.status_mo_check != 'finished'
            )

            if unfinished_moves:
                details = "\n".join(
                    f"- {move.product_id.display_name}: {move.status_mo_check or 'Belum ada status'}"
                    for move in unfinished_moves
                )

                raise UserError(
                    "Tidak dapat menyelesaikan Manufacturing Order.\n\n"
                    "Raw Materials berikut belum memiliki status 'Finished':\n"
                    f"{details}"
                )
            
            for move in production.move_raw_ids:
                confirmed_qty = move.quantity

                if float_compare(
                    production.qty_producing,
                    confirmed_qty,
                    precision_rounding=production.product_uom_id.rounding,
                ) != 0:
                    raise ValidationError(
                        _(
                            "Qty Digunakan (%s) pada (%s) harus sama dengan "
                            "Qty Producing (%s) sebelum menyelesaikan Manufacture."
                        )
                        % (
                            confirmed_qty,
                            move.product_id.display_name,
                            production.qty_producing,
                        )
                    )

            if (
                production.product_id.tracking in ("lot", "serial")
                and not production.lot_producing_id
            ):
                production.action_generate_serial()

            # for move in production.move_raw_ids:
            #     for line in move.move_line_ids:
            #         confirmation_quantity = line.mo_confirmation_quantity

            #         line.quantity_shadow = line.quantity
            #         line.quantity = confirmation_quantity

        res = super().button_mark_done()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })
            production.picking_ids.filtered(
                lambda picking: picking.picking_type_name == "Store Finished Product"
            ).write({"adt_type": "Kit Assembly"})
        
        return res

    def action_print_hasil_manufacturing(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/hasil_manufacturing?id=' + str(self.id)
        action['target'] = 'new'
        return action

    def action_send_email_hasil_manufacturing(self):
        self.ensure_one()

        response = WmsApiController().PrintHasilManufacturing(id=self.id)
        content_type = response.headers.get('Content-Type', '')
        if (
            response.status_code != 200
            or not response.data
            or 'application/pdf' not in content_type.lower()
        ):
            raise UserError(_('Gagal membuat PDF hasil manufacturing.'))

        attachment = self.env['ir.attachment'].sudo().create({
            'name': '%s_hasil_manufacturing.pdf' % (self.origin or self.name or 'manufacturing'),
            'datas': base64.b64encode(response.data).decode('utf-8'),
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
            'mimetype': 'application/pdf',
        })
        template = self.env.ref(
            'tijari_wms_18.email_template_hasil_manufacturing',
            raise_if_not_found=False,
        )

        return {
            'name': _('Kirim Email Hasil Manufacturing'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': self._name,
                'default_res_ids': [self.id],
                'default_use_template': bool(template),
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_attachment_ids': [(6, 0, [attachment.id])],
                'force_email': True,
                'tijari_hasil_manufacturing_email': True,
            },
        }

    @api.onchange('qty_producing', 'lot_producing_id')
    def _onchange_producing(self):
        if self.state in ['draft', 'cancel'] or (
            self.state == 'done' and self.is_locked
        ):
            return

        productions_bypass_qty_producting = self.filtered(
            lambda p: p.lot_producing_id
            and p.product_tracking == 'lot'
            and p._origin
            and p._origin.qty_producing == p.qty_producing
        )

        (
            self - productions_bypass_qty_producting
        ).with_context(
            skip_raw_material_quantity_update=True
        )._set_qty_producing(False)

class StockMove(models.Model):
    _inherit = "stock.move"

    def _set_quantity_done(self, qty):
        if (
            self.env.context.get('skip_raw_material_quantity_update')
            and self.raw_material_production_id
        ):
            return

        return super()._set_quantity_done(qty)
