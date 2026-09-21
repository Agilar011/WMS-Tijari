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
    handheld_location_code = fields.Char(
        string='Kode Lokasi Handheld',
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
    putaway_status = fields.Selection(
        related='move_line_id.putaway_status',
        readonly=True,
    )
    picking_state = fields.Selection(
        related='move_line_id.picking_id.state',
        readonly=True,
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

    def _prepare_move_line_values(self):
        self.ensure_one()
        move_line = self._existing_move_line()
        if self.location_putaway_id and move_line:
            move_line._check_putaway_location_mapping(self.location_putaway_id)
        values = {
            'confirmation_quantity': self.confirmation_quantity,
        }
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
