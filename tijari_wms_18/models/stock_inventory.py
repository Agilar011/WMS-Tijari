from odoo.tools.float_utils import float_compare, float_round
from odoo import _, api, models, fields
import base64
import os
from PIL import Image
import qrcode
import io
from odoo.exceptions import AccessError, UserError, ValidationError
from lxml import etree
from markupsafe import Markup
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
            result['arch'] = etree.tostring(arch, encoding='unicode')
        return result

    def unlink(self):
        if not self.env.su and self._is_operator_only():
            raise AccessError(_('Warehouse Operator tidak memiliki akses untuk menghapus Adjustment Document.'))
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        # Users who are Operators but also hold another group with create
        # rights (e.g. Warehouse Head) keep their ACL access; the guard only
        # replaces the generic ACL error for Operators without that right.
        if (
            not self.env.su
            and self._is_operator_only()
            and not self.env['ir.model.access'].check(self._name, 'create', raise_exception=False)
        ):
            raise AccessError(_('Warehouse Operator tidak memiliki akses untuk membuat Adjustment Document.'))
        inventories = super().create(vals_list)
        if 'responsible_id' in self._fields:
            notifier = self.env['wms.assignment.notification.mixin']
            empty_user_ids = {
                inventory.id: {'responsible_id': set()}
                for inventory in inventories
            }
            documents_by_user = notifier._group_new_responsible_users(
                inventories, ['responsible_id'], empty_user_ids,
            )
            notifier._send_assignment_chat_notifications(documents_by_user)
        return inventories

    def write(self, vals):
        should_notify = (
            'responsible_id' in vals
            and 'responsible_id' in self._fields
            and not self.env.context.get('skip_assignment_chat_notification')
        )
        old_user_ids = {
            inventory.id: {
                'responsible_id': set(inventory.responsible_id.ids),
            }
            for inventory in self
        } if should_notify else {}

        result = super().write(vals)
        if should_notify:
            notifier = self.env['wms.assignment.notification.mixin']
            documents_by_user = notifier._group_new_responsible_users(
                self, ['responsible_id'], old_user_ids,
            )
            notifier._send_assignment_chat_notifications(documents_by_user)
        return result

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

    # ------------------------------------------------------------------
    # Approval push notifications (Discuss chat + web push)
    # ------------------------------------------------------------------
    def _get_approval_notification_link(self):
        self.ensure_one()
        return Markup('<a href="{}">{}</a>').format(
            '/web#id=%s&model=%s&view_type=form' % (self.id, self._name),
            self.name or self.display_name,
        )

    def _notify_current_approver(self):
        """Tell the approver whose turn it is that the adjustment waits for them."""
        notifier = self.env['wms.assignment.notification.mixin']
        for inventory in self.filtered(lambda rec: rec.current_approver_id):
            notifier._send_document_chat_notification(
                inventory.current_approver_id,
                inventory,
                Markup(
                    '<p>Stock Opname {} menunggu approval Anda. '
                    'Silakan periksa hasil hitung sebelum menyetujui.</p>'
                ).format(inventory._get_approval_notification_link()),
            )

    def _notify_approval_result(self, approved):
        """Tell the creator and the responsible user the final approval result."""
        notifier = self.env['wms.assignment.notification.mixin']
        for inventory in self:
            # An old request left behind by Back to Draft can still be
            # approved or rejected from the Approval menu. Only announce a
            # result when the adjustment's active request carries it.
            if approved and inventory.approval_state != 'approved':
                continue
            if not approved and inventory.approval_state not in ('rejected', 'cancelled'):
                continue
            result = _('disetujui') if approved else _('ditolak')
            next_step = (
                _('Silakan lanjutkan dengan Update Stock.')
                if approved else ''
            )
            notifier._send_document_chat_notification(
                inventory.responsible_id | inventory.create_uid,
                inventory,
                Markup('<p>Stock Opname {} telah {} oleh {}. {}</p>').format(
                    inventory._get_approval_notification_link(),
                    result,
                    self.env.user.name,
                    next_step,
                ),
            )

    def action_state_to_wait_approval(self):
        result = super().action_state_to_wait_approval()
        self._notify_current_approver()
        return result

    def _approval_approved(self):
        result = super()._approval_approved()
        self._notify_approval_result(approved=True)
        return result

    def _approval_rejected(self):
        result = super()._approval_rejected()
        self._notify_approval_result(approved=False)
        return result


class ApprovalRequestStockInventory(models.Model):
    _inherit = 'approval.request'

    def action_approve(self):
        result = super().action_approve()
        # An intermediate approval moves the request to the next approver:
        # notify them once the adjustment is waiting for approval.
        for request in self:
            if request.source_model != 'stock.inventory' or request.state != 'waiting':
                continue
            inventory = request._get_source_document()
            if (
                inventory.exists()
                and inventory.approval_request_id == request
                and inventory.state == 'wait_approval'
            ):
                inventory._notify_current_approver()
        return result


class StockScrap(models.Model):
    _inherit = "stock.scrap"
    
    note = fields.Text(string="Notes For Official Report")

    def action_print_stok_scrab(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/stok_scrab?id=' + str(self.id)
        action['target'] = 'new'
        return action
