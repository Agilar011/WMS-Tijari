import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)


class AcumaticaWebhookErrorService(models.AbstractModel):
    _name = "acumatica.webhook.error.service"
    _description = "Acumatica Webhook Error Service"

    def _get_chat_webhook_url(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "acumatica_all_import.chat_webhook_url"
        )

    def send_error(
        self,
        webhook_type,
        webhook_name,
        error,
        error_type=None,
    ):
        webhook_url = self._get_chat_webhook_url()

        if not webhook_url:
            _logger.warning(
                "Google Chat webhook URL is not configured."
            )
            return False

        message = (
            "🚨 *Acumatica Error*\n\n"
            f"*Type:* {webhook_type}\n"
            f"*Webhook:* {webhook_name}\n"
            f"*Error Type:* {error_type or '-'}\n"
            f"*Error:*\n{error}"
        )

        try:
            response = requests.post(
                webhook_url,
                json={"text": message},
                headers={
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            response.raise_for_status()

            _logger.info(
                "Google Chat notification sent: %s",
                webhook_name,
            )

            return True

        except requests.RequestException:
            _logger.exception(
                "Failed to send Google Chat notification: %s",
                webhook_name,
            )
            return False