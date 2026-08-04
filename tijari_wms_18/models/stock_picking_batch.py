from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class StockPickingBatch(models.Model):
    _inherit = 'stock.picking.batch'

    allowed_putaway_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_putaway_product_ids',
    )
    allowed_putaway_move_line_ids = fields.Many2many(
        'stock.move.line',
        compute='_compute_allowed_putaway_move_line_ids',
    )
    scan_product_button = fields.Boolean(string='Scan Product')
    putaway_product_id = fields.Many2one(
        'product.product',
        string='Product Name',
    )
    putaway_lot_id = fields.Many2one(
        comodel_name='stock.lot',
        string='LOT Number',
        compute='_compute_putaway_values',
        readonly=True,
    )
    putaway_move_line_ids = fields.Many2many(
        comodel_name='stock.move.line',
        string='Stock Move Lines',
        compute='_compute_putaway_values',
        readonly=False,
    )
    picking_type_name = fields.Char(
        related='picking_type_id.name',
        store=False,
    )

    def _get_putaway_base_move_lines(self):
        self.ensure_one()

        return self._get_batch_move_lines().filtered(
            lambda line: (
                (line.lot_id or line.lot_name)
                and line.quantity > 0
                and line.picker_status == 'finished'
            )
        )

    def _get_putaway_move_lines(self):
        self.ensure_one()

        move_lines = self._get_putaway_base_move_lines()
        if self.putaway_product_id:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == self.putaway_product_id
            )

        return move_lines

    def _get_batch_move_lines(self):
        self.ensure_one()
        return self.move_ids.move_line_ids

    @api.depends(
        'move_ids',
        'move_ids.product_id',
        'move_ids.move_line_ids',
        'move_ids.move_line_ids.product_id',
        'move_ids.move_line_ids.lot_id',
        'move_ids.move_line_ids.quantity',
        'move_ids.move_line_ids.picker_status',
    )
    def _compute_allowed_putaway_product_ids(self):
        for batch in self:
            batch.allowed_putaway_product_ids = batch._get_putaway_base_move_lines().product_id

    @api.depends(
        'putaway_product_id',
        'move_ids',
        'move_ids.move_line_ids',
        'move_ids.move_line_ids.product_id',
        'move_ids.move_line_ids.lot_id',
        'move_ids.move_line_ids.quantity',
        'move_ids.move_line_ids.picker_status',
    )
    def _compute_allowed_putaway_move_line_ids(self):
        for batch in self:
            batch.allowed_putaway_move_line_ids = batch._get_putaway_move_lines()

    @api.depends(
        'putaway_product_id',
        'move_ids',
        'move_ids.move_line_ids',
        'move_ids.move_line_ids.product_id',
        'move_ids.move_line_ids.lot_id',
        'move_ids.move_line_ids.quantity',
        'move_ids.move_line_ids.picker_status',
    )
    def _compute_putaway_values(self):
        for batch in self:
            move_lines = batch._get_putaway_move_lines()
            batch.putaway_move_line_ids = move_lines
            batch.putaway_lot_id = (
                move_lines.mapped('lot_id')[:1]
                if batch.putaway_product_id
                else False
            )

    @api.onchange('putaway_product_id')
    def _onchange_putaway_product_id(self):
        for batch in self:
            move_lines = batch._get_putaway_move_lines()
            batch.putaway_move_line_ids = move_lines
            batch.putaway_lot_id = (
                move_lines.mapped('lot_id')[:1]
                if batch.putaway_product_id
                else False
            )

    def action_prepare_scan_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'adt_scan_qr_to_picking_product',
            'params': {
                'res_model': self._name,
                'res_id': self.id,
                'title': 'Scan Product QR Code',
            },
        }

    def action_detailed_operations(self):
        self.ensure_one()
        view_id = self.env.ref('stock.view_stock_move_line_detailed_operation_tree').id
        first_picking = self.picking_ids[:1]
        return {
            'name': _('Detailed Operations'),
            'view_mode': 'list',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move.line',
            'views': [(view_id, 'list')],
            'domain': [('id', 'in', self._get_batch_move_lines().ids)],
            'context': {
                'sml_specific_default': True,
                'default_picking_id': first_picking.id,
                'default_location_id': first_picking.location_id.id,
                'default_location_dest_id': first_picking.location_dest_id.id,
                'default_company_id': self.company_id.id,
                'show_lots_text': False,
                'picking_code': self.picking_type_code,
                'create': self.state not in ('done', 'cancel'),
            },
        }

    def action_generate_lot(self):
        for batch in self:
            batch._get_batch_move_lines().generate_lot()


    def action_validate_lot(self):
        for batch in self:
            batch.picking_ids.move_ids.action_validate_lot()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Done'),
                'message': _('Lot validated for batch operations.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _check_all_move_lines_matched(self):
        for batch in self:
            move_lines = batch._get_batch_move_lines().filtered(
                lambda line: (
                    line.state not in ('done', 'cancel')
                    and line.quantity > 0
                    and (line.lot_id or line.lot_name)
                )
            )
            if batch.picking_type_name in ('Receipts', 'Receipt Internal'):
                unfinished_lines = move_lines.filtered(
                    lambda line: line.putaway_status != 'finished'
                )

                if not unfinished_lines:
                    continue

                lines = "\n".join(
                    "- %s | Lot/Serial: %s | Qty: %s | Status: %s"
                    % (
                        line.product_id.display_name,
                        line.lot_id.name or line.lot_name or "-",
                        line.quantity,
                        dict(line._fields['putaway_status'].selection).get(
                            line.putaway_status,
                            line.putaway_status or "-"
                        ),
                    )
                    for line in unfinished_lines
                )
                raise UserError(
                    _(
                        "Validation blocked.\n\n"
                        "Semua move line putaway batch harus memiliki status "
                        "'Finished' sebelum batch divalidasi.\n\n"
                        "Move line yang belum finish:\n%s"
                    )
                    % lines
                )

                continue

            unmatched_lines = move_lines.filtered(
                lambda line: line.matching != 'match'
            )

            if not unmatched_lines:
                continue

            lines = "\n".join(
                "- %s | Lot/Serial: %s | Qty: %s | Matching: %s"
                % (
                    line.product_id.display_name,
                    line.lot_id.name or line.lot_name or "-",
                    line.quantity,
                    dict(line._fields['matching'].selection).get(
                        line.matching,
                        line.matching or "-"
                    ),
                )
                for line in unmatched_lines
            )
            raise UserError(
                _(
                    "Validation blocked.\n\n"
                    "Semua move line batch harus memiliki status matching "
                    "'Match' sebelum batch divalidasi.\n\n"
                    "Move line yang belum match:\n%s"
                )
                % lines
            )

    def action_done(self):
        self._check_all_move_lines_matched()
        return super().action_done()

    def _find_product_by_scan_code(self, scan_code):
        Product = self.env['product.product']

        return Product.search([
            '|',
            ('barcode', '=', scan_code),
            ('default_code', '=', scan_code),
        ], limit=1)

    def action_apply_scanned_product(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product = self._find_product_by_scan_code(scanned_code)

        if not product:
            raise ValidationError(
                'Product tidak ditemukan untuk kode scan: %s' % scanned_code
            )

        self.write({'putaway_product_id': product.id})

        return {
            'product_id': product.id,
            'display_name': product.display_name,
        }
