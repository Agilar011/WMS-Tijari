from odoo import models, fields, api
import requests
import qrcode
import io
import base64
from PIL import Image
from odoo.http import request
from odoo import http
import secrets
import os


class DigitalSignature(models.Model):
    _name = 'digital.signature'

    name = fields.Char(string="Sign Code", index=True, copy=False)
    document_name = fields.Char(string="Document Name", index=True, required=True)
    document_number = fields.Char(string="Document Number", index=True, required=True)
    document_model = fields.Char(string="Document Model", index=True, required=True)
    document_id = fields.Char(string="Document ID", index=True, required=True)
    date = fields.Date(string="Date", index=True, required=True)
    user_name = fields.Char(string="Signature Name", index=True, required=True)
    user_ident_number = fields.Char(string="Signature Identify Number", index=True, required=True)
    user_position = fields.Char(string="Signature Position", index=True, required=True)
    url = fields.Char(string="QR URL", copy=False)
    qr = fields.Binary(string="QR", copy=False)

    #Field pendukung untuk DMS
    # file_id = fields.Many2one('dms.file', string='File')

    @api.model
    def create(self, vals):
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "start")
        vals['name'] = secrets.token_hex(15)
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "generate hex done")
        result = super(DigitalSignature, self).create(vals)
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "create orig done")
        logo = Image.open(os.path.abspath(os.path.join(os.path.dirname(__file__), '../static/description/logo-company.png')))
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "load logo done")
        basewidth = 200
        wpercent = (basewidth/float(logo.size[0]))
        hsize = int((float(logo.size[1])*float(wpercent)))
        #ANTIALIAS
        #Image.Resampling.LANCZOS
        logo = logo.resize((basewidth, hsize), Image.ANTIALIAS)
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "logo resize done")
        QRcode = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
        base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        text = """{base_url}/digital_signature?signcode={signcode}""".format(base_url=base_url, signcode=result.name)
        result.url = text
        QRcode.add_data(text)
        QRcode.make()
        img = QRcode.make_image(fill_color="Navy", back_color="white").convert('RGB')
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "make qr done")
        img_bytes = io.BytesIO()
        pos = ((img.size[0] - logo.size[0]) // 2, (img.size[1] - logo.size[1]) // 2)
        img.paste(logo, pos)
        img.save(img_bytes,format='PNG')
        ## open('/opt/solu/logs/qr.log', 'a+').write('\n' + "make qr done")
        result.qr = base64.b64encode(img_bytes.getvalue())
        img_not_bytes = base64.b64encode(img_bytes.getvalue()).decode("ascii")
        return result
