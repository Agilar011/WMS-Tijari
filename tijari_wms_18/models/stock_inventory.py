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

    def action_send_approval_request_email(self):
        self.ensure_one()
        if self.state != 'wait_approval':
            raise UserError(_('Email permintaan approval hanya bisa dikirim saat status Waiting for Approval.'))

        approver = self.current_approver_id
        if not approver or not approver.partner_id.email:
            raise UserError(_('Approver saat ini belum memiliki alamat email.'))

        template = self.env.ref(
            'tijari_wms_18.email_template_stock_inventory_approval_request',
            raise_if_not_found=False,
        )
        if not template:
            raise UserError(_('Template email permintaan approval tidak ditemukan.'))

        try:
            from ..controllers.controllers import generate_stok_opname_pdf
            pdf_content = generate_stok_opname_pdf(self)
        except Exception as error:
            raise UserError(_('Dokumen cetak tidak berhasil dibuat: %s') % error) from error

        attachment = self.env['ir.attachment'].sudo().create({
            'name': '%s_stok_opname.pdf' % (self.name or 'inventory'),
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'name': _('Permintaan Approval Inventory Adjustment'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': self._name,
                'default_res_ids': [self.id],
                'default_use_template': True,
                'default_template_id': template.id,
                'default_composition_mode': 'comment',
                'default_attachment_ids': [(6, 0, [attachment.id])],
                'force_email': True,
                'tijari_inventory_approval_email': True,
            },
        }

class StockScrap(models.Model):
    _inherit = "stock.scrap"
    
    note = fields.Text(string="Notes For Official Report")

    def action_print_stok_scrab(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/stok_scrab?id=' + str(self.id)
        action['target'] = 'new'
        return action
