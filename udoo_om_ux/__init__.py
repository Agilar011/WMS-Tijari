# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

from . import models


def uninstall_hook(env):
    env['web_editor.assets'].reset_omux_light()
    env['web_editor.assets'].reset_omux_dark()

    # Optional: Omux Color Scheme
    ocs_assets = env['ir.asset'].search([('path', 'ilike', 'omux_color_scheme/static/set')])
    if ocs_assets:
        ocs_assets.unlink()
