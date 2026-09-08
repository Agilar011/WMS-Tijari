from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import OrderedSet, float_compare, float_round


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
        return self._get_warehouse_by_location(self.location_id)

    def _get_destination_warehouse(self):
        self.ensure_one()
        return self._get_warehouse_by_location(self.location_dest_id)

    def _get_warehouse_by_location(self, location):
        self.ensure_one()
        warehouses = self.env['stock.warehouse'].search([])
        return warehouses.filtered(
            lambda warehouse: self._location_belongs_to(
                location, warehouse.lot_stock_id
            ) or self._location_belongs_to(
                location, warehouse.view_location_id
            )
        )[:1]

    def _get_operational_warehouse(self):
        self.ensure_one()
        source_warehouse = self._get_source_warehouse()
        destination_warehouse = self._get_destination_warehouse()
        if self.transfer_type == 'transfer_in' and destination_warehouse:
            return destination_warehouse
        return source_warehouse or destination_warehouse

    def _get_receipt_warehouse(self):
        self.ensure_one()
        source_warehouse = self._get_source_warehouse()
        destination_warehouse = self._get_destination_warehouse()
        if destination_warehouse:
            return destination_warehouse
        return source_warehouse

    def _get_internal_picking_type_for_leg(self, leg):
        self.ensure_one()
        operational_warehouse = self._get_operational_warehouse()
        receipt_warehouse = self._get_receipt_warehouse()
        leg_configs = {
            'pick': ('Pick Internal', 'pick', operational_warehouse),
            'pack': ('Pack Internal', 'pack', operational_warehouse),
            'delivery': ('Transfer Internal', 'internal', operational_warehouse),
            'receipt': ('Receipt Internal', 'receive', receipt_warehouse),
        }
        config = leg_configs.get(leg)
        if not config:
            return self.env['stock.picking.type']
        name, operation_category, warehouse = config
        return self._get_required_picking_type(
            name,
            operation_category,
            warehouse=warehouse,
        )

    def _get_picking_type(self, name=False, operation_category=False, code='internal', warehouse=False):
        self.ensure_one()
        warehouse = warehouse or self._get_operational_warehouse()
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
        warehouse = self._get_operational_warehouse()
        picking_type = self.env['stock.picking.type'].resolve_picking_type(
            warehouse=warehouse,
            code='internal',
            operation_category='pick',
            transaction_key='internal_transfer_order',
            required=False,
        )
        if not picking_type:
            picking_type = self._get_picking_type(warehouse=warehouse)
        return picking_type

    def _get_receipt_internal_picking_type(self):
        self.ensure_one()
        return self._get_required_picking_type(
            'Receipt Internal',
            'receive',
            warehouse=self._get_receipt_warehouse(),
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

    def _get_required_picking_type(self, name, operation_category=False, warehouse=False):
        self.ensure_one()
        warehouse = warehouse or self._get_operational_warehouse()
        domain = [
            ('code', '=', 'internal'),
            ('name', '=', name),
        ]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        category_domain = list(domain)
        if operation_category:
            category_domain.append(('operation_category', '=', operation_category))
        picking_type = self.env['stock.picking.type'].search(category_domain, limit=1)
        if not picking_type and operation_category:
            picking_type = self.env['stock.picking.type'].search(domain, limit=1)
        if not picking_type:
            warehouse_label = warehouse.display_name if warehouse else '-'
            raise ValidationError(
                'Operation type %s belum dikonfigurasi untuk warehouse %s. '
                'Aktifkan Internal Transfer di konfigurasi warehouse tersebut.'
                % (name, warehouse_label)
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

    def _get_or_create_packing_zone_location(self, warehouse=False):
        self.ensure_one()
        warehouse = warehouse or self._get_operational_warehouse()
        if warehouse:
            warehouse._create_missing_locations({})
            packing_zone = warehouse.wh_pack_stock_loc_id
            if packing_zone and warehouse.active:
                packing_zone.active = True
            return packing_zone

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

    def _get_or_create_loading_dock_location(self, warehouse=False):
        self.ensure_one()
        warehouse = warehouse or self._get_operational_warehouse()
        if warehouse:
            warehouse._create_missing_locations({})
            loading_dock = warehouse.wh_output_stock_loc_id
            if loading_dock and warehouse.active:
                loading_dock.active = True
            return loading_dock

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

    def _get_order_adt_dest_location(self):
        self.ensure_one()
        if self.transfer_type == 'transfer_in':
            return self.location_dest_id
        return self.location_id

    def _sync_order_adt_dest_location(self):
        for order in self:
            dest_location = order._get_order_adt_dest_location()
            vals = {
                'adt_dest_location_id': dest_location.id if dest_location else False,
            }
            order.move_ids.write(vals)
            pickings = order._get_related_pickings().filtered(
                lambda picking: picking.state not in ('done', 'cancel')
            )
            pickings.write(vals)
            pickings.move_ids.write(vals)

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
        dest_location = self._get_order_adt_dest_location()
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

    def _get_move_mapped_location_name(self, leg):
        self.ensure_one()
        if leg == 'receipt':
            location = self.location_dest_id
        elif leg == 'delivery':
            location = self.location_id
        else:
            location = self.env['stock.location']
        return location.complete_name or location.display_name or False

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
            'adt_dest_location': self._get_move_mapped_location_name(
                picking.internal_transfer_leg
            ),
        }
        if picking.adt_dest_location_id:
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

    def _set_staged_picking_ready(self, picking):
        if not picking:
            return

        if picking.state == 'draft':
            picking.action_confirm()
        if picking.move_ids.filtered(lambda move: move.state not in ('done', 'cancel')):
            picking.action_assign()

    def _auto_validate_pickings_by_leg(self, legs):
        for order in self:
            pickings = order._get_related_pickings().filtered(
                lambda picking: picking.internal_transfer_leg in legs
                and picking.state not in ('done', 'cancel')
            ).sorted(lambda picking: picking.internal_transfer_sequence)
            for picking in pickings:
                order._set_staged_picking_ready(picking)
                picking._set_internal_transfer_auto_done_quantities()
                action = picking.button_validate()
                picking._process_internal_transfer_auto_validation_action(action)
                if picking.state != 'done':
                    raise UserError(_(
                        'Auto validation gagal untuk %s. Picking masih di state %s.'
                    ) % (picking.display_name, picking.state))
        return True

    def action_auto_validate_transfer_in_delivery(self):
        transfer_in_orders = self.filtered(
            lambda order: order.transfer_type == 'transfer_in'
        )
        return transfer_in_orders._auto_validate_pickings_by_leg(('delivery',))

    def action_auto_validate_transfer_out_receipt(self):
        transfer_out_orders = self.filtered(
            lambda order: order.transfer_type == 'transfer_out'
        )
        return transfer_out_orders._auto_validate_pickings_by_leg(('receipt',))

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
        picking_type = self._get_internal_picking_type_for_leg(leg)
        if picking_type:
            vals['picking_type_id'] = picking_type.id
        partner = self._get_picking_partner(leg)
        vals['partner_id'] = partner.id if partner else False
        dest_location = self._get_order_adt_dest_location()
        vals['adt_dest_location_id'] = dest_location.id if dest_location else False
        next_picking.write(vals)
        if next_picking.adt_dest_location_id:
            next_picking.move_ids.write({
                'adt_dest_location_id': next_picking.adt_dest_location_id.id,
            })
        next_picking.move_ids.write({
            'adt_dest_location': self._get_move_mapped_location_name(leg),
        })
        self.picking_ids = [(4, next_picking.id)]
        return next_picking

    def _generate_next_staged_picking(self, done_picking):
        self.ensure_one()
        if self.transaction_type == 'intra_warehouse':
            return False

        existing_legs = set(self.picking_ids.mapped('internal_transfer_leg'))
        operational_warehouse = self._get_operational_warehouse()
        if done_picking.internal_transfer_leg == 'pick' and 'pack' not in existing_legs:
            route_picking = self._adopt_next_picking(done_picking, 'Pack', 'pack')
            if route_picking:
                self._set_staged_picking_ready(route_picking)
                return route_picking

            packing_zone = self._get_or_create_packing_zone_location(operational_warehouse)
            loading_dock = self._get_or_create_loading_dock_location(operational_warehouse)
            pack_picking = self._create_transfer_picking(
                self._get_required_picking_type(
                    'Pack Internal',
                    'pack',
                    warehouse=operational_warehouse,
                ),
                packing_zone,
                loading_dock,
                'Pack',
                'pack',
                previous_picking=done_picking,
            )
            self._set_staged_picking_ready(pack_picking)
            return pack_picking
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
                self._set_staged_picking_ready(route_picking)
                return route_picking

            loading_dock = self._get_or_create_loading_dock_location(operational_warehouse)
            transit_location = self._get_or_create_transit_location()
            if not self.transit_location_id:
                self.transit_location_id = transit_location
            delivery_picking = self._create_transfer_picking(
                self._get_required_picking_type(
                    'Transfer Internal',
                    'internal',
                    warehouse=operational_warehouse,
                ),
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
            self._set_staged_picking_ready(delivery_picking)
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
            order._sync_order_adt_dest_location()
            operational_warehouse = order._get_operational_warehouse()
            receipt_warehouse = order._get_receipt_warehouse()

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
                receipt_picking_type = order._get_required_picking_type(
                    'Receipt Internal',
                    'receive',
                    warehouse=receipt_warehouse,
                )
                picking_specs = [
                    (
                        order._get_required_picking_type(
                            'Pick Internal',
                            'pick',
                            warehouse=operational_warehouse,
                        ),
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
                receipt_picking_type = order._get_required_picking_type(
                    'Receipt Internal',
                    'receive',
                    warehouse=receipt_warehouse,
                )
                picking_specs = [
                    (
                        order._get_required_picking_type(
                            'Transfer Internal',
                            'internal',
                            warehouse=operational_warehouse,
                        ),
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
                receipt_picking_type = order._get_required_picking_type(
                    'Receipt Internal',
                    'receive',
                    warehouse=receipt_warehouse,
                )
                packing_zone = order._get_or_create_packing_zone_location(operational_warehouse)
                picking_specs = [
                    (
                        order._get_required_picking_type(
                            'Pick Internal',
                            'pick',
                            warehouse=operational_warehouse,
                        ),
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
        self._sync_order_adt_dest_location()
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

    def _get_receipt_done_line_dest_location(self, done_line, move):
        scanned_location = self.env['stock.location']
        if done_line.confirmation_location_code:
            scanned_location = done_line._find_loc_by_scan_code(
                done_line.confirmation_location_code
            )
        return (
            scanned_location
            or done_line.location_putaway_id
            or done_line.location_dest_id
            or move.location_dest_id
        )

    def _is_transfer_in_inter_warehouse_delivery_without_lot(self):
        self.ensure_one()
        order = self.internal_transfer_order_id
        return bool(
            order
            and order.transaction_type == 'inter_warehouse'
            and order.transfer_type == 'transfer_in'
            and self.internal_transfer_leg == 'delivery'
        )

    def _is_transfer_in_inter_warehouse_receipt_lot_source(self):
        self.ensure_one()
        order = self.internal_transfer_order_id
        return bool(
            order
            and order.transaction_type == 'inter_warehouse'
            and order.transfer_type == 'transfer_in'
            and self.internal_transfer_leg == 'receipt'
        )

    def _assign_transfer_in_delivery_no_lot_names(self):
        for picking in self:
            for line in picking.move_line_ids.filtered(
                lambda item: item.product_id.tracking != 'none'
                and not item.lot_id
                and not item.lot_name
            ):
                product_code = line.product_id.default_code or line.product_id.id
                line.write({
                    'lot_id': False,
                    'lot_name': 'NO LOT - %s - %s' % (
                        picking.origin or picking.name,
                        product_code,
                    ),
                })

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
            lambda item: item.internal_transfer_order_id
            and item.picking_type_id.name in ('Receipts', 'Receipt Internal')
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

                done_lines = move_lines.filtered(lambda line: line[quantity_field] > 0)
                if not done_lines:
                    done_lines = move_lines[-1]
                    done_lines.write({quantity_field: quantity})

                for done_line in done_lines:
                    final_dest_location = self._get_receipt_done_line_dest_location(done_line, move)
                    done_line_vals = {
                        'confirmation_quantity': done_line[quantity_field],
                        'matching': 'match',
                        'putaway_status': 'finished',
                        'picker_status': 'finished',
                        'picked': True,
                    }
                    if final_dest_location:
                        done_line_vals.update({
                            'location_dest_id': final_dest_location.id,
                            'location_putaway_id': final_dest_location.id,
                            'matching_loc_dest_id': final_dest_location.id,
                        })
                    if done_line.lot_id:
                        done_line_vals['matching_lot_id'] = done_line.lot_id.id
                    done_line.with_context(skip_matching_sync=True).write(done_line_vals)
                move.picked = True

    def _set_internal_transfer_auto_done_quantities(self):
        MoveLine = self.env['stock.move.line']
        quantity_field = 'quantity' if 'quantity' in MoveLine._fields else 'qty_done'
        for picking in self.filtered(
            lambda item: item.internal_transfer_order_id
            and item.state not in ('done', 'cancel')
        ):
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

                done_lines = move_lines.filtered(lambda line: line[quantity_field] > 0)
                if not done_lines:
                    done_lines = move_lines[-1]
                    done_lines.write({quantity_field: quantity})

                for done_line in done_lines:
                    final_dest_location = self._get_receipt_done_line_dest_location(done_line, move)
                    line_vals = {
                        'confirmation_quantity': done_line[quantity_field],
                        'matching': 'match',
                        'putaway_status': 'finished',
                        'picker_status': 'finished',
                        'picked': True,
                    }
                    if final_dest_location:
                        line_vals.update({
                            'location_dest_id': final_dest_location.id,
                            'location_putaway_id': final_dest_location.id,
                            'matching_loc_dest_id': final_dest_location.id,
                        })
                    if done_line.lot_id:
                        line_vals['matching_lot_id'] = done_line.lot_id.id
                    done_line.with_context(skip_matching_sync=True).write(line_vals)
                move.picked = True

    def _process_internal_transfer_auto_validation_action(self, action):
        if not isinstance(action, dict):
            return

        model_name = action.get('res_model')
        context = action.get('context') or {}
        if model_name == 'stock.immediate.transfer':
            wizard = self.env[model_name].with_context(context).create({})
            wizard.process()
        elif model_name == 'stock.backorder.confirmation':
            wizard = self.env[model_name].with_context(context).create({})
            wizard.process_cancel_backorder()

    def button_validate(self):
        for picking in self:
            order = picking.internal_transfer_order_id
            if (
                order
                and order.validation_policy == 'validate_all'
                and picking.internal_transfer_leg in ('pack', 'delivery', 'receipt')
            ):
                previous_legs = []
                error_message = False
                if picking.internal_transfer_leg == 'pack':
                    previous_legs = ['pick']
                    error_message = 'Pack belum bisa divalidasi sebelum Pick selesai.'
                elif picking.internal_transfer_leg == 'delivery':
                    if order.transfer_type != 'transfer_in':
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

                previous_pickings = order._get_related_pickings().filtered(
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
        internal_transfer_pickings._set_receipt_done_quantities()

        missing_lot_lines = internal_transfer_pickings.move_line_ids.filtered(
            lambda line: line.product_id.tracking != 'none'
            and not line.lot_id
            and not line.lot_name
        )
        transfer_in_virtual_pickings = internal_transfer_pickings.filtered(
            lambda picking: picking.internal_transfer_order_id.transfer_type == 'transfer_in'
            and picking.internal_transfer_leg == 'delivery'
            and picking.internal_transfer_order_id.transaction_type != 'inter_warehouse'
            and picking.location_id
            and picking.location_id.complete_name.startswith('Virtual Locations/')
        )
        transfer_in_virtual_lines = missing_lot_lines.filtered(
            lambda line: line.picking_id in transfer_in_virtual_pickings
        )
        if transfer_in_virtual_lines:
            transfer_in_virtual_lines.picking_id._assign_transfer_in_virtual_lots()

        no_lot_delivery_pickings = internal_transfer_pickings.filtered(
            lambda picking: picking._is_transfer_in_inter_warehouse_delivery_without_lot()
        )
        no_lot_delivery_lines = missing_lot_lines.filtered(
            lambda line: line.picking_id in no_lot_delivery_pickings
        )
        if no_lot_delivery_lines:
            no_lot_delivery_lines.picking_id._assign_transfer_in_delivery_no_lot_names()

        transfer_in_receipt_pickings = internal_transfer_pickings.filtered(
            lambda picking: picking._is_transfer_in_inter_warehouse_receipt_lot_source()
        )
        transfer_in_receipt_lines = missing_lot_lines.filtered(
            lambda line: line.picking_id in transfer_in_receipt_pickings
        )
        if transfer_in_receipt_lines:
            transfer_in_receipt_lines.picking_id._assign_transfer_in_virtual_lots()

        fifo_lot_lines = (
            missing_lot_lines
            - transfer_in_virtual_lines
            - no_lot_delivery_lines
            - transfer_in_receipt_lines
        )
        if fifo_lot_lines:
            fifo_lot_lines.action_generate_or_pick_lot()

        result = super().button_validate()

        for picking in self:
            order = picking.internal_transfer_order_id
            if order and picking.state == 'done':
                order._generate_next_staged_picking(picking)
                if (
                    order.transfer_type == 'transfer_out'
                    and (
                        picking.internal_transfer_leg == 'delivery'
                        or (
                            order.transaction_type == 'intra_warehouse'
                            and picking.internal_transfer_leg == 'pick'
                        )
                    )
                ):
                    order.action_auto_validate_transfer_out_receipt()
            if (
                order
                and order.picking_ids
                and all(item.state == 'done' for item in order.picking_ids)
            ):
                order.state = 'done'

        return result


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _is_transfer_in_inter_warehouse_delivery_without_lot(self):
        self.ensure_one()
        picking = self.picking_id
        return bool(
            picking
            and picking._is_transfer_in_inter_warehouse_delivery_without_lot()
            and self.product_id.tracking != 'none'
            and not self.lot_id
        )

    def _action_done(self):
        no_lot_delivery_lines = self.filtered(
            lambda line: line._is_transfer_in_inter_warehouse_delivery_without_lot()
        )
        regular_lines = self - no_lot_delivery_lines

        result = True
        if regular_lines:
            result = super(StockMoveLine, regular_lines)._action_done()
        if no_lot_delivery_lines:
            no_lot_delivery_lines._action_done_without_lot_creation()
        return result

    def _action_done_without_lot_creation(self):
        ml_ids_to_delete = OrderedSet()

        for ml in self:
            uom_qty = float_round(
                ml.quantity,
                precision_rounding=ml.product_uom_id.rounding,
                rounding_method='HALF-UP',
            )
            precision_digits = self.env['decimal.precision'].precision_get(
                'Product Unit of Measure'
            )
            quantity = float_round(
                ml.quantity,
                precision_digits=precision_digits,
                rounding_method='HALF-UP',
            )
            if float_compare(uom_qty, quantity, precision_digits=precision_digits) != 0:
                raise UserError(_(
                    'The quantity done for the product "%(product)s" doesn\'t respect '
                    'the rounding precision defined on the unit of measure "%(unit)s". '
                    'Please change the quantity done or the rounding precision of your '
                    'unit of measure.',
                    product=ml.product_id.display_name,
                    unit=ml.product_uom_id.name,
                ))

            qty_done_float_compared = float_compare(
                ml.quantity,
                0,
                precision_rounding=ml.product_uom_id.rounding,
            )
            if qty_done_float_compared < 0:
                raise UserError(_('No negative quantities allowed'))
            if qty_done_float_compared == 0 and not ml.is_inventory:
                ml_ids_to_delete.add(ml.id)

        mls_to_delete = self.env['stock.move.line'].browse(ml_ids_to_delete)
        mls_to_delete.unlink()

        mls_todo = self - mls_to_delete
        mls_todo._check_company()

        ml_ids_to_ignore = OrderedSet()
        quants_cache = self.env['stock.quant']._get_quants_by_products_locations(
            mls_todo.product_id,
            mls_todo.location_id | mls_todo.location_dest_id,
            extra_domain=[('lot_id', '=', False)],
        )

        for ml in mls_todo.with_context(quants_cache=quants_cache):
            ml._synchronize_quant(
                -ml.quantity_product_uom,
                ml.location_id,
                action="reserved",
                lot=self.env['stock.lot'],
            )
            available_qty, in_date = ml._synchronize_quant(
                -ml.quantity_product_uom,
                ml.location_id,
                lot=self.env['stock.lot'],
            )
            ml._synchronize_quant(
                ml.quantity_product_uom,
                ml.location_dest_id,
                package=ml.result_package_id,
                in_date=in_date,
                lot=self.env['stock.lot'],
            )
            if available_qty < 0:
                ml.with_context(quants_cache=None)._free_reservation(
                    ml.product_id,
                    ml.location_id,
                    abs(available_qty),
                    lot_id=self.env['stock.lot'],
                    package_id=ml.package_id,
                    owner_id=ml.owner_id,
                    ml_ids_to_ignore=ml_ids_to_ignore,
                )
            ml_ids_to_ignore.add(ml.id)

        mls_todo.write({
            'date': fields.Datetime.now(),
        })
