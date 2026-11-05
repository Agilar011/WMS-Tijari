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

    @staticmethod
    def _format_error_message(
        webhook_type,
        webhook_name,
        error,
        error_type=None,
        transaction_name=None,
    ):
        """Build one Google Chat format for technical and business errors."""
        transaction_line = (
            f"*Transaksi:* {transaction_name}\n"
            if transaction_name
            else ""
        )
        return (
            "🚨 *Acumatica Error*\n\n"
            f"*Type:* {webhook_type or '-'}\n"
            f"*Webhook:* {webhook_name or '-'}\n"
            f"{transaction_line}"
            f"*Error Type:* {error_type or '-'}\n"
            f"*Error:*\n{error or '-'}"
        )

    @staticmethod
    def _format_business_error(message):
        """Normalize curated business-error messages into shared categories."""
        rules = (
            (
                "operation_type",
                "Operation Type belum tersedia",
                "Konfigurasi tipe operasi untuk transaksi ini belum tersedia di WMS.",
                "Minta admin memeriksa dan melengkapi pengaturan Operation Type yang sesuai.",
                lambda text: "operation type" in text or "tipe operasi" in text or "tipe transfer" in text,
            ),
            (
                "destination_location_type",
                "Tipe lokasi tujuan tidak sesuai",
                "Lokasi tujuan bertipe Customer tidak dapat digunakan untuk transaksi ini.",
                "Periksa dan pilih lokasi tujuan dengan tipe yang sesuai.",
                lambda text: "bertipe customer" in text or "tipe customer" in text,
            ),
            (
                "stock_insufficient",
                "Stok tidak mencukupi",
                "Stok produk di lokasi yang diperlukan belum mencukupi.",
                "Periksa ketersediaan dan lokasi stok produk.",
                lambda text: "stok" in text and ("tidak mencukupi" in text or "belum mencukupi" in text),
            ),
            (
                "document_processed",
                "Dokumen sudah diproses",
                "Transaksi tidak dapat diperbarui karena proses atau dokumen WMS sudah berjalan.",
                "Periksa status dokumen di WMS. Hubungi admin jika perubahan tetap diperlukan.",
                lambda text: "tidak dapat diperbarui" in text or "sudah diproses" in text or "sudah berstatus" in text or "proses sebelumnya sudah berjalan" in text,
            ),
            (
                "transaction_lines",
                "Baris produk belum tersedia",
                "Transaksi belum memiliki baris atau detail produk yang diperlukan.",
                "Lengkapi detail produk pada transaksi lalu proses kembali.",
                lambda text: "belum memiliki baris" in text or "tidak memiliki baris produk" in text or "belum memiliki detail produk" in text,
            ),
            (
                "header_missing",
                "Header transaksi tidak ditemukan",
                "Data header transaksi tidak ditemukan di data yang diterima.",
                "Periksa kembali data transaksi yang dikirim dari Acumatica.",
                lambda text: "header" in text and ("tidak ditemukan" in text or "belum ditemukan" in text),
            ),
            (
                "product_missing",
                "Produk belum terdaftar",
                "Produk yang dirujuk transaksi belum terdaftar atau belum tersedia di WMS.",
                "Periksa kode produk dan lengkapi master produk di WMS.",
                lambda text: "produk" in text and ("belum terdaftar" in text or "belum tersedia" in text or "belum ditemukan" in text),
            ),
            (
                "customer_missing",
                "Customer belum terdaftar",
                "Customer yang dirujuk transaksi belum terdaftar di WMS.",
                "Periksa kode customer dan lengkapi master customer di WMS.",
                lambda text: "customer" in text and ("belum terdaftar" in text or "belum ditemukan" in text),
            ),
            (
                "vendor_missing",
                "Vendor belum terdaftar",
                "Vendor yang dirujuk transaksi belum terdaftar di WMS.",
                "Periksa kode vendor dan lengkapi master vendor di WMS.",
                lambda text: "vendor" in text and ("belum terdaftar" in text or "belum ditemukan" in text),
            ),
            (
                "warehouse_location_mapping",
                "Mapping warehouse/lokasi belum tersedia",
                "Warehouse atau lokasi yang dirujuk transaksi belum memiliki mapping aktif di WMS.",
                "Periksa kode warehouse/lokasi dan aktifkan mapping WMS yang sesuai.",
                lambda text: ("warehouse" in text or "lokasi" in text) and ("mapping" in text or "tidak ditemukan" in text or "belum ditemukan" in text or "belum memiliki" in text or "belum tersedia" in text or "tidak aktif" in text or "konfigurasi" in text),
            ),
            (
                "details_incomplete",
                "Detail transaksi belum lengkap",
                "Detail transaksi belum memenuhi syarat untuk diproses atau diselesaikan.",
                "Periksa kelengkapan dan validitas detail transaksi di WMS.",
                lambda text: "belum dapat diselesaikan" in text or "detail transaksi" in text or "belum dapat diproses" in text,
            ),
        )
        lines = [line.strip() for line in str(message or "").splitlines() if line.strip()]
        matches = []
        for line in lines:
            lowered = line.lower()
            for key, title, issue, action, predicate in rules:
                if predicate(lowered):
                    if key not in {match[0] for match in matches}:
                        matches.append((key, title, issue, action))
                    break
            else:
                if "unknown" not in {match[0] for match in matches}:
                    matches.append((
                        "unknown",
                        "Error bisnis perlu diperiksa",
                        "Data atau konfigurasi transaksi belum memenuhi syarat untuk diproses.",
                        "Periksa detail error dan konfigurasi WMS. Hubungi admin jika masalah berlanjut.",
                    ))

        if not matches:
            matches.append((
                "unknown",
                "Error bisnis perlu diperiksa",
                "Data atau konfigurasi transaksi belum memenuhi syarat untuk diproses.",
                "Periksa detail error dan konfigurasi WMS. Hubungi admin jika masalah berlanjut.",
            ))

        categories = "\n".join(f"• {match[1]}" for match in matches)
        issues = "\n".join(f"• {match[2]}" for match in matches)
        actions = "\n".join(f"• {match[3]}" for match in matches)
        detail = "\n".join(f"• {line}" for line in lines) or "• Tidak ada detail tambahan."
        return (
            f"*Kategori:*\n{categories}\n"
            f"*Masalah:*\n{issues}\n"
            f"*Tindakan:*\n{actions}\n"
            f"*Detail:*\n{detail}"
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

        message = self._format_error_message(
            webhook_type=webhook_type,
            webhook_name=webhook_name,
            error=error,
            error_type=error_type,
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
            _logger.warning(
                "Google Chat webhook URL is not configured."
            )
            return False

        if event_type == "error":
            message_text = self._format_error_message(
                webhook_type=webhook_type,
                webhook_name=webhook_name,
                error=self._format_business_error(message),
                error_type="business",
                transaction_name=transaction_name,
            )
        else:
            event_labels = {
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
