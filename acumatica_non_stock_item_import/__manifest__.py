{
    'name':     'Acumatica Non-Stock Item Import',
    'version':  '18.0.1.0.0',
    'summary':  'Import data Non-Stock Item dari Acumatica WMS ke Odoo product.template',
    'category': 'Inventory',
    'author':   'ADT',
    'depends':  ['base', 'product', 'stock', 'acumatica_stock_item_import'],
    'data': [
        'security/ir.model.access.csv',
        'data/acumatica_non_stock_item_config_data.xml',
        'views/acumatica_non_stock_item_config_views.xml',
        'views/acumatica_non_stock_item_line_views.xml',
        'views/import_non_stock_item_wizard_views.xml',
        'views/product_template_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'license':  'LGPL-3',
}
