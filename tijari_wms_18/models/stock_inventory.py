from odoo.tools.float_utils import float_compare, float_round
from odoo import _, api, models, fields
import base64
import os
from PIL import Image
import qrcode
import io
from odoo.exceptions import AccessError, UserError, ValidationError
from lxml import etree
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

    def _is_operator_only(self):
        if not self.env.user.has_group('tijari_wms_18.group_operator'):
            return False
        elevated = (
            'tijari_wms_18.group_it_staff',
            'stock.group_stock_manager',
            'base.group_system',
        )
        return not any(self.env.user.has_group(group) for group in elevated)

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if self._is_operator_only() and view_type in ('form', 'list'):
            arch = etree.fromstring(result['arch'].encode())
            root_tag = 'form' if view_type == 'form' else 'list'
            root = arch if arch.tag == root_tag else arch.find('.//' + root_tag)
            if root is not None:
                root.set('create', 'false')
                root.set('delete', 'false')
                if view_type == 'list':
                    root.set('edit', 'false')
                else:
                    for field_node in arch.xpath('.//field'):
                        if field_node.get('name') != 'notes':
                            field_node.set('readonly', '1')
                    for button in arch.xpath('.//header//button'):
                        if button.get('name') != 'action_view_inventory_adjustment':
                            button.set('invisible', '1')
            result['arch'] = etree.tostring(arch, encoding='unicode')
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and self._is_operator_only():
            raise AccessError(_('Warehouse Operator hanya memiliki akses baca pada Adjustment Document.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and self._is_operator_only() and set(vals) - {'notes'}:
            raise AccessError(_('Warehouse Operator hanya dapat mengubah Notes pada Adjustment Document.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self._is_operator_only():
            raise AccessError(_('Warehouse Operator tidak memiliki akses untuk menghapus Adjustment Document.'))
        return super().unlink()
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
