from odoo import _, fields, models
from odoo.exceptions import ValidationError, UserError

from odoo.tools.float_utils import float_compare


class MoveUnpackItemWizard(models.TransientModel):
    _name = "move.unpack.wizard"
    _description = "Unpacked Item Details"
 
    move_id = fields.Many2one('stock.move', string='Stock Move')
    state = fields.Selection(related='move_id.state')
    product_id = fields.Many2one('product.product', string='Product', related='move_id.product_id')

    status_check = fields.Selection([
            ('finished', 'Finished'),
            ('unfinished', 'Unfinished'),
        ], string='Status', default='unfinished', related='move_id.status_check')

    product_uom_qty = fields.Float('Total Qty', related='move_id.product_uom_qty')
    remaining_package_qty = fields.Float('Qty Unpack', related='move_id.remaining_package_qty')
    so_confirmation_quantity = fields.Float('Qty Dikirim')

    product_uom = fields.Many2one('uom.uom', string='Uom', related='move_id.product_uom')

    def action_mark_check_finished(self):
        move_id = self.move_id
        move_id.so_confirmation_quantity = self.so_confirmation_quantity
        move_id.action_mark_check_finished()
    
    def action_mark_check_unfinished(self):
        move_id = self.move_id
        move_id.action_mark_check_unfinished()
