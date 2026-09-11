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
    scan_product_by_lot_button = fields.Boolean(
        string='Scan Product By Lot',
        compute='_compute_scan_product_by_lot_button',
    )
    putaway_product_id = fields.Many2one(
        'product.product',
        string='Product Name',
    )
    allowed_putaway_lot_ids = fields.Many2many(
        'stock.lot',
        compute='_compute_allowed_putaway_lot_ids',
    )
    putaway_lot_id = fields.Many2one(
        comodel_name='stock.lot',
        string='LOT Number',
        readonly=False,
        domain="[('id', 'in', allowed_putaway_lot_ids)]",
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

    def _sync_responsible_users(self):
        for picking in self:
            missing_do = (
                picking.pick_responsible_ids
                - picking.do_responsible_ids
            )

            if missing_do:
                picking.do_responsible_ids = (
                    picking.do_responsible_ids | missing_do
                )

            responsible_users = (
                picking.pick_responsible_ids
                | picking.pack_responsible_ids
                | picking.do_responsible_ids
            )

            picking.user_ids = [(6, 0, responsible_users.ids)]

    def _compute_scan_product_by_lot_button(self):
        for batch in self:
            batch.scan_product_by_lot_button = True

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
        if self.putaway_lot_id:
            move_lines = move_lines.filtered(
                lambda line: line.lot_id == self.putaway_lot_id or line.lot_name == self.putaway_lot_id.name
            )

        return move_lines

    def _get_putaway_move_lines_for_product(self, product):
        self.ensure_one()

        move_lines = self._get_putaway_base_move_lines()
        if product:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == product
            )
        return move_lines

    def _get_putaway_lots(self):
        self.ensure_one()

        move_lines = self._get_putaway_base_move_lines()
        if self.putaway_product_id:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == self.putaway_product_id
            )

        lots = move_lines.lot_id
        lot_names = move_lines.filtered(
            lambda line: line.lot_name and not line.lot_id
        ).mapped('lot_name')
        if lot_names:
            domain = [('name', 'in', lot_names)]
            products = move_lines.product_id
            if products:
                domain.append(('product_id', 'in', products.ids))
            lots |= self.env['stock.lot'].search(domain)
        return lots

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
        'putaway_lot_id',
        'move_ids',
        'move_ids.move_line_ids',
        'move_ids.move_line_ids.product_id',
        'move_ids.move_line_ids.lot_id',
        'move_ids.move_line_ids.lot_name',
        'move_ids.move_line_ids.quantity',
        'move_ids.move_line_ids.picker_status',
    )
    def _compute_allowed_putaway_lot_ids(self):
        for batch in self:
            batch.allowed_putaway_lot_ids = batch._get_putaway_lots()

    @api.depends(
        'putaway_product_id',
        'putaway_lot_id',
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
        'putaway_lot_id',
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

    @api.onchange('putaway_product_id')
    def _onchange_putaway_product_id(self):
        for batch in self:
            move_lines = batch._get_putaway_move_lines_for_product(batch.putaway_product_id)
            batch.putaway_move_line_ids = move_lines
            batch.putaway_lot_id = (
                move_lines.mapped('lot_id')[:1]
                if batch.putaway_product_id
                else False
            )

    @api.onchange('putaway_lot_id')
    def _onchange_putaway_lot_id(self):
        for batch in self:
            if not batch.putaway_lot_id:
                batch.putaway_product_id = False
                batch.putaway_move_line_ids = batch._get_putaway_move_lines()
                continue
            move_lines = batch._get_putaway_base_move_lines().filtered(
                lambda line: (
                    line.lot_id == batch.putaway_lot_id
                    or line.lot_name == batch.putaway_lot_id.name
                )
            )
            products = move_lines.product_id
            if products:
                batch.putaway_product_id = products[:1]
            batch.putaway_move_line_ids = batch._get_putaway_move_lines()

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

    def _find_putaway_product_by_lot_scan_code(self, scan_code):
        self.ensure_one()
        StockLot = self.env['stock.lot']

        lots = StockLot.search([('name', '=', scan_code)])
        move_lines = self._get_putaway_base_move_lines().filtered(
            lambda line: (
                (lots and line.lot_id in lots)
                or (line.lot_name and line.lot_name == scan_code)
            )
        )

        if not move_lines:
            if lots:
                raise ValidationError(_('Lot hasil scan tidak ada di dokumen ini.'))
            raise ValidationError(_('Lot tidak ditemukan untuk kode scan: %s') % scan_code)

        products = move_lines.product_id
        if len(products) > 1:
            raise ValidationError(_('Lot hasil scan mengarah ke lebih dari satu product.'))

        return products[:1], move_lines, lots[:1]

    def action_apply_scanned_product(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product = self._find_product_by_scan_code(scanned_code)

        if not product:
            raise ValidationError(
                'Product tidak ditemukan untuk kode scan: %s' % scanned_code
            )

        move_lines = self._get_putaway_move_lines_for_product(product)
        self.write({
            'putaway_product_id': product.id,
            'putaway_lot_id': move_lines.mapped('lot_id')[:1].id,
        })

        return {
            'product_id': product.id,
            'display_name': product.display_name,
        }

    def action_apply_scanned_product_by_lot(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product, move_lines, lot = self._find_putaway_product_by_lot_scan_code(scanned_code)

        self.write({
            'putaway_product_id': product.id,
            'putaway_lot_id': lot.id,
        })

        return {
            'product_id': product.id,
            'display_name': product.display_name,
            'lot_id': lot.id,
            'move_line_ids': move_lines.ids,
        }

class StockPickingToBatchInherit(models.TransientModel):
    _inherit = 'stock.picking.to.batch'

    pick_responsible_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_to_batch_pick_responsible_rel",
        column1="wizard_id",
        column2="user_id",
        string="Assigned Picker",
        domain=[("share", "=", False)],
    )

    pack_responsible_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_to_batch_pack_responsible_rel",
        column1="wizard_id",
        column2="user_id",
        string="Assigned Packer",
        domain=[("share", "=", False)],
    )

    do_responsible_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_to_batch_do_responsible_rel",
        column1="wizard_id",
        column2="user_id",
        string="Assigned Loader",
        domain=[("share", "=", False)],
    )

    can_edit_pack_responsible_ids = fields.Boolean(
        string="Can Edit Pack Responsible",
        compute="_compute_can_edit_pack_responsible_ids",
        help="Technical field driving the view: only a user who is themself "
             "listed in this transfer's Penanggungjawab Pick may edit "
             "Penanggungjawab Pack here.",
    )

    def _compute_can_edit_pack_responsible_ids(self):
        current_user = self.env.user
        for picking in self:
            picking.can_edit_pack_responsible_ids = current_user in picking.pick_responsible_ids

    @api.onchange(
        "pick_responsible_ids",
        "pack_responsible_ids",
        "do_responsible_ids",
    )
    def _onchange_responsible_ids(self):
        for wizard in self:
            missing_do = (
                wizard.pick_responsible_ids
                - wizard.do_responsible_ids
            )

            if missing_do:
                wizard.do_responsible_ids = (
                    wizard.do_responsible_ids | missing_do
                )

    def attach_pickings(self):
        self.ensure_one()

        pickings = self.env['stock.picking'].browse(
            self.env.context.get('active_ids')
        )

        if self.mode == 'new':
            company = pickings.company_id

            if len(company) > 1:
                raise UserError(
                    _("The selected pickings should belong to an unique company.")
                )

            batch = self.env['stock.picking.batch'].create({
                'user_id': self.user_id.id,
                'company_id': company.id,
                'picking_type_id': pickings[0].picking_type_id.id,
                'description': self.description,
            })
        else:
            batch = self.batch_id

        # Pick responsible is also Loader responsible.
        missing_do = (
            self.pick_responsible_ids
            - self.do_responsible_ids
        )

        do_responsible_ids = (
            self.do_responsible_ids
            | missing_do
        )

        # All responsible users.
        responsible_users = (
            self.pick_responsible_ids
            | self.pack_responsible_ids
            | do_responsible_ids
        )

        pickings.with_context(
            tijari_responsible_sync=True
        ).write({
            'batch_id': batch.id,
            'pick_responsible_ids': [
                (6, 0, self.pick_responsible_ids.ids)
            ],
            'pack_responsible_ids': [
                (6, 0, self.pack_responsible_ids.ids)
            ],
            'do_responsible_ids': [
                (6, 0, self.do_responsible_ids.ids)
            ],
        })

        # you have to set some pickings to batch before confirm it.
        if self.mode == 'new' and not self.is_create_draft:
            batch.action_confirm()

        return {
            'name': _('Batch Transfer'),
            'view_mode': 'form',
            'res_model': 'stock.picking.batch',
            'type': 'ir.actions.act_window',
            'res_id': batch.id,
        }
