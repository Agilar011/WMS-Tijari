from odoo import api, fields, models
from odoo.exceptions import UserError

class StockLocationAcumatica(models.Model):
    _name = 'stock.location.acumatica'
    _description = 'Location mapping untuk grouping location dari Acumatica ke location di Odoo (untuk kebutuhan import data dari Acumatica). stock.location.acumatica -> stock.location'

    name = fields.Char(string='Location Name (Acumatica)', required=True)
    code = fields.Char(string='Location Code (Acumatica)', required=True)
    building = fields.Char(string='Building ID (Acumatica)')
    odoo_location_id = fields.Many2one('stock.location', string='Location Grouping')
    odoo_building_id = fields.Many2one('stock.warehouse', string='Building Grouping')
    active = fields.Boolean(string='Aktif', default=True)
    is_active = fields.Boolean(string='Is Active')

    @api.onchange('odoo_location_id')
    def _onchange_odoo_location_id(self):        
        if self.odoo_location_id:
            warehouse_id = self.env['stock.warehouse'].search([('lot_stock_id', '=', self.odoo_location_id.location_id.id), ('code', '=', self.building)], limit=1)
            if warehouse_id:
                if warehouse_id != self.env.user.warehouse_id and warehouse_id not in self.env.user.warehouse_ids:
                    # Jika warehouse hasil pencarian tidak termasuk dalam warehouse yang diizinkan untuk user, maka tidak diset
                    self.odoo_location_id = False
                    return {
                        'warning': {
                            'title': 'Access Warning',
                            'message': 'Anda Tidak memiliki akses ke warehouse ini.'
                        }
                    }

                else:
                    self.odoo_building_id = warehouse_id
            else:
                self.odoo_building_id = False
