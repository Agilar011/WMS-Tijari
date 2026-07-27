# -*- coding: utf-8 -*-

import json

from odoo import _, api, models
from odoo.exceptions import AccessDenied, UserError
from ..exceptions import AccountNotRegistered


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        """
        Override OAuth signin.

        Flow:
        1. Login using existing oauth_uid.
        2. If not found, try matching existing user by email/login.
        3. If matched, link OAuth account.
        4. Otherwise fallback to default signup.
        """

        oauth_uid = validation["user_id"]

        # ---------------------------------------------------------
        # 1. Existing OAuth user
        # ---------------------------------------------------------
        oauth_user = self.search([
            ("oauth_uid", "=", oauth_uid),
            ("oauth_provider_id", "=", provider),
        ], limit=1)

        if oauth_user:
            oauth_user.write({
                "oauth_access_token": params["access_token"],
            })
            return oauth_user.login

        # ---------------------------------------------------------
        # 2. Existing user with same email
        # ---------------------------------------------------------
        email = validation.get("email")

        if email:
            existing_user = self.search([
                "|",
                ("login", "=", email),
                ("email", "=", email),
            ], limit=1)

            if existing_user:
                existing_user.write({
                    "oauth_provider_id": provider,
                    "oauth_uid": oauth_uid,
                    "oauth_access_token": params["access_token"],
                })

                return existing_user.login

        raise AccountNotRegistered()