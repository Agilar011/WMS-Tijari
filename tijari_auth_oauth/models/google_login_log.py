from odoo import api, fields, models, registry
from odoo.http import request


class GoogleLoginLog(models.Model):
    _name = "wms.google.login.log"
    _description = "Google Login Log"
    _order = "login_date desc, id desc"

    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        required=True,
        readonly=True,
        copy=False,
        default="New",
    )

    login_date = fields.Datetime(
        string="Login Attempt",
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )

    status = fields.Selection(
        [
            ("success", "Success"),
            ("denied", "Denied"),
        ],
        string="Status",
        required=True,
        readonly=True,
        index=True,
    )

    reason = fields.Selection(
        [
            ("missing_email", "Missing Email"),
            ("email_mismatch", "Email Mismatch"),
            ("invalid_domain", "Invalid Email Domain"),
            ("user_not_found", "User Not Found"),
            ("user_inactive", "User Inactive/Archived"),
            ("access_denied", "Access Denied"),
            ("oauth_error", "OAuth Error"),
            ("invalid_token", "Invalid Token"),
            ("validation_error", "Validation Error"),
            ("unknown", "Unknown"),
        ],
        string="Reason",
        readonly=True,
        index=True,
    )

    email = fields.Char(
        string="Google Email",
        readonly=True,
        index=True,
    )

    name_from_google = fields.Char(
        string="Google Name",
        readonly=True,
    )

    oauth_uid = fields.Char(
        string="OAuth UID",
        readonly=True,
        index=True,
    )

    provider_id = fields.Many2one(
        "auth.oauth.provider",
        string="OAuth Provider",
        readonly=True,
    )

    user_id = fields.Many2one(
        "res.users",
        string="Odoo User",
        readonly=True,
        index=True,
    )

    ip_address = fields.Char(
        string="IP Address",
        readonly=True,
    )

    user_agent = fields.Char(
        string="User Agent",
        readonly=True,
    )

    error_message = fields.Text(
        string="Error Message",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "wms.google.login.log"
                ) or "New"

        return super().create(vals_list)

    @api.model
    def log_event(
        self,
        validation=None,
        provider=None,
        status="denied",
        reason="unknown",
        error_message=None,
        user=None,
    ):
        validation = validation or {}

        vals = {
            "email": (
                validation.get("email") or ""
            ).strip().lower(),

            "name_from_google": validation.get("name"),

            "oauth_uid": validation.get("user_id"),

            "provider_id": (
                provider.id
                if provider
                else False
            ),

            "user_id": (
                user.id
                if user
                else False
            ),

            "status": status,
            "reason": reason,
            "error_message": error_message,
        }

        if request:
            vals.update({
                "ip_address": request.httprequest.remote_addr,
                "user_agent": request.httprequest.headers.get(
                    "User-Agent"
                ),
            })

        dbname = self.env.cr.dbname

        with registry(dbname).cursor() as new_cr:
            new_env = api.Environment(
                new_cr,
                self.env.uid,
                self.env.context,
            )

            log = new_env["wms.google.login.log"].create(vals)

            new_cr.commit()

            return log.name