{
    'name': 'Acumatica Temporary Receipt Generator',
    'version': '18.0.1.0.0',
    'summary': 'Temporary WH33 PO Receipt staging generator',
    'category': 'Inventory/Inventory',
    'author': 'Tijari / OpenAI',
    'depends': ['acumatica_all_import'],
    'data': [
        'security/ir.model.access.csv',
        'views/temp_receipt_generator_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
