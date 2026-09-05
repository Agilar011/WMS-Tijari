from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

class WMSStockPackageLevel(models.Model):
    _inherit = 'stock.package_level'
    _description = 'WMSStockPackageLevel'

    status = fields.Selection([
        ('finished', 'Finished'),
        ('unfinished', 'Unfinished'),
    ], string='Status', default='unfinished')

    package_cat = fields.Selection([
            ('box', 'Box'),
            ('palet', 'Palet'),
        ], string='Package Category', related='package_id.package_cat')

    def action_mark_finished(self):
        self.write({'status': 'finished'})
        return True

    def action_mark_unfinished(self):
        self.write({'status': 'unfinished'})
        return True

    def action_show_package_details(self):
        self.ensure_one()
        view = self.env.ref('stock.package_level_form_edit_view')

        return {
            'name': _('Package Content'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'stock.package_level',
            'views': [(False, 'form')],
            'target': 'new',
            'res_id': self.id,
        }
    