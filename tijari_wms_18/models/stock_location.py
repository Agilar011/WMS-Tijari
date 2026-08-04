from odoo import api, fields, models
from odoo.exceptions import ValidationError

class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.depends('name', 'complete_name')
    @api.depends_context('show_location_short_name')
    def _compute_display_name(self):
        if not self.env.context.get('show_location_short_name'):
            return super()._compute_display_name()

        for location in self:
            location.display_name = location.warehouse_id.code + '/' + location.name

    @api.model
    @api.readonly
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        if not self.env.context.get('show_location_short_name'):
            return super().name_search(name=name, args=args, operator=operator, limit=limit)

        return super(StockLocation, self.with_context(show_location_short_name=False)).name_search(
            name=name,
            args=args,
            operator=operator,
            limit=limit,
        )


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
    is_error = fields.Boolean(string='Is Error')
    error_message = fields.Char(string='Error Message', readonly=True)

    loginext_branch = fields.Char(string='Branch Name (Loginext)', required=True)
    loginext_state = fields.Many2one('loginext.master.state', string='State Name (loginext)')

    @api.onchange('odoo_location_id')
    def _onchange_odoo_location_id(self):
        if self.is_error:
            raise ValidationError('Lokasi ini memiliki error, silakan perbaiki terlebih dahulu sebelum mengubah grouping.')
        if self.odoo_location_id:
            warehouse_id = self.env['stock.warehouse'].search([('code', '=', self.building)], limit=1)
            if warehouse_id:
                if warehouse_id != self.env.user.warehouse_id and warehouse_id not in self.env.user.warehouse_ids:
                    # Jika warehouse hasil pencarian tidak termasuk dalam warehouse yang diizinkan untuk user, maka tidak diset
                    raise ValidationError(f'Lokasi ini berada di building {self.building} yang tidak termasuk dalam warehouse yang diizinkan untuk user. Warehouse yang diizinkan: {", ".join(self.env.user.warehouse_ids.mapped("name"))}')
                else:
                    self.odoo_building_id = warehouse_id
            else:
                raise ValidationError(f'Lokasi ini berada di building {self.building} yang tidak ditemukan di Odoo. Pastikan building sudah terdaftar di Odoo sebelum mengatur grouping.')
