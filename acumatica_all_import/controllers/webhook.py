# -*- coding: utf-8 -*-
import logging

from odoo import _, http
from odoo.exceptions import UserError

from .master_mapping import MasterMappingMixin
from .operation_type_mapping import OperationTypeMappingMixin
from .transaction_mapping import TransactionMappingMixin
from .transaction_processing import TransactionProcessingMixin
from .webhook_common import WebhookCommonMixin

_logger = logging.getLogger(__name__)


class AcumaticaWebhookController(
    http.Controller,
    WebhookCommonMixin,
    MasterMappingMixin,
    OperationTypeMappingMixin,
    TransactionMappingMixin,
    TransactionProcessingMixin,
):
    """Single HTTP entry point for Acumatica master and transaction webhooks."""

    def _resolve_webhook_type(self, webhook_key):
        master_key = self._normalize_master_key(webhook_key)
        if master_key in self._master_configs():
            return "master", master_key

        transaction_key = self._normalize_transaction_type(webhook_key)
        if transaction_key in self._transaction_configs():
            return "transaction", transaction_key

        raise UserError(_("Unknown webhook type: %s") % webhook_key)

    def _receive_webhook(self, webhook_key, **kwargs):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_response("error", err, http_status=401)

        try:
            webhook_type, webhook_name = self._resolve_webhook_type(webhook_key)
            payload = self._raw_payload(kwargs)
            log = self._create_webhook_log(webhook_type, webhook_name, payload)
            return self._json_response(
                "success",
                _("Webhook logged as pending. Process it from Webhook Logs."),
                log_id=log.id,
                webhook_type=webhook_type,
                webhook_name=webhook_name,
                state=log.state,
            )
        except UserError as exc:
            return self._json_response("error", str(exc), http_status=400)
        except Exception as exc:
            _logger.exception("Unexpected error in Acumatica webhook")
            return self._json_response(
                "error",
                _("Unexpected server error: %s") % str(exc),
                http_status=500,
            )

    @http.route(
        "/acumatica/webhook/<string:webhook_key>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def acumatica_webhook(self, webhook_key, **kwargs):
        return self._receive_webhook(webhook_key, **kwargs)
