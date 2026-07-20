# -*- coding: utf-8 -*-
import logging

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request


_logger = logging.getLogger(__name__)


class AcumaticaWebhookController(http.Controller):
    def _json_response(self, status, message, http_status=200, **extra):
        body = {
            "status": status,
            "message": message,
        }
        body.update(extra)
        return request.make_json_response(body, status=http_status)

    def _check_api_key(self):
        api_key = request.httprequest.headers.get("X-API-Key")
        if not api_key:
            return False, _("Missing X-API-Key header")

        ICP = request.env["ir.config_parameter"].sudo()
        has_key = (
            request.env["acumatica.webhook.api.key"].sudo()._latest_key()
            or ICP.get_param("acumatica.webhook_api_key")
            or ICP.get_param("wms.api_key")
        )
        if not has_key:
            return False, _("Webhook API Key is not configured")

        KeyHistory = request.env["acumatica.webhook.api.key"].sudo()
        if not KeyHistory._matches_latest_key(api_key):
            return False, _("Invalid API Key")

        return True, None

    def _raw_payload(self, kwargs):
        payload = request.httprequest.get_json(silent=True) or kwargs
        if isinstance(payload, dict) and isinstance(payload.get("params"), (dict, list)):
            payload = payload["params"]
        return payload

    def _records_from_payload(self, payload):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            raise UserError(_("Payload must be a JSON object or array."))

        for key in ("records", "data", "value"):
            records = payload.get(key)
            if isinstance(records, list):
                return records

        return [payload]

    def _records_from_payload_keys(self, payload, keys):
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            raise UserError(_("Payload must be a JSON object or array."))

        for key in keys:
            records = payload.get(key)
            if isinstance(records, list):
                return records

        return self._records_from_payload(payload)

    def _value(self, item, key, default=""):
        value = item.get(key)
        if isinstance(value, dict):
            return value.get("value") or default
        if value is None:
            return default
        return value

    def _bool_value(self, item, *keys):
        value = self._first_value(item, *keys)
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "y")
        return bool(value)

    def _float_value(self, item, *keys):
        value = self._first_value(item, *keys)
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _int_value(self, item, *keys):
        value = self._first_value(item, *keys)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _first_value(self, item, *keys):
        for key in keys:
            value = self._value(item, key, default=False)
            if value not in (False, None, ""):
                return value
        return ""

    def _note_value(self, item):
        note = item.get("note") or item.get("Note")
        if isinstance(note, dict):
            return note.get("value") or ""
        return note or ""

    def _upsert_line(self, model_name, vals, lookup_fields):
        Line = request.env[model_name].sudo()
        for fields_group in lookup_fields:
            domain = []
            for field_name in fields_group:
                if not vals.get(field_name):
                    domain = []
                    break
                domain.append((field_name, "=", vals[field_name]))
            if not domain:
                continue
            found = Line.search(domain, limit=1)
            if found:
                found.write(vals)
                return found, "updated"
        return Line.create(vals), "created"

    def _process_lines(self, model_name, records, vals_getter, lookup_fields):
        created = updated = imported = errors = 0
        line_ids = []

        for index, item in enumerate(records, start=1):
            if not isinstance(item, dict):
                errors += 1
                continue

            vals = vals_getter(item, index)
            line, state = self._upsert_line(model_name, vals, lookup_fields)
            if state == "created":
                created += 1
            else:
                updated += 1
            line_ids.append(line.id)

        lines = request.env[model_name].sudo().browse(line_ids)
        if lines:
            lines._do_import()
            imported = len(lines.filtered(lambda line: line.import_state in ("imported", "updated", "skipped")))
            errors += len(lines.filtered(lambda line: line.import_state == "error"))

        return {
            "created": created,
            "updated": updated,
            "imported": imported,
            "errors": errors,
            "line_ids": line_ids,
        }
