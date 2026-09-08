# -*- coding: utf-8 -*-
from odoo import fields, http, SUPERUSER_ID, tools, _, api
from odoo.http import request, route
from odoo.exceptions import UserError
from odoo.addons.auth_signup.models.res_users import SignupError
import random
import string
import werkzeug
import logging


class TijariDigitalSign(http.Controller):

    @http.route(['/digital_signature'], type='http', auth='public', website=True)
    def digitalsignature(self, *args, **post):
        if not post.get("signcode"):
            return request.render("http_routing.404")
        signcode = post.get("signcode", "0")
        digitalsign = request.env['digital.signature'].sudo().search([('name', '=', signcode)], limit=1)
        if not digitalsign:
            return request.render("http_routing.404")

        values = {}
        values['date'] = digitalsign.date
        values['document_name'] = digitalsign.document_name
        values['document_number'] = digitalsign.document_number
        values['user_ident_number'] = digitalsign.user_ident_number
        values['user_name'] = digitalsign.user_name
        values['user_position'] = digitalsign.user_position

        return request.render("tijari_digital_sign.digital_signature", values)
