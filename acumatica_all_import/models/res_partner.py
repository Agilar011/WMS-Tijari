from odoo import models, fields


class ResPartner(models.Model):
    """
    Extend res.partner dengan field-field dari Acumatica.
    Semua field baru diprefix 'adt_' untuk menghindari conflict.

    PENTING: Beberapa nama field sengaja TIDAK menggunakan nama bawaan Odoo:
      - property_stock_supplier  → sudah ada di Odoo (Many2one stock.location)
      - property_stock_customer  → sudah ada di Odoo (Many2one stock.location)
      - property_account_*       → sudah ada di Odoo (Many2one account.account)

    Field standar Odoo yang dipakai langsung (TIDAK perlu dibuat ulang):
      Customer:
        - name              → CustomerName
        - company_registry  → CustomerID
      Vendor:
        - name              → VendorName
        - company_registry  → VendorID
        - comment           → note (internal_notes)
    """
    _inherit = 'res.partner'

    # ══════════════════════════════════════════════════════
    # FIELD BERSAMA (Customer & Vendor)
    # ══════════════════════════════════════════════════════

    adt_external_id = fields.Char(
        string='UUID Acumatica',
        index=True,
        help='ID unik record di Acumatica (GUID)',
    )
    adt_fob_point = fields.Char(
        string='FOB Point (Acumatica)',
        help='FOBPoint dari Acumatica WMS',
    )
    adt_last_modified_datetime = fields.Datetime(
        string='Last Modified (Acumatica)',
        help='LastModifiedDateTime dari Acumatica WMS',
    )

    # ══════════════════════════════════════════════════════
    # FIELD CUSTOMER
    # ══════════════════════════════════════════════════════

    adt_b_account_id = fields.Char(
        string='BAccount ID (Acumatica)',
        help='BAccountID dari Acumatica WMS',
    )
    adt_customer_class = fields.Char(
        string='Customer Class (Acumatica)',
        help='CustomerClass dari Acumatica WMS',
    )
    adt_status = fields.Selection([
        ('Active',     'Active'),
        ('Inactive',   'Inactive'),
        ('Hold',       'Hold'),
        ('CreditHold', 'Credit Hold'),
        ('OneTime',    'One Time'),
    ],
        string='Status Customer (Acumatica)',
        help='Status Customer di Acumatica WMS',
    )
    adt_currency_id = fields.Char(
        string='Currency ID (Acumatica)',
        help='CurrencyID dari Acumatica WMS',
    )
    adt_warehouse_id = fields.Char(
        string='Warehouse ID (Acumatica)',
        help='WarehouseID dari Acumatica WMS',
    )
    adt_shipping_zone_id = fields.Char(
        string='Shipping Zone ID (Acumatica)',
        help='ShippingZoneID dari Acumatica WMS',
    )
    adt_created_datetime = fields.Datetime(
        string='Created Date (Acumatica)',
        help='CreatedDateTime dari Acumatica WMS',
    )
    adt_note_id = fields.Char(
        string='Note ID (Acumatica)',
        help='NoteID UUID dari Acumatica WMS',
    )
    adt_note = fields.Text(
        string='Note (Acumatica)',
        help='Note/keterangan dari Acumatica WMS',
    )

    # ══════════════════════════════════════════════════════
    # FIELD VENDOR
    # ══════════════════════════════════════════════════════

    adt_vendor_state = fields.Selection([
        ('Active',   'Active'),
        ('Inactive', 'Inactive'),
        ('Hold',     'Hold'),
        ('OneTime',  'One Time'),
    ],
        string='Status Vendor (Acumatica)',
        help='Status Vendor di Acumatica WMS',
    )
    adt_class = fields.Char(
        string='Vendor Class (Acumatica)',
        help='VendorClass dari Acumatica WMS',
    )
    adt_lead_time_days = fields.Integer(
        string='Lead Time Days (Acumatica)',
        help='LeadTimedays dari Acumatica WMS',
    )

    # customer_rank = fields.Integer(
    #     string='Customer Rank',
    #     help='Used to prioritize customers during import (lower is higher priority)',
    # )