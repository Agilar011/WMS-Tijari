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

    def _get_selected_comparison_records(self):
        records = self.exists()
        if not records:
            records = self.browse(self.env.context.get('active_ids') or []).exists()
        if not records:
            raise UserError(_("Select at least one Inventory Stock Comparison row first."))
        return records

    def _get_consignment_location_context(self, rows):
        """Resolve existing consignment locations and batch-load their source lines."""
        mapping_ids = {
            row['location_mapping_id'][0]
            for row in rows
            if row.get('location_mapping_id')
        }
        mappings = {
            mapping.id: mapping
            for mapping in self.env['stock.location.acumatica'].browse(list(mapping_ids))
        }
        codes_by_row = {}
        candidate_names = set()
        for row in rows:
            mapping_tuple = row.get('location_mapping_id')
            mapping = mappings.get(mapping_tuple[0]) if mapping_tuple else False
            if mapping and mapping.code and mapping.odoo_location_id and row.get('location_id'):
                continue
            raw_code = (row.get('warehouse_code') or '').split(',', 1)[0].strip().upper()
            if not raw_code:
                continue
            consignment_code = raw_code.split('-', 1)[1].strip() if '-' in raw_code else raw_code
            codes_by_row[row['id']] = (raw_code, consignment_code)
            candidate_names.update((raw_code, consignment_code))

        locations = self.env['stock.location'].search([
            ('is_consignment', '=', True),
            ('usage', '=', 'internal'),
            ('name', 'in', list(candidate_names)),
        ]) if candidate_names else self.env['stock.location'].browse()
        locations_by_name = {}
        for location in locations:
            locations_by_name.setdefault(location.name, []).append(location)

        source_codes = {raw_code for raw_code, _suffix in codes_by_row.values()}
        source_lines = self.env['acumatica.warehouse.line'].sudo().search([
            ('warehouse_id', 'in', list(source_codes)),
            ('receiving_location_id', '=ilike', 'CONS'),
        ], order='id desc') if source_codes else self.env['acumatica.warehouse.line'].browse()
        source_line_by_code = {}
        for source_line in source_lines:
            source_line_by_code.setdefault(source_line.warehouse_id.strip().upper(), source_line)

        locations_by_row = {}
        missing_codes = set()
        missing_source_codes = set()
        ambiguous_codes = set()
        for row_id, (raw_code, suffix) in codes_by_row.items():
            destination = False
            ambiguous = False
            for name in dict.fromkeys((raw_code, suffix)):
                candidates = locations_by_name.get(name, [])
                if len(candidates) == 1:
                    destination = candidates[0]
                    break
                if len(candidates) > 1:
                    ambiguous = True
                    break
            if destination:
                locations_by_row[row_id] = destination
            elif ambiguous:
                ambiguous_codes.add(raw_code)
            elif raw_code in source_line_by_code:
                missing_codes.add(raw_code)
            else:
                missing_source_codes.add(raw_code)

        return {
            'mappings': mappings,
            'locations_by_row': locations_by_row,
            'source_line_by_code': source_line_by_code,
            'missing_codes': sorted(missing_codes),
            'missing_source_codes': sorted(missing_source_codes),
            'ambiguous_codes': sorted(ambiguous_codes),
        }

    def _open_missing_consignment_location_wizard(self, records, operation, codes):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Location'),
            'res_model': 'acumatica.inventory.stock.location.confirmation',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_operation': operation,
                'default_comparison_ids': [(6, 0, records.ids)],
                'default_confirmation_message': _(
                    'Lokasi %(codes)s Tidak ditemukan di WMS, jalankan generate location melalui sistem?',
                    codes=', '.join(codes),
                ),
            },
        }

    def action_create_opname(self):
        """Create an opname from the selected comparison rows only."""
        records = self._get_selected_comparison_records()

        rows = records.read([
            'inventory_id', 'description', 'api_on_hand', 'warehouse_code',
            'location_id', 'location_mapping_id',
        ])
        location_context = self._get_consignment_location_context(rows)
        if location_context['ambiguous_codes']:
            raise UserError(_(
                "More than one consignment location matches these codes: %(warehouse_codes)s. Make the location code unique before creating the opname.",
                warehouse_codes=', '.join(location_context['ambiguous_codes']),
            ))
        if location_context['missing_source_codes']:
            raise UserError(_(
                "These locations are not in WMS and have no Consignment source row for automatic generation: %(warehouse_codes)s.",
                warehouse_codes=', '.join(location_context['missing_source_codes']),
            ))
        if location_context['missing_codes']:
            return self._open_missing_consignment_location_wizard(
                records, 'opname', location_context['missing_codes']
            )
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
        missing_location_warehouses = set()
        for row in rows:
            code = row['inventory_id']
            product = code_by_default.get(code) or code_by_barcode.get(code)
            if not product and row['description']:
                product = product_by_name.get(row['description'])
            location = row['location_id']
            location_mapping = row['location_mapping_id']
            mapping = (
                location_context['mappings'].get(location_mapping[0])
                if location_mapping else False
            )
            if mapping and mapping.code and mapping.odoo_location_id and location:
                target_location_id = location[0]
            else:
                consignment_location = location_context['locations_by_row'].get(row['id'])
                target_location_id = consignment_location.id if consignment_location else False
            if not target_location_id:
                missing_location_warehouses.update(
                    warehouse_code.strip()
                    for warehouse_code in (row['warehouse_code'] or '').split(',')
                    if warehouse_code.strip()
                )
            if product and target_location_id:
                opname_rows.append({
                    'product_id': product.id,
                    'location_id': target_location_id,
                    'api_on_hand': row['api_on_hand'] or 0.0,
                })

        if missing_location_warehouses:
            raise UserError(_(
                "Cannot create the opname because these warehouse codes do not have a "
                "valid Odoo location mapping: %(warehouse_codes)s. Resolve the location "
                "mapping first.",
                warehouse_codes=', '.join(sorted(missing_location_warehouses)),
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

    def action_create_inventory(self):
        """Create Direct Receipts from the selected comparison rows only."""
        records = self._get_selected_comparison_records()
        rows = records.read([
            'inventory_id', 'description', 'api_on_hand', 'warehouse_code',
            'location_id', 'location_mapping_id',
        ])
        location_context = self._get_consignment_location_context(rows)
        if location_context['ambiguous_codes']:
            raise UserError(_(
                "More than one consignment location matches these codes: %(warehouse_codes)s. Make the location code unique before creating receipts.",
                warehouse_codes=', '.join(location_context['ambiguous_codes']),
            ))
        if location_context['missing_source_codes']:
            raise UserError(_(
                "These locations are not in WMS and have no Consignment source row for automatic generation: %(warehouse_codes)s.",
                warehouse_codes=', '.join(location_context['missing_source_codes']),
            ))
        if location_context['missing_codes']:
            return self._open_missing_consignment_location_wizard(
                records, 'receipt', location_context['missing_codes']
            )

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

        missing_location_warehouses = set()
        missing_consignment_warehouses = set()
        missing_products = set()
        receipt_lines = []
        for row in rows:
            code = row['inventory_id']
            product = code_by_default.get(code) or code_by_barcode.get(code)
            if not product and row['description']:
                product = product_by_name.get(row['description'])

            quantity = row['api_on_hand'] or 0.0
            if not product:
                if quantity > 0.0:
                    missing_products.add(code or row['description'] or _('Unknown product'))
                continue
            if float_compare(quantity, 0.0, precision_rounding=product.uom_id.rounding) <= 0:
                continue

            mapping_tuple = row['location_mapping_id']
            mapping = location_context['mappings'].get(mapping_tuple[0]) if mapping_tuple else False
            location_tuple = row['location_id']
            if mapping and mapping.code and mapping.odoo_location_id and location_tuple:
                destination = mapping.odoo_location_id
                operation_warehouse_code = mapping.code
            else:
                raw_code = (row['warehouse_code'] or '').split(',', 1)[0].strip().upper()
                destination = location_context['locations_by_row'].get(row['id'])
                if not destination:
                    missing_location_warehouses.add(raw_code or row['warehouse_code'] or '')
                    continue

                location_warehouse = destination.warehouse_id
                operation_warehouse_code = (
                    location_warehouse.code
                    or (raw_code.split('-', 1)[0].strip() if '-' in raw_code else False)
                )
                if not operation_warehouse_code:
                    missing_consignment_warehouses.add(raw_code or destination.display_name)
                    continue

            receipt_lines.append({
                'product': product,
                'quantity': quantity,
                'location': destination,
                'operation_warehouse_code': operation_warehouse_code,
            })

        if missing_location_warehouses:
            raise UserError(_(
                "Cannot resolve these warehouse codes to either a mapped Odoo location or an existing consignment location: %(warehouse_codes)s.",
                warehouse_codes=', '.join(sorted(missing_location_warehouses)),
            ))
        if missing_consignment_warehouses:
            raise UserError(_(
                "Cannot determine the owning warehouse for these consignment locations: %(warehouse_codes)s. Ensure the location code includes the warehouse prefix, for example WH09-C0342.",
                warehouse_codes=', '.join(sorted(missing_consignment_warehouses)),
            ))
        if missing_products:
            raise UserError(_(
                "Cannot create inventory receipts because these products could not be matched to Odoo products: %(products)s.",
                products=', '.join(sorted(missing_products)),
            ))
        if not receipt_lines:
            raise UserError(_(
                "No receipts were created. The current filter has no positive API on-hand quantities."
            ))

        PickingType = self.env['stock.picking.type']
        picking_type_by_code = {}
        for warehouse_code in {line['operation_warehouse_code'] for line in receipt_lines}:
            picking_type_by_code[warehouse_code] = PickingType.resolve_document_only_picking_type(
                target_operation_type='direct_receipt',
                document_only=True,
                warehouse_code=warehouse_code,
                required=True,
            )

        grouped_lines = {}
        for line in receipt_lines:
            picking_type = picking_type_by_code[line['operation_warehouse_code']]
            grouped_lines.setdefault(picking_type.id, {
                'picking_type': picking_type,
                'lines': [],
            })['lines'].append(line)

        supplier_location = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        picking_groups = list(grouped_lines.values())
        picking_vals_list = []
        for group in picking_groups:
            picking_type = group['picking_type']
            source_location = picking_type.default_location_src_id or supplier_location
            header_destination = picking_type.default_location_dest_id
            if not source_location or not header_destination:
                raise UserError(_(
                    "The Direct Receipt operation type %(operation_type)s must have source and header destination locations configured.",
                    operation_type=picking_type.display_name,
                ))
            group['source_location'] = source_location
            company = picking_type.company_id or self.env.company
            picking_vals_list.append({
                'picking_type_id': picking_type.id,
                'location_id': source_location.id,
                'location_dest_id': header_destination.id,
                'partner_id': company.partner_id.id,
                'adt_type': 'Beginning Balance',
                'origin': 'Beginning Balance',
            })

        # Batch-create headers, then batch-create every move across all receipts.
        pickings = self.env['stock.picking'].create(picking_vals_list)
        move_date = fields.Datetime.now()
        move_vals_list = []
        for group, picking in zip(picking_groups, pickings):
            source_location = group['source_location']
            for line in group['lines']:
                product = line['product']
                destination = line['location']
                move_vals_list.append({
                    'name': product.display_name,
                    'product_id': product.id,
                    'product_uom': product.uom_id.id,
                    'product_uom_qty': line['quantity'],
                    'location_id': source_location.id,
                    'location_dest_id': destination.id,
                    'adt_dest_location_id': destination.id,
                    'picking_id': picking.id,
                    'date': move_date,
                })
        self.env['stock.move'].create(move_vals_list)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Created Direct Receipts'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
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
                        mapping.odoo_location_id AS location_id
                    FROM stock_location_acumatica mapping
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

    @api.model
    def _snapshot_product_order(self):
        # Keep the same winner as Product.search(..., limit=1), whose default
        # order is defined by product.product.
        return self.env['product.product']._order

    @api.model
    def _resolve_products(self, inventory_ids, descriptions):
        """Resolve line identities in batches, preserving code-before-name priority."""
        Product = self.env['product.product']
        # Keep False/empty values too: the original exact search also queried
        # default_code=False/barcode=False when a line had no inventory code.
        descriptions = {name for name in descriptions if name}
        code_products = Product.browse()
        if inventory_ids:
            code_products = Product.search([
                '|', ('default_code', 'in', list(inventory_ids)),
                ('barcode', 'in', list(inventory_ids)),
            ], order=self._snapshot_product_order())
        by_code = {}
        for product in code_products:
            by_code.setdefault(product.default_code or False, product)
            by_code.setdefault(product.barcode or False, product)

        code_matches = {code: by_code.get(code) for code in inventory_ids}
        missing_codes = {code for code, product in code_matches.items() if not product}
        name_products = Product.browse()
        if missing_codes and descriptions:
            name_products = Product.search(
                [('name', 'in', list(descriptions))],
                order=self._snapshot_product_order(),
            )
        by_name = {}
        for product in name_products:
            by_name.setdefault(product.name, product)
        return code_matches, by_name

    @api.model
    def _resolved_product_for(self, inventory_id, description, code_matches, by_name):
        return code_matches.get(inventory_id) or by_name.get(description)

    def _search_product_id(self, operator, value):
        """Search candidate SQL-view rows using batched ORM product matching."""
        # Preserve the old fallback for operators other than '='/'=='/'!='.
        if operator in ('=', '==', '!='):
            target_id = int(value) if value not in (False, None, '') else False
        else:
            try:
                target_id = int(str(value))
            except (TypeError, ValueError):
                target_id = -1

        Product = self.env['product.product']
        target = Product.browse(target_id).exists() if target_id else Product.browse()
        if target_id and not target:
            return [('id', 'not in', [])] if operator == '!=' else [('id', 'in', [])]
        if not target_id or not target:
            # Null searches are uncommon; still resolve them with ORM so
            # active_test, access rules, and translated names remain intact.
            self.env.cr.execute(
                f'SELECT id, inventory_id, description FROM {self._table}'
            )
            candidates = self.env.cr.fetchall()
        else:
            candidate_codes = [code for code in (target.default_code, target.barcode) if code]
            candidate_names = [target.name] if target.name else []
            clauses = []
            params = []
            if candidate_codes:
                clauses.append('inventory_id = ANY(%s)')
                params.append(candidate_codes)
            if not target.default_code or not target.barcode:
                clauses.append("(inventory_id IS NULL OR inventory_id = '')")
            if candidate_names:
                clauses.append('description = ANY(%s)')
                params.append(candidate_names)
            if not clauses:
                return [('id', 'in', [])] if operator != '!=' else [('id', 'not in', [])]
            self.env.cr.execute(
                f"SELECT id, inventory_id, description FROM {self._table} WHERE {' OR '.join(clauses)}",
                params,
            )
            candidates = self.env.cr.fetchall()

        if not candidates:
            matching_ids = []
        else:
            code_matches, by_name = self._resolve_products(
                {row[1] for row in candidates}, {row[2] for row in candidates}
            )
            matching_ids = []
            for row_id, inventory_id, description in candidates:
                product = self._resolved_product_for(
                    inventory_id, description, code_matches, by_name
                )
                if (product.id if product else False) == target_id:
                    matching_ids.append(row_id)
        return [
            ('id', 'not in' if operator == '!=' else 'in', matching_ids)
        ]

    def _search_match_status(self, operator, value):
        # Status is dynamic, so calculate it from one batch of view rows and
        # one batch of matching quants. Do not instantiate every view row as an
        # ORM record and trigger per-row lookups while evaluating this domain.
        self.env.cr.execute(f"""
            SELECT id, inventory_id, description, location_id, api_on_hand
              FROM {self._table}
        """)
        rows = self.env.cr.fetchall()
        values = self._compute_snapshot_values(rows)
        if operator == '!=':
            matched_ids = [
                record_id for record_id, snapshot in values.items()
                if snapshot['match_status'] != value
            ]
        else:
            # Preserve the current behavior for all non-equality operators.
            matched_ids = [
                record_id for record_id, snapshot in values.items()
                if snapshot['match_status'] == value
            ]
        return [('id', 'in', matched_ids)]

    @api.model
    def _compute_snapshot_values(self, rows):
        """Calculate snapshot values for tuples (id, code, name, location, API qty)."""
        if not rows:
            return {}
        inventory_ids = {row[1] for row in rows}
        descriptions = {row[2] for row in rows if row[2]}
        code_matches, by_name = self._resolve_products(inventory_ids, descriptions)
        values = {}
        products_by_record = {}
        for record_id, inventory_id, description, location_id, api_on_hand in rows:
            api_on_hand = api_on_hand or 0.0
            product = self._resolved_product_for(
                inventory_id, description, code_matches, by_name
            )
            products_by_record[record_id] = product
            values[record_id] = {
                'product_id': product.id if product else False,
                'odoo_quantity': 0.0,
                'odoo_reserved_quantity': 0.0,
                'odoo_available_quantity': 0.0,
                'difference': api_on_hand,
                'match_status': 'missing_product' if not product else 'missing_location',
            }

        scopes = {}
        for record_id, _inventory_id, _description, location_id, _api_on_hand in rows:
            product = products_by_record[record_id]
            if product and location_id:
                scopes.setdefault((product.id, location_id), []).append(record_id)
        if not scopes:
            return values

        products = {
            product.id: product
            for product in self.env['product.product'].browse(
                sorted({product_id for product_id, _location_id in scopes})
            )
        }
        locations = self.env['stock.location'].browse(
            sorted({location_id for _product_id, location_id in scopes})
        )
        location_paths = {location.id: location.parent_path for location in locations}

        Quant = self.env['stock.quant'].sudo()
        quant_domain = [
            ('product_id', 'in', list(products)),
            ('location_id', 'child_of', list(location_paths)),
        ]

        # Distribute each quant once to each requested ancestor scope. Keep
        # availability buckets by lot because Odoo clamps tracked lot buckets
        # independently, while it clamps an untracked product's total once.
        expiration_cutoff = self.env.context.get('with_expiration')
        if expiration_cutoff:
            expiration_cutoff = fields.Datetime.to_datetime(expiration_cutoff)
        totals = {}
        quant_groupby = ['product_id', 'location_id', 'lot_id']
        if expiration_cutoff:
            quant_groupby.append('expiration_date')
        quant_groups = Quant._read_group(
            quant_domain,
            quant_groupby,
            ['quantity:sum', 'reserved_quantity:sum'],
        )
        for quant_group in quant_groups:
            product, location, lot = quant_group[:3]
            if expiration_cutoff:
                expiration_date, quantity, reserved_quantity = quant_group[3:]
            else:
                quantity, reserved_quantity = quant_group[3:]
            ancestor_ids = location.parent_path.rstrip('/').split('/')
            for ancestor_text in ancestor_ids:
                if not ancestor_text.isdigit():
                    continue
                key = (product.id, int(ancestor_text))
                if key not in scopes:
                    continue
                bucket = totals.setdefault(key, {'reserved': 0.0, 'lots': {}})
                bucket['reserved'] += reserved_quantity or 0.0
                if expiration_cutoff and expiration_date and expiration_date < expiration_cutoff:
                    continue
                lot_id = lot.id or False
                bucket['lots'][lot_id] = bucket['lots'].get(lot_id, 0.0) + (quantity or 0.0) - (reserved_quantity or 0.0)

        api_quantity_by_record = {row[0]: (row[4] or 0.0) for row in rows}
        for (product_id, location_id), records in scopes.items():
            product = products[product_id]
            totals_for_scope = totals.get((product_id, location_id), {'reserved': 0.0, 'lots': {}})
            precision = product.uom_id.rounding if product.uom_id else 0.01
            lot_quantities = list(totals_for_scope['lots'].values())
            if product.tracking == 'none':
                odoo_quantity = sum(lot_quantities)
                if float_compare(odoo_quantity, 0.0, precision_rounding=precision) < 0:
                    odoo_quantity = 0.0
            else:
                odoo_quantity = sum(
                    quantity for quantity in lot_quantities
                    if float_compare(quantity, 0.0, precision_rounding=precision) > 0
                )

            for record_id in records:
                api_on_hand = api_quantity_by_record[record_id]
                values[record_id].update({
                    'odoo_quantity': odoo_quantity,
                    'odoo_reserved_quantity': totals_for_scope['reserved'],
                    'odoo_available_quantity': odoo_quantity - totals_for_scope['reserved'],
                    'difference': api_on_hand - odoo_quantity,
                    'match_status': (
                        'match'
                        if float_compare(api_on_hand, odoo_quantity, precision_rounding=precision) == 0
                        else 'not_match'
                    ),
                })
        return values

    @api.depends('inventory_id', 'warehouse_code', 'description', 'api_on_hand', 'location_id')
    def _compute_snapshot(self):
        rows = [
            (record.id, record.inventory_id, record.description, record.location_id.id, record.api_on_hand)
            for record in self
        ]
        values = self._compute_snapshot_values(rows)
        for record in self:
            snapshot = values[record.id]
            record.product_id = snapshot['product_id']
            record.odoo_quantity = snapshot['odoo_quantity']
            record.odoo_reserved_quantity = snapshot['odoo_reserved_quantity']
            record.odoo_available_quantity = snapshot['odoo_available_quantity']
            record.difference = snapshot['difference']
            record.match_status = snapshot['match_status']


class StockInventory(models.Model):
    _inherit = 'stock.inventory'

    acumatica_stock_comparison_data = fields.Json(copy=False)

    def action_state_to_in_progress(self):
        if not self.env.context.get("skip_inventory_operation_queue"):
            self.ensure_one()
            return self._queue_inventory_operation("begin")
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
