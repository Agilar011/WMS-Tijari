from odoo.tools.float_utils import float_compare, float_round
from odoo import _, api, models, fields
import base64
import os
from PIL import Image
import qrcode
import io
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero
import logging

_logger = logging.getLogger(__name__)

class InventoryAdjustmentsGroup(models.Model):
    _inherit = "stock.inventory"
    
    notes = fields.Text(string="Notes For Official Report")
    status_ba = fields.Selection([
        ('conform', 'Confirmed'),
        ('discrepancy', 'Discrepancy'),],
    string='Status BA',

    )
    def action_print_stok_opname(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/stok_opname?id=' + str(self.id)
        action['target'] = 'new'
        return action

class StockScrap(models.Model):
    _inherit = "stock.scrap"
    
    note = fields.Text(string="Notes For Official Report")

    def action_print_stok_scrab(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/stok_scrab?id=' + str(self.id)
        action['target'] = 'new'
        return action