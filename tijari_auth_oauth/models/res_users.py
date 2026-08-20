# -*- coding: utf-8 -*-

import logging

from odoo import api, models
from odoo.exceptions import AccessDenied

from ..exceptions import AccountNotRegistered


_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        """
        OAuth signin flow.

        Flow:
        1. Validate Google email domain.
        2. Login using existing oauth_uid.
        3. If not found, try matching existing Odoo user by email/login.
        4. If matched, link OAuth account.
        5. If no user exists, create a new user without additional roles.
        """

        # =========================================================
        # GOOGLE USER DATA
        # =========================================================
        oauth_uid = validation.get("user_id")
        email = (validation.get("email") or "").strip().lower()

        _logger.info(
            "OAuth signin attempt - email=%s, oauth_uid=%s, provider=%s",
            email,
            oauth_uid,
            provider,
        )

        if not email:
            _logger.warning(
                "OAuth signin rejected: Google account has no email."
            )
            raise AccessDenied()

        # =========================================================
        # 1. EMAIL DOMAIN VALIDATION
        # =========================================================
        if not email.endswith("@aditya.co.id"):
            _logger.warning(
                "OAuth signin rejected: unauthorized email domain - %s",
                email,
            )
            raise AccessDenied()

        # =========================================================
        # 2. EXISTING OAUTH USER
        # =========================================================
        oauth_user = self.search([
            ("oauth_uid", "=", oauth_uid),
            ("oauth_provider_id", "=", provider),
        ], limit=1)

        if oauth_user:
            _logger.info(
                "Existing OAuth user found: id=%s login=%s",
                oauth_user.id,
                oauth_user.login,
            )

            oauth_user.write({
                "oauth_access_token": params.get("access_token"),
            })

            return oauth_user.login

        # =========================================================
        # 3. EXISTING ODOO USER BY EMAIL / LOGIN
        # =========================================================
        existing_user = self.search([
            "|",
            ("login", "=ilike", email),
            ("email", "=ilike", email),
        ], limit=1)

        if existing_user:
            _logger.info(
                "Existing Odoo user found: id=%s login=%s. "
                "Linking OAuth account.",
                existing_user.id,
                existing_user.login,
            )

            existing_user.write({
                "oauth_provider_id": provider,
                "oauth_uid": oauth_uid,
                "oauth_access_token": params.get("access_token"),
            })

            return existing_user.login

        # =========================================================
        # 4. CREATE NEW USER
        # =========================================================
        _logger.info(
            "No existing Odoo user found for %s. "
            "Creating new user.",
            email,
        )

        user = self.create({
            "name": validation.get("name") or email,
            "login": email,
            "email": email,
            "oauth_provider_id": provider,
            "oauth_uid": oauth_uid,
            "oauth_access_token": params.get("access_token"),
        })

        _logger.info(
            "New Odoo user created: id=%s login=%s",
            user.id,
            user.login,
        )

        return user.login