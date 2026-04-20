{
    'name': 'Acumatica Issue Change Item Delivery Import',
    'version': '18.0.1.0.0',
    'summary': 'Import Issue Type Change Item dari Acumatica ke Odoo Delivery Order',
    'description': '''
        Modul untuk menarik data Issue Type Change Item dari Acumatica
        dan mengubahnya menjadi Delivery Order di Odoo.
    ''',
    'category': 'Inventory/Inventory',
    'author': 'Tijari',
    'depends': ['base', 'stock', 'contacts', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'views/acumatica_issue_config_views.xml',
        'views/acumatica_issue_line_views.xml',
        'wizard/import_issue_wizard_views.xml',
        'data/acumatica_issue_config_data.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
