# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import secrets

from odoo import _, api, fields, models


class AcumaticaWebhookApiKey(models.Model):
    _name = "acumatica.webhook.api.key"
    _description = "Acumatica Webhook API Key"
    _order = "generated_at desc, id desc"

    PARAM_PLAIN = "acumatica.webhook_api_key"
    PARAM_LEGACY = "wms.api_key"
    HASH_ITERATIONS = 260000

    name = fields.Char(required=True, readonly=True, default=lambda self: _("Webhook API Key"))
    api_key = fields.Char(string="API Key", copy=False)
    key_hash = fields.Char(string="API Key Hash", readonly=True, copy=False)
    key_preview = fields.Char(string="API Key Preview", readonly=True, copy=False)
    generated_at = fields.Datetime(string="Generated At", readonly=True, default=fields.Datetime.now)
    active = fields.Boolean(default=True, readonly=True)
    is_latest = fields.Boolean(string="Latest", compute="_compute_is_latest")

    @api.depends("active", "generated_at")
    def _compute_is_latest(self):
        latest = self.sudo()._latest_key()
        for rec in self:
            rec.is_latest = rec.id == latest.id

    @api.model
    def _generate_plain_key(self):
        return "ACU-%s" % secrets.token_urlsafe(32)

    @api.model
    def _hash_api_key(self, api_key):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            api_key.encode("utf-8"),
            salt,
            self.HASH_ITERATIONS,
        )
        return "pbkdf2_sha256$%s$%s$%s" % (
            self.HASH_ITERATIONS,
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )

    @api.model
    def _verify_api_key(self, api_key, stored_hash):
        if not api_key or not stored_hash:
            return False
        try:
            algorithm, iterations, salt, digest = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            expected = hashlib.pbkdf2_hmac(
                "sha256",
                api_key.encode("utf-8"),
                base64.b64decode(salt.encode("ascii")),
                int(iterations),
            )
            return hmac.compare_digest(expected, base64.b64decode(digest.encode("ascii")))
        except Exception:
            return False

    @api.model
    def _preview_key(self, api_key):
        return "%s...%s" % (api_key[:10], api_key[-8:])

    @api.model
    def _latest_key(self):
        return self.sudo().search([("active", "=", True)], order="generated_at desc, id desc", limit=1)

    @api.model
    def _matches_latest_key(self, api_key):
        latest = self._latest_key()
        if latest:
            return self._verify_api_key(api_key, latest.key_hash)

        ICP = self.env["ir.config_parameter"].sudo()
        legacy_key = ICP.get_param(self.PARAM_PLAIN) or ICP.get_param(self.PARAM_LEGACY)
        return bool(legacy_key and hmac.compare_digest(api_key, legacy_key))

    @api.model
    def _delete_param(self, key):
        self.env["ir.config_parameter"].sudo().search([("key", "=", key)]).unlink()

    @api.model
    def generate_key_record(self):
        api_key = self._generate_plain_key()
        record = self.sudo().create({
            "name": _("Webhook API Key %s") % fields.Datetime.to_string(fields.Datetime.now()),
            "api_key": api_key,
            "key_hash": self._hash_api_key(api_key),
            "key_preview": self._preview_key(api_key),
            "generated_at": fields.Datetime.now(),
            "active": True,
        })
        self._delete_param(self.PARAM_PLAIN)
        return record, api_key

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            api_key = vals.get("api_key") or self._generate_plain_key()
            vals["api_key"] = api_key
            vals["key_hash"] = self._hash_api_key(api_key)
            vals["key_preview"] = self._preview_key(api_key)
            vals.setdefault(
                "name",
                _("Webhook API Key %s") % fields.Datetime.to_string(fields.Datetime.now()),
            )
        records = super().create(vals_list)
        self._delete_param(self.PARAM_PLAIN)
        return records

    def write(self, vals):
        if "api_key" in vals:
            api_key = vals.get("api_key")
            vals["key_hash"] = self._hash_api_key(api_key) if api_key else False
            vals["key_preview"] = self._preview_key(api_key) if api_key else False
        return super().write(vals)

    def action_deactivate(self):
        self.write({"active": False})


class AcumaticaWebhookKeyConfig(models.TransientModel):
    _name = "acumatica.webhook.key.config"
    _description = "Acumatica Webhook API Key Configuration"

    PARAM_PLAIN = "acumatica.webhook_api_key"
    PARAM_LEGACY = "wms.api_key"

    api_key_status = fields.Char(string="Status", readonly=True)
    generated_api_key = fields.Char(
        string="Generated API Key",
        readonly=True,
        copy=False,
        help="Shown only after generating a new key. Copy it before closing this screen.",
    )
    latest_key_preview = fields.Char(string="API Key Preview", readonly=True)
    latest_api_key = fields.Char(string="API Key", readonly=True)
    generated_at = fields.Char(string="Last Generated At", readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        KeyHistory = self.env["acumatica.webhook.api.key"].sudo()
        latest = KeyHistory._latest_key()
        ICP = self.env["ir.config_parameter"].sudo()
        legacy_key = ICP.get_param(self.PARAM_PLAIN) or ICP.get_param(self.PARAM_LEGACY)
        vals.update({
            "api_key_status": _("API key configured") if latest else (
                _("Plaintext legacy API key configured") if legacy_key else _("API key is not configured")
            ),
            "latest_key_preview": latest.key_preview if latest else (
                _("Plaintext legacy parameter is still active") if legacy_key else ""
            ),
            "latest_api_key": latest.api_key if latest else (legacy_key or ""),
            "generated_at": fields.Datetime.to_string(latest.generated_at) if latest else "",
        })
        return vals

    def action_generate_api_key(self):
        self.ensure_one()
        key_record, api_key = self.env["acumatica.webhook.api.key"].sudo().generate_key_record()
        self.write({
            "generated_api_key": api_key,
            "latest_key_preview": key_record.key_preview,
            "latest_api_key": api_key,
            "generated_at": fields.Datetime.to_string(key_record.generated_at),
            "api_key_status": _("API key configured"),
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Webhook API Key"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_clear_api_key(self):
        self.ensure_one()
        self.env["acumatica.webhook.api.key"].sudo().search([("active", "=", True)]).write({"active": False})
        self.env["ir.config_parameter"].sudo().search([("key", "=", self.PARAM_PLAIN)]).unlink()
        legacy_key = self.env["ir.config_parameter"].sudo().get_param(self.PARAM_LEGACY)
        self.write({
            "generated_api_key": False,
            "latest_key_preview": _("Plaintext legacy parameter is still active") if legacy_key else False,
            "latest_api_key": legacy_key or False,
            "generated_at": False,
            "api_key_status": _("Plaintext legacy API key configured") if legacy_key else _("API key is not configured"),
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Webhook API Key"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_key_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Webhook API Key History"),
            "res_model": "acumatica.webhook.api.key",
            "view_mode": "list,form",
            "target": "current",
        }
