from odoo import fields, models

class ResUsers(models.Model):
    _inherit = 'res.users'

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Default Warehouse'
    )

    warehouse_ids = fields.Many2many(
        'stock.warehouse',
        string='Allowed Warehouses'
    )

