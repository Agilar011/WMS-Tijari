{
    'name':        'Acumatica Vendor Import',
    'version':     '18.0.1.0.0',
    'summary':     'Import data Vendor dari Acumatica WMS ke Odoo res.partner',
    'category':    'Inventory',
    'author':      'ADT',
    'depends':     ['base', 'stock', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'data/acumatica_vendor_config_data.xml',
        'views/acumatica_vendor_config_views.xml',
        'views/acumatica_vendor_line_views.xml',
        'views/import_vendor_wizard_views.xml',
        'views/res_partner_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'license':     'LGPL-3',
}