from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PutawayMoveLineWizard(models.TransientModel):
    _name = 'putaway.move.line.wizard'
    _description = 'Putaway Move Line'

    move_line_id = fields.Many2one(
        'stock.move.line',
        string='Move Line',
        required=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        related='move_line_id.product_id',
        readonly=True,
    )
    picking_type_name = fields.Char(
        related='move_line_id.picking_type_name',
        readonly=True,
    )
    adt_dest_location_id = fields.Many2one(
        'stock.location',
        related='move_line_id.adt_dest_location_id',
        readonly=True,
    )
    location_putaway_id = fields.Many2one(
        'stock.location',
        string='Putaway Location',
        domain="[('id', 'child_of', adt_dest_location_id)]",
    )
    confirmation_location_code = fields.Char(
        string='Scan Location',
        readonly=True,
    )
    confirmation_lot_code = fields.Char(
        string='Confirmation Lot',
        readonly=True,
    )
    handheld_scan_code = fields.Char(
        string='Scan Handheld',
        help='Scan kode lot atau lokasi untuk Storage.',
    )
    matching_lot_id = fields.Many2one(
        'stock.lot',
        string='Confirmation Lot',
        domain="[('id', 'in', allowed_matching_lot_ids)]",
    )
    allowed_matching_lot_ids = fields.Many2many(
        'stock.lot',
        related='move_line_id.allowed_matching_lot_ids',
        readonly=True,
    )
    matching = fields.Selection(
        [('match', 'Match'), ('not_match', 'Not Match')],
        readonly=True,
    )
    second_matching = fields.Char(readonly=True)
    handheld_location_code = fields.Char(
        string='Scan Handheld',
        help='Masukkan kode lokasi dari scanner handheld atau ketik manual.',
    )
    original_location_putaway_id = fields.Many2one(
        'stock.location',
        readonly=True,
    )
    original_confirmation_location_code = fields.Char(
        readonly=True,
    )
    quantity = fields.Float(
        string='Quantity',
        readonly=True,
    )
    confirmation_quantity = fields.Float(
        string='Confirmation Quantity',
    )
    remaining_putaway_quantity = fields.Float(
        string='Sisa Qty Putaway',
        compute='_compute_remaining_putaway_quantity',
    )
    putaway_status = fields.Selection(
        related='move_line_id.putaway_status',
        readonly=True,
    )
    picking_state = fields.Selection(
        related='move_line_id.picking_id.state',
        readonly=True,
    )

    @api.depends('quantity', 'confirmation_quantity')
    def _compute_remaining_putaway_quantity(self):
        for wizard in self:
            wizard.remaining_putaway_quantity = (
                wizard.quantity - wizard.confirmation_quantity
            )

    @staticmethod
    def _reload_action():
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _existing_move_line(self):
        self.ensure_one()
        move_line = self.move_line_id.exists()
        return move_line[:1] if move_line else False

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        move_line = self.env['stock.move.line'].browse(
            self.env.context.get('default_move_id')
            or self.env.context.get('active_id')
        )
        if move_line.exists():
            values.update({
                'move_line_id': move_line.id,
                'location_putaway_id': move_line.location_putaway_id.id,
                'original_location_putaway_id': move_line.location_putaway_id.id,
                'confirmation_location_code': move_line.confirmation_location_code,
                'confirmation_lot_code': move_line.confirmation_lot_code,
                'matching_lot_id': move_line.matching_lot_id.id,
                'matching': move_line.matching,
                'second_matching': move_line.second_matching,
                'original_confirmation_location_code': move_line.confirmation_location_code,
                'quantity': move_line.quantity,
                'confirmation_quantity': move_line.confirmation_quantity,
            })
        return values

    @api.onchange('location_putaway_id')
    def _onchange_location_putaway_id(self):
        for wizard in self:
            if wizard.location_putaway_id:
                wizard.confirmation_location_code = (
                    wizard.location_putaway_id.barcode
                    or wizard.location_putaway_id.name
                )

    @api.onchange('handheld_location_code')
    def _onchange_handheld_location_code(self):
        for wizard in self:
            code = (wizard.handheld_location_code or '').strip()
            if not code:
                continue

            location = wizard.move_line_id._find_loc_by_scan_code(code)
            if not location:
                raise ValidationError(_('Kode lokasi tidak terdaftar.'))
            wizard.move_line_id._check_putaway_location_mapping(location)

            wizard.update({
                'confirmation_location_code': code,
                'location_putaway_id': location.id,
                'handheld_location_code': False,
            })

    @api.onchange('handheld_scan_code')
    def _onchange_handheld_scan_code(self):
        for wizard in self:
            code = (wizard.handheld_scan_code or '').strip()
            if not code or wizard.picking_type_name not in (
                'Storage', 'Store Finished Product'
            ):
                continue
            values = wizard.move_line_id._get_handheld_scan_values(code)
            wizard.update({
                key: value
                for key, value in values.items()
                if key in (
                    'confirmation_lot_code',
                    'matching_lot_id',
                    'matching',
                    'second_matching',
                    'confirmation_location_code',
                    'location_putaway_id',
                )
            })
            wizard.handheld_scan_code = False

    @api.onchange('matching_lot_id')
    def _onchange_matching_lot_id(self):
        for wizard in self:
            lot = wizard.matching_lot_id
            wizard.confirmation_lot_code = lot.name if lot else False
            is_match = bool(
                lot
                and wizard.move_line_id._is_storage_lot_match(lot)
            )
            wizard.matching = 'match' if is_match else 'not_match'
            wizard.second_matching = 'Match' if is_match else 'Not Match'

    def _prepare_move_line_values(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if self.location_putaway_id and move_line:
            move_line._check_putaway_location_mapping(self.location_putaway_id)
        values = {
            'confirmation_quantity': self.confirmation_quantity,
        }
        if self.picking_type_name in ('Storage', 'Store Finished Product'):
            values.update({
                'confirmation_lot_code': self.confirmation_lot_code,
                'matching_lot_id': self.matching_lot_id.id,
                'matching': self.matching,
                'second_matching': self.second_matching,
            })
        location_changed = (
            self.location_putaway_id != self.original_location_putaway_id
            or self.confirmation_location_code != self.original_confirmation_location_code
        )
        if location_changed:
            values.update({
                'location_putaway_id': self.location_putaway_id.id,
                'location_dest_id': self.location_putaway_id.id,
                'confirmation_location_code': self.confirmation_location_code,
            })
        return values

    def action_prepare_scan_location(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if not move_line:
            return self._reload_action()
        if not self.move_line_id:
            raise ValidationError(_('Move line tidak ditemukan.'))
        return move_line.action_prepare_scan_location()

    def action_apply_scanned_field(self, field_name, scanned_code):
        self.ensure_one()
        if field_name != 'confirmation_location_code':
            raise ValidationError(_('Field scan tidak valid.'))

        move_line = self._existing_move_line()
        if not move_line:
            return self._reload_action()

        location = move_line._find_loc_by_scan_code(scanned_code)
        if not location:
            raise ValidationError(_('Barcode tidak terdaftar.'))
        move_line._check_putaway_location_mapping(location)

        self.write({
            'confirmation_location_code': scanned_code,
            'location_putaway_id': location.id,
        })
        return {
            'id': self.id,
            'confirmation_location_code': scanned_code,
            'location_putaway_id': [
                location.id,
                location.name,
            ],
        }

    def action_save(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if not move_line:
            return self._reload_action()
        move_line.write(self._prepare_move_line_values())
        return {'type': 'ir.actions.act_window_close'}

    def action_save_and_finish(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if not move_line:
            return self._reload_action()
        move_line.write(self._prepare_move_line_values())
        move_line.action_mark_putaway_finished()
        return move_line.move_id.action_open_move_putaway()

    def action_rollback(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if not move_line:
            return self._reload_action()
        move_line.action_mark_putaway_unfinished()
        return move_line.action_open_putaway_move_line_wizard()

    def action_cancel(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if not move_line:
            return self._reload_action()
        return move_line.move_id.action_open_move_putaway()
