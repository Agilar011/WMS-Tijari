from odoo import api, models, fields

class ProductProduct(models.Model):
    """ Extend of Product_product"""
    _inherit = 'product.product'

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        location_id = self.env.context.get('tijari_ito_source_location_id')
        if (
            not location_id
            or not self.env.context.get('tijari_ito_filter_source_stock')
        ):
            return super().name_search(name, args, operator, limit)

        requested_limit = limit or 100
        candidate_limit = max(requested_limit * 4, 40)
        maximum_candidate_limit = max(candidate_limit, 1000)
        Quant = self.env['stock.quant']

        while True:
            candidates = super().name_search(
                name,
                args,
                operator,
                candidate_limit,
            )
            if not candidates:
                return []

            available_ids = {
                product.id
                for product, available_qty in Quant._read_group(
                    [
                        ('product_id', 'in', [product_id for product_id, _ in candidates]),
                        ('location_id', 'child_of', location_id),
                    ],
                    ['product_id'],
                    ['available_quantity:sum'],
                )
                if available_qty > 0
            }
            available_candidates = [
                candidate
                for candidate in candidates
                if candidate[0] in available_ids
            ]
            if (
                len(available_candidates) >= requested_limit
                or len(candidates) < candidate_limit
                or candidate_limit >= maximum_candidate_limit
            ):
                return available_candidates[:requested_limit]

            candidate_limit = min(candidate_limit * 2, maximum_candidate_limit)

    @api.constrains('barcode')
    def _check_barcode_uniqueness(self):
        """Allow the same barcode to be assigned to multiple products."""
        return

    @api.depends('name', 'default_code', 'product_tmpl_id')
    @api.depends_context(
        'display_default_code',
        'seller_id',
        'company_id',
        'partner_id',
        'lang',
        'tijari_stock_picking_product_code_only',
    )
    def _compute_display_name(self):
        if not self.env.context.get('tijari_stock_picking_product_code_only'):
            return super()._compute_display_name()

        for product in self:
            product.display_name = product.default_code or ''

    adt_external_id = fields.Char(
        string='UUID Acumatica',
        index=True,
        help='ID unik record Stock Item di Acumatica (GUID)',
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

    adt_product_type = fields.Selection([
        ('stock_item', 'Stock Item'),
        ('non_stock_item', 'Non-Stock Item'),
    ], string='Product Type (Acumatica)', help='ItemType dari Acumatica WMS')

    adt_external_id = fields.Char(
        string='UUID Acumatica',
        index=True,
        help='ID unik record Stock Item di Acumatica (GUID)',
    )
    adt_item_class = fields.Char(
        string='Item Class (Acumatica)',
        help='ItemClass dari Acumatica WMS (contoh: ASSET, RAW, FINISH)',
    )
    adt_status = fields.Char(
        string='Item Status (Acumatica)',
        help='ItemStatus dari Acumatica WMS',
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
    adt_acumatica_write_date = fields.Datetime(
        string='Last Modified (Acumatica)',
        help='LastModifiedDateTime dari Acumatica WMS',
    )
