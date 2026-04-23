# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime as fDT
from odoo.tools import float_is_zero, float_compare
import hashlib
import base64
from ast import literal_eval

class ProductTemplate(models.Model):
    """
    Extend product.template dengan field-field dari Acumatica Stock Item.
    Semua field baru diprefix 'adt_' untuk menghindari conflict.

    Field standar Odoo yang dipakai langsung (TIDAK perlu dibuat):
      - default_code  → InventoryID
      - name          → Description
      - type          → ItemType  (consu / service)
      - uom_id        → BaseUOM   (Many2one ke uom.uom)
    """
    _inherit = 'product.template'

    adt_external_id = fields.Char(
        string='UUID Acumatica',
        index=True,
        help='ID unik record Stock Item di Acumatica (GUID)',
    )
    adt_item_class = fields.Char(
        string='Item Class (Acumatica)',
        help='ItemClass dari Acumatica WMS (contoh: ASSET, RAW, FINISH)',
    )
    adt_item_status = fields.Selection([
        ('Active',      'Active'),
        ('Inactive',    'Inactive'),
        ('ToDelete',    'To Delete'),
        ('NoSales',     'No Sales'),
        ('NoPurchases', 'No Purchases'),
        ('NoRequest',   'No Request'),
    ],
        string='Item Status (Acumatica)',
        help='ItemStatus dari Acumatica WMS',
    )
    adt_item_type = fields.Char(
        string='Item Type (Acumatica)',
        help='ItemType dari Acumatica WMS (contoh: Finished Good, Non-Stock Item, Service)',
    )
    adt_valuation_method = fields.Selection([
        ('FIFO',     'FIFO'),
        ('Average',  'Average Cost'),
        ('Standard', 'Standard Cost'),
        ('Specific', 'Specific Identification'),
    ],
        string='Valuation Method (Acumatica)',
        help='ValuationMethod dari Acumatica WMS',
    )
    adt_last_modified_datetime = fields.Datetime(
        string='Last Modified (Acumatica)',
        help='LastModifiedDateTime dari Acumatica WMS',
    )

    adt_note           = fields.Text(string='Note (Acumatica)',          help='note dari Acumatica WMS')
    adt_base_unit      = fields.Char(string='Base Unit (Acumatica)',     help='BaseUnit dari Acumatica WMS')
    adt_is_a_kit       = fields.Boolean(string='Is A Kit (Acumatica)',   help='IsAKit dari Acumatica WMS')
    adt_is_kit         = fields.Boolean(string='Is Kit (Acumatica)',     help='IsKit dari Acumatica WMS')
    adt_note_id        = fields.Char(string='Note ID (Acumatica)',       help='NoteID dari Acumatica WMS')
    adt_posting_class  = fields.Char(string='Posting Class (Acumatica)', help='PostingClass dari Acumatica WMS')
    adt_price_class    = fields.Char(string='Price Class (Acumatica)',   help='PriceClass dari Acumatica WMS')
    adt_purchase_unit  = fields.Char(string='Purchase Unit (Acumatica)', help='PurchaseUnit dari Acumatica WMS')
    adt_sales_unit     = fields.Char(string='Sales Unit (Acumatica)',    help='SalesUnit dari Acumatica WMS')
    adt_volume_uom     = fields.Char(string='Volume UOM (Acumatica)',    help='VolumeUOM dari Acumatica WMS')
    adt_weight_uom     = fields.Char(string='Weight UOM (Acumatica)',    help='WeightUOM dari Acumatica WMS')
