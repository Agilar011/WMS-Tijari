# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
import base64
import os
from PIL import Image
import qrcode
import io

class StockQuantPackage(models.Model):
    _inherit = "stock.quant.package"

    note = fields.Html(string="Notes")
    warehouse_note = fields.Text(string="Warehouse Note")
    origin = fields.Char(string="Source Document")
    scheduled_date = fields.Date(string='scheduled_date')
    picking_id = fields.Many2one("stock.picking", string="Picking", index=True, store=True, copy=False)
    qr_code_image = fields.Binary(string='Sign')
    package_cat = fields.Selection([
        ('box', 'Box'),
        ('palet', 'Palet'),
    ], string='Package Category', default="box", required=True)
    is_empty = fields.Boolean('is_empty', compute="compute_is_empty", store=True)

    @api.depends('quant_ids')
    def compute_is_empty(self):
        for line in self:
            line.is_empty = False if line.quant_ids else True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            package_cat = vals.get('package_cat')

            if package_cat and not vals.get('name'):
                sequence_code = {
                    'box': 'stock.quant.package.box',
                    'palet': 'stock.quant.package.palet',
                }

                vals['name'] = self.env[
                    'ir.sequence'
                ].next_by_code(sequence_code[package_cat])

        return super().create(vals_list)

    def action_open_generate_package_wizard(self):
        return {
            'name': 'Generate Package',
            'type': 'ir.actions.act_window',
            'res_model': 'generate.package.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
    
    # def action_print_packing_list(self):
    #     action = {}
    #     action['type'] = 'ir.actions.act_url'
    #     action['url'] = '/print/packing_list?id=' + str(self.id)
    #     action['target'] = 'new'
    #     return action

    def action_print_packing_package(self):
        self.ensure_one()

        if not self.name:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Package Name belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        self.create_qrcode_name()

        return {
            'type': 'ir.actions.act_url',
            'url': '/print/packing_package?id=%s' % self.id,
            'target': 'new',
        }
        
    def action_print_packing_list(self):
        self.ensure_one()

        if not self.name:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Package Name belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        self.create_qrcode_name()

        return {
            'type': 'ir.actions.act_url',
            'url': '/print/packing_list?id=%s' % self.id,
            'target': 'new',
        }

    def create_qrcode_name(self):
        for rec in self:
            if rec.name:
                rec.qr_code_image = rec.create_qrcode(rec.name)

    def create_qrcode(self, text):
        logo_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                '../static/src/img/logo-company.png'
            )
        )
        logo = Image.open(logo_path)
        basewidth = 80
        wpercent = basewidth / float(logo.size[0])
        hsize = int(float(logo.size[1]) * wpercent)
        logo = logo.resize((basewidth, hsize))
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(
            fill_color="black",
            back_color="white"
        ).convert('RGB')
        img = img.resize((300, 300))
        pos = ((img.size[0] - logo.size[0]) // 2,(img.size[1] - logo.size[1]) // 2)
        img.paste(logo, pos)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()