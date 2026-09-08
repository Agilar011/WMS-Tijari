# -*- coding: utf-8 -*-
{
    "name": "WMS Google OAuth",
    "version": "18.0.1.0.0",
    "summary": "Extend Google OAuth authentication for existing users",
    "description": """
WMS Google OAuth
================

This module extends Odoo's OAuth authentication flow by linking
an existing user account based on email before creating a new one.

Features:
- Link existing user with Google OAuth account.
- Prevent duplicate user creation.
- Store OAuth Provider and OAuth UID automatically.
""",
    "author": "PT Tijari Teknologi Automasi",
    "website": "",
    "license": "LGPL-3",
    "category": "Authentication",
    "depends": [
        "base",
        "auth_oauth",
    ],
    "data": [
        "security/groups.xml",
        "views/login_password_toggle_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tijari_auth_oauth/static/src/js/password_visibility_toggle.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
