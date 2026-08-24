# -*- coding: utf-8 -*-
from odoo import fields, models
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

    # def action_print_packing_list(self):
    #     action = {}
    #     action['type'] = 'ir.actions.act_url'
    #     action['url'] = '/print/packing_list?id=' + str(self.id)
    #     action['target'] = 'new'
    #     return action

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