import logging
from time import perf_counter

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class AcumaticaInventoryStockQuant(models.Model):
    """Read-only comparison between aggregated Odoo quants and API stock."""

    _name = 'acumatica.inventory.stock.quant'
    _description = 'Inventory Stock Comparison'
    _auto = False
    _rec_name = 'product_id'
    _order = 'warehouse_code, inventory_id'

    @api.model
    def action_open_generate_wizard(self, *args, **kwargs):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Data Stock ERP',
            'res_model': 'acumatica.inventory.stock.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_opname(self):
        """Create a draft opname from the current comparison search results."""
        domain = self.env.context.get('active_domain') or []
        records = self.search(domain, order='id')
        if not records:
            raise UserError(_("There are no Inventory Stock Comparison rows to create an opname."))

        rows = records.read([
            'inventory_id', 'description', 'api_on_hand', 'location_id',
        ])
        inventory_codes = list({row['inventory_id'] for row in rows if row['inventory_id']})
        descriptions = list({row['description'] for row in rows if row['description']})
        Product = self.env['product.product']
        products_by_code = Product.search([
            '|', ('default_code', 'in', inventory_codes),
            ('barcode', 'in', inventory_codes),
        ], order='id') if inventory_codes else Product.browse()
        products_by_name = Product.search(
            [('name', 'in', descriptions)], order='id'
        ) if descriptions else Product.browse()
        code_by_default = {product.default_code: product for product in products_by_code if product.default_code}
        code_by_barcode = {product.barcode: product for product in products_by_code if product.barcode}
        product_by_name = {product.name: product for product in products_by_name}

        opname_rows = []
        missing_location = 0
        for row in rows:
            code = row['inventory_id']
            product = code_by_default.get(code) or code_by_barcode.get(code)
            if not product and row['description']:
                product = product_by_name.get(row['description'])
            location = row['location_id']
            if not location:
                missing_location += 1
            if product and location:
                opname_rows.append({
                    'product_id': product.id,
                    'location_id': location[0],
                    'api_on_hand': row['api_on_hand'] or 0.0,
                })

        if missing_location:
            raise UserError(_(
                "Cannot create the opname because the current filter contains "
                "%(location_count)s row(s) without a mapped location. Resolve these "
                "comparison rows first.",
                location_count=missing_location,
            ))

        if not opname_rows:
            raise UserError(_(
                "No opname lines could be created. All rows in the current filter "
                "have products that are not matched to Odoo products."
            ))

        products = Product.browse(list({row['product_id'] for row in opname_rows}))
        locations = self.env['stock.location'].browse(
            list({row['location_id'] for row in opname_rows})
        )
        inventory = self.env['stock.inventory'].create({
            'product_selection': 'manual',
            'product_ids': [(6, 0, products.ids)],
            'location_ids': [(6, 0, locations.ids)],
            'exclude_sublocation': True,
            'acumatica_stock_comparison_data': opname_rows,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Opname'),
            'res_model': 'stock.inventory',
            'view_mode': 'form',
            'views': [(self.env.ref('stock_inventory.view_inventory_group_form').id, 'form')],
            'res_id': inventory.id,
            'target': 'current',
        }

    product_id = fields.Many2one(
        'product.product', string='Product', compute='_compute_snapshot', search='_search_product_id',
    )
    location_id = fields.Many2one('stock.location', string='Location')
    location_mapping_id = fields.Many2one('stock.location.acumatica', string='Location Mapping')
    config_id = fields.Many2one('acumatica.config', string='API Configuration')
    warehouse_code = fields.Char(string='Warehouse Code')
    inventory_id = fields.Char(string='InventoryID')
    description = fields.Char(string='Description')
    api_on_hand = fields.Float(string='Stock API')
    api_available = fields.Float(string='Available API')
    source_line_count = fields.Integer(string='Staging Lines')
    sync_date = fields.Datetime(string='Last API Sync')

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
                WITH location_mapping AS (
                    SELECT DISTINCT ON (mapping.code)
                        mapping.code AS warehouse_code,
                        mapping.id AS location_mapping_id,
                        COALESCE(mapping.odoo_location_id, warehouse.lot_stock_id) AS location_id
                    FROM stock_location_acumatica mapping
                    LEFT JOIN stock_warehouse warehouse
                        ON warehouse.id = mapping.odoo_building_id
                    WHERE mapping.active IS TRUE
                      AND mapping.code IS NOT NULL
                    ORDER BY mapping.code, mapping.id
                ), mapped_lines AS (
                    SELECT
                        line.*,
                        mapping.location_mapping_id AS resolved_mapping_id,
                        mapping.location_id,
                        CASE
                            WHEN mapping.location_id IS NOT NULL
                                THEN 'location:' || mapping.location_id::text
                            ELSE 'warehouse:' || line.warehouse_code
                        END AS location_group_key
                    FROM acumatica_inventory_stock_line line
                    LEFT JOIN location_mapping mapping
                        ON mapping.warehouse_code = line.warehouse_code
                    WHERE line.warehouse_code IS NOT NULL
                      AND line.inventory_id IS NOT NULL
                )
                SELECT
                    MIN(line.id) AS id,
                    line.config_id AS config_id,
                    string_agg(DISTINCT line.warehouse_code, ', ' ORDER BY line.warehouse_code) AS warehouse_code,
                    line.inventory_id AS inventory_id,
                    MAX(line.description) AS description,
                    SUM(line.on_hand_acumatica) AS api_on_hand,
                    SUM(line.available) AS api_available,
                    COUNT(line.id) AS source_line_count,
                    MAX(line.sync_date) AS sync_date,
                    line.location_id AS location_id,
                    MIN(line.resolved_mapping_id) AS location_mapping_id
                FROM mapped_lines line
                GROUP BY
                    line.config_id,
                    line.inventory_id,
                    line.location_group_key,
                    line.location_id
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

    def _search_match_status(self, operator, value):
        records = self.search([])
        if operator in ('=', '=='):
            records = records.filtered(lambda record: record.match_status == value)
        elif operator == '!=':
            records = records.filtered(lambda record: record.match_status != value)
        else:
            records = records.filtered(lambda record: record.match_status == value)
        return [('id', 'in', records.ids)]

    @api.depends('inventory_id', 'warehouse_code', 'description', 'api_on_hand', 'location_id')
    def _compute_snapshot(self):
        Quant = self.env['stock.quant'].sudo()
        for record in self:
            product = record._get_product()
            location = record.location_id
            record.product_id = product
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


class StockInventory(models.Model):
    _inherit = 'stock.inventory'

    acumatica_stock_comparison_data = fields.Json(copy=False)

    def action_state_to_in_progress(self):
        started_at = perf_counter()
        inventories = self.filtered('acumatica_stock_comparison_data')
        _logger.info("Inventory adjustment begin inventories=%s comparison_count=%s", self.ids, len(inventories))
        for inventory in inventories:
            phase_started = perf_counter()
            rows = inventory.acumatica_stock_comparison_data or []
            created_count = inventory._ensure_acumatica_stock_comparison_quants()
            _logger.info(
                "Inventory adjustment id=%s phase=ensure_comparison_quants "
                "rows=%s created=%s elapsed=%.3fs",
                inventory.id,
                len(rows),
                created_count,
                perf_counter() - phase_started,
            )

        phase_started = perf_counter()
        result = super().action_state_to_in_progress()
        _logger.info(
            "Inventory adjustment phase=base_begin elapsed=%.3fs",
            perf_counter() - phase_started,
        )
        for inventory in inventories:
            phase_started = perf_counter()
            rows = inventory.acumatica_stock_comparison_data or []
            inventory._apply_acumatica_stock_comparison_counts()
            _logger.info(
                "Inventory adjustment id=%s phase=apply_comparison_counts "
                "rows=%s elapsed=%.3fs",
                inventory.id,
                len(rows),
                perf_counter() - phase_started,
            )
        _logger.info(
            "Inventory adjustment phase=complete inventories=%s total=%.3fs",
            self.ids,
            perf_counter() - started_at,
        )
        return result

    def _ensure_acumatica_stock_comparison_quants(self):
        """Create empty internal quants for API rows with no existing stock."""
        self.ensure_one()
        Quant = self.env['stock.quant'].sudo()
        Product = self.env['product.product'].sudo()
        Location = self.env['stock.location'].sudo()
        rows = self.acumatica_stock_comparison_data or []
        product_ids = {row.get('product_id') for row in rows if row.get('product_id')}
        location_ids = {row.get('location_id') for row in rows if row.get('location_id')}
        products = {product.id: product for product in Product.browse(list(product_ids)).exists()}
        locations = {location.id: location for location in Location.browse(list(location_ids)).exists()}

        valid_rows = [
            (row, products.get(row.get('product_id')), locations.get(row.get('location_id')))
            for row in rows
            if row.get('api_on_hand')
            and products.get(row.get('product_id'))
            and locations.get(row.get('location_id'))
        ]
        if not valid_rows:
            return 0

        scope_product_ids = sorted({product.id for _, product, _ in valid_rows})
        scope_location_ids = sorted({location.id for _, _, location in valid_rows})
        if self.exclude_sublocation:
            location_domain = [('location_id', 'in', scope_location_ids)]
        else:
            location_domain = [('location_id', 'child_of', scope_location_ids)]
        existing_quants = Quant.search([
            ('product_id', 'in', scope_product_ids),
            *location_domain,
        ])
        quants_by_product = {}
        for quant in existing_quants:
            quants_by_product.setdefault(quant.product_id.id, []).append(quant)

        # Keep row order: when parent and child scopes overlap, an earlier row
        # creates the quant that makes a later row's search non-empty.
        planned_locations = {}
        create_vals = []
        for _row, product, location in valid_rows:
            product_quants = quants_by_product.get(product.id, ())
            product_planned_locations = planned_locations.get(product.id, ())
            if self.exclude_sublocation:
                has_quant = any(quant.location_id.id == location.id for quant in product_quants)
                has_planned_quant = any(
                    planned_location.id == location.id
                    for planned_location in product_planned_locations
                )
            else:
                location_path = location.parent_path
                has_quant = any(
                    quant.location_id.parent_path.startswith(location_path)
                    for quant in product_quants
                )
                has_planned_quant = any(
                    planned_location.parent_path.startswith(location_path)
                    for planned_location in product_planned_locations
                )
            if has_quant or has_planned_quant:
                continue
            create_vals.append({
                'product_id': product.id,
                'location_id': location.id,
                'quantity': 0.0,
            })
            planned_locations.setdefault(product.id, []).append(location)

        if create_vals:
            Quant.create(create_vals)
        return len(create_vals)

    def _acumatica_stock_comparison_quant_domain(self, product, location):
        """Match the quant scope used by this inventory adjustment."""
        location_domain = (
            [('location_id', '=', location.id)]
            if self.exclude_sublocation
            else [('location_id', 'child_of', location.id)]
        )
        return [('product_id', '=', product.id)] + location_domain

    def _apply_acumatica_stock_comparison_counts(self):
        self.ensure_one()
        started_at = perf_counter()
        rows = self.acumatica_stock_comparison_data or []
        lookup_started_at = perf_counter()
        # A comparison row for a parent location covers its internal child
        # locations too. Resolve the broadest scopes first so a parent total
        # cannot be added on top of a child total for the same stock.
        candidates = []
        product_ids = {row['product_id'] for row in rows if row.get('product_id')}
        location_ids = {row['location_id'] for row in rows if row.get('location_id')}
        products = {
            product.id: product
            for product in self.env['product.product'].browse(list(product_ids)).exists()
        }
        locations = {
            location.id: location
            for location in self.env['stock.location'].browse(list(location_ids)).exists()
        }
        valid_rows = [
            (row, products.get(row.get('product_id')), locations.get(row.get('location_id')))
            for row in rows
            if products.get(row.get('product_id')) and locations.get(row.get('location_id'))
        ]
        scoped_quants = self.stock_quant_ids if valid_rows else self.env['stock.quant']
        quants_by_product = {}
        for quant in scoped_quants:
            quants_by_product.setdefault(quant.product_id.id, []).append(quant)
        scope_cache = {}

        for row, product, location in valid_rows:
            cache_key = (product.id, location.id)
            quants = scope_cache.get(cache_key)
            if quants is None:
                product_quants = quants_by_product.get(product.id, ())
                if self.exclude_sublocation:
                    quants = self.env['stock.quant'].browse([
                        quant.id for quant in product_quants
                        if quant.location_id.id == location.id
                    ])
                else:
                    location_path = location.parent_path
                    quants = self.env['stock.quant'].browse([
                        quant.id for quant in product_quants
                        if quant.location_id.parent_path.startswith(location_path)
                    ])
                scope_cache[cache_key] = quants
            if not quants:
                if row['api_on_hand']:
                    raise UserError(_(
                        "No stocsumpk quant exists for %(product)s under %(location)s, "
                        "so its Stock API quantity cannot be assigned to an opname quant.",
                        product=product.display_name,
                        location=location.display_name,
                    ))
                continue

            candidates.append({
                'product': product,
                'location': location,
                'quants': quants,
                'api_on_hand': row['api_on_hand'] or 0.0,
            })

        _logger.info(
            "Inventory adjustment id=%s phase=index_comparison_quants rows=%s "
            "products=%s locations=%s quants=%s candidates=%s elapsed=%.3fs",
            self.id,
            len(rows),
            len(products),
            len(locations),
            len(scoped_quants),
            len(candidates),
            perf_counter() - lookup_started_at,
        )

        candidates.sort(key=lambda item: (
            item['location'].parent_path.count('/'),
            -len(item['quants']),
            item['location'].id,
            item['product'].id,
        ))
        assigned_quant_ids = set()
        applied_count = 0
        skipped_overlap_count = 0
        for item in candidates:
            # If this row overlaps a broader row already applied, skip the
            # entire row: its API total may include the same stock, so applying
            # only the remaining quants would still double-count that total.
            if assigned_quant_ids.intersection(item['quants'].ids):
                skipped_overlap_count += 1
                continue
            quants = item['quants']
            assigned_quant_ids.update(quants.ids)
            # The API provides only a product/location total. Put that total on
            # one deterministic quant and count the other quants at zero.
            quants = quants.sorted(key=lambda quant: (-quant.quantity, quant.id))
            quants.write({'inventory_quantity': 0.0})
            quants[:1].inventory_quantity = item['api_on_hand']
            applied_count += 1
        _logger.info(
            "Inventory adjustment id=%s phase=write_comparison_counts rows=%s "
            "candidates=%s applied=%s skipped_overlap=%s total=%.3fs",
            self.id,
            len(rows),
            len(candidates),
            applied_count,
            skipped_overlap_count,
            perf_counter() - started_at,
        )
