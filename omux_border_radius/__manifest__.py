# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Omux Border Radius',
    'category': 'Hidden',
    'version': '1.0.0',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'data': [
        'data/asset_data.xml',
    ],
    'assets': {
        'omux_border_radius/sharp': [
            (
                'before',
                'web/static/src/scss/primary_variables.scss',
                'omux_border_radius/static/src/sharp/*',
            ),
        ],
        'omux_border_radius/subtle': [
            (
                'before',
                'web/static/src/scss/primary_variables.scss',
                'omux_border_radius/static/src/subtle/*',
            ),
        ],
        'omux_border_radius/moderate': [
            (
                'before',
                'web/static/src/scss/primary_variables.scss',
                'omux_border_radius/static/src/moderate/*',
            ),
        ],
        'omux_border_radius/soft': [
            (
                'before',
                'web/static/src/scss/primary_variables.scss',
                'omux_border_radius/static/src/soft/*',
            ),
        ],
    },
}
