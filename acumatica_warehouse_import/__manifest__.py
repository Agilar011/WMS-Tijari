{
    'name': 'Acumatica Warehouse Import',
    'version': '18.0.1.0.0',
    'summary': 'Import Warehouse & Location dari Acumatica WMS API ke Odoo',
    'description': """
        Modul ini menyediakan fitur import Warehouse (Header) dan Locations (Detail)
        dari sistem Acumatica WMS ke dalam stock.warehouse dan stock.location Odoo.

        Fitur:
        - Import Warehouse → stock.warehouse (Header)
        - Import Locations → stock.location (Detail, child dari warehouse)
        - Field "to be" disimpan ke adt_* di stock.warehouse & stock.location
        - Preview & seleksi sebelum import
        - Log hasil import per baris
    """,
    'category': 'Inventory/Configuration',
    'author': 'Custom',
    'depends': [
        'base',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/acumatica_warehouse_config_views.xml',
        'data/acumatica_warehouse_config_data.xml',
        'views/acumatica_warehouse_line_views.xml',
        'wizard/import_warehouse_wizard_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
