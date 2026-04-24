{
    'name': 'Acumatica UoM Import',
    'version': '18.0.1.0.0',
    'summary': 'Import Units of Measure dari Acumatica WMS API',
    'description': """
        Modul ini menyediakan fitur import Unit of Measure (UoM)
        dari sistem Acumatica WMS ke dalam Odoo secara otomatis.

        Fitur:
        - Konfigurasi koneksi API Acumatica
        - Preview data UoM sebelum di-import
        - Import massal atau selektif
        - Log hasil import
    """,
    'category': 'Inventory/Configuration',
    'author': 'Custom',
    'depends': [
        'base',
        'uom',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/acumatica_config_views.xml',
        'data/acumatica_config_data.xml',
        'views/acumatica_uom_import_views.xml',
        'wizard/import_uom_wizard_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
