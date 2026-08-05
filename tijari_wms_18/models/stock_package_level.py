from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

class WMSStockPackageLevel(models.Model):
    _inherit = 'stock.package_level'
    _description = 'WMSStockPackageLevel'

    status = fields.Selection([
        ('finished', 'Finished'),
        ('unfinished', 'Unfinished'),
    ], string='Status', default='unfinished')

    def action_mark_finished(self):
        self.write({'status': 'finished'})
        return True

    def action_mark_unfinished(self):
        self.write({'status': 'unfinished'})
        return True
    