# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Omux Backend (Community Edition)',
    'category': 'Themes/Backend',
    'summary': 'Modern Odoo Backend with start menu, dual sidebar, dark mode, global search, bookmark manager, split view, quick pop-up, quick create, recent items, fullscreen forms, RTL support, language switcher, mobile responsive layout, flexible chatter, sticky headers, group toggles, full-width sheet, enhanced list & kanban views, required input markers, batch create, app menu sorting, right-click menu, user wise menu sorting, WCAG 2.2-ready, Enterprise color theme, RTL CSS, multi-language ready.',
    'version': '1.7.4',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'live_test_url': 'https://omux.sveltware.com/web/login',
    'support': 'jupetern24@gmail.com',
    'sequence': 777,
    'images': [
        'static/description/banner.png',
        'static/description/theme_screenshot.png',
    ],
    'depends': [
        'base_sparse_field',
        'auth_signup',
        'web_editor',
        'omux_shared_lib',
        'omux_config_base',
        'omux_state_manager',
        'omux_web_refresher',
        'omux_list_indicator',
        'omux_list_density',
        'omux_border_radius',
        'omux_input_style',
    ],
    'excludes': [
        'web_enterprise',
    ],
    'uninstall_hook': 'uninstall_hook',
    'data': [
        'data/asset_data.xml',
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'views/webclient_templates.xml',
        'views/res_company_views.xml',
        'views/ir_ui_menu.xml',
    ],
    'assets': {
        'web._assets_primary_variables': {
            (
                'prepend',
                'udoo_om_ux/static/src/scss/style_variables.scss',
            ),
            (
                'before',
                'web/static/src/scss/primary_variables.scss',
                'udoo_om_ux/static/src/scss/primary_variables.scss',
            ),
            (
                'before',
                'web/static/src/**/*.variables.scss',
                'udoo_om_ux/static/src/**/*.variables.scss',
            ),
        },
        'web._assets_secondary_variables': [
            (
                'before',
                'web/static/src/scss/secondary_variables.scss',
                'udoo_om_ux/static/src/scss/secondary_variables.scss',
            ),
        ],
        'web._assets_backend_helpers': [
            (
                'before',
                'web/static/src/scss/bootstrap_overridden.scss',
                'udoo_om_ux/static/src/scss/bs_backend_overridden.scss',
            ),
        ],
        'web.assets_backend': [
            (
                'replace',
                'web/static/src/webclient/navbar/navbar.scss',
                'udoo_om_ux/static/src/webclient/navbar/navbar.scss',
            ),
            (
                'after',
                'web/static/src/scss/fontawesome_overridden.scss',
                'udoo_om_ux/static/src/scss/overridden_icons.scss',
            ),
            (
                'before',
                'mail/static/src/views/fields/**/*',
                'udoo_om_ux/static/src/patch/chatter/form_compiler.js',
            ),
            (
                'before',
                'mail/static/src/views/fields/**/*',
                'udoo_om_ux/static/src/patch/chatter/form_renderer.js',
            ),
            (
                'before',
                'mail/static/src/views/fields/**/*',
                'udoo_om_ux/static/src/patch/chatter/form_renderer.scss',
            ),
            (
                'before',
                'web/static/src/webclient/**/*',
                'udoo_om_ux/static/src/views/**/*',
            ),
            (
                'before',
                'web/static/src/webclient/**/*',
                'udoo_om_ux/static/src/search/**/*',
            ),
            'udoo_om_ux/static/src/webclient/**/*',
            'udoo_om_ux/static/src/patch/button_box.js',
            'udoo_om_ux/static/src/patch/chatter.js',
            (
                'remove',
                'udoo_om_ux/static/src/**/*.dark.scss',
            ),  # Don't include dark theme
            (
                'after',
                'udoo_om_ux/static/src/webclient/**/*',
                'udoo_om_ux/static/src/scss/style_backend.scss',
            ),
        ],
        'web.dark_mode_variables': [
            (
                'before',
                'udoo_om_ux/static/src/scss/primary_variables.scss',
                'udoo_om_ux/static/src/scss/primary_variables_dark.scss',
            ),
            (
                'before',
                'udoo_om_ux/static/src/**/*.variables.scss',
                'udoo_om_ux/static/src/**/*.variables.dark.scss',
            ),
            (
                'before',
                'udoo_om_ux/static/src/scss/secondary_variables.scss',
                'udoo_om_ux/static/src/scss/secondary_variables_dark.scss',
            ),
        ],
        'web.assets_web_dark': [
            ('include', 'web.dark_mode_variables'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/omux/dark.scss',
            ),
            (
                'before',
                'udoo_om_ux/static/src/scss/bs_backend_overridden.scss',
                'udoo_om_ux/static/src/scss/bs_backend_overridden_dark.scss',
            ),
            (
                'after',
                'web/static/lib/bootstrap/scss/_functions.scss',
                'udoo_om_ux/static/src/scss/bs_functions_overridden_dark.scss',
            ),
            'udoo_om_ux/static/src/**/*.dark.scss',
        ],
        'web.assets_backend_lazy_dark': [
            ('include', 'web.dark_mode_variables'),
            (
                'before',
                'udoo_om_ux/static/src/scss/bs_backend_overridden.scss',
                'udoo_om_ux/static/src/scss/bs_backend_overridden_dark.scss',
            ),
            (
                'after',
                'web/static/lib/bootstrap/scss/_functions.scss',
                'udoo_om_ux/static/src/scss/bs_functions_overridden_dark.scss',
            ),
        ],
        'web.assets_web': [
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/omux/light.scss',
            ),
        ],
        'web.assets_frontend': [
            (
                'before',
                'web/static/lib/bootstrap/scss/_variables.scss',
                'udoo_om_ux/static/src/scss/bs_frontend_variables.scss',
            ),
            (
                'after',
                'web/static/src/scss/fontawesome_overridden.scss',
                'udoo_om_ux/static/src/scss/overridden_icons.scss',
            ),
            (
                'replace',
                'web/static/src/webclient/navbar/navbar.scss',
                'udoo_om_ux/static/src/webclient/navbar/navbar.scss',
            ),
            'udoo_om_ux/static/src/scss/style_login_page.scss',
        ],
        'web._assets_core': [
            'omux_shared_lib/static/lib/object_hash.js',
            'udoo_om_ux/static/src/core/**/*',
            (
                'after',
                'web/static/src/session.js',
                'udoo_om_ux/static/src/omux.js',
            ),
            (
                'after',
                'web/static/src/core/utils/ui.js',
                'udoo_om_ux/static/src/patch/_ui.js',
            ),
        ],
        # COLOR
        'web.assets_web_magenta': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/magenta.scss',
            ),
        ],
        'web.assets_web_magenta_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/magenta_dark.scss',
            ),
        ],
        'web.assets_web_dodger': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/dodger.scss',
            ),
        ],
        'web.assets_web_dodger_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/dodger_dark.scss',
            ),
        ],
        'web.assets_web_lime': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/lime.scss',
            ),
        ],
        'web.assets_web_lime_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/lime_dark.scss',
            ),
        ],
        'web.assets_web_green': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/green.scss',
            ),
        ],
        'web.assets_web_green_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/green_dark.scss',
            ),
        ],
        'web.assets_web_emerald': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/emerald.scss',
            ),
        ],
        'web.assets_web_emerald_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/emerald_dark.scss',
            ),
        ],
        'web.assets_web_sky': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/sky.scss',
            ),
        ],
        'web.assets_web_sky_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/sky_dark.scss',
            ),
        ],
        'web.assets_web_rose': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/rose.scss',
            ),
        ],
        'web.assets_web_rose_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/rose_dark.scss',
            ),
        ],
        'web.assets_web_yellow': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/yellow.scss',
            ),
        ],
        'web.assets_web_yellow_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/yellow_dark.scss',
            ),
        ],
        'web.assets_web_orange': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/orange.scss',
            ),
        ],
        'web.assets_web_orange_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/orange_dark.scss',
            ),
        ],
        'web.assets_web_pink': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/pink.scss',
            ),
        ],
        'web.assets_web_pink_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/pink_dark.scss',
            ),
        ],
        'web.assets_web_indigo': [
            ('include', 'web.assets_web'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/indigo.scss',
            ),
        ],
        'web.assets_web_indigo_dark': [
            ('include', 'web.assets_web_dark'),
            (
                'after',
                'udoo_om_ux/static/src/scss/style_variables.scss',
                'udoo_om_ux/static/src/scss/pallets/indigo_dark.scss',
            ),
        ],
        'omux.conf': [
            'udoo_om_ux/static/src/conf/*.js',
            'udoo_om_ux/static/src/conf/*.xml',
            'udoo_om_ux/static/src/conf/*.scss',
        ],
    },
    'price': 149,
    'currency': 'USD',
}
