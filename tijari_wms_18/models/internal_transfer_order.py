from odoo import api, fields, models
from odoo.exceptions import ValidationError


class InternalTransferOrder(models.Model):
    _name = 'internal.transfer.order'
    _description = 'Internal Transfer Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'schedule_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    external_ref = fields.Char(
        string='External Ref',
        copy=False,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('ready', 'Ready'),
            ('done', 'Done'),
            ('cancel', 'Canceled'),
        ],
        string='Status',
        default='draft',
        copy=False,
        tracking=True,
    )
    transaction_type = fields.Selection(
        selection=[
            ('inter_warehouse', 'Inter Warehouse'),
            ('intra_warehouse', 'Intra Warehouse'),
            ('consignment', 'Consignment'),
            ('vendor_return', 'Vendor Return'),
        ],
        string='Transaction Type',
        default='inter_warehouse',
        tracking=True,
    )
    transfer_type = fields.Selection(
        selection=[
            ('transfer_in', 'Transfer IN'),
            ('transfer_out', 'Transfer OUT'),
        ],
        string='Transfer Type',
        default='transfer_out',
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Contact',
        tracking=True,
    )
    location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Source Location',
        tracking=True,
    )
    location_dest_id = fields.Many2one(
        comodel_name='stock.location',
        string='Destination Location',
        tracking=True,
    )
    transit_location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Transit Location',
        domain=[('usage', '=', 'transit')],
        tracking=True,
    )
    schedule_date = fields.Datetime(
        string='Schedule Date',
        default=fields.Datetime.now,
        tracking=True,
    )
    validation_policy = fields.Selection(
        selection=[
            ('validate_all', 'Validate All'),
            ('double_validate', 'Double Validate'),
        ],
        string='Validation Policy',
        default='validate_all',
        required=True,
        tracking=True,
    )
    move_ids = fields.One2many(
        comodel_name='stock.move',
        inverse_name='internal_transfer_order_id',
        string='Operations',
        copy=True,
    )
    generated_move_ids = fields.Many2many(
        comodel_name='stock.move',
        string='Generated Operations',
        compute='_compute_generated_move_ids',
    )
    picking_ids = fields.Many2many(
        comodel_name='stock.picking',
        relation='internal_transfer_order_stock_picking_rel',
        column1='internal_transfer_order_id',
        column2='picking_id',
        string='Transfers',
        copy=False,
        readonly=True,
    )
    picking_count = fields.Integer(
        string='Transfer Count',
        compute='_compute_picking_count',
    )
    note = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            if order.name == 'New':
                order.name = 'ITO/%05d' % order.id
        return orders

    @api.depends('picking_ids')
    def _compute_picking_count(self):
        for order in self:
            order.picking_count = len(order._get_related_pickings())

    @api.depends('picking_ids.move_ids')
    def _compute_generated_move_ids(self):
        for order in self:
            order.generated_move_ids = order._get_related_pickings().move_ids

    def _get_related_pickings(self):
        self.ensure_one()
        pickings = self.picking_ids
        if self.id:
            pickings |= self.env['stock.picking'].search([
                ('internal_transfer_order_id', '=', self.id),
            ])
        return pickings

    def _get_vendor_return_receipt_picking(self):
        self.ensure_one()
        if self.transaction_type != 'vendor_return':
            return self.env['stock.picking']
        return self._get_related_pickings().filtered(
            lambda picking: picking.internal_transfer_leg == 'receipt'
        )[:1]

    @api.onchange('location_id', 'location_dest_id')
    def _onchange_locations(self):
        for order in self:
            for move in order.move_ids:
                move.location_id = order.location_id
                move.location_dest_id = order.location_dest_id

    def _location_belongs_to(self, location, parent_location):
        if not location or not parent_location:
            return False
        return location == parent_location or (
            location.parent_path
            and parent_location.parent_path
            and location.parent_path.startswith(parent_location.parent_path)
        )

    def _get_source_warehouse(self):
        self.ensure_one()
        warehouses = self.env['stock.warehouse'].search([])
        return warehouses.filtered(
            lambda warehouse: self._location_belongs_to(
                self.location_id, warehouse.lot_stock_id
            ) or self._location_belongs_to(
                self.location_id, warehouse.view_location_id
            )
        )[:1]

    def _get_picking_type(self, name=False, operation_category=False, code='internal'):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        domain = [('code', '=', code)]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        if name:
            domain.append(('name', '=', name))
        if operation_category:
            domain.append(('operation_category', '=', operation_category))

        picking_type = self.env['stock.picking.type'].search(domain, limit=1)
        if picking_type:
            return picking_type

        fallback_domain = [('code', '=', code)]
        if warehouse:
            fallback_domain.append(('warehouse_id', '=', warehouse.id))
        return self.env['stock.picking.type'].search(fallback_domain, limit=1)

    def _get_internal_picking_type(self):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        domain = [
            ('code', '=', 'internal'),
            ('is_default_api', '=', True),
        ]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        picking_type = self.env['stock.picking.type'].search(domain, limit=1)
        if not picking_type:
            picking_type = self._get_picking_type()
        return picking_type

    def _get_receipt_internal_picking_type(self):
        self.ensure_one()
        return self._get_required_picking_type(
            'Receipt Internal',
            'internal',
        )

    def _get_vendor_return_receipt_picking_type(self):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        domain = [
            ('code', '=', 'internal'),
            ('name', '=', 'Receipt Internal'),
        ]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        picking_type = self.env['stock.picking.type'].search(domain, limit=1)
        if picking_type:
            return picking_type

        warehouse_code = warehouse.code if warehouse else False
        picking_type = self.env['stock.picking.type'].resolve_document_only_picking_type(
            target_operation_type='direct_receipt',
            api_acumatica='vendor_return',
            document_only=True,
            warehouse_code=warehouse_code,
        )
        if picking_type:
            return picking_type

        incoming_domain = [('code', '=', 'incoming')]
        if warehouse:
            incoming_domain.append(('warehouse_id', '=', warehouse.id))
        picking_type = self.env['stock.picking.type'].search(incoming_domain, limit=1)
        if not picking_type:
            raise ValidationError(
                'Operation type penerimaan Vendor Return belum dikonfigurasi.'
            )
        return picking_type

    def _get_vendor_return_direct_delivery_picking_type(self):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        warehouse_code = warehouse.code if warehouse else False
        return self.env['stock.picking.type'].resolve_document_only_picking_type(
            target_operation_type='direct_delivery_order',
            api_acumatica='vendor_return',
            document_only=True,
            warehouse_code=warehouse_code,
            required=True,
        )

    def _get_required_picking_type(self, name, operation_category=False):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        domain = [
            ('code', '=', 'internal'),
            ('name', '=', name),
        ]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        if operation_category:
            domain.append(('operation_category', '=', operation_category))
        picking_type = self.env['stock.picking.type'].search(domain, limit=1)
        if not picking_type:
            raise ValidationError(
                'Operation type %s belum dikonfigurasi.' % name
            )
        return picking_type

    def _get_or_create_transit_location(self):
        transit_location = self.transit_location_id or self.env['stock.location'].search([
            ('usage', '=', 'transit'),
        ], limit=1)
        if not transit_location:
            transit_location = self.env['stock.location'].create({
                'name': 'Transit',
                'usage': 'transit',
            })
        return transit_location

    def _get_or_create_packing_zone_location(self):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        parent_location = warehouse.lot_stock_id if warehouse else self.location_id
        packing_zone = self.env['stock.location'].search([
            ('location_id', '=', parent_location.id),
            ('name', '=', 'Packing Zone'),
        ], limit=1)
        if not packing_zone:
            packing_zone = self.env['stock.location'].create({
                'name': 'Packing Zone',
                'usage': 'internal',
                'location_id': parent_location.id,
                'company_id': parent_location.company_id.id,
            })
        return packing_zone

    def _get_or_create_loading_dock_location(self):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        parent_location = warehouse.lot_stock_id if warehouse else self.location_id
        loading_dock = self.env['stock.location'].search([
            ('location_id', '=', parent_location.id),
            ('name', '=', 'Loading Dock'),
        ], limit=1)
        if not loading_dock:
            loading_dock = self.env['stock.location'].create({
                'name': 'Loading Dock',
                'usage': 'internal',
                'location_id': parent_location.id,
                'company_id': parent_location.company_id.id,
            })
        return loading_dock

    def _prepare_picking_vals(self, picking_type, location, location_dest, suffix, leg):
        self.ensure_one()
        vals = {
            'picking_type_id': picking_type.id,
            'scheduled_date': self.schedule_date,
            'origin': self._get_picking_origin(leg),
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'adt_type': self._get_picking_adt_type(),
            'adt_external_ref': self.external_ref or self.name,
            'internal_transfer_order_id': self.id,
            'internal_transfer_leg': leg,
            'internal_transfer_sequence': self._get_transfer_leg_sequence(leg),
        }
        partner = self._get_picking_partner(leg)
        if partner:
            vals['partner_id'] = partner.id
        dest_location = self._get_picking_mapped_dest_location(leg)
        if dest_location:
            vals['adt_dest_location_id'] = dest_location.id
        return vals

    def _get_picking_origin(self, leg):
        self.ensure_one()
        return self.external_ref or self.name

    def _get_transfer_leg_sequence(self, leg):
        self.ensure_one()
        if self.transfer_type == 'transfer_in':
            return {
                'delivery': 10,
                'receipt': 20,
                'pick': 30,
                'pack': 40,
            }.get(leg, 99)
        return {
            'pick': 10,
            'pack': 20,
            'delivery': 30,
            'receipt': 40,
        }.get(leg, 99)

    def _get_picking_adt_type(self):
        self.ensure_one()
        if self.transaction_type == 'consignment':
            return 'Shipment Consignment'
        if self.transaction_type == 'vendor_return':
            return 'Vendor Return'
        return 'Internal Transfer'

    def _get_picking_mapped_dest_location(self, leg):
        self.ensure_one()
        if leg == 'receipt':
            return self.location_dest_id
        return self.env['stock.location']

    def _get_warehouse_partner(self):
        self.ensure_one()
        warehouse = self._get_source_warehouse()
        if not warehouse:
            return self.env.company.partner_id

        company_partner = warehouse.company_id.partner_id or self.env.company.partner_id
        if warehouse.partner_id and warehouse.partner_id != company_partner:
            return warehouse.partner_id

        partner_name = '%s (%s)' % (warehouse.name, warehouse.code)
        partner = self.env['res.partner'].search([
            ('name', '=', partner_name),
            ('parent_id', '=', False),
        ], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': partner_name,
                'type': 'delivery',
                'company_id': warehouse.company_id.id,
            })
        warehouse.partner_id = partner.id
        return partner

    def _get_picking_partner(self, leg):
        self.ensure_one()
        if self.transaction_type not in ('consignment', 'vendor_return'):
            return self.env['res.partner']
        if leg == 'receipt':
            return self._get_warehouse_partner()
        return self.partner_id

    def _copy_move_to_picking(self, source_move, picking, location, location_dest):
        vals = {
            'name': source_move.name or source_move.product_id.display_name,
            'product_id': source_move.product_id.id,
            'product_uom_qty': source_move.product_uom_qty,
            'product_uom': source_move.product_uom.id,
            'picking_id': picking.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'adt_inventory_id': source_move.adt_inventory_id,
            'adt_line_nbr': source_move.adt_line_nbr,
            'adt_line_type': source_move.adt_line_type,
            'adt_transfer_order_line_number': source_move.adt_transfer_order_line_number,
            'adt_transfer_order_number': source_move.adt_transfer_order_number,
            'adt_transfer_order_type': source_move.adt_transfer_order_type,
            'adt_from_location_code': source_move.adt_from_location_code,
            'adt_to_location_code': source_move.adt_to_location_code,
            'adt_quantity': source_move.adt_quantity,
            'adt_type': source_move.adt_type,
            'product_note': source_move.product_note,
        }
        if picking.internal_transfer_leg == 'receipt' and picking.adt_dest_location_id:
            vals['adt_dest_location_id'] = picking.adt_dest_location_id.id
        return self.env['stock.move'].create(vals)

    def _get_move_match_key(self, move):
        return (
            move.product_id.id,
            move.adt_line_nbr,
            move.adt_transfer_order_line_number,
            move.adt_inventory_id,
            move.adt_transfer_order_number,
        )

    def _link_picking_moves(self, previous_picking, next_picking):
        self.ensure_one()
        if not previous_picking or not next_picking:
            return

        previous_moves_by_key = {
            self._get_move_match_key(move): move
            for move in previous_picking.move_ids
        }
        for next_move in next_picking.move_ids:
            previous_move = previous_moves_by_key.get(
                self._get_move_match_key(next_move)
            )
            if previous_move:
                previous_move.move_dest_ids = [(4, next_move.id)]

        unlinked_next_moves = next_picking.move_ids.filtered(
            lambda move: not move.move_orig_ids.filtered(
                lambda original: original.picking_id == previous_picking
            )
        )
        for product in unlinked_next_moves.product_id:
            previous_moves = previous_picking.move_ids.filtered(
                lambda move: move.product_id == product
            ).sorted('id')
            next_moves = unlinked_next_moves.filtered(
                lambda move: move.product_id == product
            ).sorted('id')
            for previous_move, next_move in zip(previous_moves, next_moves):
                previous_move.move_dest_ids = [(4, next_move.id)]

    def _create_transfer_picking(
        self, picking_type, location, location_dest, suffix, leg,
        previous_picking=False,
    ):
        self.ensure_one()
        picking = self.env['stock.picking'].create(self._prepare_picking_vals(
            picking_type,
            location,
            location_dest,
            suffix,
            leg,
        ))
        for move in self.move_ids:
            self._copy_move_to_picking(
                move,
                picking,
                location,
                location_dest,
            )
        self._link_picking_moves(previous_picking, picking)
        self.picking_ids = [(4, picking.id)]
        return picking

    def _adopt_next_picking(self, done_picking, suffix, leg):
        self.ensure_one()
        next_picking = done_picking.move_ids.move_dest_ids.picking_id.filtered(
            lambda picking: picking.state != 'cancel'
        )[:1]
        if not next_picking:
            return False

        vals = {
            'origin': self._get_picking_origin(leg),
            'adt_type': self._get_picking_adt_type(),
            'adt_external_ref': self.external_ref or self.name,
            'internal_transfer_order_id': self.id,
            'internal_transfer_leg': leg,
            'internal_transfer_sequence': self._get_transfer_leg_sequence(leg),
        }
        partner = self._get_picking_partner(leg)
        vals['partner_id'] = partner.id if partner else False
        dest_location = self._get_picking_mapped_dest_location(leg)
        vals['adt_dest_location_id'] = dest_location.id if dest_location else False
        next_picking.write(vals)
        if leg == 'receipt' and next_picking.adt_dest_location_id:
            next_picking.move_ids.write({
                'adt_dest_location_id': next_picking.adt_dest_location_id.id,
            })
        self.picking_ids = [(4, next_picking.id)]
        return next_picking

    def _generate_next_staged_picking(self, done_picking):
        self.ensure_one()
        if self.transaction_type == 'intra_warehouse':
            return False

        existing_legs = set(self.picking_ids.mapped('internal_transfer_leg'))
        if done_picking.internal_transfer_leg == 'pick' and 'pack' not in existing_legs:
            route_picking = self._adopt_next_picking(done_picking, 'Pack', 'pack')
            if route_picking:
                return route_picking

            packing_zone = self._get_or_create_packing_zone_location()
            loading_dock = self._get_or_create_loading_dock_location()
            return self._create_transfer_picking(
                self._get_required_picking_type('Pack Internal', 'pack'),
                packing_zone,
                loading_dock,
                'Pack',
                'pack',
                previous_picking=done_picking,
            )
        if done_picking.internal_transfer_leg == 'pack' and 'delivery' not in existing_legs:
            route_picking = self._adopt_next_picking(
                done_picking,
                'Transfer OUT',
                'delivery',
            )
            if route_picking:
                receipt_picking = self.picking_ids.filtered(
                    lambda picking: picking.internal_transfer_leg == 'receipt'
                )[:1]
                self._link_picking_moves(route_picking, receipt_picking)
                return route_picking

            loading_dock = self._get_or_create_loading_dock_location()
            transit_location = self._get_or_create_transit_location()
            if not self.transit_location_id:
                self.transit_location_id = transit_location
            delivery_picking = self._create_transfer_picking(
                self._get_required_picking_type('Transfer Internal', 'internal'),
                loading_dock,
                transit_location,
                'Transfer OUT',
                'delivery',
                previous_picking=done_picking,
            )
            receipt_picking = self.picking_ids.filtered(
                lambda picking: picking.internal_transfer_leg == 'receipt'
            )[:1]
            self._link_picking_moves(delivery_picking, receipt_picking)
            return delivery_picking
        return False

    def action_generate_internal_pickings(self):
        for order in self:
            if order._get_related_pickings():
                continue

            if not order.location_id or not order.location_dest_id:
                raise ValidationError(
                    'Source Location dan Destination Location harus diisi.'
                )
            transit_location = order._get_or_create_transit_location()
            if not order.transit_location_id:
                order.transit_location_id = transit_location
            if not order.move_ids:
                raise ValidationError('Operation line belum diisi.')

            if order.transaction_type == 'vendor_return':
                receipt_picking_type = order._get_vendor_return_receipt_picking_type()
                picking_specs = [
                    (
                        order._get_vendor_return_direct_delivery_picking_type(),
                        order.location_id,
                        transit_location,
                        'Direct Delivery',
                        'delivery',
                    ),
                    (
                        receipt_picking_type,
                        transit_location,
                        order.location_dest_id,
                        'Transfer IN',
                        'receipt',
                    ),
                ]
            elif order.transaction_type == 'intra_warehouse':
                receipt_picking_type = order._get_receipt_internal_picking_type()
                if not receipt_picking_type:
                    raise ValidationError(
                        'Operation type Receipt Internal belum dikonfigurasi.'
                    )
                picking_specs = [
                    (
                        order._get_required_picking_type('Pick Internal', 'pick'),
                        order.location_id,
                        transit_location,
                        'Pick',
                        'pick',
                    ),
                    (
                        receipt_picking_type,
                        transit_location,
                        order.location_dest_id,
                        'Transfer IN',
                        'receipt',
                    ),
                ]
            elif order.transfer_type == 'transfer_in':
                receipt_picking_type = order._get_receipt_internal_picking_type()
                if not receipt_picking_type:
                    raise ValidationError(
                        'Operation type Receipt Internal belum dikonfigurasi.'
                    )
                picking_specs = [
                    (
                        order._get_required_picking_type('Transfer Internal', 'internal'),
                        order.location_id,
                        transit_location,
                        'Transfer OUT',
                        'delivery',
                    ),
                    (
                        receipt_picking_type,
                        transit_location,
                        order.location_dest_id,
                        'Transfer IN',
                        'receipt',
                    ),
                ]
            else:
                receipt_picking_type = order._get_receipt_internal_picking_type()
                if not receipt_picking_type:
                    raise ValidationError(
                        'Operation type Receipt Internal belum dikonfigurasi.'
                    )
                packing_zone = order._get_or_create_packing_zone_location()
                picking_specs = [
                    (
                        order._get_required_picking_type('Pick Internal', 'pick'),
                        order.location_id,
                        packing_zone,
                        'Pick',
                        'pick',
                    ),
                    (
                        receipt_picking_type,
                        transit_location,
                        order.location_dest_id,
                        'Transfer IN',
                        'receipt',
                    ),
                ]

            pickings = self.env['stock.picking']
            for picking_type, location, location_dest, suffix, leg in picking_specs:
                pickings |= order._create_transfer_picking(
                    picking_type,
                    location,
                    location_dest,
                    suffix,
                    leg,
                )
            order.picking_ids = [(6, 0, pickings.ids)]
            order.state = 'ready'

        return True

    def action_ready(self):
        orders_to_generate = self.filtered(lambda order: not order._get_related_pickings())
        if orders_to_generate:
            orders_to_generate.action_generate_internal_pickings()
        existing_orders = self - orders_to_generate
        if existing_orders:
            existing_orders.write({'state': 'ready'})
        return True

    def action_done(self):
        for order in self:
            related_pickings = order._get_related_pickings()
            if not related_pickings:
                raise ValidationError(
                    'Transfer belum dibuat. Set Ready terlebih dahulu untuk generate transfer.'
                )
            pending_pickings = related_pickings.filtered(
                lambda picking: picking.state != 'done'
            )
            if pending_pickings:
                raise ValidationError(
                    'Internal Transfer Order belum bisa Done sebelum semua transfer selesai.'
                )
        self.write({'state': 'done'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_pickings(self):
        self.ensure_one()
        pickings = self._get_related_pickings()
        action = self.env['ir.actions.actions']._for_xml_id(
            'stock.action_picking_tree_all'
        )
        action['domain'] = [('id', 'in', pickings.ids)]
        action['context'] = {'create': False}
        return action


class StockMove(models.Model):
    _inherit = 'stock.move'

    internal_transfer_order_id = fields.Many2one(
        comodel_name='internal.transfer.order',
        string='Internal Transfer Order',
        ondelete='cascade',
        index=True,
        copy=False,
    )


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    internal_transfer_order_id = fields.Many2one(
        comodel_name='internal.transfer.order',
        string='Internal Transfer Order',
        index=True,
        copy=False,
    )
    internal_transfer_leg = fields.Selection(
        selection=[
            ('pick', 'Pick'),
            ('pack', 'Pack'),
            ('delivery', 'Transfer OUT'),
            ('receipt', 'Transfer IN'),
        ],
        string='Internal Transfer Leg',
        copy=False,
    )
    internal_transfer_sequence = fields.Integer(
        string='Internal Transfer Sequence',
        default=99,
        copy=False,
        index=True,
    )

    def _assign_transfer_in_virtual_lots(self):
        Lot = self.env['stock.lot']
        for line in self.move_line_ids.filtered(
            lambda item: item.product_id.tracking != 'none'
            and not item.lot_id
            and not item.lot_name
        ):
            lot_name = line._tjr_build_lot_name()
            lot = Lot.search([
                ('name', '=', lot_name),
                ('product_id', '=', line.product_id.id),
            ], limit=1)
            if not lot:
                lot = Lot.create({
                    'name': lot_name,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_id.uom_id.id,
                    'company_id': False,
                    'location_id': line.location_id.id,
                })
            line.write({
                'lot_id': lot.id,
                'lot_name': False,
            })

    def _set_receipt_done_quantities(self):
        MoveLine = self.env['stock.move.line']
        quantity_field = 'quantity' if 'quantity' in MoveLine._fields else 'qty_done'
        receipt_pickings = self.filtered(
            lambda item: item.picking_type_id.name in ('Receipts', 'Receipt Internal')
            and item.state not in ('done', 'cancel')
        )
        for picking in receipt_pickings:
            for move in picking.move_ids.filtered(lambda item: item.state not in ('done', 'cancel')):
                quantity = move.product_uom_qty
                if not quantity:
                    continue

                move_lines = move.move_line_ids
                if not move_lines:
                    move_lines = MoveLine.create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })

                zero_lines = move_lines[:-1]
                if zero_lines:
                    zero_lines.with_context(skip_matching_sync=True).write({
                        quantity_field: 0.0,
                        'confirmation_quantity': 0.0,
                        'matching': 'match',
                        'putaway_status': 'finished',
                        'picker_status': 'finished',
                        'picked': True,
                    })

                done_line = move_lines[-1]
                done_line_vals = {
                    quantity_field: quantity,
                    'confirmation_quantity': quantity,
                    'location_dest_id': move.location_dest_id.id,
                    'location_putaway_id': move.location_dest_id.id,
                    'matching_loc_dest_id': move.location_dest_id.id,
                    'matching': 'match',
                    'putaway_status': 'finished',
                    'picker_status': 'finished',
                    'picked': True,
                }
                if done_line.lot_id:
                    done_line_vals['matching_lot_id'] = done_line.lot_id.id
                done_line.with_context(skip_matching_sync=True).write(done_line_vals)
                move.picked = True

    def button_validate(self):
        for picking in self:
            order = picking.internal_transfer_order_id
            if (
                order
                and (
                    order.transfer_type != 'transfer_in'
                    or order.transaction_type == 'intra_warehouse'
                )
                and order.validation_policy == 'validate_all'
                and picking.internal_transfer_leg in ('pack', 'delivery', 'receipt')
            ):
                previous_legs = []
                error_message = False
                if picking.internal_transfer_leg == 'pack':
                    previous_legs = ['pick']
                    error_message = 'Pack belum bisa divalidasi sebelum Pick selesai.'
                elif picking.internal_transfer_leg == 'delivery':
                    previous_legs = ['pick', 'pack']
                    error_message = (
                        'Transfer OUT belum bisa divalidasi sebelum Pick dan Pack selesai.'
                    )
                elif picking.internal_transfer_leg == 'receipt':
                    if order.transaction_type == 'intra_warehouse':
                        previous_legs = ['pick']
                        error_message = (
                            'Transfer IN belum bisa divalidasi sebelum Pick selesai.'
                        )
                    elif order.transfer_type == 'transfer_in':
                        previous_legs = ['delivery']
                        error_message = (
                            'Transfer IN belum bisa divalidasi sebelum Transfer OUT selesai.'
                        )
                    else:
                        previous_legs = ['pick', 'pack', 'delivery']
                        error_message = (
                            'Transfer IN belum bisa divalidasi sebelum Pick, Pack, dan Transfer OUT selesai.'
                        )

                previous_pickings = order.picking_ids.filtered(
                    lambda item: item.internal_transfer_leg in previous_legs
                )
                existing_previous_legs = set(
                    previous_pickings.mapped('internal_transfer_leg')
                )
                if previous_legs and (
                    not set(previous_legs).issubset(existing_previous_legs)
                    or any(item.state != 'done' for item in previous_pickings)
                ):
                    raise ValidationError(error_message)

        self.filtered(
            lambda picking: picking.internal_transfer_order_id
            and picking.state == 'draft'
        ).action_confirm()

        internal_transfer_pickings = self.filtered(
            lambda picking: picking.internal_transfer_order_id
            and picking.state not in ('done', 'cancel')
        )
        # internal_transfer_pickings.action_assign()
        missing_lot_lines = internal_transfer_pickings.move_line_ids.filtered(
            lambda line: line.product_id.tracking != 'none'
            and not line.lot_id
            and not line.lot_name
        )
        transfer_in_virtual_pickings = internal_transfer_pickings.filtered(
            lambda picking: picking.internal_transfer_order_id.transfer_type == 'transfer_in'
            and picking.internal_transfer_leg == 'delivery'
            and picking.location_id
            and picking.location_id.complete_name.startswith('Virtual Locations/')
        )
        transfer_in_virtual_lines = missing_lot_lines.filtered(
            lambda line: line.picking_id in transfer_in_virtual_pickings
        )
        if transfer_in_virtual_lines:
            transfer_in_virtual_lines.picking_id._assign_transfer_in_virtual_lots()

        fifo_lot_lines = missing_lot_lines - transfer_in_virtual_lines
        if fifo_lot_lines:
            fifo_lot_lines.action_generate_or_pick_lot()

        self._set_receipt_done_quantities()

        result = super().button_validate()

        for picking in self:
            order = picking.internal_transfer_order_id
            if order and picking.state == 'done':
                order._generate_next_staged_picking(picking)
            if (
                order
                and order.picking_ids
                and all(item.state == 'done' for item in order.picking_ids)
            ):
                order.state = 'done'

        return result
