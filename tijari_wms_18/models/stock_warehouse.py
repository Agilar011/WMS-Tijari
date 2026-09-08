# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    adt_internal_transfer_enabled = fields.Boolean(
        string='Internal Transfer',
        help=(
            'Create warehouse operation types for Internal Transfer: '
            'Pick Internal, Pack Internal, Transfer Internal, and Receipt Internal.'
        ),
    )
    adt_document_only_enabled = fields.Boolean(
        string='Document Only',
        help=(
            'Create direct document-only operation types for this warehouse: '
            'Direct Receipt and Direct Delivery Order.'
        ),
    )
    adt_api_picking_type_enabled = fields.Boolean(
        string='SOP Aditya',
        help=(
            'Apply SOP Aditya: incoming 1 step, outgoing 3 steps, '
            'internal transfer active, document-only active, and configure '
            'Receipt, Pick, Pack, and Delivery operation types.'
        ),
    )
    adt_pick_internal_type_id = fields.Many2one(
        'stock.picking.type',
        string='Pick Internal Type',
        check_company=True,
        copy=False,
    )
    adt_pack_internal_type_id = fields.Many2one(
        'stock.picking.type',
        string='Pack Internal Type',
        check_company=True,
        copy=False,
    )
    adt_transfer_internal_type_id = fields.Many2one(
        'stock.picking.type',
        string='Transfer Internal Type',
        check_company=True,
        copy=False,
    )
    adt_receipt_internal_type_id = fields.Many2one(
        'stock.picking.type',
        string='Receipt Internal Type',
        check_company=True,
        copy=False,
    )
    adt_direct_receipt_type_id = fields.Many2one(
        'stock.picking.type',
        string='Direct Receipt Type',
        check_company=True,
        copy=False,
    )
    adt_direct_delivery_type_id = fields.Many2one(
        'stock.picking.type',
        string='Direct Delivery Type',
        check_company=True,
        copy=False,
    )
    adt_internal_transfer_route_id = fields.Many2one(
        'stock.route',
        string='Internal Transfer Route',
        ondelete='restrict',
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('adt_api_picking_type_enabled'):
                vals.update({
                    'reception_steps': 'one_step',
                    'delivery_steps': 'pick_pack_ship',
                    'adt_internal_transfer_enabled': True,
                    'adt_document_only_enabled': True,
                })
        warehouses = super().create(vals_list)
        warehouses._adt_sync_shipment_configuration()
        warehouses.filtered('adt_api_picking_type_enabled')._adt_sync_api_picking_type_configuration()
        return warehouses

    def write(self, vals):
        if vals.get('adt_internal_transfer_enabled') is False:
            self._adt_check_can_disable_internal_transfer()
        if vals.get('adt_document_only_enabled') is False:
            self._adt_check_can_disable_document_only()
        res = super().write(vals)
        if not self.env.context.get('skip_adt_shipment_sync'):
            trigger_fields = {
                'adt_internal_transfer_enabled',
                'adt_document_only_enabled',
                'active',
                'code',
                'name',
                'company_id',
            }
            if trigger_fields & set(vals):
                self._adt_sync_shipment_configuration()
        if 'adt_api_picking_type_enabled' in vals:
            self._adt_sync_api_picking_type_configuration()
        if (
            vals.get('adt_api_picking_type_enabled')
            and not self.env.context.get('skip_adt_sop_sync')
        ):
            self._adt_apply_sop_aditya()
        return res

    def _adt_apply_sop_aditya(self):
        """Apply the complete Aditya warehouse SOP when it is enabled."""
        warehouses = self.filtered('adt_api_picking_type_enabled')
        for warehouse in warehouses:
            sop_values = {
                'reception_steps': 'one_step',
                'delivery_steps': 'pick_pack_ship',
                'adt_internal_transfer_enabled': True,
                'adt_document_only_enabled': True,
            }
            if any(warehouse[field] != value for field, value in sop_values.items()):
                warehouse.with_context(skip_adt_sop_sync=True).write(sop_values)
            warehouse._adt_sync_shipment_configuration()
            warehouse._adt_sync_api_picking_type_configuration()

    def _adt_check_can_disable_internal_transfer(self):
        for warehouse in self:
            picking_type_ids = warehouse._adt_get_internal_transfer_picking_types().ids
            warehouse._adt_check_no_picking_for_disable(
                picking_type_ids,
                _('Internal Transfer'),
            )

    def _adt_check_can_disable_document_only(self):
        for warehouse in self:
            picking_type_ids = warehouse._adt_get_document_only_picking_types().ids
            warehouse._adt_check_no_picking_for_disable(
                picking_type_ids,
                _('Document Only'),
            )

    def _adt_check_no_picking_for_disable(self, picking_type_ids, label):
        if not picking_type_ids:
            return
        picking = self.env['stock.picking'].search([
            ('picking_type_id', 'in', picking_type_ids),
        ], limit=1)
        if picking:
            raise UserError(_(
                "%s tidak bisa dinonaktifkan karena sudah ada transaksi "
                "yang menggunakan operation type terkait: %s."
            ) % (label, picking.display_name))

    def _adt_get_internal_transfer_picking_types(self):
        self.ensure_one()
        picking_types = (
            self.adt_pick_internal_type_id
            | self.adt_pack_internal_type_id
            | self.adt_transfer_internal_type_id
            | self.adt_receipt_internal_type_id
        )
        if picking_types:
            return picking_types
        return self.env['stock.picking.type'].with_context(active_test=False).search([
            ('warehouse_id', '=', self.id),
            ('name', 'in', [
                'Pick Internal',
                'Pack Internal',
                'Transfer Internal',
                'Receipt Internal',
            ]),
        ])

    def _adt_get_document_only_picking_types(self):
        self.ensure_one()
        picking_types = self.adt_direct_receipt_type_id | self.adt_direct_delivery_type_id
        if picking_types:
            return picking_types
        return self.env['stock.picking.type'].with_context(active_test=False).search([
            ('warehouse_id', '=', self.id),
            ('name', 'in', [
                'Direct Receipt',
                'Direct Delivery Order',
            ]),
        ])

    def action_ensure_document_only_picking_types(self):
        warehouses = self or self.search([])
        warehouses.write({'adt_document_only_enabled': True})
        return True

    def _adt_sync_shipment_configuration(self):
        for warehouse in self.with_context(active_test=False):
            warehouse._adt_sync_internal_transfer_configuration()
            warehouse._adt_sync_document_only_configuration()
        return True

    def _adt_sync_api_picking_type_configuration(self):
        for warehouse in self:
            operation_types = (
                (warehouse.in_type_id, 'incoming', 'receive'),
                (warehouse.pick_type_id, 'internal', 'pick'),
                (warehouse.out_type_id, 'outgoing', 'delivery'),
            )
            for picking_type, code, category in operation_types:
                if not picking_type or picking_type.code != code:
                    continue
                picking_type.write({
                    'operation_category': category,
                    'is_api_config': warehouse.adt_api_picking_type_enabled,
                })
            # Operation type internal transfer & document-only khusus dipakai flow
            # API/internal, sehingga selalu eligible untuk resolver API.
            (warehouse._adt_get_internal_transfer_picking_types()).write({'is_api_config': True})
            (warehouse._adt_get_document_only_picking_types()).write({'is_api_config': True})

    def action_adt_sync_api_picking_types(self):
        """Button: terapkan is_api_config ke operation type warehouse terpilih."""
        self._adt_sync_api_picking_type_configuration()
        return True

    def _adt_get_internal_transfer_locations(self):
        self.ensure_one()
        self._create_missing_locations({})
        packing_zone = self.wh_pack_stock_loc_id
        loading_dock = self.wh_output_stock_loc_id
        if packing_zone and self.active:
            packing_zone.active = True
        if loading_dock and self.active:
            loading_dock.active = True
        return packing_zone, loading_dock

    def _adt_create_sequence(self, sequence_code):
        self.ensure_one()
        sequence_name = _('%(name)s Sequence %(code)s', name=self.name, code=sequence_code)
        sequence = self.env['ir.sequence'].sudo().create({
            'name': sequence_name,
            'prefix': '%s/%s/' % (self.code, sequence_code),
            'padding': 5,
            'company_id': self.company_id.id,
        })
        return sequence

    def _adt_get_or_create_picking_type(
        self,
        field_name,
        name,
        sequence_code,
        code,
        operation_category,
        location_src=False,
        location_dest=False,
        is_document_only=False,
        is_default_api=False,
        is_api_config=False,
    ):
        self.ensure_one()
        PickingType = self.env['stock.picking.type'].with_context(active_test=False)
        picking_type = self[field_name] or PickingType.search([
            ('warehouse_id', '=', self.id),
            ('name', '=', name),
            ('code', '=', code),
        ], limit=1)
        if not picking_type:
            max_sequence = PickingType.search_read(
                [('sequence', '!=', False)],
                ['sequence'],
                limit=1,
                order='sequence desc',
            )
            max_sequence = max_sequence and max_sequence[0]['sequence'] or 0
            picking_type = PickingType.create({
                'name': name,
                'code': code,
                'warehouse_id': self.id,
                'company_id': self.company_id.id,
                'sequence': max_sequence + 1,
                'sequence_code': sequence_code,
                'sequence_id': self._adt_create_sequence(sequence_code).id,
                'use_create_lots': False,
                'use_existing_lots': code == 'internal',
            })

        vals = {
            'active': self.active,
            'operation_category': operation_category,
            'is_document_only_api': is_document_only,
            'is_default_api': is_default_api,
            'is_api_config': is_api_config,
            'company_id': self.company_id.id,
        }
        if location_src:
            vals['default_location_src_id'] = location_src.id
        if location_dest:
            vals['default_location_dest_id'] = location_dest.id
        picking_type.write(vals)
        return picking_type

    def _adt_sync_internal_transfer_configuration(self):
        self.ensure_one()
        if not self.adt_internal_transfer_enabled:
            if self.adt_internal_transfer_route_id:
                self.adt_internal_transfer_route_id.rule_ids.write({'active': False})
                self.adt_internal_transfer_route_id.write({'active': False})
            return

        packing_zone, loading_dock = self._adt_get_internal_transfer_locations()
        transit_location = self.company_id.internal_transit_location_id
        if transit_location:
            transit_location.active = True

        pick_type = self._adt_get_or_create_picking_type(
            'adt_pick_internal_type_id',
            'Pick Internal',
            'PICKINT',
            'internal',
            'pick',
            self.lot_stock_id,
            packing_zone,
            is_api_config=True,
        )
        pack_type = self._adt_get_or_create_picking_type(
            'adt_pack_internal_type_id',
            'Pack Internal',
            'PACKINT',
            'internal',
            'pack',
            packing_zone,
            loading_dock,
            is_api_config=True,
        )
        transfer_type = self._adt_get_or_create_picking_type(
            'adt_transfer_internal_type_id',
            'Transfer Internal',
            'TRINT',
            'internal',
            'internal',
            loading_dock,
            transit_location or self.lot_stock_id,
            is_default_api=True,
            is_api_config=True,
        )
        receipt_type = self._adt_get_or_create_picking_type(
            'adt_receipt_internal_type_id',
            'Receipt Internal',
            'RCPTINT',
            'internal',
            'receive',
            transit_location or self.lot_stock_id,
            self.lot_stock_id,
            is_api_config=True,
        )
        self.with_context(skip_adt_shipment_sync=True).write({
            'adt_pick_internal_type_id': pick_type.id,
            'adt_pack_internal_type_id': pack_type.id,
            'adt_transfer_internal_type_id': transfer_type.id,
            'adt_receipt_internal_type_id': receipt_type.id,
        })
        if transit_location:
            self._adt_create_or_update_internal_transfer_route(
                pick_type,
                pack_type,
                transfer_type,
                receipt_type,
                packing_zone,
                loading_dock,
                transit_location,
            )

    def _adt_create_or_update_internal_transfer_route(
        self,
        pick_type,
        pack_type,
        transfer_type,
        receipt_type,
        packing_zone,
        loading_dock,
        transit_location,
    ):
        self.ensure_one()
        route = self.adt_internal_transfer_route_id
        route_vals = {
            'name': '%s: Internal Transfer (3 steps)' % self.name,
            'active': self.active,
            'warehouse_selectable': True,
            'product_selectable': False,
            'product_categ_selectable': True,
            'company_id': self.company_id.id,
            'sequence': 30,
        }
        if route:
            route.write(route_vals)
            route.rule_ids.write({'active': False})
        else:
            route = self.env['stock.route'].create(route_vals)
            self.with_context(skip_adt_shipment_sync=True).write({
                'adt_internal_transfer_route_id': route.id,
                'route_ids': [(4, route.id)],
            })

        rules = self._get_rule_values([
            self.Routing(self.lot_stock_id, packing_zone, pick_type, 'pull'),
            self.Routing(packing_zone, loading_dock, pack_type, 'push'),
            self.Routing(loading_dock, transit_location, transfer_type, 'push'),
            self.Routing(transit_location, self.lot_stock_id, receipt_type, 'push'),
        ], values={
            'active': True,
            'route_id': route.id,
            'propagate_cancel': True,
        })
        self._find_existing_rule_or_create(rules)

    def _adt_sync_document_only_configuration(self):
        self.ensure_one()
        if not self.adt_document_only_enabled:
            (self.adt_direct_receipt_type_id | self.adt_direct_delivery_type_id).write({'active': False})
            return

        direct_receipt = self._adt_get_or_create_picking_type(
            'adt_direct_receipt_type_id',
            'Direct Receipt',
            'DRC',
            'incoming',
            'receive',
            False,
            self.lot_stock_id,
            is_document_only=True,
            is_api_config=True,
        )
        direct_delivery = self._adt_get_or_create_picking_type(
            'adt_direct_delivery_type_id',
            'Direct Delivery Order',
            'DDO',
            'outgoing',
            'delivery',
            self.lot_stock_id,
            False,
            is_document_only=True,
            is_api_config=True,
        )
        self.with_context(skip_adt_shipment_sync=True).write({
            'adt_direct_receipt_type_id': direct_receipt.id,
            'adt_direct_delivery_type_id': direct_delivery.id,
        })
