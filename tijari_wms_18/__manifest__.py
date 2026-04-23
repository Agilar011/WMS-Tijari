
{
    'name': 'WMS from Tijari',
    'version': '18.0.0.0.0',
    'summary': 'WMS',
    'description': 'WMS',
    'category': 'Tools',
    'author': 'Tijari',
    'company': 'Tijari',
    'maintainer': 'Tijari Corp.',
    'website': 'https://www.tijari.id',
    'license': 'LGPL-3',
    'depends': [
        'base', 
        'stock', 
        'stock_sms',
    ],
    'data': [
        'views/stock.xml',
        'views/stock_picking_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
        ],
        'web.assets_backend': [
            'tijari_wms_18/static/src/js/generate_lot_button.js',
            'tijari_wms_18/static/src/xml/generate_lot_button.xml'
        ]
    },
    'installable': True,
    'auto_install': False,
    'application': True,
}
