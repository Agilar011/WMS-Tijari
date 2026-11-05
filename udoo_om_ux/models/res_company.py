# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from odoo import api, fields, models


class Company(models.Model):
    _inherit = 'res.company'

    ps_brand = fields.Serialized()
    menus_preset = fields.Many2many('ir.ui.menu', domain=[('parent_id', '=', False)])

    logo_lui = fields.Binary(attachment=False)
    logo_dui = fields.Binary(attachment=False)
    bg_lui = fields.Binary(attachment=False)
    bg_dui = fields.Binary(attachment=False)
    bg_mobile_lui = fields.Binary(attachment=False)
    bg_mobile_dui = fields.Binary(attachment=False)
    login_bg = fields.Image(attachment=False, max_width=2560, max_height=1440)
    login_bg_mobile = fields.Image(attachment=False, max_width=2560, max_height=1440)

    @api.model
    def get_home_background_field(self, company_id, color_scheme, mobile=False):
        company = self.sudo().browse(company_id).exists()
        if not company:
            return False
        is_dark = color_scheme == 'dark'
        general_field = 'bg_lui' if is_dark else 'bg_dui'
        mobile_field = 'bg_mobile_lui' if is_dark else 'bg_mobile_dui'
        if mobile and company[mobile_field]:
            return mobile_field
        return general_field if company[general_field] else False

    def get_menus_preset(self):
        return [o['id'] for o in self.menus_preset.read(['id'])]
