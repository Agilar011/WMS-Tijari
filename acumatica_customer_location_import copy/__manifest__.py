{
    'name':     'Acumatica Master Data Module',
    'version':  '18.0.1.0.0',
    'summary':  'master data import dari Acumatica ke Odoo',
    'category': 'Inventory, Master Data, Transaction',
    'author':   'Tijari',
    'depends':  ['base', 'stock', 'acumatica_customer_import'],
    'data': [
        'security/ir.model.access.csv',
        'data/acumatica_customer_location_config_data.xml',
        'views/acumatica_customer_location_config_views.xml',
        'views/acumatica_customer_location_views.xml',
        'views/import_customer_location_wizard_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'license':  'LGPL-3',
}
