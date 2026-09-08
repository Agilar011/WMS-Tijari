from odoo import api, fields, models, tools
from odoo.tools import float_compare


class AcumaticaInventoryStockQuant(models.Model):
    """Read-only comparison between aggregated Odoo quants and API stock."""

    _name = 'acumatica.inventory.stock.quant'
    _description = 'Inventory Stock Comparison'
    _auto = False
    _rec_name = 'product_id'
    _order = 'warehouse_code, inventory_id'

    product_id = fields.Many2one(
        'product.product', string='Product', compute='_compute_snapshot', search='_search_product_id',
    )
    location_id = fields.Many2one(
        'stock.location', string='Location', compute='_compute_snapshot', search='_search_location_id',
    )
    location_mapping_id = fields.Many2one(
        'stock.location.acumatica', string='Location Mapping', compute='_compute_snapshot',
    )
    config_id = fields.Many2one('acumatica.config', string='API Configuration', readonly=True)
    warehouse_code = fields.Char(string='Warehouse Code', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    api_on_hand = fields.Float(string='Stock API', readonly=True)
    api_available = fields.Float(string='Available API', readonly=True)
    source_line_count = fields.Integer(string='Staging Lines', readonly=True)
    sync_date = fields.Datetime(string='Last API Sync', readonly=True)

    odoo_quantity = fields.Float(string='On Hand Odoo', compute='_compute_snapshot')
    odoo_reserved_quantity = fields.Float(string='Reserved Odoo', compute='_compute_snapshot')
    odoo_available_quantity = fields.Float(string='Available Odoo', compute='_compute_snapshot')
    difference = fields.Float(string='Difference', compute='_compute_snapshot')
    match_status = fields.Selection([
        ('match', 'Match'),
        ('not_match', 'Unmatch'),
        ('missing_product', 'Missing Product'),
        ('missing_location', 'Missing Location'),
    ], string='Match Status', compute='_compute_snapshot', search='_search_match_status')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(line.id) AS id,
                    line.config_id AS config_id,
                    line.warehouse_code AS warehouse_code,
                    line.inventory_id AS inventory_id,
                    MAX(line.description) AS description,
                    SUM(line.on_hand_acumatica) AS api_on_hand,
                    SUM(line.available) AS api_available,
                    COUNT(line.id) AS source_line_count,
                    MAX(line.sync_date) AS sync_date
                FROM acumatica_inventory_stock_line line
                WHERE line.warehouse_code IS NOT NULL
                  AND line.inventory_id IS NOT NULL
                GROUP BY line.config_id, line.warehouse_code, line.inventory_id
            )
        """)

    def _get_product(self):
        self.ensure_one()
        Product = self.env['product.product']
        product = Product.search([
            '|',
            ('default_code', '=', self.inventory_id),
            ('barcode', '=', self.inventory_id),
        ], limit=1)
        if not product and self.description:
            product = Product.search([('name', '=', self.description)], limit=1)
        return product

    def _get_location(self):
        self.ensure_one()
        mapping = self.env['stock.location.acumatica'].search([
            ('code', '=', self.warehouse_code),
            ('active', '=', True),
        ], limit=1)
        if mapping.odoo_location_id:
            return mapping, mapping.odoo_location_id
        if mapping.odoo_building_id and mapping.odoo_building_id.lot_stock_id:
            return mapping, mapping.odoo_building_id.lot_stock_id
        return mapping, self.env['stock.location'].browse()

    def _search_snapshot_value(self, field_name, operator, value):
        records = self.search([])
        if operator in ('=', '=='):
            records = records.filtered(lambda record: record[field_name].id == value)
        elif operator == '!=':
            records = records.filtered(lambda record: record[field_name].id != value)
        else:
            records = records.filtered(lambda record: str(record[field_name].id) == str(value))
        return [('id', 'in', records.ids)]

    def _search_product_id(self, operator, value):
        return self._search_snapshot_value('product_id', operator, value)

    def _search_location_id(self, operator, value):
        return self._search_snapshot_value('location_id', operator, value)

    def _search_match_status(self, operator, value):
        records = self.search([])
        if operator in ('=', '=='):
            records = records.filtered(lambda record: record.match_status == value)
        elif operator == '!=':
            records = records.filtered(lambda record: record.match_status != value)
        else:
            records = records.filtered(lambda record: record.match_status == value)
        return [('id', 'in', records.ids)]

    @api.depends('inventory_id', 'warehouse_code', 'description', 'api_on_hand')
    def _compute_snapshot(self):
        Quant = self.env['stock.quant'].sudo()
        for record in self:
            product = record._get_product()
            mapping, location = record._get_location()
            record.product_id = product
            record.location_id = location
            record.location_mapping_id = mapping
            record.odoo_quantity = 0.0
            record.odoo_reserved_quantity = 0.0
            record.odoo_available_quantity = 0.0
            record.difference = record.api_on_hand

            if not product:
                record.match_status = 'missing_product'
                continue
            if not location:
                record.match_status = 'missing_location'
                continue

            record.odoo_quantity = Quant._get_available_quantity(product, location, strict=False)
            quants = Quant.search([
                ('product_id', '=', product.id),
                ('location_id', 'child_of', location.id),
            ])
            record.odoo_reserved_quantity = sum(quants.mapped('reserved_quantity'))
            record.odoo_available_quantity = record.odoo_quantity - record.odoo_reserved_quantity
            record.difference = record.api_on_hand - record.odoo_quantity
            precision = product.uom_id.rounding if product.uom_id else 0.01
            record.match_status = (
                'match'
                if float_compare(record.api_on_hand, record.odoo_quantity, precision_rounding=precision) == 0
                else 'not_match'
            )
