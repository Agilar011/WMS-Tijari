from odoo import fields, models

class StockLocationAcumatica(models.Model):
    _name = 'stock.location.acumatica'
    _description = 'Location mapping untuk grouping location dari Acumatica ke location di Odoo (untuk kebutuhan import data dari Acumatica). stock.location.acumatica -> stock.location'

    name = fields.Char(string='Nama Location (Acumatica)', required=True)
    code = fields.Char(string='Kode Location (Acumatica)', required=True)
    odoo_location_id = fields.Many2one('stock.location', string='Location di Odoo')
    active = fields.Boolean(string='Aktif', default=True)