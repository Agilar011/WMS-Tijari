from collections import defaultdict

from markupsafe import Markup, escape

from odoo import api, models, _


class WMSAssignmentNotification(models.AbstractModel):
    _name = 'wms.assignment.notification.mixin'
    _description = 'WMS Assignment Chat Notifications'

    @api.model
    def _send_assignment_chat_notifications(self, documents_by_user):
        """Send one private Discuss message per newly assigned internal user."""
        if self.env.context.get('skip_assignment_chat_notification'):
            return

        current_partner = self.env.user.partner_id
        users = self.env['res.users'].browse(list(documents_by_user)).exists()
        for user in users.filtered(lambda assigned_user: (
            assigned_user.active
            and not assigned_user.share
            and assigned_user.id != self.env.uid
            and assigned_user.partner_id
        )):
            documents = documents_by_user[user.id]
            document_specs = {}
            for document in documents:
                for spec in self._get_assignment_document_specs(document):
                    document_specs[(spec['model'], spec['id'])] = spec

            if not document_specs:
                continue

            body = Markup('').join(
                Markup(
                    '<p>Dokumen WMS <a href="{}">{}</a> untuk operasi {} '
                    'siap diproses. Silakan periksa detail dokumen sebelum pelaksanaan.</p>'
                ).format(
                    escape(spec['url']),
                    escape(spec['number']),
                    escape(spec['operation']),
                )
                for spec in document_specs.values()
            )
            push_target = self._get_assignment_push_target(documents)

            try:
                with self.env.cr.savepoint():
                    channel = self.env['discuss.channel'].channel_get(
                        (current_partner | user.partner_id).ids
                    )
                    channel.with_context(
                        wms_assignment_push_target=push_target,
                    ).message_post(
                        body=body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
            except Exception:
                # A notification failure must not roll back the assignment.
                import logging
                logging.getLogger(__name__).exception(
                    'Unable to send WMS assignment chat notification to user %s',
                    user.id,
                )

    @api.model
    def _get_assignment_push_target(self, documents):
        """Choose the record opened when the recipient clicks the push alert."""
        batch_ids = [
            document.id for document in documents
            if document._name == 'stock.picking.batch'
        ]
        if batch_ids:
            target = self.env['stock.picking.batch'].browse(batch_ids[:1])
        else:
            picking_ids = [
                document.id for document in documents
                if document._name == 'stock.picking'
            ]
            pickings = self.env['stock.picking'].browse(picking_ids)
            batches = pickings.mapped('batch_id')
            if len(pickings) > 1 and len(batches) == 1 and batches:
                target = batches
            elif pickings:
                target = pickings[:1]
            else:
                target = documents[0] if documents else False

        if not target:
            return {}
        return {'model': target._name, 'res_id': target.id}

    @api.model
    def _get_assignment_document_specs(self, document):
        if document._name == 'stock.picking.batch' and document.picking_ids:
            specs = []
            for picking in document.picking_ids:
                specs.extend(self._get_assignment_document_specs(picking))
            return specs

        if document._name == 'stock.picking':
            number = document.origin or document.name
            operation = document.picking_type_id.name or _('Stock Transfer')
        elif document._name == 'stock.picking.batch':
            number = document.name
            operation = (
                document.picking_type_id.name
                or (_('Wave') if document.is_wave else _('Batch Transfer'))
            )
        elif document._name == 'stock.inventory':
            number = document.name or document.display_name
            operation = _('Stock Opname')
        else:
            number = document.display_name
            operation = document._description or document._name

        return [{
            'model': document._name,
            'id': document.id,
            'number': number,
            'operation': operation,
            'url': '/web#id=%s&model=%s&view_type=form' % (
                document.id,
                document._name,
            ),
        }]

    @api.model
    def _group_new_responsible_users(self, records, field_names, old_user_ids_by_record):
        """Return newly added users mapped to records that contain the assignment."""
        documents_by_user = defaultdict(list)
        for record in records:
            previous_user_ids = set()
            current_user_ids = set()
            for field_name in field_names:
                previous_user_ids |= old_user_ids_by_record.get(
                    record.id, {}
                ).get(field_name, set())
                current_user_ids |= set(record[field_name].ids)
            for user_id in current_user_ids - previous_user_ids:
                documents_by_user[user_id].append(record)
        return documents_by_user


class DiscussChannelWMSPushTarget(models.Model):
    _inherit = 'discuss.channel'

    def _notify_by_web_push_prepare_payload(self, message, msg_vals=False):
        payload = super()._notify_by_web_push_prepare_payload(
            message, msg_vals=msg_vals,
        )
        target = self.env.context.get('wms_assignment_push_target')
        if target and self.channel_type == 'chat':
            payload['options']['data'].update({
                'model': target['model'],
                'res_id': target['res_id'],
            })
            payload['options'].update({
                'requireInteraction': True,
                'vibrate': [200, 100, 200],
            })
        return payload

