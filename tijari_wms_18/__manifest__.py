
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
        'product',
    ],
    'data': [
        'views/stock.xml',
        'views/stock_picking_views.xml',
        'views/hide_menu.xml',
        'views/wms_operations_action.xml',
        'views/wms_operations_menu.xml',
        'views/stock_report_velocity_views.xml',
        'views/stock_report_aging_views.xml',
        'views/stock_report_inherit_inventory.xml',
        'views/master_menu_view.xml',
        'views/assets.xml',
        'views/stock_location_action.xml',
        'views/stock_location_menu.xml',
        'views/stock_location_views.xml',
        'views/res_partner.xml',
        'views/res_users.xml',
        'views/product_template.xml',
        'views/stock_move.xml',
    ],
    'assets': {
        'web.assets_frontend': [
        ],
        'web.assets_backend': [
            'tijari_wms_18/static/src/js/generate_lot_button.js',
            'tijari_wms_18/static/src/xml/generate_lot_button.xml',
            'tijari_wms_18/static/src/xml/auto_input_code.xml'

        ]
    },
    'installable': True,
    'auto_install': False,
    'application': True,
}
