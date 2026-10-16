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

    def _get_chat_webhook_url_user(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "acumatica_all_import.chat_webhook_url_user"
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

    def _get_user_facing_field_changes(
        self,
        record,
        values,
        field_names=None,
        prefix=None,
    ):
        """Describe changed business fields without exposing internal IDs."""
        changes = []
        allowed_fields = set(field_names) if field_names else None

        def display_value(field, value):
            if field.type == "many2one":
                related = value
                if isinstance(value, int):
                    related = record.env[field.comodel_name].browse(value).exists()
                return related.display_name if related else "—"
            if isinstance(value, bool):
                return "Ya" if value else "Tidak"
            if value in (False, None, ""):
                return "—"
            if field.type == "selection" and not callable(field.selection):
                return dict(field.selection).get(value, str(value))
            return str(value)

        for field_name, new_value in values.items():
            if allowed_fields is not None and field_name not in allowed_fields:
                continue
            field = record._fields.get(field_name)
            if not field or field.type in ("one2many", "many2many"):
                continue

            old_value = record[field_name]
            if field.type == "many2one":
                old_compare = old_value.id or False
                new_compare = new_value.id if hasattr(new_value, "id") else new_value or False
            elif field.type == "float":
                old_compare = float(old_value or 0.0)
                new_compare = float(new_value or 0.0)
            else:
                old_compare = old_value or False
                new_compare = new_value or False

            if old_compare == new_compare:
                continue

            label = field.string or field_name
            if prefix:
                label = f"{prefix} — {label}"
            changes.append(
                f"• {label}: {display_value(field, old_value)} → "
                f"{display_value(field, new_value)}"
            )

        return changes

    def send_user_error(
        self,
        webhook_type,
        webhook_name,
        message,
        event_type="error",
        transaction_name=None,
    ):
        """Send a user-friendly transaction error or update to Google Chat.

        Keep ``message`` focused on what happened and what the user can do;
        technical exception details belong in ``send_error``.
        """
        webhook_url = self._get_chat_webhook_url_user()
        if not webhook_url:
            raise ValueError("Google Chat webhook URL is not configured.")

        if not webhook_url:
            _logger.warning(
                "Google Chat webhook URL is not configured."
            )
            return False

        event_labels = {
            "error": "Perlu perhatian",
            "update": "Pembaruan transaksi",
        }
        event_label = event_labels.get(event_type, "Informasi transaksi")
        transaction_line = (
            f"\n*Transaksi:* {transaction_name}"
            if transaction_name
            else ""
        )
        message_text = (
            f"📋 *Informasi Transaksi Acumatica*\n\n"
            f"*Status:* {event_label}\n"
            f"*Proses:* {webhook_name}"
            f"{transaction_line}\n"
            f"*Informasi:*\n{message}\n\n"
            f"_Sumber: {webhook_type}_"
        )

        try:
            response = requests.post(
                webhook_url,
                json={"text": message_text},
                headers={
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            response.raise_for_status()

            _logger.info(
                "Google Chat user notification sent: %s",
                webhook_name,
            )
            return True

        except requests.RequestException:
            _logger.exception(
                "Failed to send Google Chat user notification: %s",
                webhook_name,
            )
            return False
