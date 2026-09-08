# -*- coding: utf-8 -*-
# Copyright 2025 Sveltware Solutions

{
    'name': 'Omux List Indicator',
    'category': 'Hidden',
    'version': '1.0.0',
    'license': 'OPL-1',
    'author': 'Sveltware Solutions',
    'website': 'https://www.linkedin.com/in/sveltware',
    'data': [
        'data/asset_data.xml',
    ],
    'assets': {
        'omux_list_indicator.grouping_indicator': [
            'omux_list_indicator/static/src/list_controller.js',
            (
                'after',
                'web/static/src/views/list/list_controller.xml',
                'omux_list_indicator/static/src/list_controller.xml',
            ),
        ],
    }
}
