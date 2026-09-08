# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from odoo import fields, models


class Company(models.Model):
    _inherit = 'res.company'

    ps_brand = fields.Serialized()
    menus_preset = fields.Many2many('ir.ui.menu', domain=[('parent_id', '=', False)])

    logo_lui = fields.Binary(attachment=False)
    logo_dui = fields.Binary(attachment=False)
    bg_lui = fields.Binary(attachment=False)
    bg_dui = fields.Binary(attachment=False)

    def get_menus_preset(self):
        return [o['id'] for o in self.menus_preset.read(['id'])]
