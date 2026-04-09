# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Omux Web Refresher',
    'category': 'Hidden',
    'version': '1.0.0',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'images': [
        'static/description/banner.png',
    ],
    'depends': ['omux_view_action'],
    'assets': {
        'web.assets_backend': [
            (
                'after',
                'omux_view_action/static/src/control_panel.xml',
                'omux_web_refresher/static/src/control_panel.xml',
            ),
            'omux_web_refresher/static/src/*.js',
        ]
    },
}
