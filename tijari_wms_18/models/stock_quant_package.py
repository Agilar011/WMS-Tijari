# -*- coding: utf-8 -*-
from odoo import fields, models


class StockQuantPackage(models.Model):
    _inherit = "stock.quant.package"

    note = fields.Html(string="Notes")
    warehouse_note = fields.Text(string="Warehouse Note")
    origin = fields.Char(string="Source Document")
    scheduled_date = fields.Date(string='scheduled_date')
    picking_id = fields.Many2one("stock.picking", string="Picking", index=True, store=True, copy=False)

    def action_print_packing_list(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/packing_list?id=' + str(self.id)
        action['target'] = 'new'
        return action
