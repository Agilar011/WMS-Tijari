import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaWebhookLog(models.Model):
    _name = 'acumatica.webhook.log'
    _description = 'Acumatica Webhook Log'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Name', compute='_compute_name')
    webhook_type = fields.Selection([
        ('master', 'Master'),
        ('transaction', 'Transaksi'),
    ], string='Type', required=True, readonly=True)
    webhook_name = fields.Char(string='Nama Webhook', required=True, readonly=True, index=True)
    company_id_text = fields.Char(string='Company ID', readonly=True)
    acumatica_event_id = fields.Char(string='Acumatica Event ID', readonly=True)
    acumatica_timestamp = fields.Char(string='Acumatica Timestamp', readonly=True)
    payload = fields.Text(string='Payload', required=True, readonly=True)

    state = fields.Selection([
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True, index=True)
    created_count = fields.Integer(string='Created', readonly=True)
    updated_count = fields.Integer(string='Updated', readonly=True)
    imported_count = fields.Integer(string='Imported', readonly=True)
    error_count = fields.Integer(string='Errors', readonly=True)
    line_count = fields.Integer(string='Lines', readonly=True)
    result_message = fields.Text(string='Result Message', readonly=True)
    processed_date = fields.Datetime(string='Processed Date', readonly=True)

    def _compute_name(self):
        for rec in self:
            rec.name = '%s - %s - %s' % (
                dict(self._fields['webhook_type'].selection).get(rec.webhook_type, rec.webhook_type or '-'),
                rec.webhook_name or '-',
                rec.create_date or fields.Datetime.now(),
            )

    @staticmethod
    def _loads_payload(payload_text):
        try:
            return json.loads(payload_text or '{}')
        except json.JSONDecodeError as exc:
            raise UserError(_('Payload JSON tidak valid: %s') % exc)

    @staticmethod
    def _processing_payload(payload):
        return payload

    def action_process_to_staging(self):
        for rec in self:
            payload = rec._loads_payload(rec.payload)
            processing_payload = rec._processing_payload(payload)
            try:
                if rec.webhook_type == 'master':
                    from ..controllers.master_webhook import AcumaticaMasterWebhookController
                    controller = AcumaticaMasterWebhookController()
                    controller.env = self.env
                    result = controller._process_master_payload(rec.webhook_name, processing_payload)
                elif rec.webhook_type == 'transaction':
                    from ..controllers.transaction_webhook import AcumaticaTransactionWebhookController
                    controller = AcumaticaTransactionWebhookController()
                    controller.env = self.env
                    result = controller._process_transaction_payload(rec.webhook_name, processing_payload)
                else:
                    raise UserError(_('Webhook type tidak valid: %s') % rec.webhook_type)

                rec.write({
                    'state': 'processed' if not result.get('errors') else 'error',
                    'created_count': result.get('created', 0),
                    'updated_count': result.get('updated', 0),
                    'imported_count': result.get('imported', 0),
                    'error_count': result.get('errors', 0),
                    'line_count': result.get('product_lines') or result.get('component_lines') or len(result.get('line_ids', [])),
                    'result_message': json.dumps(result, indent=2, default=str),
                    'processed_date': fields.Datetime.now(),
                })
            except Exception as exc:
                _logger.exception('Error processing Acumatica webhook log %s', rec.id)
                rec.write({
                    'state': 'error',
                    'error_count': rec.error_count + 1,
                    'result_message': str(exc),
                    'processed_date': fields.Datetime.now(),
                })
                raise

        return True
