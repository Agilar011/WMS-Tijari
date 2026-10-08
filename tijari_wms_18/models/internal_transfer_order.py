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
    external_ref_in = fields.Char(
        string='External Ref IN',
        copy=False,
        index=True,
    )
    external_ref_out = fields.Char(
        string='External Ref OUT',
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
        ],
        string='Kategori Transfer',
        default='intra_warehouse',
        tracking=True,
    )
    transfer_type = fields.Selection(
        selection=[
            ('transfer_in', 'Transfer IN'),
            ('transfer_out', 'Transfer OUT'),
            ('intra_group_transfer', 'Intra Group Transfer'),
            ('inter_group_transfer', 'Inter Group Transfer'),
        ],
        string='Transfer Type',
        default=lambda self: (
            'transfer_out'
            if self.env.context.get('default_transaction_type') == 'inter_warehouse'
            else 'intra_group_transfer'
        ),
        tracking=True,
    )
    inter_transfer_type = fields.Selection(
        selection=[
            ('transfer_in', 'Transfer IN'),
            ('transfer_out', 'Transfer OUT'),
        ],
        string='Transfer Type',
        compute='_compute_transfer_type_ui',
        inverse='_inverse_inter_transfer_type',
    )
    intra_transfer_type = fields.Selection(
        selection=[
            ('intra_group_transfer', 'Intra Group Transfer'),
            ('inter_group_transfer', 'Inter Group Transfer'),
        ],
        string='Transfer Type',
        compute='_compute_transfer_type_ui',
        inverse='_inverse_intra_transfer_type',
    )
    adt_order_type = fields.Char(
        string='Order Type (Acumatica)',
        tracking=True,
    )
    adt_transaction_type = fields.Char(
        string='Tipe Transaksi',
        tracking=True,
        copy=False,
    )
    document_only = fields.Boolean(
        string='Document Only',
        default=False,
        tracking=True,
        copy=False,
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
    location_group_id = fields.Many2one(
        comodel_name='stock.location',
        string='Location Group',
        domain=[('is_location_mapping', '=', True)],
        tracking=True,
    )
    source_location_scan_code = fields.Char(
        string='Scan Handheld Source',
        store=False,
        help='Scan barcode, unique code, atau nama Source Location.',
    )
    destination_location_scan_code = fields.Char(
        string='Scan Handheld Destination',
        store=False,
        help='Scan barcode, unique code, atau nama Destination Location.',
    )
    available_source_product_ids = fields.Many2many(
        comodel_name='product.product',
        string='Products Available at Source Location',
        compute='_compute_available_source_product_ids',
    )
    intra_location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Source Location',
        compute='_compute_intra_locations_ui',
        inverse='_inverse_intra_location_id',
    )
    intra_location_dest_id = fields.Many2one(
        comodel_name='stock.location',
        string='Destination Location',
        compute='_compute_intra_locations_ui',
        inverse='_inverse_intra_location_dest_id',
    )
    transit_location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Transit Location',
        domain=[('usage', '=', 'transit')],
        default=lambda self: self.env['stock.location'].search(
            [('usage', '=', 'transit')],
            limit=1,
        ).id,
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
    description = fields.Text(string='Description')

    @api.depends(
        'transaction_type',
        'transfer_type',
        'intra_transfer_type',
        'location_group_id',
        'location_id',
        'location_dest_id',
    )
    def _compute_intra_locations_ui(self):
        for order in self:
            group = order.location_group_id
            is_intra = order.transaction_type == 'intra_warehouse'
            is_intra_group = (
                is_intra and order.intra_transfer_type == 'intra_group_transfer'
            )
            is_inter_group = is_intra and order.intra_transfer_type == 'inter_group_transfer'
            order.intra_location_id = (
                order.location_id
                if is_inter_group or (
                    is_intra_group and order._intra_group_location_belongs_to(order.location_id, group)
                )
                else False
            )
            order.intra_location_dest_id = (
                order.location_dest_id
                if is_inter_group or (
                    is_intra_group and order._intra_group_location_belongs_to(order.location_dest_id, group)
                )
                else False
            )

    def _inverse_intra_location_id(self):
        for order in self:
            order.location_id = order.intra_location_id

    def _inverse_intra_location_dest_id(self):
        for order in self:
            order.location_dest_id = order.intra_location_dest_id

    @api.onchange('source_location_scan_code')
    def _onchange_source_location_scan_code(self):
        for order in self:
            code = (order.source_location_scan_code or '').strip()
            if not code:
                continue
            order.intra_location_id = order._find_intra_group_location_by_scan_code(
                code
            )
            order.source_location_scan_code = False

    @api.onchange('destination_location_scan_code')
    def _onchange_destination_location_scan_code(self):
        for order in self:
            code = (order.destination_location_scan_code or '').strip()
            if not code:
                continue
            order.intra_location_dest_id = (
                order._find_intra_group_location_by_scan_code(code)
            )
            order.destination_location_scan_code = False

    def _find_intra_group_location_by_scan_code(self, code):
        self.ensure_one()
        if (
            self.transaction_type != 'intra_warehouse'
            or self.intra_transfer_type != 'intra_group_transfer'
        ):
            raise ValidationError(
                'Scan lokasi hanya tersedia untuk Intra Group Transfer.'
            )
        if not self.location_group_id:
            raise ValidationError('Pilih Location Group sebelum scan lokasi.')

        Location = self.env['stock.location']
        base_domain = [
            '|',
            ('id', 'child_of', self.location_group_id.id),
            ('location_group_id', '=', self.location_group_id.id),
        ]
        for field_name in ('barcode', 'unique_code', 'complete_name', 'name'):
            matches = Location.search(
                base_domain + [(field_name, '=', code)],
            )
            if len(matches) > 1:
                raise ValidationError(_(
                    'Kode scan "%(code)s" cocok dengan beberapa lokasi di '
                    'Location Group %(group)s.'
                ) % {
                    'code': code,
                    'group': self.location_group_id.display_name,
                })
            if matches:
                return matches
        raise ValidationError(_(
            'Lokasi dengan barcode, unique code, atau nama "%(code)s" tidak '
            'ditemukan di Location Group %(group)s.'
        ) % {
            'code': code,
            'group': self.location_group_id.display_name,
        })

    @api.onchange('transaction_type', 'transfer_type', 'location_id', 'location_dest_id')
    def _onchange_inter_warehouse_partner(self):
        for order in self:
            if (
                order.transaction_type == 'inter_warehouse'
                and order.adt_transaction_type != 'Shipment Consignment'
                and order.adt_transaction_type != 'Vendor Return'
            ):
                order.partner_id = order._get_inter_warehouse_partner()

    def _get_inter_warehouse_partner(self, side=False):
        self.ensure_one()
        if self.transaction_type != 'inter_warehouse':
            return self.env['res.partner']

        if self.adt_transaction_type in ('Shipment Consignment', 'Vendor Return'):
            return self.partner_id

        if not side:
            if self.transfer_type == 'transfer_out':
                side = 'destination'
            elif self.transfer_type == 'transfer_in':
                side = 'source'
            else:
                return self.env['res.partner']
        if side not in ('source', 'destination'):
            return self.env['res.partner']

        location = (
            self.location_id if side == 'source' else self.location_dest_id
        )
        if not location:
            return self.env['res.partner']

        virtual_root = self.env.ref(
            'stock.stock_location_locations_virtual', raise_if_not_found=False
        )
        warehouse = (
            self._get_source_warehouse()
            if side == 'source'
            else self._get_destination_warehouse()
        )
        is_virtual_location = bool(
            virtual_root and self._location_belongs_to(location, virtual_root)
        )
        if virtual_root and not is_virtual_location and warehouse:
            virtual_location = self.env['stock.location'].search([
                ('name', '=', warehouse.code),
                ('location_id', '=', virtual_root.id),
            ], limit=1)
            if virtual_location:
                location = virtual_location
                is_virtual_location = True

        partner_name = (
            location.name if is_virtual_location else
            (warehouse.code if warehouse else location.name)
        )
        if not partner_name:
            return self.env['res.partner']
        return self.env['res.partner'].search([
            ('name', '=', partner_name),
            ('partner_type', '=', 'warehouse'),
        ], limit=1)

    @api.depends(
        'transaction_type',
        'transfer_type',
        'intra_transfer_type',
        'location_group_id',
        'location_id',
        'intra_location_id',
    )
    def _compute_available_source_product_ids(self):
        for order in self:
            source_location = (
                order.intra_location_id
                if order.transaction_type == 'intra_warehouse'
                else order.location_id
            )
            order.available_source_product_ids = order._get_available_source_products(
                source_location
            )

    @api.onchange(
        'transaction_type', 'intra_transfer_type', 'location_id', 'intra_location_id'
    )
    def _onchange_available_source_product_ids(self):
        for order in self:
            location = (
                order.intra_location_id
                if order.transaction_type == 'intra_warehouse'
                else order.location_id
            )
            order.available_source_product_ids = order._get_available_source_products(
                location
            )

    def _get_available_source_products(self, location):
        self.ensure_one()
        selected_transfer_type = self.intra_transfer_type or self.transfer_type
        if (
            self.transaction_type != 'intra_warehouse'
            or selected_transfer_type != 'intra_group_transfer'
            or not location
        ):
            return self.env['product.product']

        available_by_product = self.env['stock.quant']._read_group(
            [('location_id', 'child_of', location.id)],
            ['product_id'],
            ['available_quantity:sum'],
        )
        return self.env['product.product'].browse([
            product.id
            for product, available_qty in available_by_product
            if available_qty > 0
        ])

    @api.depends('transaction_type', 'transfer_type')
    def _compute_transfer_type_ui(self):
        inter_values = {'transfer_in', 'transfer_out'}
        intra_values = {'intra_group_transfer', 'inter_group_transfer'}
        for order in self:
            order.inter_transfer_type = (
                order.transfer_type
                if order.transaction_type == 'inter_warehouse'
                and order.transfer_type in inter_values
                else False
            )
            order.intra_transfer_type = (
                order.transfer_type
                if order.transaction_type == 'intra_warehouse'
                and order.transfer_type in intra_values
                else False
            )

    @api.onchange('transaction_type')
    def _onchange_transaction_type_default_transfer_type(self):
        for order in self:
            if order.transaction_type == 'intra_warehouse' and order.transfer_type not in (
                'intra_group_transfer', 'inter_group_transfer'
            ):
                order.transfer_type = 'intra_group_transfer'
            elif order.transaction_type == 'inter_warehouse' and order.transfer_type not in (
                'transfer_in', 'transfer_out'
            ):
                order.transfer_type = 'transfer_out'

    def _inverse_inter_transfer_type(self):
        for order in self:
            if order.inter_transfer_type:
                order.transfer_type = order.inter_transfer_type

    def _inverse_intra_transfer_type(self):
        for order in self:
            if order.intra_transfer_type:
                order.transfer_type = order.intra_transfer_type

    @api.model_create_multi
    def create(self, vals_list):
        # A new ITO and its Operations rows are created in one ORM call. In
        # that path, stock.move.create() can run before the child move has a
        # persisted internal_transfer_order_id, so copy the header locations
        # into the x2many create commands first.
        prepared_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            transaction_type = (
                vals.get('transaction_type')
                or self.env.context.get('default_transaction_type')
                or 'intra_warehouse'
            )
            if (
                'transfer_type' not in vals
                and not self.env.context.get('default_transfer_type')
            ):
                if transaction_type == 'inter_warehouse':
                    vals['transfer_type'] = 'transfer_out'
                elif transaction_type == 'intra_warehouse':
                    vals['transfer_type'] = 'intra_group_transfer'
            transfer_type = (
                vals.get('transfer_type')
                or self.env.context.get('default_transfer_type')
                or (
                    'transfer_out'
                    if transaction_type == 'inter_warehouse'
                    else 'intra_group_transfer'
                )
            )
            if (
                transaction_type == 'intra_warehouse'
                and transfer_type == 'intra_group_transfer'
                and vals.get('location_group_id')
            ):
                vals['location_dest_id'] = vals['location_group_id']
            source_location_id = (
                vals.get('location_id') or vals.get('intra_location_id')
            )
            destination_location_id = (
                vals.get('location_dest_id') or vals.get('intra_location_dest_id')
            )
            move_commands = vals.get('move_ids')
            if move_commands and (source_location_id or destination_location_id):
                prepared_commands = []
                for command in move_commands:
                    if (
                        isinstance(command, (tuple, list))
                        and len(command) >= 3
                        and command[0] == 0
                        and isinstance(command[2], dict)
                    ):
                        move_vals = dict(command[2])
                        if not move_vals.get('location_id') and source_location_id:
                            move_vals['location_id'] = source_location_id
                        if (
                            not move_vals.get('location_dest_id')
                            and destination_location_id
                        ):
                            move_vals['location_dest_id'] = destination_location_id
                        command = (command[0], command[1], move_vals)
                    prepared_commands.append(command)
                vals['move_ids'] = prepared_commands
            prepared_vals_list.append(vals)

        vals_list = prepared_vals_list
        orders = super().create(vals_list)
        for order in orders:
            if order.name == 'New':
                order.name = 'ITO/%05d' % order.id
        return orders

    def write(self, vals):
        # Data ITO hanya boleh diedit selama seluruh picking hasil generate
        # masih draft. Satu picking yang sudah confirmed/assigned/done/cancel
        # membuat header dan pasangan transfer tidak boleh diubah lagi.
        editable_vals = set(vals) - {'state', 'picking_ids'}
        protected_ready_vals = {
            'transaction_type',
            'transfer_type',
            'location_group_id',
            'location_id',
            'location_dest_id',
        }
        if editable_vals:
            for order in self:
                if order.state == 'ready' and editable_vals & protected_ready_vals:
                    raise ValidationError(_(
                        'Internal Transfer Order %s sudah Ready dan tidak dapat '
                        'mengubah tipe atau lokasi transfer.'
                    ) % order.display_name)
                related_pickings = order._get_related_pickings()
                blocked_picking = related_pickings.filtered(
                    lambda picking: picking.state != 'draft'
                )[:1]
                if blocked_picking:
                    raise ValidationError(_(
                        'Internal Transfer Order %s tidak dapat diedit karena '
                        'picking %s sudah tidak dalam state Draft.'
                    ) % (order.display_name, blocked_picking.display_name))
        result = super().write(vals)
        if editable_vals & {'external_ref', 'external_ref_in', 'external_ref_out'}:
            for order in self:
                for picking in order._get_related_pickings().filtered(
                    lambda item: item.state == 'draft'
                ):
                    picking_ref = order._get_picking_external_ref(
                        picking.internal_transfer_leg
                    )
                    picking.write({
                        'origin': picking_ref,
                        'adt_external_ref': picking_ref,
                    })
        if editable_vals & {'note', 'description'}:
            for order in self:
                draft_pickings = order._get_related_pickings().filtered(
                    lambda item: item.state == 'draft'
                )
                if draft_pickings:
                    draft_pickings.write({
                        'note': order.note or False,
                        'desc_note': order.description or False,
                        'adt_description': order.description or False,
                    })
        return result

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

    @api.onchange(
        'location_id',
        'location_dest_id',
        'intra_location_id',
        'intra_location_dest_id',
    )
    def _onchange_locations(self):
        for order in self:
            for move in order.move_ids:
                move.location_id = order.location_id
                move.location_dest_id = order.location_dest_id

    @api.onchange('transaction_type', 'transfer_type', 'intra_transfer_type', 'location_group_id')
    def _onchange_intra_location_group(self):
        for order in self:
            if order.transaction_type != 'intra_warehouse':
                order.location_group_id = False
                continue
            if order.intra_transfer_type != 'intra_group_transfer':
                order.location_group_id = False
                continue
            if order.state == 'ready':
                continue
            location_group_changed = (
                order._origin.location_group_id != order.location_group_id
            )
            if not order.location_group_id:
                order.location_id = False
                order.location_dest_id = False
                continue
            if not order._intra_group_location_belongs_to(order.location_id, order.location_group_id):
                order.location_id = False
            if location_group_changed or not order._intra_group_location_belongs_to(
                order.location_dest_id, order.location_group_id
            ):
                order.location_dest_id = order.location_group_id

    @api.constrains(
        'transaction_type',
        'transfer_type',
        'location_group_id',
        'location_id',
        'location_dest_id',
    )
    def _check_intra_location_group(self):
        for order in self:
            if order.transaction_type != 'intra_warehouse':
                continue
            if order.intra_transfer_type != 'intra_group_transfer':
                continue
            if not order.location_group_id:
                # Existing API-created intra orders are kept compatible until
                # the Data Hub mapping is migrated to populate this field.
                continue
            invalid_locations = (order.location_id | order.location_dest_id).filtered(
                lambda location: not order._intra_group_location_belongs_to(
                    location,
                    order.location_group_id,
                )
            )
            if invalid_locations:
                raise ValidationError(_(
                    'Source dan Destination Location harus berada di bawah atau '
                    'tergabung ke '
                    'Location Group yang dipilih.'
                ))

    def _intra_group_location_belongs_to(self, location, group_location):
        if not location or not group_location:
            return False
        return bool(
            self._location_belongs_to(location, group_location)
            or location.location_group_id == group_location
        )

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
        if leg == 'receipt':
            if self.transaction_type == 'intra_warehouse':
                return self._get_required_picking_type(
                    'Storage',
                    'internal',
                    warehouse=receipt_warehouse,
                )
            if self.transfer_type == 'transfer_in':
                return self._get_required_picking_type(
                    ('Receipts', 'Receipt Internal'),
                    'receive',
                    warehouse=receipt_warehouse,
                    code=('incoming', 'internal'),
                )
            return self._get_transfer_out_direct_receipt_picking_type()

        leg_configs = {
            'pick': (('Pick', 'Pick Internal'), 'pick', operational_warehouse),
            'pack': (('Pack', 'Pack Internal'), 'pack', operational_warehouse),
            'delivery': (
                ('Internal Transfer', 'Internal Transfers', 'Transfer Internal'),
                'internal',
                operational_warehouse,
            ),
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
            ('Receipts', 'Receipt Internal'),
            'receive',
            warehouse=self._get_receipt_warehouse(),
            code=('incoming', 'internal'),
        )

    def _get_vendor_return_receipt_picking_type(self):
        self.ensure_one()
        warehouse = self._get_receipt_warehouse()
        warehouse_code = warehouse.code if warehouse else False
        PickingType = self.env['stock.picking.type']

        if self.document_only:
            picking_type = PickingType.resolve_document_only_picking_type(
                target_operation_type='direct_receipt',
                api_acumatica='vendor_return',
                document_only=True,
                warehouse_code=warehouse_code,
            )
            if picking_type:
                return picking_type

        picking_type = PickingType.resolve_picking_type(
            warehouse=warehouse,
            warehouse_code=warehouse_code,
            code='incoming',
            operation_category='receive',
            api_acumatica='vendor_return',
            transaction_key='vendor_return',
            required=False,
        )
        if picking_type:
            return picking_type

        incoming_domain = [
            ('code', '=', 'incoming'),
            ('operation_category', '=', 'receive'),
            ('active', '=', True),
            ('is_document_only_api', '=', False),
        ]
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
        # Vendor Return source locations can be under a Consignment branch
        # outside the warehouse's stock/view location hierarchy. For the
        # transfer_in flow, the destination identifies the operational
        # warehouse that owns the Direct Delivery operation type.
        warehouse = self._get_source_warehouse() or self._get_operational_warehouse()
        if not warehouse:
            # Consignment locations may live under Virtual Locations and thus
            # have no stock.warehouse ancestor. Their Acumatica code is kept
            # on the consignment leaf (for example WH33-C0017); resolve that
            # code through stock.location.acumatica to its owning building.
            location = self.location_id
            while location and not warehouse:
                warehouse = self.env['stock.picking.type']._adt_find_warehouse(
                    location.name
                )
                if not warehouse and location.name:
                    mappings = self.env['stock.location.acumatica'].search([
                        ('is_active', '=', True),
                        ('odoo_building_id', '!=', False),
                    ]).filtered(
                        lambda mapping: (mapping.code or '').endswith(
                            '-%s' % location.name
                        )
                    )
                    if len(mappings) == 1:
                        warehouse = mappings.odoo_building_id
                location = location.location_id
        warehouse_code = warehouse.code if warehouse else False
        if not self.document_only:
            return self.env['stock.picking.type'].resolve_picking_type(
                warehouse=warehouse,
                warehouse_code=warehouse_code,
                code='outgoing',
                operation_category='delivery',
                api_acumatica='vendor_return',
                transaction_key='vendor_return',
                required=True,
            )
        return self.env['stock.picking.type'].resolve_document_only_picking_type(
            target_operation_type='direct_delivery_order',
            api_acumatica='vendor_return',
            document_only=True,
            warehouse_code=warehouse_code,
            required=True,
        )

    def _get_transfer_in_direct_delivery_picking_type(self):
        self.ensure_one()
        warehouse = self._get_operational_warehouse()
        warehouse_code = warehouse.code if warehouse else False
        is_vendor_return = (
            (self.adt_transaction_type or '').strip().lower() == 'vendor return'
            or any(
                (move.adt_type or '').strip().lower()
                in ('vendor return', 'vendor return document')
                for move in self.move_ids
            )
        )
        if is_vendor_return and not self.document_only:
            # Vendor Return's transfer-out leg must use Direct Delivery Order.
            # The consignment source can sit outside the warehouse hierarchy,
            # so resolve the operation type from the operational/destination
            # warehouse for this transfer_in flow.
            return self.env['stock.picking.type'].resolve_document_only_picking_type(
                target_operation_type='direct_delivery_order',
                api_acumatica='vendor_return',
                document_only=True,
                warehouse_code=warehouse_code,
                required=True,
            )
        return self.env['stock.picking.type'].resolve_document_only_picking_type(
            target_operation_type='direct_delivery_order',
            api_acumatica='transfer_in',
            document_only=True,
            warehouse_code=warehouse_code,
            required=True,
        )

    def _get_transfer_out_direct_receipt_picking_type(self):
        self.ensure_one()
        warehouse = self._get_receipt_warehouse()
        warehouse_code = warehouse.code if warehouse else False
        return self.env['stock.picking.type'].resolve_document_only_picking_type(
            target_operation_type='direct_receipt',
            api_acumatica='transfer_out',
            document_only=True,
            warehouse_code=warehouse_code,
            required=True,
        )

    def _get_required_picking_type(
        self,
        name,
        operation_category=False,
        warehouse=False,
        code='internal',
    ):
        self.ensure_one()
        warehouse = warehouse or self._get_operational_warehouse()
        names = (name,) if isinstance(name, str) else tuple(name)
        codes = (code,) if isinstance(code, str) else tuple(code)
        for current_code in codes:
            for current_name in names:
                domain = [
                    ('code', '=', current_code),
                    ('name', '=', current_name),
                ]
                if warehouse:
                    domain.append(('warehouse_id', '=', warehouse.id))
                category_domain = list(domain)
                if operation_category:
                    category_domain.append(('operation_category', '=', operation_category))
                picking_type = self.env['stock.picking.type'].search(
                    category_domain,
                    limit=1,
                )
                if not picking_type and operation_category:
                    picking_type = self.env['stock.picking.type'].search(
                        domain,
                        limit=1,
                    )
                if picking_type:
                    return picking_type

        warehouse_label = warehouse.display_name if warehouse else '-'
        raise ValidationError(
            'Operation type %s belum dikonfigurasi untuk warehouse %s. '
            'Aktifkan operation type yang sesuai di konfigurasi warehouse tersebut.'
            % (', '.join(names), warehouse_label)
        )

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
        if (
            self.transaction_type == 'intra_warehouse'
            or self.transfer_type == 'transfer_in'
        ):
            return self.location_dest_id
        return self.location_id

    def _get_picking_adt_dest_location(self, leg):
        self.ensure_one()
        if leg == 'delivery' and self.adt_transaction_type == 'Shipment Consignment':
            return self.env['stock.location']
        if self.transaction_type == 'intra_warehouse':
            return self.location_dest_id if leg == 'receipt' else self.location_id
        return self._get_order_adt_dest_location()

    def _sync_order_adt_dest_location(self):
        for order in self:
            order_dest_location = order._get_order_adt_dest_location()
            order.move_ids.write({
                'adt_dest_location_id': (
                    order_dest_location.id if order_dest_location else False
                ),
            })
            pickings = order._get_related_pickings().filtered(
                lambda picking: picking.state not in ('done', 'cancel')
            )
            for picking in pickings:
                dest_location = order._get_picking_adt_dest_location(
                    picking.internal_transfer_leg
                )
                vals = {
                    'adt_dest_location_id': dest_location.id if dest_location else False,
                }
                picking.write(vals)
                picking.move_ids.write(vals)

    def _get_picking_external_ref(self, leg):
        self.ensure_one()
        if leg == 'receipt':
            return (
                self.external_ref_in
                or self.external_ref_out
                or self.external_ref
                or self.name
            )
        if leg in ('pick', 'pack', 'delivery'):
            return (
                self.external_ref_out
                or self.external_ref_in
                or self.external_ref
                or self.name
            )
        return self.external_ref_in or self.external_ref_out or self.external_ref or self.name

    def _prepare_picking_vals(self, picking_type, location, location_dest, suffix, leg):
        self.ensure_one()
        picking_external_ref = self._get_picking_external_ref(leg)
        vals = {
            'picking_type_id': picking_type.id,
            'scheduled_date': self.schedule_date,
            'origin': picking_external_ref,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'adt_type': self._get_picking_adt_type_for_leg(leg),
            'adt_order_type': self.adt_order_type or False,
            'adt_external_ref': picking_external_ref,
            'internal_transfer_order_id': self.id,
            'internal_transfer_leg': leg,
            'internal_transfer_sequence': self._get_transfer_leg_sequence(leg),
            'adt_is_document_only': bool(self.document_only),
            'note': self.note or False,
            'desc_note': self.description or False,
            'adt_description': self.description or False,
        }
        partner = self._get_picking_partner(leg)
        if partner:
            vals['partner_id'] = partner.id
        dest_location = self._get_picking_adt_dest_location(leg)
        if dest_location:
            vals['adt_dest_location_id'] = dest_location.id
        return vals

    def _get_picking_origin(self, leg):
        self.ensure_one()
        return self._get_picking_external_ref(leg)

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
        # Manual ITO records do not carry an Acumatica transaction type.
        # Keep API-provided values unchanged, but label generated documents
        # from a manual order consistently as Internal Transfer.
        return self.adt_transaction_type or 'Internal Transfer'

    def _get_picking_adt_type_for_leg(self, leg):
        self.ensure_one()
        if self.transfer_type == 'transfer_in' and self.adt_transaction_type == 'SOTR':
            return 'Receipt SOTR' if leg == 'receipt' else 'Transfer Shipment'
        return self._get_picking_adt_type()

    def _get_move_mapped_location_name(self, leg):
        self.ensure_one()
        if leg == 'delivery' and self.adt_transaction_type == 'Shipment Consignment':
            location = self.env['stock.location']
        elif leg == 'receipt':
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
        if self.adt_transaction_type == 'Shipment Consignment':
            return self.partner_id
        if (
            self.transaction_type == 'inter_warehouse'
            and self.adt_transaction_type != 'Vendor Return'
        ):
            side = 'source' if leg == 'receipt' else 'destination'
            return self._get_inter_warehouse_partner(side)
        if self.adt_transaction_type == 'Vendor Return':
            return self.env['res.partner']
        if self.transaction_type not in ('consignment', 'vendor_return'):
            return self.env['res.partner']
        if leg == 'receipt':
            return self._get_warehouse_partner()
        return self.partner_id

    def _copy_move_to_picking(self, source_move, picking, location, location_dest):
        vals = {
            'name': source_move.name or source_move.product_id.display_name,
            'description_picking': (
                source_move.description_picking
                or source_move.name
                or source_move.product_id.display_name
            ),
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
            'adt_type': source_move.adt_type or self._get_picking_adt_type(),
            'product_note': source_move.product_note,
            'adt_dest_location': self._get_move_mapped_location_name(
                picking.internal_transfer_leg
            ),
        }
        if picking.adt_dest_location_id:
            vals['adt_dest_location_id'] = picking.adt_dest_location_id.id
        picking_move = self.env['stock.move'].create(vals)
        selected_lots = source_move.internal_transfer_scan_lot_ids.filtered(
            lambda lot: lot.product_id == picking_move.product_id
        )
        if selected_lots:
            picking_move.internal_transfer_scan_lot_ids = selected_lots
            if picking_move.product_id.tracking == 'serial':
                picking_move.lot_ids = picking_move.lot_ids | selected_lots
            else:
                move_line_vals = []
                for lot in selected_lots:
                    line_vals = picking_move._prepare_move_line_vals(quantity=0)
                    line_vals.update({'lot_id': lot.id, 'lot_name': lot.name})
                    move_line_vals.append(line_vals)
                self.env['stock.move.line'].create(move_line_vals)
        return picking_move

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

        # The explicit Pick -> Storage link can be added after Pick has
        # already been confirmed. Recompute the dependent move first so a
        # completed Pick releases Storage from ``waiting``.
        picking.move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel')
        )._recompute_state()
        if picking.state == 'draft':
            picking.action_confirm()
        if picking.move_ids.filtered(lambda move: move.state not in ('done', 'cancel')):
            picking.action_assign()

    def _prepare_transfer_out_delivery(self, picking):
        self.ensure_one()
        if not (
            self.transfer_type == 'transfer_out'
            and picking.internal_transfer_leg == 'delivery'
            and picking.picking_type_id.code == 'internal'
            and picking.state not in ('done', 'cancel')
        ):
            return False

        pack_picking = self._get_related_pickings().filtered(
            lambda item: item.internal_transfer_leg == 'pack'
            and item.state == 'done'
        ).sorted('internal_transfer_sequence')[-1:]
        if not pack_picking:
            return False

        transit_location = self.transit_location_id or self._get_or_create_transit_location()
        if not self.transit_location_id:
            self.transit_location_id = transit_location
        source_location = pack_picking.location_dest_id
        if (picking.location_id == source_location
                and picking.location_dest_id == transit_location
                and all(move.location_id == source_location
                        and move.location_dest_id == transit_location
                        for move in picking.move_ids)):
            return False

        if picking.state == 'assigned':
            picking.do_unreserve()
        picking.write({
            'location_id': source_location.id,
            'location_dest_id': transit_location.id,
        })
        picking.move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel')
        ).write({
            'location_id': source_location.id,
            'location_dest_id': transit_location.id,
        })
        return True

    def _prepare_transfer_in_receipt(self, picking):
        self.ensure_one()
        if not (
            self.transfer_type == 'transfer_in'
            and picking.internal_transfer_leg == 'receipt'
            and picking.state not in ('done', 'cancel')
        ):
            return False

        transit_location = self.transit_location_id or self._get_or_create_transit_location()
        if not self.transit_location_id:
            self.transit_location_id = transit_location

        active_moves = picking.move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel')
        )
        # This leg receives stock that the paired Transfer OUT has already
        # moved into transit. It must consume that stock like a normal
        # receipt, rather than start a new MTO procurement for the
        # transit-to-destination route. Keep move_orig_ids intact so any
        # explicit, valid predecessor dependency is still respected.
        active_moves.filtered(
            lambda move: move.procure_method != 'make_to_stock'
        ).write({'procure_method': 'make_to_stock'})
        if (
            picking.location_id == transit_location
            and all(move.location_id == transit_location for move in active_moves)
        ):
            return False

        if picking.state == 'assigned':
            picking.do_unreserve()
        picking.write({'location_id': transit_location.id})
        active_moves.write({'location_id': transit_location.id})
        return True

    def _sync_transfer_package_levels(self, picking):
        self.ensure_one()
        if not (
            picking.internal_transfer_leg == 'delivery'
            and picking.picking_type_id.code == 'internal'
        ):
            return

        packed_packages = self._get_related_pickings().filtered(
            lambda item: item.internal_transfer_leg == 'pack'
            and item.state == 'done'
        ).mapped('package_level_ids.package_id')
        for package in picking.move_line_ids.filtered(
            lambda line: line.state not in ('done', 'cancel') and line.package_id
        ).mapped('package_id') & packed_packages:
            package_lines = picking.move_line_ids.filtered(
                lambda line: line.state not in ('done', 'cancel')
                and line.package_id == package
            )
            if not package_lines or not picking._check_move_lines_map_quant_package(package):
                continue

            package_level = picking.package_level_ids.filtered(
                lambda level: level.package_id == package
            )[:1]
            if package_level:
                (package_lines - package_level.move_line_ids).write({
                    'package_level_id': package_level.id,
                })
                continue

            package_level = self.env['stock.package_level'].create({
                'picking_id': picking.id,
                'package_id': package.id,
                'move_line_ids': [(6, 0, package_lines.ids)],
                'company_id': picking.company_id.id,
            })

    def _auto_validate_pickings_by_leg(self, legs, shipment_picking=False):
        for order in self:
            pickings = order._get_related_pickings().filtered(
                lambda picking: picking.internal_transfer_leg in legs
                and picking.state not in ('done', 'cancel')
            ).sorted(lambda picking: picking.internal_transfer_sequence)
            for picking in pickings:
                if (
                    shipment_picking
                    and order.adt_transaction_type == 'Shipment Consignment'
                    and picking.internal_transfer_leg == 'receipt'
                ):
                    order._set_consignment_receipt_shipped_quantities(
                        picking,
                        shipment_picking,
                    )
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

    def action_auto_validate_transfer_out_receipt(self, shipment_picking=False):
        transfer_out_orders = self.filtered(
            lambda order: order.transfer_type == 'transfer_out'
        )
        return transfer_out_orders._auto_validate_pickings_by_leg(
            ('receipt',),
            shipment_picking=shipment_picking,
        )

    def _set_consignment_receipt_shipped_quantities(self, receipt_picking, shipment_picking):
        self.ensure_one()
        if not (
            self.adt_transaction_type in ('Shipment Consignment', 'Transfer Shipment')
            and shipment_picking.internal_transfer_order_id == self
            and shipment_picking.internal_transfer_leg == 'delivery'
            and shipment_picking.shipment_information in ('full_shipment', 'partial')
        ):
            return

        receipt_quantities = []
        for receipt_move in receipt_picking.move_ids.filtered(
            lambda move: move.state not in ('done', 'cancel')
        ):
            source_move = receipt_move.move_orig_ids.filtered(
                lambda move: move.picking_id == shipment_picking
            )[:1]
            if not source_move:
                source_move = shipment_picking.move_ids.filtered(
                    lambda move: self._get_move_match_key(move)
                    == self._get_move_match_key(receipt_move)
                )[:1]
            if not source_move:
                raise UserError(_(
                    'Tidak dapat mencocokkan move Direct Receipt untuk %s dengan Transfer OUT.'
                ) % receipt_move.product_id.display_name)

            target_quantity = source_move.product_uom._compute_quantity(
                source_move.shipped_qty,
                receipt_move.product_uom,
            )
            receipt_quantities.append((receipt_move, target_quantity))

        has_quantity_difference = any(
            float_compare(
                target_quantity,
                receipt_move.product_uom_qty,
                precision_rounding=receipt_move.product_uom.rounding,
            ) != 0
            for receipt_move, target_quantity in receipt_quantities
        )
        if has_quantity_difference and receipt_picking.state == 'assigned':
            receipt_picking.do_unreserve()

        for receipt_move, target_quantity in receipt_quantities:
            if float_compare(
                target_quantity,
                receipt_move.product_uom_qty,
                precision_rounding=receipt_move.product_uom.rounding,
            ) != 0:
                receipt_move.product_uom_qty = target_quantity

    def _create_transfer_picking(
        self, picking_type, location, location_dest, suffix, leg,
        previous_picking=False,
    ):
        self.ensure_one()
        if not location:
            raise ValidationError(
                'Internal Transfer Order %s tidak dapat membuat langkah %s: '
                'Source Location belum ditentukan.'
                % (self.display_name, suffix)
            )
        if not location_dest:
            raise ValidationError(
                'Internal Transfer Order %s tidak dapat membuat langkah %s: '
                'Destination Location belum ditentukan.'
                % (self.display_name, suffix)
            )
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
            lambda picking: picking.state not in ('done', 'cancel')
        )[:1]
        if not next_picking:
            return False

        vals = {
            'origin': self._get_picking_external_ref(leg),
            'adt_type': self._get_picking_adt_type_for_leg(leg),
            'adt_order_type': self.adt_order_type or False,
            'adt_external_ref': self._get_picking_external_ref(leg),
            'internal_transfer_order_id': self.id,
            'internal_transfer_leg': leg,
            'internal_transfer_sequence': self._get_transfer_leg_sequence(leg),
            'note': self.note or False,
            'desc_note': self.description or False,
            'adt_description': self.description or False,
        }
        if leg == 'delivery' and self.transfer_type == 'transfer_out':
            source_location = done_picking.location_dest_id
            transit_location = self._get_or_create_transit_location()
            if not self.transit_location_id:
                self.transit_location_id = transit_location
            if (
                next_picking.state == 'assigned'
                and (
                    next_picking.location_id != source_location
                    or next_picking.location_dest_id != transit_location
                )
            ):
                next_picking.do_unreserve()
            vals.update({
                'location_id': source_location.id,
                'location_dest_id': transit_location.id,
            })
        picking_type = self._get_internal_picking_type_for_leg(leg)
        if picking_type:
            vals['picking_type_id'] = picking_type.id
        partner = self._get_picking_partner(leg)
        vals['partner_id'] = partner.id if partner else False
        dest_location = self._get_picking_adt_dest_location(leg)
        vals['adt_dest_location_id'] = dest_location.id if dest_location else False
        next_picking.write(vals)
        if leg == 'delivery' and self.transfer_type == 'transfer_out':
            next_picking.move_ids.write({
                'location_id': source_location.id,
                'location_dest_id': transit_location.id,
            })
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
            if done_picking.internal_transfer_leg != 'pick':
                return False

            storage_picking = self.picking_ids.filtered(
                lambda picking: (
                    picking.internal_transfer_leg == 'receipt'
                    and picking.state != 'cancel'
                )
            )[:1]
            if not storage_picking:
                return False

            # The Storage picking is generated together with Pick, but it
            # must only become actionable after Pick is completed. Linking
            # the moves here also gives Storage access to the picked lots.
            self._link_picking_moves(done_picking, storage_picking)
            self._set_staged_picking_ready(storage_picking)
            return storage_picking

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
                    ('Pack', 'Pack Internal'),
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
        if done_picking.internal_transfer_leg == 'pack':
            route_picking = self._get_related_pickings().filtered(
                lambda picking: (
                    picking.internal_transfer_leg == 'delivery'
                    and picking.state not in ('done', 'cancel')
                )
            )[:1]
            if not route_picking:
                route_picking = self._adopt_next_picking(
                    done_picking,
                    'Transfer OUT',
                    'delivery',
                )
            if route_picking:
                self._prepare_transfer_out_delivery(route_picking)
                receipt_picking = self.picking_ids.filtered(
                    lambda picking: picking.internal_transfer_leg == 'receipt'
                )[:1]
                self._link_picking_moves(route_picking, receipt_picking)
                self._set_staged_picking_ready(route_picking)
                # Keep the Pack -> Internal Transfer dependency explicit.
                # A downstream picking can be confirmed/assigned while the
                # previous move is already done; re-linking here guarantees
                # that Odoo exposes it as the Pack's Next Transfer.
                self._link_picking_moves(done_picking, route_picking)
                return route_picking

            loading_dock = self._get_or_create_loading_dock_location(operational_warehouse)
            transit_location = self._get_or_create_transit_location()
            if not self.transit_location_id:
                self.transit_location_id = transit_location
            source_location = (
                done_picking.location_dest_id
                if self.transfer_type == 'transfer_out'
                else loading_dock
            )
            delivery_picking = self._create_transfer_picking(
                self._get_required_picking_type(
                    ('Internal Transfer', 'Internal Transfers', 'Transfer Internal'),
                    'internal',
                    warehouse=operational_warehouse,
                ),
                source_location,
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
            # The Next Transfer smart button is driven by move_dest_ids.  Do
            # this after the delivery is staged so Pack remains linked even
            # when the downstream move is assigned immediately.
            self._link_picking_moves(done_picking, delivery_picking)
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
            if (
                order.transaction_type == 'inter_warehouse'
                and order.adt_transaction_type != 'Vendor Return'
            ):
                order.partner_id = order._get_inter_warehouse_partner()
            transit_location = order._get_or_create_transit_location()
            if not order.transit_location_id:
                order.transit_location_id = transit_location
            if not order.move_ids:
                raise ValidationError('Operation line belum diisi.')
            order._sync_order_adt_dest_location()
            operational_warehouse = order._get_operational_warehouse()
            receipt_warehouse = order._get_receipt_warehouse()

            transaction_api = (order.adt_transaction_type or '').strip().lower().replace('_', ' ')
            is_one_step_same_location = (
                order.transaction_type == 'intra_warehouse'
                and order.location_id == order.location_dest_id
                and (
                    transaction_api in ('1-step', '1 step', 'transfer one step')
                    or any(
                        'transfer one step' in (move.adt_type or '').strip().lower()
                        for move in order.move_ids
                    )
                )
            )

            if is_one_step_same_location:
                warehouse = order._get_operational_warehouse()
                warehouse_code = warehouse.code if warehouse else False
                PickingType = self.env['stock.picking.type']
                direct_delivery_type = PickingType.resolve_document_only_picking_type(
                    target_operation_type='direct_delivery_order',
                    api_acumatica='transfer_one_step',
                    document_only=True,
                    warehouse_code=warehouse_code,
                    required=True,
                )
                direct_receipt_type = PickingType.resolve_document_only_picking_type(
                    target_operation_type='direct_receipt',
                    api_acumatica='transfer_one_step',
                    document_only=True,
                    warehouse_code=warehouse_code,
                    required=True,
                )
                picking_specs = [
                    (
                        direct_delivery_type,
                        order.location_id,
                        order.location_id,
                        'Direct Delivery',
                        'delivery',
                    ),
                    (
                        direct_receipt_type,
                        order.location_dest_id,
                        order.location_dest_id,
                        'Direct Receipt',
                        'receipt',
                    ),
                ]
            elif order.transaction_type == 'vendor_return':
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
                    'Storage',
                    'internal',
                    warehouse=receipt_warehouse,
                )
                picking_specs = [
                    (
                        order._get_required_picking_type(
                            ('Pick', 'Pick Internal'),
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
                        'Storage',
                        'receipt',
                    ),
                ]
            elif order.transfer_type == 'transfer_in':
                receipt_picking_type = order._get_required_picking_type(
                    ('Receipts', 'Receipt Internal'),
                    'receive',
                    warehouse=receipt_warehouse,
                    code=('incoming', 'internal'),
                )
                picking_specs = [
                    (
                        order._get_transfer_in_direct_delivery_picking_type(),
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
                receipt_picking_type = order._get_transfer_out_direct_receipt_picking_type()
                packing_zone = order._get_or_create_packing_zone_location(operational_warehouse)
                picking_specs = [
                    (
                        order._get_required_picking_type(
                            ('Pick', 'Pick Internal'),
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
        orders_to_generate = self.filtered(
            lambda order: not order._get_related_pickings()
        )
        for order in orders_to_generate.filtered(
            lambda item: (
                item.transaction_type == 'intra_warehouse'
                and not item._is_bad_stock_destination()
            )
        ):
            order._check_intra_source_products_available()

        self._sync_order_adt_dest_location()
        if orders_to_generate:
            orders_to_generate.action_generate_internal_pickings()
        existing_orders = self - orders_to_generate
        if existing_orders:
            existing_orders.write({'state': 'ready'})
        return True

    def _is_bad_stock_destination(self):
        self.ensure_one()
        destination = self.location_dest_id
        return bool(
            destination
            and destination.is_location_mapping
            and 'bad stock' in (destination.name or '').casefold()
        )

    def _check_intra_source_products_available(self):
        self.ensure_one()
        if self.transaction_type != 'intra_warehouse' or not self.location_id:
            return True

        products = self.move_ids.filtered(
            lambda move: move.state != 'cancel' and move.product_id
        ).mapped('product_id')
        if not products:
            return True

        quants = self.env['stock.quant'].search([
            ('product_id', 'in', products.ids),
            ('location_id', 'child_of', self.location_id.id),
        ])
        available_by_product = {}
        for quant in quants:
            available_by_product[quant.product_id.id] = (
                available_by_product.get(quant.product_id.id, 0.0)
                + quant.available_quantity
            )

        unavailable_products = products.filtered(
            lambda product: float_compare(
                available_by_product.get(product.id, 0.0),
                0.0,
                precision_rounding=product.uom_id.rounding,
            ) <= 0
        )
        if unavailable_products:
            product_names = '\n'.join(
                f'- {product.display_name}' for product in unavailable_products
            )
            raise UserError(_(
                'Produk berikut tidak memiliki stok tersedia di Source Location '
                '"%(location)s":\n%(products)s'
            ) % {
                'location': self.location_id.display_name,
                'products': product_names,
            })
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
        action['views'] = [
            (self.env.ref(
                'tijari_wms_18.stock_picking_tree_internal_transfer_order_columns'
            ).id, 'list'),
            (False, 'kanban'),
            (False, 'form'),
        ]
        return action


class StockMove(models.Model):
    _inherit = 'stock.move'

    internal_transfer_product_scan_code = fields.Char(
        string='Scan Product',
        store=False,
        help='Scan barcode or internal reference to select the operation product.',
    )
    internal_transfer_scan_lot_ids = fields.Many2many(
        comodel_name='stock.lot',
        relation='stock_move_internal_transfer_scan_lot_rel',
        column1='move_id',
        column2='lot_id',
        string='Scanned Lot/Serial Numbers',
        copy=False,
    )

    internal_transfer_order_id = fields.Many2one(
        comodel_name='internal.transfer.order',
        string='Internal Transfer Order',
        ondelete='cascade',
        index=True,
        copy=False,
    )
    internal_transfer_available_source_product_ids = fields.Many2many(
        related='internal_transfer_order_id.available_source_product_ids',
        string='ITO Available Source Products',
    )
    internal_transfer_transaction_type = fields.Selection(
        related='internal_transfer_order_id.transaction_type',
    )
    internal_transfer_intra_transfer_type = fields.Selection(
        related='internal_transfer_order_id.intra_transfer_type',
    )

    @api.onchange('product_id', 'internal_transfer_order_id')
    def _onchange_internal_transfer_order_locations(self):
        for move in self.filtered(
            lambda item: item.internal_transfer_order_id and not item.picking_id
        ):
            order = move.internal_transfer_order_id
            move.location_id = order.location_id
            move.location_dest_id = order.location_dest_id
            move.internal_transfer_scan_lot_ids = move.internal_transfer_scan_lot_ids.filtered(
                lambda lot: lot.product_id == move.product_id
            )

    @api.onchange('internal_transfer_product_scan_code')
    def _onchange_internal_transfer_product_scan_code(self):
        Product = self.env['product.product']
        Lot = self.env['stock.lot']
        Quant = self.env['stock.quant']
        for move in self:
            code = (move.internal_transfer_product_scan_code or '').strip()
            if not code:
                continue
            product = Product.search([
                '|', ('barcode', '=', code), ('default_code', '=', code),
            ], limit=1)
            order = move.internal_transfer_order_id
            scanned_lot = Lot.browse()
            if not product and order:
                lot_domain = [
                    ('name', '=', code),
                    ('product_id.tracking', 'in', ('lot', 'serial')),
                ]
                if order.company_id:
                    lot_domain.append(('company_id', 'in', [False, order.company_id.id]))
                candidate_lots = Lot.search(lot_domain)
                if (
                    order.transaction_type == 'intra_warehouse'
                    and order.intra_transfer_type == 'intra_group_transfer'
                ):
                    source_location = order.intra_location_id or order.location_id
                    available_products = order._get_available_source_products(source_location)
                    candidate_lots = candidate_lots.filtered(
                        lambda lot: lot.product_id in available_products
                    )
                source_location = (
                    (order.intra_location_id or order.location_id)
                    if order.transaction_type == 'intra_warehouse'
                    else order.location_id
                )
                if source_location and source_location.usage in ('internal', 'transit'):
                    candidate_lots = candidate_lots.filtered(
                        lambda lot: sum(Quant.search([
                            ('product_id', '=', lot.product_id.id),
                            ('lot_id', '=', lot.id),
                            ('location_id', 'child_of', source_location.id),
                            ('quantity', '>', 0),
                        ]).mapped('available_quantity')) > 0
                    )
                if len(candidate_lots) > 1:
                    raise ValidationError(
                        _('Kode lot %s cocok dengan lebih dari satu lot yang tersedia.') % code
                    )
                if candidate_lots:
                    scanned_lot = candidate_lots
                    product = scanned_lot.product_id

            if not product:
                raise ValidationError(
                    _('Kode %s tidak ditemukan sebagai barcode, SKU, atau lot/serial.') % code
                )

            if order and (
                order.transaction_type == 'intra_warehouse'
                and order.intra_transfer_type == 'intra_group_transfer'
            ):
                source_location = order.intra_location_id or order.location_id
                available_products = order._get_available_source_products(source_location)
                if product not in available_products:
                    raise ValidationError(
                        _('Product hasil scan tidak tersedia di Source Location.')
                    )

            if move.product_id and move.product_id != product:
                move.internal_transfer_scan_lot_ids = move.internal_transfer_scan_lot_ids.filtered(
                    lambda lot: lot.product_id == product
                )
            move.product_id = product
            if scanned_lot:
                move.internal_transfer_scan_lot_ids |= scanned_lot
            move.internal_transfer_product_scan_code = False


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
    is_ito_internal_transfer = fields.Boolean(
        string='ITO Internal Transfer',
        compute='_compute_is_ito_internal_transfer',
    )
    internal_transfer_sequence = fields.Integer(
        string='Internal Transfer Sequence',
        default=99,
        copy=False,
        index=True,
    )

    @api.depends('internal_transfer_order_id', 'internal_transfer_leg')
    def _compute_is_ito_internal_transfer(self):
        for picking in self:
            picking.is_ito_internal_transfer = bool(
                picking.internal_transfer_order_id
                and picking.internal_transfer_leg == 'delivery'
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
            and item.picking_type_id.name != 'Storage'
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

    def action_refresh_consignment_transfer_out(self):
        invalid_pickings = self.filtered(
            lambda picking: not (
                picking.internal_transfer_order_id
                and picking.internal_transfer_order_id.adt_transaction_type == 'Shipment Consignment'
                and picking.internal_transfer_leg == 'delivery'
                and picking.picking_type_id.code == 'internal'
                and picking.state not in ('done', 'cancel')
            )
        )
        if invalid_pickings:
            raise UserError(_(
                'Refresh from Pack hanya tersedia untuk Transfer OUT Shipment Consignment yang belum selesai.'
            ))

        for picking in self:
            order = picking.internal_transfer_order_id
            if not order._prepare_transfer_out_delivery(picking):
                pack_picking = order._get_related_pickings().filtered(
                    lambda item: item.internal_transfer_leg == 'pack'
                    and item.state == 'done'
                )
                if not pack_picking:
                    raise UserError(_('Dokumen Pack harus selesai sebelum package di-refresh.'))
            picking.action_assign()

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def button_validate(self):
        for picking in self:
            order = picking.internal_transfer_order_id
            if (
                order
                and order.validation_policy == 'validate_all'
                and picking.internal_transfer_leg in ('pack', 'delivery', 'receipt')
            ):
                api_transaction_type = (
                    (order.adt_transaction_type or '').strip().lower().replace('_', ' ')
                )
                is_same_location_transfer_one_step = (
                    order.transaction_type == 'intra_warehouse'
                    and order.location_id == order.location_dest_id
                    and (
                        api_transaction_type in ('1-step', '1 step', 'transfer one step')
                        or any(
                            'transfer one step' in (move.adt_type or '').strip().lower()
                            for move in order.move_ids
                        )
                    )
                )
                if (
                    is_same_location_transfer_one_step
                    and picking.internal_transfer_leg in ('delivery', 'receipt')
                ):
                    continue

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
        internal_transfer_pickings_to_reassign = self.env['stock.picking']
        for picking in internal_transfer_pickings.filtered(
            lambda item: (
                item.internal_transfer_order_id.transfer_type == 'transfer_out'
                and item.internal_transfer_leg == 'delivery'
                and item.picking_type_id.code == 'internal'
            )
        ):
            if picking.internal_transfer_order_id._prepare_transfer_out_delivery(picking):
                internal_transfer_pickings_to_reassign |= picking
        for picking in internal_transfer_pickings.filtered(
            lambda item: (
                item.internal_transfer_order_id.transfer_type == 'transfer_in'
                and item.internal_transfer_leg == 'receipt'
            )
        ):
            if picking.internal_transfer_order_id._prepare_transfer_in_receipt(picking):
                internal_transfer_pickings_to_reassign |= picking
        if internal_transfer_pickings_to_reassign:
            internal_transfer_pickings_to_reassign.action_assign()
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
                    and not (
                        picking.internal_transfer_leg == 'delivery'
                        and order.adt_transaction_type in (
                            'Shipment Consignment',
                            'Transfer Shipment',
                        )
                        and picking.picking_type_id.code == 'internal'
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
