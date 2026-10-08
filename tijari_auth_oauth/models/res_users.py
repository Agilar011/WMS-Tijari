# -*- coding: utf-8 -*-

import logging

from odoo import api, models
from odoo.exceptions import AccessDenied
from ..exceptions import OAuthAccessDenied


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

        provider_record = self.env["auth.oauth.provider"].browse(provider)
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

            self.env["wms.google.login.log"].log_event(
                validation=validation,
                provider=provider_record,
                status="denied",
                reason="missing_email",
                error_message="Google account has no email.",
            )
            
            raise OAuthAccessDenied("missing_email")
        
        # =========================================================
        # 1. EMAIL DOMAIN VALIDATION
        # =========================================================
        # if not email.endswith("@aditya.co.id"):
        #     _logger.warning(
        #         "OAuth signin rejected: unauthorized email domain - %s",
        #         email,
        #     )

        #     self.env["wms.google.login.log"].log_event(
        #         validation=validation,
        #         provider=provider_record,
        #         status="denied",
        #         reason="invalid_domain",
        #         error_message=(
        #             f"Unauthorized email domain: {email}"
        #         ),
        #     )

        #     raise OAuthAccessDenied("invalid_domain")

        # =========================================================
        # 2. EXISTING OAUTH USER
        # =========================================================
        oauth_user = self.with_context(
            active_test=False
        ).search([
            ("oauth_uid", "=", oauth_uid),
            ("oauth_provider_id", "=", provider),
        ], limit=1)

        if oauth_user:
            _logger.info(
                "Existing OAuth user found: id=%s login=%s active=%s",
                oauth_user.id,
                oauth_user.login,
                oauth_user.active,
            )

            if not oauth_user.active:
                self.env["wms.google.login.log"].log_event(
                    validation=validation,
                    provider=provider_record,
                    reason="user_inactive",
                    error_message=(
                        f"User {oauth_user.login} is archived."
                    ),
                    user=oauth_user,
                )

                raise OAuthAccessDenied("user_inactive")

            if (
                not oauth_user.email
                or oauth_user.email.strip().lower() != email
            ):
                self.env["wms.google.login.log"].log_event(
                    validation=validation,
                    provider=provider_record,
                    reason="email_mismatch",
                    error_message=(
                        f"OAuth email {email} does not match "
                        f"user email {oauth_user.email}."
                    ),
                    user=oauth_user,
                )

                raise OAuthAccessDenied("email_mismatch")

            oauth_user.write({
                "oauth_access_token": params.get("access_token"),
            })

            return oauth_user.login

        # =========================================================
        # 3. EXISTING ODOO USER BY EMAIL / LOGIN
        # =========================================================
        existing_user = self.with_context(
            active_test=False
        ).search([
            "|",
            ("login", "=ilike", email),
            ("email", "=ilike", email),
        ], limit=1)

        if existing_user:
            
            _logger.info(
                "Existing Odoo user found: id=%s login=%s active=%s "
                "Linking OAuth account.",
                existing_user.id,
                existing_user.login,
                existing_user.active,
            )

            if not existing_user.active:
                self.env["wms.google.login.log"].log_event(
                    validation=validation,
                    provider=provider_record,
                    reason="user_inactive",
                    error_message=(
                        f"User {existing_user.login} is archived."
                    ),
                    user=existing_user,
                )

                raise OAuthAccessDenied("user_inactive")

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

        guest_group = self.env.ref(
            "tijari_auth_oauth.group_guest"
        )
        
        user = self.create({
            "name": validation.get("name") or email,
            "login": email,
            "email": email,
            "oauth_provider_id": provider,
            "oauth_uid": oauth_uid,
            "oauth_access_token": params.get("access_token"),
            "groups_id": [(6, 0, [guest_group.id])],
        })

        if user.partner_id:
            user.partner_id.write({
                "image_1920": False,
            })

        _logger.info(
            "New Odoo user created: id=%s login=%s",
            user.id,
            user.login,
        )

        return user.login

    @api.model
    def _auth_oauth_validate(self, provider, access_token):
        oauth_provider = self.env["auth.oauth.provider"].browse(provider)

        if not access_token:
            self.env["wms.google.login.log"].log_event(
                validation={},
                provider=oauth_provider,
                reason="oauth_error",
                error_message="OAuth access token is missing.",
            )

            raise AccessDenied("Missing OAuth access token")

        try:
            return super()._auth_oauth_validate(
                provider,
                access_token,
            )

        except AccessDenied as e:
            self.env["wms.google.login.log"].log_event(
                validation={},
                provider=oauth_provider,
                reason="access_denied",
                error_message=str(e),
            )

            raise

        except Exception as e:
            self.env["wms.google.login.log"].log_event(
                validation={},
                provider=oauth_provider,
                reason="oauth_error",
                error_message=str(e),
            )

            raise