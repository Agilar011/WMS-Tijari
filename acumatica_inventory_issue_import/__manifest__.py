{
    'name': 'Acumatica Inventory Issue Delivery Import',
    'version': '18.0.1.0.0',
    'summary': 'Import Inventory Issue dari Acumatica ke Odoo Delivery Order',
    'description': '''
        Modul untuk menarik data Inventory Issue dari Acumatica
        dan mengubahnya menjadi Delivery Order di Odoo.
    ''',
    'category': 'Inventory/Inventory',
    'author': 'Tijari',
    'depends': ['base', 'stock', 'contacts', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'views/acumatica_inventory_issue_config_views.xml',
        'views/acumatica_inventory_issue_line_views.xml',
        'wizard/import_inventory_issue_wizard_views.xml',
        'data/acumatica_inventory_issue_config_data.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
