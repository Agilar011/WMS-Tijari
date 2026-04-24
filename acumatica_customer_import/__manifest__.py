{
    'name': 'Acumatica Customer Import',
    'version': '18.0.1.0.0',
    'summary': 'Import Customer dari Acumatica WMS API ke res.partner Odoo',
    'description': """
        Modul ini menyediakan fitur import Customer dari sistem Acumatica WMS
        ke dalam master data res.partner Odoo.

        Fitur:
        - Konfigurasi koneksi API Acumatica (shared dengan modul UoM jika terinstall)
        - Preview data Customer sebelum di-import
        - Import massal atau selektif
        - Field "to be" di-skip saat import, di-log untuk referensi
        - Log hasil import per baris
    """,
    'category': 'Contacts/Import',
    'author': 'Custom',
    'depends': [
        'base',
        'contacts',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/acumatica_customer_config_views.xml',
        'data/acumatica_customer_config_data.xml',
        'views/acumatica_customer_line_views.xml',
        'wizard/import_customer_wizard_views.xml',
        'views/res_partner_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
