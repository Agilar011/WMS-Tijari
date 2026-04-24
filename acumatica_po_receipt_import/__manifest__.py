{
    'name': 'Acumatica Inventory Receipt Import',
    'version': '18.0.1.0.0',
    'summary': 'Import Inventory Receipt dari Acumatica ke Odoo Stock Picking',
    'description': '''
        Modul ini menyediakan fitur import Inventory Receipt dari Acumatica ke Odoo.
        Polanya disamakan dengan modul contoh customer:
        - API configuration
        - Preview line hasil fetch
        - Import massal atau selektif ke stock.picking / stock.move
    ''',
    'category': 'Inventory/Inventory',
    'author': 'Tijari',
    'depends': ['base', 'contacts', 'stock', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'views/acumatica_receipt_config_views.xml',
        'data/acumatica_receipt_config_data.xml',
        'views/acumatica_receipt_line_views.xml',
        'views/import_receipt_wizard_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
