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
            order.picking_count = len(order.picking_ids)

    @api.depends('picking_ids.move_ids')
    def _compute_generated_move_ids(self):
        for order in self:
            order.generated_move_ids = order.picking_ids.move_ids

    @api.onchange('location_id', 'location_dest_id')
    def _onchange_locations(self):
        for order in self:
            for move in order.move_ids:
                move.location_id = order.location_id
                move.location_dest_id = order.location_dest_id

    def _get_internal_picking_type(self):
        picking_type = self.env['stock.picking.type'].search([
            ('operation_category', '=', 'internal'),
            ('is_default_api', '=', True),
        ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('operation_category', '=', 'internal'),
            ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('is_default_api', '=', True),
            ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
            ], limit=1)
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

    def _prepare_picking_vals(self, picking_type, location, location_dest, suffix, leg):
        self.ensure_one()
        return {
            'picking_type_id': picking_type.id,
            'scheduled_date': self.schedule_date,
            'origin': '%s - %s' % (self.name, suffix),
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'adt_type': 'Internal Transfer',
            'adt_external_ref': self.name,
            'internal_transfer_order_id': self.id,
            'internal_transfer_leg': leg,
        }

    def _copy_move_to_picking(self, source_move, picking, location, location_dest):
        return self.env['stock.move'].create({
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
        })

    def action_generate_internal_pickings(self):
        Picking = self.env['stock.picking']
        for order in self:
            if order.picking_ids:
                continue

            picking_type = order._get_internal_picking_type()
            if not picking_type:
                raise ValidationError(
                    'Operation type internal belum dikonfigurasi.'
                )
            if not order.location_id or not order.location_dest_id:
                raise ValidationError(
                    'Source Location dan Destination Location harus diisi.'
                )
            transit_location = order._get_or_create_transit_location()
            if not order.transit_location_id:
                order.transit_location_id = transit_location
            if not order.move_ids:
                raise ValidationError('Operation line belum diisi.')

            delivery_picking = Picking.create(order._prepare_picking_vals(
                picking_type,
                order.location_id,
                transit_location,
                'Transfer OUT',
                'delivery',
            ))
            receipt_picking = Picking.create(order._prepare_picking_vals(
                picking_type,
                transit_location,
                order.location_dest_id,
                'Transfer IN',
                'receipt',
            ))

            for move in order.move_ids:
                order._copy_move_to_picking(
                    move,
                    delivery_picking,
                    order.location_id,
                    transit_location,
                )
                order._copy_move_to_picking(
                    move,
                    receipt_picking,
                    transit_location,
                    order.location_dest_id,
                )

            (delivery_picking | receipt_picking).action_confirm()
            order.picking_ids = [(6, 0, [delivery_picking.id, receipt_picking.id])]
            order.state = 'ready'

        return True

    def action_ready(self):
        orders_to_generate = self.filtered(lambda order: not order.picking_ids)
        if orders_to_generate:
            orders_to_generate.action_generate_internal_pickings()
        existing_orders = self - orders_to_generate
        if existing_orders:
            existing_orders.write({'state': 'ready'})
        return True

    def action_done(self):
        for order in self:
            if not order.picking_ids:
                raise ValidationError(
                    'Transfer belum dibuat. Set Ready terlebih dahulu untuk generate transfer.'
                )
            pending_pickings = order.picking_ids.filtered(
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
        action = self.env['ir.actions.actions']._for_xml_id(
            'stock.action_picking_tree_all'
        )
        action['domain'] = [('id', 'in', self.picking_ids.ids)]
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
            ('delivery', 'Transfer OUT'),
            ('receipt', 'Transfer IN'),
        ],
        string='Internal Transfer Leg',
        copy=False,
    )

    def button_validate(self):
        for picking in self:
            order = picking.internal_transfer_order_id
            if (
                order
                and order.validation_policy == 'validate_all'
                and picking.internal_transfer_leg == 'receipt'
            ):
                delivery_pickings = order.picking_ids.filtered(
                    lambda item: item.internal_transfer_leg == 'delivery'
                )
                if (
                    not delivery_pickings
                    or any(item.state != 'done' for item in delivery_pickings)
                ):
                    raise ValidationError(
                        'Transfer IN belum bisa divalidasi sebelum Transfer OUT selesai.'
                    )

        result = super().button_validate()

        for picking in self:
            order = picking.internal_transfer_order_id
            if (
                order
                and order.picking_ids
                and all(item.state == 'done' for item in order.picking_ids)
            ):
                order.state = 'done'

        return result
