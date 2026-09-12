import base64
import re
import traceback
import os
from PIL import Image
import qrcode
import io
import logging 
import json
import requests
from collections import defaultdict
from odoo import models, api, fields, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_compare
from odoo.addons.tijari_wms_18.controllers.controllers import WmsApiController
from odoo.tools.float_utils import float_is_zero

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Memberi label unik untuk menghindari warning 'Same label: Type (Acumatica)'
    adt_receipt_nbr = fields.Char(string='Receipt Nbr (Acumatica)')
    adt_vendor_code = fields.Char(string='VendorID (Acumatica)')
    adt_partner_ref = fields.Char(string='Vendor Ref (Acumatica)')
    adt_branch_warehouse = fields.Char(string='Branch (Acumatica)')
    adt_actual_qty = fields.Float(string='Control Qty (Acumatica)')
    adt_is_hold = fields.Boolean(string='Hold (Acumatica)')
    adt_inventory_ref = fields.Char(string='Inventory Ref Nbr (Acumatica)')
    adt_acumatica_write_date = fields.Datetime(string='Last Modified (Acumatica)')
    adt_header_location_code = fields.Char(string='Header Location (Acumatica)')
    adt_post_period = fields.Char(string='Post Period (Acumatica)')
    adt_status = fields.Char(string='Status (Acumatica)')
    adt_total_qty = fields.Float(string='Total Qty (Acumatica)')
    
    adt_type = fields.Char(string='Type (Acumatica)')
    
    adt_external_ref = fields.Char(string='External Ref (Acumatica)')
    adt_warehouse_code = fields.Char(string='Warehouse (Acumatica)')
    adt_external_id = fields.Char(string='UUID Header Acumatica', index=True)
    adt_to_warehouse_code = fields.Char(string='To Warehouse (Acumatica)')
    adt_from_warehouse_code = fields.Char(string='From Warehouse (Acumatica)')
    adt_description = fields.Char(string='Description (Acumatica)')
    adt_order_type = fields.Char(string='Order Type (Acumatica)')
    adt_order_nbr = fields.Char(string='Order Nbr (Acumatica)')
    adt_change_item_ref_nbr = fields.Char(string='Change Item Ref. Nbr (Acumatica)')
    adt_is_document_only = fields.Boolean(string='Is Document Only', index=True, copy=False)
    operation_category = fields.Selection(related='picking_type_id.operation_category', string='Operation Category', store=True, readonly=True)
    adt_destination_location_address = fields.Char(string='Destination Address')
    qr_code_image = fields.Binary(string='Sign')

    adt_actual_amount = fields.Float(string='Control Amount (Acumatica)')
    adt_total_amount = fields.Float(string='Total Amount (Acumatica)')

    adt_receipt_type = fields.Char(string='Receipt Type (Acumatica)')
    adt_trans_type = fields.Char(string='Trans Type (Acumatica)')
    sync_state = fields.Selection([
        ('ready', 'Ready'),
        ('not_ready', 'Not Ready'),
    ], string='Sync State', default='ready', readonly=True, help='Data acumatica yg tidak sesuai dengan master yg ada di wms akan masuk ke state Not Ready, dan record tidak bisa di proses sampai data master nya sudah sinkron.')

    sync_message = fields.Char(string='Sync Message', readonly=True, help='Keterangan jika ada data acumatica yang tidak sesuai dengan master yang ada di wms.')
    adt_shipment_status = fields.Char(string='Shipment Status (Acumatica)')
    destination_location = fields.Char(string='to delete field')
    created_by = fields.Char(string='Created by')
    approved_by = fields.Char(string='Approved by')
    created_by_id = fields.Many2one("res.users", string='Created by')
    approved_by_id = fields.Many2one("res.users", string='Approved by')
    user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_user_rel",
        column1="picking_id",
        column2="user_id",
        string="Responsible Users",
        domain=[("share", "=", False)],
    )

    pick_responsible_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_pick_responsible_rel",
        column1="picking_id",
        column2="user_id",
        string="Assigned Picker",
    )

    pack_responsible_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_pack_responsible_rel",
        column1="picking_id",
        column2="user_id",
        string="Assigned Packer",
    )

    do_responsible_ids = fields.Many2many(
        comodel_name="res.users",
        relation="stock_picking_do_responsible_rel",
        column1="picking_id",
        column2="user_id",
        string="Assigned Loader",
    )

    @api.model
    def _get_responsible_carry_over_fields(self):
        """Fields that describe "who is responsible" for this transfer.

        Kept in one place because two different mechanisms need the exact
        same field list to stay in sync:
        - the pick -> do "mirror" rule (assigning a Pick responsible also
          assigns them as a DO responsible), and
        - carrying these fields forward/backward across chained transfers
          (Pick -> Pack -> Delivery Order) so users don't re-enter them.
        """
        return [
            'pick_responsible_ids',
            'pack_responsible_ids',
            'do_responsible_ids',
            'user_ids',
        ]

    @api.onchange(
        "pick_responsible_ids",
        "pack_responsible_ids",
        "do_responsible_ids",
    )
    def _onchange_responsible_ids(self):
        for picking in self:
            # Requirement: assigning a Pick responsible also assigns them as
            # a DO responsible (additive, never removes someone already set
            # on do_responsible_ids that isn't in pick_responsible_ids).
            missing_do = picking.pick_responsible_ids - picking.do_responsible_ids
            if missing_do:
                picking.do_responsible_ids = picking.do_responsible_ids | missing_do

            responsible_users = (
                picking.pick_responsible_ids
                | picking.pack_responsible_ids
                | picking.do_responsible_ids
            )

            picking.user_ids = [(6, 0, responsible_users.ids)]

    can_edit_pack_responsible_ids = fields.Boolean(
        string="Can Edit Pack Responsible",
        compute="_compute_can_edit_pack_responsible_ids",
        help="Technical field driving the view: only a user who is themself "
             "listed in this transfer's Penanggungjawab Pick may edit "
             "Penanggungjawab Pack here.",
    )

    def _compute_can_edit_pack_responsible_ids(self):
        current_user = self.env.user
        for picking in self:
            picking.can_edit_pack_responsible_ids = current_user in picking.pick_responsible_ids

    all_moves_picked = fields.Boolean(
        compute='_compute_all_moves_picked',
    )
    allowed_putaway_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_putaway_product_ids',
    )
    scan_product_button = fields.Boolean(string='Scan Product')
    scan_product_by_lot_button = fields.Boolean(
        string='Scan Product By Lot',
        compute='_compute_scan_product_by_lot_button',
    )
    putaway_product_id = fields.Many2one(
        'product.product', string="Product Name")
    allowed_putaway_lot_ids = fields.Many2many(
        'stock.lot',
        compute='_compute_allowed_putaway_lot_ids',
    )
    putaway_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="LOT Number",
        readonly=False,
        domain="[('id', 'in', allowed_putaway_lot_ids)]",
    )
    putaway_move_line_ids = fields.Many2many(
        comodel_name="stock.move.line",
        string="Stock Move Lines",
        compute='_compute_putaway_values',
        readonly=False,
    )
    putaway_move_ids = fields.Many2many(
        comodel_name="stock.move",
        string="Putaway Stock Moves",
        compute='_compute_putaway_move_ids',
    )
    putaway_progress_status = fields.Selection(
        [
            ('finished', 'Finished'),
            ('unfinished', 'Unfinished'),
        ],
        string='Status',
        compute='_compute_putaway_progress_status',
    )
    allowed_picker_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_picker_product_ids',
    )
    scan_picker_product_button = fields.Boolean(string='Scan Product')
    scan_picker_product_by_lot_button = fields.Boolean(
        string='Scan Product By Lot',
        compute='_compute_scan_product_by_lot_button',
    )
    picker_product_id = fields.Many2one(
        'product.product',
        string="Product Name",
    )
    allowed_picker_lot_ids = fields.Many2many(
        'stock.lot',
        compute='_compute_allowed_picker_lot_ids',
    )
    picker_lot_id = fields.Many2one(
        'stock.lot',
        string="LOT Number",
        domain="[('id', 'in', allowed_picker_lot_ids)]",
        readonly=False,
    )
    picker_progress_status = fields.Selection(
        [
            ('finished', 'Finished'),
            ('unfinished', 'Unfinished'),
        ],
        string='Status',
        compute='_compute_picker_progress_status',
    )
    picker_move_ids = fields.Many2many(
        comodel_name="stock.move",
        string="Stock Moves",
        compute='_compute_picker_values',
        readonly=True,
    )

    filtered_move_ids = fields.One2many(
        comodel_name="stock.move",
        string="Filtered Stock Moves",
        compute='_compute_filtered_move_ids',
    )

    def _compute_scan_product_by_lot_button(self):
        for picking in self:
            picking.scan_product_by_lot_button = True
            picking.scan_picker_product_by_lot_button = True

    available_package_ids = fields.Many2many(
        "stock.quant.package",
        compute="_compute_available_package_ids",
        string="Available Packages",
    )

    scanned_package_id = fields.Many2one(
        "stock.quant.package",
        string="Package Number",
    )

    filtered_package_level_id = fields.Many2one(
        'stock.package_level',
        string='Filtered Package Level',
        readonly=True
    )

    @api.onchange('scanned_package_id')
    def _onchange_scanned_package_id(self):
        for picking in self:
            picking.filtered_package_level_id = False

            if not picking.scanned_package_id:
                continue

            package_level = picking.package_level_ids.filtered(
                lambda p: p.package_id == picking.scanned_package_id
            )[:1]

            if package_level:
                picking.filtered_package_level_id = package_level

    scan_package_button = fields.Boolean(string="Scan Package")

    filtered_package_level_ids = fields.One2many(
        "stock.package_level",
        compute="_compute_filtered_package_level_ids",
    )

    def _sync_adt_quantities_from_moves(self):
        for picking in self:
            picking.update({
                'adt_total_qty': sum(picking.move_ids.mapped('product_uom_qty')),
                'adt_actual_qty': sum(picking.move_ids.mapped('quantity')),
            })

    @api.depends("package_level_ids")
    def _compute_available_package_ids(self):
        for picking in self:
            picking.available_package_ids = (
                picking.package_level_ids.mapped("package_id")
            )

    @api.depends(
        "package_level_ids",
        "scanned_package_id",
    )
    def _compute_filtered_package_level_ids(self):

        for picking in self:

            if not picking.scanned_package_id:

                picking.filtered_package_level_ids = (
                    picking.package_level_ids
                )

            else:

                picking.filtered_package_level_ids = (
                    picking.package_level_ids.filtered(
                        lambda p:
                        p.package_id
                        == picking.scanned_package_id
                    )
                )

    def write(self, vals):
        import_audit_fields = {
            field_name for field_name in vals
            if field_name in self._fields and field_name not in {
                'write_uid', 'write_date', 'message_follower_ids', 'activity_ids',
            }
        }
        import_audit_before = {
            picking.id: {
                field_name: picking[field_name]
                for field_name in import_audit_fields
            }
            for picking in self
        }
        if (
            'pick_responsible_ids' in vals
            and not self.env.context.get('tijari_responsible_sync')
            and self.env.user.has_group('tijari_wms_18.group_operator')
        ):
            raise UserError(_(
                "Hanya user non-operator yang dapat mengisi/mengubah Penanggungjawab Pick."
            ))

        if (
            'pack_responsible_ids' in vals
            and not self.env.context.get('tijari_responsible_sync')
        ):
            current_user = self.env.user
            not_allowed = self.filtered(lambda p: current_user not in p.pick_responsible_ids)
            if not_allowed:
                raise UserError(_(
                    "Hanya user yang terdaftar di Penanggungjawab Pick pada transfer "
                    "ini yang dapat mengisi/mengubah Penanggungjawab Pack. Anda belum "
                    "terdaftar sebagai Penanggungjawab Pick pada: %s",
                    ", ".join(not_allowed.mapped('name')),
                ))

        result = super().write(vals)
        if import_audit_fields and not self.env.context.get('skip_acumatica_import_log'):
            staging_models = (
                'acumatica.receipt.line', 'acumatica.inventory.recieved.line',
                'acumatica.transfer.line', 'acumatica.shipment.line',
                'acumatica.transfer.shipment.line', 'acumatica.transfer.one.step.line',
                'acumatica.transfer.two.step.line', 'acumatica.direct.transfer.staging',
                'acumatica.vendor.return.direct.transfer.staging',
                'acumatica.credit.memo.consignment.staging',
                'acumatica.invoice.consignment.staging', 'acumatica.inventory.issue.line',
                'acumatica.issue.line', 'acumatica.issue.po.return.line',
                'acumatica.kit.assembly', 'acumatica.shipment.gi.staging',
                'acumatica.shipment.completed.staging',
                'acumatica.sales.order.shipment.staging',
            )
            for picking in self:
                staging = self.env['acumatica.import.log.mixin'].browse()
                for model_name in staging_models:
                    try:
                        model = self.env[model_name]
                    except KeyError:
                        continue
                    if model and 'odoo_picking_id' in model._fields:
                        staging = model.search([('odoo_picking_id', '=', picking.id)], limit=1)
                        if staging:
                            break
                if not staging or not hasattr(staging, '_acumatica_post_import_log'):
                    continue
                changed_fields = []
                for field_name in import_audit_fields:
                    old_value = import_audit_before[picking.id].get(field_name)
                    new_value = picking[field_name]
                    field = picking._fields[field_name]
                    if field.type == 'many2one':
                        old_value = old_value.display_name if old_value else False
                        new_value = new_value.display_name if new_value else False
                    elif field.type in ('many2many', 'one2many'):
                        old_value = ', '.join(old_value.mapped('display_name'))
                        new_value = ', '.join(new_value.mapped('display_name'))
                    if old_value != new_value:
                        changed_fields.append({
                            'field_name': field_name,
                            'field_label': field.string,
                            'old_value': old_value,
                            'new_value': new_value,
                        })
                if changed_fields:
                    staging._acumatica_post_import_log(
                        'updated',
                        'Data stock.picking diperbarui dari import transaksi.',
                        picking,
                        changed_fields,
                    )
        if (
            not self.env.context.get('skip_user_ids_sync')
            and 'user_id' in vals
            and 'user_ids' not in vals
        ):
            self._sync_user_ids_from_user_id()
        if 'pick_responsible_ids' in vals:
            self._sync_do_responsible_from_pick()
        if (
            'user_ids' not in vals
            and {'pick_responsible_ids', 'pack_responsible_ids', 'do_responsible_ids'} & set(vals)
        ):
            self._sync_user_ids_from_responsible()
        if self._get_responsible_carry_over_fields_set() & set(vals):
            self._propagate_responsible_to_next_transfers()
        if 'adt_is_document_only' not in vals and ({'origin', 'adt_type'} & set(vals)):
            self._set_acumatica_document_only_flag()
        if not self.env.context.get('skip_document_only_picking_type_sync') and (
            {'adt_is_document_only', 'picking_type_id', 'origin', 'adt_type'} & set(vals)
        ):
            self._set_document_only_picking_type()
        return result

    def _sync_user_ids_from_user_id(self):
        for picking in self.filtered(lambda record: record.user_id and record.user_id not in record.user_ids):
            picking.with_context(skip_user_ids_sync=True).write({
                'user_ids': [(4, picking.user_id.id)],
            })

    @api.model
    def _get_responsible_carry_over_fields_set(self):
        return set(self._get_responsible_carry_over_fields())

    def _sync_do_responsible_from_pick(self):
        """Requirement: assigning Pick responsibles also assigns them as DO
        responsibles (additive - never removes an existing DO responsible
        that wasn't part of pick_responsible_ids)."""
        for picking in self:
            missing = picking.pick_responsible_ids - picking.do_responsible_ids
            if missing:
                picking.with_context(tijari_responsible_sync=True).write({
                    'do_responsible_ids': [(4, user.id) for user in missing],
                })

    def _sync_user_ids_from_responsible(self):
        """Keep user_ids as the union of pick/pack/do responsible for writes
        that don't go through the web client (the onchange only fires there).
        Mirrors _onchange_responsible_ids so API/automation writes end up
        with the same result a form save would produce."""
        for picking in self:
            responsible_users = (
                picking.pick_responsible_ids
                | picking.pack_responsible_ids
                | picking.do_responsible_ids
            )
            if set(responsible_users.ids) != set(picking.user_ids.ids):
                picking.with_context(tijari_responsible_sync=True).write({
                    'user_ids': [(6, 0, responsible_users.ids)],
                })

    def _propagate_responsible_to_next_transfers(self):
        """Carry pick/pack/do responsible + user_ids forward onto the next
        transfer(s) already created in the chain (e.g. Pick -> Pack -> DO),
        so users don't have to re-enter them there.

        Only fills fields that are still empty on the target picking - it
        never overwrites values a user (or an earlier propagation) already
        set on the downstream transfer.
        """
        fields_to_copy = self._get_responsible_carry_over_fields()
        for picking in self:
            next_transfers = picking._get_next_transfers()
            if not next_transfers:
                continue
            for target in next_transfers:
                vals = {}
                for field_name in fields_to_copy:
                    source_ids = picking[field_name].ids
                    if not source_ids or target[field_name]:
                        continue
                    vals[field_name] = [(6, 0, source_ids)]
                if vals:
                    target.with_context(tijari_responsible_sync=True).write(vals)

    def action_detailed_operations(self):
        action = super().action_detailed_operations()
        action.setdefault('context', {})
        action['context']['picking_type_name'] = self.picking_type_name
        return action

    @staticmethod
    def _document_only_value(value):
        if isinstance(value, bool):
            return value
        if value in (False, None, ''):
            return False
        return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'document only')

    def _set_acumatica_document_only_flag(self):
        staging_specs = [
            ('acumatica.receipt.line', 'receipt_nbr', 'document_only'),
            ('acumatica.transfer.line', 'reference_nbr', 'document_only'),
            ('acumatica.receipt.change.item.line', 'reference_nbr', 'document_only'),
            ('acumatica.inventory.recieved.line', 'reference_nbr', 'document_only'),
            ('acumatica.shipment.line', 'shipment_nbr', 'document_only'),
            ('acumatica.shipment.gi.staging', 'adt_ShipmentNbr', 'adt_DocumentOnly'),
            ('acumatica.issue.line', 'reference_nbr', 'document_only'),
            ('acumatica.inventory.issue.line', 'reference_nbr', 'document_only'),
            ('acumatica.issue.po.return.line', 'reference_nbr', 'document_only'),
            ('acumatica.transfer.shipment.line', 'shipment_nbr', 'document_only'),
            ('acumatica.transfer.one.step.line', 'reference_nbr', 'document_only'),
            ('acumatica.transfer.two.step.line', 'reference_nbr', 'document_only'),
            ('acumatica.direct.transfer.staging', 'adt_ReferenceNbr', 'adt_DocumentOnly'),
            ('acumatica.vendor.return.direct.transfer.staging', 'adt_ReferenceNbr', 'adt_DocumentOnly'),
            ('acumatica.credit.memo.consignment.staging', 'adt_ReferenceNbr', 'adt_DocumentOnly'),
            ('acumatica.receipt.external.line', 'reference_nbr', 'document_only'),
            ('acumatica.toko.pegang.do.line', 'reference_nbr', 'document_only'),
        ]
        for picking in self:
            if picking.adt_is_document_only or not picking.origin:
                continue
            is_document_only = False
            for model_name, reference_field, document_field in staging_specs:
                if model_name not in self.env.registry.models:
                    continue
                Model = self.env[model_name].sudo()
                if reference_field not in Model._fields or document_field not in Model._fields:
                    continue
                staging = Model.search([(reference_field, '=', picking.origin)], limit=1)
                if staging and self._document_only_value(staging[document_field]):
                    is_document_only = True
                    break
            if is_document_only:
                picking.sudo().with_context(skip_document_only_sync=True).write({'adt_is_document_only': True})
        self._set_document_only_picking_type()

    def _get_document_only_operation(self):
        self.ensure_one()
        picking_type_code = self.picking_type_id.code
        if picking_type_code == 'incoming':
            return 'direct_receipt'
        if picking_type_code == 'outgoing':
            return 'direct_delivery_order'

        adt_type = (self.adt_type or '').strip().lower()
        if any(token in adt_type for token in ('receipt', 'transfer in', 'return')):
            return 'direct_receipt'
        if any(token in adt_type for token in ('issue', 'shipment', 'delivery', 'transfer out')):
            return 'direct_delivery_order'
        return False

    def _set_document_only_picking_type(self):
        PickingType = self.env['stock.picking.type'].sudo()
        for picking in self:
            if not picking.adt_is_document_only:
                continue
            if picking.picking_type_id.is_document_only_api:
                continue

            operation = picking._get_document_only_operation()
            if not operation:
                continue

            warehouse = picking.picking_type_id.warehouse_id or picking.location_dest_id.warehouse_id or picking.location_id.warehouse_id
            document_only_type = PickingType.resolve_document_only_picking_type(
                target_operation_type=operation,
                document_only=True,
                warehouse_code=warehouse.code if warehouse else False,
            )
            if document_only_type and document_only_type != picking.picking_type_id:
                picking.with_context(skip_document_only_picking_type_sync=True).sudo().write({
                    'picking_type_id': document_only_type.id,
                })

    def _adt_preserve_document_only_destination(self):
        for picking in self:
            if not picking.adt_dest_location_id:
                continue
            if picking.location_dest_id != picking.adt_dest_location_id:
                picking.with_context(skip_document_only_sync=True).sudo().write({
                    'location_dest_id': picking.adt_dest_location_id.id,
                })
            picking.move_ids.sudo().write({
                'location_dest_id': picking.adt_dest_location_id.id,
                'adt_dest_location_id': picking.adt_dest_location_id.id,
            })
            picking.move_line_ids.sudo().write({
                'location_dest_id': picking.adt_dest_location_id.id,
            })


    wms_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('waiting', 'Waiting Another Operation'),
            ('confirmed', 'Waiting'),
            ('assigned', 'Ready'),
            ('waiting_response', 'Waiting For Shipment'),
            ('return_shipment', 'Returned Shipment'),
            ('done', 'Done'),
            ('cancel', 'Cancelled'),
        ],
        string="WMS State",
        compute="_compute_wms_state",
        store=True,
        copy=False,
        tracking=True,
    )

    shipment_information = fields.Selection([
        ('partial', 'Partial Shipment'),
        ('full_shipment', 'Full Shipment'),
        # ('full_return', 'Canceled'),
    ], string='Informasi TMS', help='Status shipment yang akan dikirimkan dari TMS.')

    status_ba = fields.Selection([
        ('conform', 'Confirmed'),
        ('discrepancy', 'Discrepancy'),],
    string='Status BA',
    )

    transaction_type = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
        ('internal', 'Internal'),
    ], string='Type transaksi', readonly=True)

    def _get_putaway_base_move_lines(self):
        self.ensure_one()

        return self.move_line_ids.filtered(
                lambda line: (
                    line.quantity > 0
                    and (line.lot_id or line.lot_name)
                    and line.picker_status == 'finished'
                )
            )

    def _get_putaway_move_lines(self):
        self.ensure_one()

        move_lines = self._get_putaway_base_move_lines()
        if self.putaway_product_id:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == self.putaway_product_id and line.quantity > 0
            )
        if self.putaway_lot_id:
            move_lines = move_lines.filtered(
                lambda line: line.lot_id == self.putaway_lot_id or line.lot_name == self.putaway_lot_id.name
            )

        return move_lines

    def _get_putaway_move_lines_for_product(self, product):
        self.ensure_one()

        move_lines = self._get_putaway_base_move_lines()
        if product:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == product and line.quantity > 0
            )
        return move_lines

    def _get_lots_from_move_lines(self, move_lines, products=False):
        lots = move_lines.lot_id
        lot_names = move_lines.filtered(
            lambda line: line.lot_name and not line.lot_id
        ).mapped('lot_name')
        if lot_names:
            domain = [('name', 'in', lot_names)]
            if products:
                domain.append(('product_id', 'in', products.ids))
            lots |= self.env['stock.lot'].search(domain)
        return lots

    def _get_putaway_lots(self):
        self.ensure_one()

        move_lines = self._get_putaway_base_move_lines()
        if self.putaway_product_id:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == self.putaway_product_id
            )
        return self._get_lots_from_move_lines(move_lines, move_lines.product_id)

    def _get_picker_base_moves(self):
        self.ensure_one()

        return self.move_ids_without_package.filtered(
            lambda move: (
                move._origin.id
                and move.state != 'cancel'
                and move.product_id
            )
        )

    def _get_picker_moves(self):
        self.ensure_one()

        moves = self._get_picker_base_moves()
        if self.picker_product_id:
            moves = moves.filtered(
                lambda move: move.product_id == self.picker_product_id
            )

        return moves

    def _get_picker_lots(self):
        self.ensure_one()

        moves = self._get_picker_moves()
        lots = moves.lot_ids | moves.move_line_ids.lot_id

        lot_names = moves.move_line_ids.filtered(
            lambda line: line.lot_name and not line.lot_id
        ).mapped('lot_name')
        if lot_names:
            domain = [('name', 'in', lot_names)]
            products = moves.product_id
            if products:
                domain.append(('product_id', 'in', products.ids))
            lots |= self.env['stock.lot'].search(domain)

        return lots

    @api.depends("state")
    def _compute_wms_state(self):
        for picking in self:
            if picking.state != "done" or picking.adt_type != "Sales Order Shipment":
                picking.wms_state = picking.state

    @api.depends(
        'move_line_ids',
        'move_line_ids.product_id',
        'move_line_ids.lot_id',
        'move_line_ids.quantity',
        'move_line_ids.picker_status',
    )
    def _compute_allowed_putaway_product_ids(self):
        for picking in self:
            picking.allowed_putaway_product_ids = picking._get_putaway_base_move_lines().product_id

    @api.depends(
        'putaway_product_id',
        'putaway_lot_id',
        'move_line_ids',
        'move_line_ids.product_id',
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
        'move_line_ids.quantity',
        'move_line_ids.picker_status',
    )
    def _compute_allowed_putaway_lot_ids(self):
        for picking in self:
            picking.allowed_putaway_lot_ids = picking._get_putaway_lots()

    @api.depends(
        'move_ids_without_package',
        'move_ids_without_package.product_id',
        'move_ids_without_package.state',
    )
    def _compute_allowed_picker_product_ids(self):
        for picking in self:
            picking.allowed_picker_product_ids = picking._get_picker_base_moves().product_id

    @api.depends(
        'picker_product_id',
        'move_ids_without_package',
        'move_ids_without_package.product_id',
        'move_ids_without_package.state',
        'move_ids_without_package.lot_ids',
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
    )
    def _compute_allowed_picker_lot_ids(self):
        for picking in self:
            picking.allowed_picker_lot_ids = picking._get_picker_lots()

    @api.depends(
        'picker_product_id',
        'picker_lot_id',
        'move_ids_without_package',
        'move_ids_without_package.product_uom_qty',
        'move_ids_without_package.quantity',
        'move_ids_without_package.product_uom',
        'move_ids_without_package.state',
    )
    def _compute_picker_progress_status(self):
        for picking in self:
            moves = picking._get_picker_moves()
            demand_qty = sum(moves.mapped('product_uom_qty'))
            picked_qty = sum(moves.mapped('quantity'))
            rounding = moves[:1].product_uom.rounding if moves else 0.01
            picking.picker_progress_status = (
                'finished'
                if moves and float_compare(picked_qty, demand_qty, precision_rounding=rounding) == 0
                else 'unfinished'
            )

    @api.depends(
        'putaway_product_id',
        'putaway_lot_id',
        'move_line_ids',
        'move_line_ids.product_id',
        'move_line_ids.lot_id',
        'move_line_ids.picker_status',
    )
    def _compute_putaway_values(self):
        for picking in self:
            move_lines = picking._get_putaway_move_lines()
            picking.putaway_move_line_ids = move_lines

    @api.depends(
        'putaway_product_id',
        'putaway_lot_id',
        'move_line_ids',
        'move_line_ids.move_id',
        'move_line_ids.product_id',
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
        'move_line_ids.quantity',
        'move_line_ids.picker_status',
        'move_line_ids.state',
    )
    def _compute_putaway_move_ids(self):
        for picking in self:
            picking.putaway_move_ids = picking._get_putaway_move_lines().mapped('move_id')

    @api.depends(
        'putaway_product_id',
        'move_line_ids',
        'move_line_ids.product_id',
        'move_line_ids.quantity',
        'move_line_ids.confirmation_quantity',
        'move_line_ids.picker_status',
        'move_line_ids.product_uom_id',
    )
    def _compute_putaway_progress_status(self):
        for picking in self:
            move_lines = picking._get_putaway_move_lines()
            picked_qty = sum(move_lines.mapped('quantity'))
            confirmation_qty = sum(move_lines.mapped('confirmation_quantity'))
            rounding = move_lines[:1].product_uom_id.rounding if move_lines else 0.01
            picking.putaway_progress_status = (
                'finished'
                if move_lines and float_compare(confirmation_qty, picked_qty, precision_rounding=rounding) == 0
                else 'unfinished'
            )

    @api.depends(
        'picker_product_id',
        'picker_lot_id',
        'move_ids_without_package',
        'move_ids_without_package.product_id',
        'move_ids_without_package.state',
    )
    def _compute_picker_values(self):
        for picking in self:
            picking.picker_move_ids = picking._get_picker_moves()

    @api.depends(
        'picker_product_id',
    )
    def _compute_filtered_move_ids(self):
        for picking in self:
            picking.filtered_move_ids = picking._get_picker_moves()

    @api.onchange('putaway_product_id')
    def _onchange_putaway_product_id(self):
        for picking in self:
            move_lines = picking._get_putaway_move_lines_for_product(picking.putaway_product_id)
            picking.putaway_move_line_ids = move_lines
            picking.putaway_lot_id = (
                move_lines.mapped('lot_id')[:1]
                if picking.putaway_product_id
                else False
            )

    @api.onchange('putaway_lot_id')
    def _onchange_putaway_lot_id(self):
        for picking in self:
            if not picking.putaway_lot_id:
                picking.putaway_product_id = False
                picking.putaway_move_line_ids = picking._get_putaway_move_lines()
                continue
            move_lines = picking._get_putaway_base_move_lines().filtered(
                lambda line: (
                    line.lot_id == picking.putaway_lot_id
                    or line.lot_name == picking.putaway_lot_id.name
                )
            )
            products = move_lines.product_id
            if products:
                picking.putaway_product_id = products[:1]
            picking.putaway_move_line_ids = picking._get_putaway_move_lines()

    @api.onchange('picker_product_id')
    def _onchange_picker_product_id(self):
        for picking in self:
            picking.picker_move_ids = picking._get_picker_moves()
            picking.picker_lot_id = picking._get_picker_lots()[:1] if picking.picker_product_id else False

    @api.onchange('picker_lot_id')
    def _onchange_picker_lot_id(self):
        for picking in self:
            if not picking.picker_lot_id:
                picking.picker_product_id = False
                picking.picker_move_ids = picking._get_picker_moves()
                continue
            moves = picking._get_picker_base_moves().filtered(
                lambda move: (
                    picking.picker_lot_id in move.lot_ids
                    or picking.picker_lot_id in move.move_line_ids.lot_id
                    or picking.picker_lot_id.name in move.move_line_ids.mapped('lot_name')
                )
            )
            products = moves.product_id
            if products:
                picking.picker_product_id = products[:1]
            picking.picker_move_ids = picking._get_picker_moves()

    def _set_document_only_done_quantities(self):
        MoveLine = self.env['stock.move.line'].sudo()
        for picking in self:
            for move in picking.move_ids.filtered(lambda line: line.state not in ('done', 'cancel')):
                quantity = move.product_uom_qty
                if not quantity:
                    continue

                move_lines = move.move_line_ids
                quantity_field = 'quantity' if 'quantity' in MoveLine._fields else 'qty_done'
                # move.write({
                #     'quantity': quantity,
                # })
                if move_lines:
                    done_lines = move_lines.filtered(lambda line: line[quantity_field] > 0)
                    if not done_lines:
                        done_lines = move_lines[-1]
                        done_lines.write({quantity_field: quantity})

                    for line in done_lines:
                        line_vals = {'picked': True}
                        if (
                            move.product_id.tracking != 'none'
                            and not line.lot_id
                            and not line.lot_name
                        ):
                            line_vals['lot_name'] = picking.origin or picking.name or 'DOCUMENT ONLY'
                        line.write(line_vals)
                else:
                    move_line_vals = {
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        quantity_field: quantity,
                        'picked': True,
                    }
                    if move.product_id.tracking != 'none':
                        move_line_vals['lot_name'] = picking.origin or picking.name or 'DOCUMENT ONLY'
                    MoveLine.create(move_line_vals)

                move.move_line_ids.flush_recordset([quantity_field, 'picked'])
                move.flush_recordset(['quantity', 'picked'])
                self.env.cr.execute(
                    "UPDATE stock_move_line SET picked = TRUE WHERE move_id = %s",
                    [move.id],
                )
                self.env.cr.execute(
                    "UPDATE stock_move SET picked = TRUE WHERE id = %s",
                    [move.id],
                )
                move.move_line_ids.invalidate_recordset(['picked'])
                move.invalidate_recordset(['picked'])

    def _process_document_only_validation_action(self, action):
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

    def action_validate_document_only_import(self, force=False):
        for picking in self:
            if force and not picking.adt_is_document_only:
                picking.sudo().write({'adt_is_document_only': True})
            if not picking.adt_is_document_only or picking.state in ('done', 'cancel'):
                continue
            if not picking.move_ids:
                raise UserError(_("Document only picking %s has no lines to validate.") % picking.display_name)

            picking._adt_preserve_document_only_destination()
            picking.action_confirm()
            picking.action_assign()
            picking.button_validate()
            picking._adt_preserve_document_only_destination()
            # picking._set_document_only_done_quantities()
            # action = picking.with_context().button_validate()
            # picking._process_document_only_validation_action(action)
        return True


# Function to foward adt_type from parent picking
    @api.model_create_multi
    def create(self, vals_list):
        # print("=" * 100)
        # print("CREATE PICKING")
        # traceback.print_stack(limit=15)        
        print('=' * 100)
        print("@api.model_create_multi")

        print(f"Self: {self}")
        print(f"Vals List: {vals_list}")

        # Karena vals_list adalah sebuah LIST, kita harus melakukan looping
        # for vals in vals_list:
        #     # Ambil nilai 'origin' dengan aman dari dictionary
        #     origin = vals.get('origin')
            
        #     if origin:
        #         # Perbaikan pencarian: menggunakan titik 'stock.picking' dan format domain yang benar
        #         parent_picking = self.env['stock.picking'].search([('origin', '=', origin)], limit=1)
                
        #         # Jika parent_picking ditemukan, salin nilai adt_type ke data baru
        #         if parent_picking and parent_picking.adt_type:
        #             vals['adt_type'] = parent_picking.adt_type

        # # Panggil fungsi super() dengan melewatkan vals_list yang sudah diperbarui
        pickings = super(StockPicking, self).create(vals_list)
        for picking, vals in zip(pickings, vals_list):
            if 'user_ids' not in vals:
                picking._sync_user_ids_from_user_id()
            if 'pick_responsible_ids' in vals:
                picking._sync_do_responsible_from_pick()
            if (
                'user_ids' not in vals
                and {'pick_responsible_ids', 'pack_responsible_ids', 'do_responsible_ids'} & set(vals)
            ):
                picking._sync_user_ids_from_responsible()
            if self._get_responsible_carry_over_fields_set() & set(vals):
                picking._propagate_responsible_to_next_transfers()
        pickings._set_acumatica_document_only_flag()
        pickings._set_document_only_picking_type()
        print(pickings)
        return pickings


    def action_put_in_pack(self, move_lines_to_pack=False):
        self.ensure_one()

        if self.env.context.get('sml_specific_default'):
            self = self.with_context(
                clean_context(self.env.context)
            )

        if self.state in ('done', 'cancel'):
            return super().action_put_in_pack(
                move_lines_to_pack=move_lines_to_pack
            )

        move_line_ids = self._package_move_lines(
            move_lines_to_pack=move_lines_to_pack
        )

        if not move_line_ids:
            raise UserError((
                "There is nothing eligible to put in a pack."
            ))

        # packages = self.env['stock.quant.package']
        # for move in move_line_ids.mapped('move_id'):

        #     lines = move_line_ids.filtered(
        #         lambda ml: ml.move_id == move
        #     )

        #     package = self._put_in_pack(lines)

        #     packages |= package

        # return True

        move_line_ids = move_line_ids.filtered(
            lambda line:
                line.quantity > 0
                and not line.result_package_id
        )

        if not move_line_ids:
            raise UserError(
                _("There is nothing eligible to put in a pack.")
            )

        # Group move line berdasarkan destination location.
        packages = self.env["stock.quant.package"]

        # Satu move line diproses satu per satu.
        for move_line in move_line_ids:
            package = self._put_in_pack(move_line)
            packages |= package

        return packages[-1] if packages else False
    
    def _put_in_pack(self, move_line_ids):
        """
        Create a package and package level for move lines that have
        the same destination location.

        Custom behavior:
        - Preserve the existing `location_dest_id`.
        - Do not recalculate putaway strategy during packing.
        """
        self.ensure_one()

        if not move_line_ids.location_dest_id:
            raise UserError(
                (
                    "Destination location is missing for product %s."
                ) % move_line_ids.product_id.display_name
            )

        package = self._get_put_in_pack_package()

        package_type = (
            move_line_ids.move_id
            .product_packaging_id
            .package_type_id
        )

        if package_type:
            package.package_type_id = package_type

        move_line_ids.write({
            "result_package_id": package.id,
        })
        # Buat package level untuk package tersebut.
        self.env["stock.package_level"].with_context(
            from_put_in_pack=True
        ).create({
            "package_id": package.id,
            "picking_id": self.id,
            "location_id": False,
            "location_dest_id": move_line_ids.location_dest_id.id,
            "move_line_ids": [
                (6, 0, move_line_ids.ids)
            ],
            "company_id": self.company_id.id,
        })

        return package

    def _get_put_in_pack_package(self):
        return self.env['stock.quant.package'].create({})

    def _check_sync_state(self):
        for picking in self:
            if picking.sync_state == 'not_ready':
                raise UserError(
                    f'Picking {picking.name} tidak bisa diproses karena data tidak lengkap: {picking.sync_message}'
                )

    # def action_confirm(self):
    #     self._check_sync_state()
    #     return super().action_confirm()
    
    def action_confirm(self):
        _logger.info(">>> action_confirm CALLED %s", self.ids)
        # for picking in self:
        #     if (
        #         picking.picking_type_name == 'Internal Transfers'
        #         and picking.location_id
        #         and picking.location_dest_id
        #         and picking.location_id == picking.location_dest_id
        #     ):
        #         raise ValidationError(
        #             _("Source Location dan Destination Location tidak boleh sama.")
        #         )

        marked_as_todo = self.filtered(lambda picking: picking.state == 'draft')
        res = super().action_confirm()
        self._adt_apply_dest_location_to_move_lines()
        self._remove_qty_move_line()

        # Transfer IN: ketika Receipt Internal di-Mark as Todo, otomatis
        # proses leg delivery yang menjadi pasangan transfer-nya.
        transfer_in_receipts = marked_as_todo.filtered(
            lambda picking: (
                picking.state in ('confirmed', 'waiting', 'assigned')
                and picking.internal_transfer_order_id
                and picking.internal_transfer_order_id.transfer_type == 'transfer_in'
                and picking.internal_transfer_leg == 'receipt'
                and picking.picking_type_id.name == 'Receipt Internal'
            )
        )
        for receipt in transfer_in_receipts:
            receipt.internal_transfer_order_id.action_auto_validate_transfer_in_delivery()
        
        for picking in self:
                    for move in picking.move_ids:
                        for line in move.move_line_ids:
                            print(line)
                            if line.lot_id:
                                print(line.lot_id)
                                print(f"write source_location: {line.lot_id.location_id.id} product_lot_id: {line.lot_id.id,}")
                                line.write({
                                    'source_location_id': line.lot_id.location_id.id or line.location_id.id,
                                    'product_lot_id': line.lot_id.id,
                                })        

        return res

    def _adt_apply_dest_location_to_move_lines(self):
        for picking in self:
            if not picking.adt_dest_location_id:
                continue

            for move in picking.move_ids_without_package:
                final_dest_location = move._adt_get_final_dest_location()
                if not final_dest_location:
                    continue

                if not move.adt_dest_location_id:
                    move.location_dest_id = picking.adt_dest_location_id
                    move.adt_dest_location_id = picking.adt_dest_location_id

                if move.move_line_ids:
                    move.move_line_ids.write({
                        'location_dest_id': final_dest_location.id,
                    })

    def _remove_qty_move_line(self):
        # for move in self.move_ids:
        #     move.action_generate_lot()
        #     for line in move.move_line_ids:
        #         line.quantity = 0
        for move in self.move_line_ids:
            move.quantity = 0

    adt_dest_location_id = fields.Many2one(
        "stock.location",
        domain="[('usage', '=', 'internal')]",
        string="Mapped Location",
    )
    internal_transfer_adt_dest_location_id = fields.Many2one(
        "stock.location",
        string="Mapped Location",
    )
    note_ba = fields.Text(string="Notes For Official Report")
    picking_type_name = fields.Char(string="Picking Type Name", related="picking_type_id.name", store=True)

    @api.onchange('internal_transfer_adt_dest_location_id')
    def _onchange_internal_transfer_adt_dest_location_id(self):
        for picking in self:
            if picking.picking_type_name != 'Internal Transfers':
                continue
            location = picking.internal_transfer_adt_dest_location_id
            picking.location_id = location
            picking.location_dest_id = location
            picking.adt_dest_location_id = location

    def _allow_custom_push_destination(self):
        self.ensure_one()
        # Untuk picking type incomine, kalo dibutuhkan untuk internal, manufacturing, dan lain lain bisa ditambahkan "self.picking_type_id.code in ["incoming", "internal", "manufacturing"]" atau yang lain sesuai kebutuhan
        return self.picking_type_id.code == "incoming"

    def action_send_email_hasil_picking(self):
        self.ensure_one()

        # partner = self.partner_id
        # if not partner or not partner.email:
        #     raise ValidationError('Partner belum memiliki email.')

        # Generate PDF dari report Odoo, lebih baik daripada panggil controller langsung
        controller = WmsApiController()
        response = controller.PrintWarehouseReceipt(id=self.id)

        if response.status_code != 200:
            raise UserError(f"Gagal mendapatkan PDF. Kode status: {response.status_code}")

        pdf_content = response.data
        pdf_base64 = base64.b64encode(pdf_content)

        attachment_new = self.env['ir.attachment'].sudo().create({
            'name': f"Picking {self.name}.pdf",
            'datas': pdf_base64.decode('utf-8'),
            'res_model': 'stock.picking',
            'res_id': self.id,
            'type': 'binary',
            'mimetype': 'application/pdf',
        })

        template = self.env.ref(
            'tijari_wms_18.email_template_stock_picking_custom',
            raise_if_not_found=False
        )

        return {
            'name': 'Kirim Email Berita Acara',
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'stock.picking',
                'default_res_ids': [self.id],
                'default_use_template': bool(template),
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_attachment_ids': [(6, 0, [attachment_new.id])],
                'tijari_hasil_picking_email': True,
            },
        }

    def action_print_warehouse_receipt(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/warehouse_receipt?id=' + str(self.id)
        action['target'] = 'new'
        return action

    def do_print_picking(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/warehouse_receipt?id=' + str(self.id)
        action['target'] = 'new'
        return action

    def action_open_stock_move_scan_wizard(self):
        self.ensure_one()

        wizard = self.env['stock.move.scan.wizard'].create({
            'picking_id': self.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': ('Scan Product'),
            'res_model': 'stock.move.scan.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    @api.depends('move_ids.picked')
    def _compute_all_moves_picked(self):
        for picking in self:
            moves = picking.move_ids
            picking.all_moves_picked = (
                bool(moves) and all(move.picked for move in moves)
            )

    def action_prepare_scan_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'adt_scan_qr_to_picking_product',
            'params': {
                'picking_id': self.id,
                'title': 'Scan Product QR Code',
            },
        }

    def action_prepare_scan_package(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'adt_scan_qr_to_picking_package',
            'params': {
                'picking_id': self.id,
                'title': 'Scan Package QR Code',
            },
        }

    @api.model
    def action_open_by_scanned_origin(self, scanned_code):
        origin = (scanned_code or '').strip()
        if not origin:
            raise ValidationError(_("Origin hasil scan kosong."))

        pickings = self.search([('origin', '=', origin)], order='id desc', limit=1)
        if not pickings:
            raise ValidationError(_("Stock Picking tidak ditemukan untuk nomor dokumen: %s") % origin)

        action = {
            'type': 'ir.actions.act_window',
            'name': _('Stock Picking: %s') % origin,
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
            'context': {
                'search_default_origin': origin,
            },
        }
        if len(pickings) == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': pickings.id,
            })
        return action

    def _find_product_by_scan_code(self, scan_code):
        Product = self.env['product.product']

        return Product.search([
            '|',
            ('barcode', '=', scan_code),
            ('default_code', '=', scan_code),
        ], limit=1)

    def _find_putaway_product_by_lot_scan_code(self, scan_code):
        self.ensure_one()
        StockLot = self.env['stock.lot']

        lots = StockLot.search([('name', '=', scan_code)])
        move_lines = self._get_putaway_base_move_lines().filtered(
            lambda line: (
                (lots and line.lot_id in lots)
                or (line.lot_name and line.lot_name == scan_code)
            )
        )

        if not move_lines:
            if lots:
                raise ValidationError(_("Lot hasil scan tidak ada di dokumen ini."))
            raise ValidationError(_("Lot tidak ditemukan untuk kode scan: %s") % scan_code)

        products = move_lines.product_id
        if len(products) > 1:
            raise ValidationError(_("Lot hasil scan mengarah ke lebih dari satu product."))

        return products[:1], move_lines, lots[:1]

    def _find_picker_product_by_lot_scan_code(self, scan_code):
        self.ensure_one()
        StockLot = self.env['stock.lot']

        lots = StockLot.search([('name', '=', scan_code)])
        moves = self._get_picker_base_moves().filtered(
            lambda move: (
                (lots and move.lot_ids and bool(move.lot_ids & lots))
                or move.move_line_ids.filtered(
                    lambda line: (
                        (lots and line.lot_id in lots)
                        or (line.lot_name and line.lot_name == scan_code)
                    )
                )
            )
        )

        if not moves:
            if lots:
                raise ValidationError(_("Lot hasil scan tidak ada di dokumen ini."))
            raise ValidationError(_("Lot tidak ditemukan untuk kode scan: %s") % scan_code)

        products = moves.product_id
        if len(products) > 1:
            raise ValidationError(_("Lot hasil scan mengarah ke lebih dari satu product."))

        return products[:1], moves, lots[:1]

    def action_apply_scanned_product(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product = self._find_product_by_scan_code(scanned_code)

        if not product:
            raise ValidationError("Product tidak ditemukan untuk kode scan: %s" % scanned_code)

        move_lines = self._get_putaway_move_lines_for_product(product)
        self.write({
            'putaway_product_id': product.id,
            'putaway_lot_id': move_lines.mapped('lot_id')[:1].id,
        })

        return {
            'product_id': product.id,
            'display_name': product.display_name,
        }

    def action_apply_scanned_product_by_lot(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product, move_lines, lot = self._find_putaway_product_by_lot_scan_code(scanned_code)

        self.write({
            'putaway_product_id': product.id,
            'putaway_lot_id': lot.id,
        })

        return {
            'product_id': product.id,
            'display_name': product.display_name,
            'lot_id': lot.id,
            'move_line_ids': move_lines.ids,
        }

    def action_apply_scanned_picker_product_by_lot(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product, picker_moves, lot = self._find_picker_product_by_lot_scan_code(scanned_code)

        self.write({
            'picker_product_id': product.id,
            'picker_lot_id': lot.id,
        })

        return {
            'product_id': product.id,
            'display_name': product.display_name,
            'move_ids': picker_moves.ids,
        }

    def action_apply_scanned_picker_product(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product = self._find_product_by_scan_code(scanned_code)

        if not product:
            raise ValidationError("Product tidak ditemukan untuk kode scan: %s" % scanned_code)

        picker_moves = self._get_picker_base_moves().filtered(
            lambda move: move.product_id == product
        )
        if not picker_moves:
            raise ValidationError(_("Product hasil scan tidak ada di dokumen ini."))

        self.write({
            'picker_product_id': product.id,
            'picker_lot_id': picker_moves.lot_ids[:1].id or picker_moves.move_line_ids.lot_id[:1].id,
        })

        return {
            'product_id': product.id,
            'display_name': product.display_name,
            'move_ids': picker_moves.ids,
        }

    def action_apply_scanned_package(self, scanned_code):
        self.ensure_one()

        scanned_code = (scanned_code or '').strip()

        package = self.available_package_ids.filtered(
            lambda available_package: available_package.name == scanned_code
        )[:1]

        if not package:
            raise ValidationError(
                "Package tidak ditemukan untuk kode scan: %s" % scanned_code
            )

        package_level = self.package_level_ids.filtered(
            lambda package_level: package_level.package_id == package
        )[:1]

        self.write({
            "scanned_package_id": package.id,
            "filtered_package_level_id": package_level.id or False,
        })

        wizard = False

        if package_level:
            wizard = self.env[
                "package.level.detail.wizard"
            ].create({
                "package_level_id": package_level.id,
                "status": (
                    "finished"
                    if package_level.status == "finished"
                    else "unfinished"
                ),
                "package_id": package_level.package_id.id,
                "move_line_ids": [
                    (6, 0, package_level.move_line_ids.ids)
                ],
            })

        return {
            "package_id": package.id,
            "package_level_id": package_level.id or False,
            "package_detail_wizard_id": wizard.id if wizard else False,
            "display_name": package.display_name,
        }
    
    def action_mark_as_done(self):
        self.ensure_one()
        
        if self.wms_state != "return_shipment":
            raise UserError(
                _("Only documents in Returned Items state can be completed.")
            )
    
        return_picking = self.env["stock.picking"].search([
            ("return_id", "=", self.id)
        ], limit=1)
    
        if not return_picking:
            raise UserError(
                _("Return document has not been created yet.")
            )
    
        if return_picking.state != "done":
            raise UserError(
                _("Please validate the Return document first.")
            )
    
        self.wms_state = "done"
    
        return True
    

    @api.onchange("state")
    def _onchange_state_update_wms_state(self):
        for picking in self:
            if picking.state == 'done':
                continue
            picking.wms_state = picking.state        


    def _format_datetime(self, dt):
        if not dt:
            return None

        if isinstance(dt, str):
            dt = Datetime.from_string(dt)

        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # ==========================================================
    # Prepare Payload
    # ==========================================================

    # def _prepare_loginext_payload(self):
    #     self.ensure_one()
    #     print(self)

    #     print(self.origin)

    #     header_to_send = self.env["loginext.staging.data"].search(
    #         [("odoo_shipment_number", "=", self.origin)],
    #         limit=1,
    #     )
    #     print(header_to_send)

    #     if not header_to_send:
    #         raise UserError("Data staging TMS tidak dapat ditemukan")
        
    #     return {
    #         "orderNo": header_to_send.loginext_order_no,
    #         "shipmentOrderDt": self._format_datetime(
    #             header_to_send.loginext_shipment_order_dt
    #         ),
    #         "shipmentOrderTypeCd": header_to_send.loginext_shipment_order_type_cd,
    #         "orderState": header_to_send.loginext_order_state,
    #         "distributionCenter": header_to_send.loginext_distribution_center,
    #         "returnBranch": header_to_send.loginext_return_branch,
    #         "packageWeight": str(header_to_send.loginext_package_weight or 0),
    #         "packageVolume": str(header_to_send.loginext_package_volume or 0),
    #         "preparationTime": 30,
    #         "paymentType": header_to_send.loginext_payment_type,
    #         "packageValue": str(header_to_send.loginext_package_value or 0),
    #         "numberOfItems": header_to_send.loginext_number_of_items or 0,
    #         "partialDeliveryAllowedFl": "Y" if header_to_send.loginext_partial_delivery_allowed_fl else "N",
    #         "returnAllowedFl": "Y" if header_to_send.loginext_return_allowed_fl else "N",
    #         "cancellationAllowedFl": "Y" if header_to_send.loginext_cancellation_allowed_fl else "N",
    #         "deliverServiceTime": '30',
    #         "deliverStartTimeWindow": self._format_datetime(header_to_send.loginext_deliver_start_time_window),
    #         "deliverEndTimeWindow": self._format_datetime(header_to_send.loginext_deliver_end_time_window),
    #         "deliveryType": header_to_send.loginext_delivery_type,
    #         "deliverBranch": header_to_send.loginext_deliver_branch,
    #         "deliverAccountCode": header_to_send.loginext_deliver_account_code,
    #         "deliverAccountName": header_to_send.loginext_deliver_account_name,
    #         "deliverApartment": header_to_send.loginext_deliver_apartment,
    #         "deliverStreetName": header_to_send.loginext_deliver_street_name,
    #         "deliverLocality": header_to_send.loginext_deliver_locality,
    #         "deliverCity": header_to_send.loginext_deliver_city,
    #         "deliverState": header_to_send.loginext_deliver_state,
    #         "deliverCountry": header_to_send.loginext_deliver_country,
    #         "deliverPinCode": header_to_send.loginext_deliver_pin_code,
    #         "deliverAddressTimezone": header_to_send.loginext_deliver_address_timezone,
    #         "deliverNotes": header_to_send.loginext_deliver_notes,
    #         "shipmentCrateMappings": [
    #             {
    #                 "crateCd": crate.loginext_crate_cd,
    #                 "crateName": crate.loginext_crate_name,
    #                 "crateType": crate.loginext_crate_type,
    #                 "crateWeight": crate.loginext_crate_weight,
    #                 "shipmentlineitems": [
    #                     {
    #                         "itemCd": item.loginext_item_cd,
    #                         "itemName": item.loginext_item_name,
    #                         "itemPrice": item.loginext_item_price,
    #                         "itemQuantity": item.loginext_item_quantity,
    #                         "itemType": item.loginext_item_type,
    #                         "itemWeight": item.loginext_item_weight,
    #                     }
    #                     for item in crate.item_ids
    #                 ],
    #             }
    #             for crate in header_to_send.crate_ids
    #         ],
    #     }

    # ==========================================================
    # POST API
    # ==========================================================

    def action_post_loginext(self):
        # print("=" * 80)
        # print("Sent LOGINEXT REQUEST")
        # self.wms_state = 'waiting_response'

        # LOGIN_URL = "https://api.loginextsolutions.com/LoginApp/login/authenticate"
        # CREATE_URL = "https://api.loginextsolutions.com/ShipmentApp/mile/v2/create"

        # USERNAME = "api.tms@aditya.co.id"
        # PASSWORD = "9CE5Q8Jz_#xXR"

        # body = [
        #     rec._prepare_loginext_payload()
        #     for rec in self
        # ]

        # print("=" * 80)
        # print("LOGINEXT REQUEST")
        # print("=" * 80)
        # print(json.dumps(body, indent=4))

        # session = requests.Session()

        # try:
        #     # ======================================================
        #     # LOGIN
        #     # ======================================================

        #     login_payload = {
        #         "userName": USERNAME,
        #         "password": PASSWORD,
        #         "sessionExpiryTimeout": "1",
        #     }

        #     login_response = session.post(
        #         LOGIN_URL,
        #         json=login_payload,
        #         timeout=30,
        #     )

        #     print("=" * 80)
        #     print("LOGINEXT LOGIN RESPONSE")
        #     print("=" * 80)
        #     print(f"Status : {login_response.status_code}")
        #     print(login_response.text)


        #     login_response.raise_for_status()
        #     www_authenticate = login_response.headers.get("WWW-Authenticate")
        #     # ======================================================
        #     # CREATE SHIPMENT
        #     # ======================================================

        #     headers = {
        #         "Content-Type": "application/json",
        #         "Accept": "application/json",
        #     }

        #     if www_authenticate:
        #         headers["WWW-Authenticate"] = www_authenticate

        #     print("Sent Response to Loginext")
        #     response = session.post(
        #         CREATE_URL,
        #         headers=headers,
        #         json=body,
        #         timeout=1,
        #     )

        #     print("=" * 80)
        #     print("LOGINEXT CREATE RESPONSE")
        #     print("=" * 80)
        #     print(f"Status : {response.status_code}")
        #     print(response.text)

        #     response.raise_for_status()

        #     print("=" * 80)
        #     print("END LOGINEXT REQUEST")
        #     print("=" * 80)

            res = self.button_validate()

            return res


        # except requests.exceptions.RequestException as e:
        #     _logger.exception(e)
        #     raise UserError(f"Loginext API Error\n\n{e}")

    def action_assign(self):
        _logger.info(">>> action_assign CALLED %s", self.ids)

        res = super().action_assign()

        for picking in self:
            for move in picking.move_ids:
                for line in move.move_line_ids:
                    print(line)
                    if line.lot_id:
                        print(line.lot_id)
                        # vals = {
                        #     'source_location_id': line.lot_id.location_id.id or line.location_id.id,
                        # }
                        # vals['product_lot_id'] = line.lot_id.id
                        # line.write(vals)
                        print(f"write source_location: {line.lot_id.location_id.id} product_lot_id: {line.lot_id.id,}")
                        line.write({
                            'source_location_id': line.lot_id.location_id.id or line.location_id.id,
                            'product_lot_id': line.lot_id.id,
                        })

        return res

    def action_mark_todo_and_check_availability(self):
        """Mobile-friendly single-tap replacement for "Mark as Todo" +
        "Check Availability" on Pick operations (see the button-hiding
        xpath in stock_picking_views.xml for the "Pick" condition).

        Deliberately NOT a blind `self.action_assign()` call:
        `action_assign` already confirms draft pickings internally, but
        it also raises a "Nothing to check the availability for"
        `UserError` when there is nothing left to reserve -- which
        *would* incorrectly fire right after a plain "Mark as Todo" on a
        picking that becomes fully assigned automatically during
        confirm. Instead this re-checks `show_check_availability` (the
        same computed field the core button's `invisible` attribute
        relies on) *after* confirming, and only calls `action_assign()`
        on pickings that genuinely still need it. Both core actions
        (`action_confirm`/`action_assign`, including the overrides
        above) are reused as-is, never reimplemented.
        """
        to_confirm = self.filtered(lambda picking: picking.state == 'draft')
        if to_confirm:
            to_confirm.action_confirm()

        to_check = self.filtered(lambda picking: picking.show_check_availability)
        if to_check:
            to_check.action_assign()

        return True

    def action_confirm_shipment(self):
        self.ensure_one()

        if not self.shipment_information:
            raise UserError(_("Shipment Information is required."))

        if self.shipment_information == "full_shipment":
            self.wms_state = "done"
            return

        self._generate_return_from_actual_qty()

        self.wms_state = "return_shipment"

    def button_validate(self):
        document_only_pickings = self.filtered(
            lambda picking: picking.adt_is_document_only or picking.picking_type_id.is_document_only_api
        )
        for picking in document_only_pickings.filtered(lambda item: item.state not in ('done', 'cancel')):
            picking._adt_preserve_document_only_destination()
            if picking.state == 'draft':
                picking.action_confirm()
            if picking.state in ('confirmed', 'waiting', 'assigned'):
                picking.action_assign()
            picking._adt_preserve_document_only_destination()
            picking._set_document_only_done_quantities()

        for picking in self:
            if picking.adt_is_document_only or picking.picking_type_id.is_document_only_api:
                continue
            # Pick harus diblokir sebelum validasi standar Odoo memproses
            # perpindahan stok apabila masih ada line yang belum Match.
            if picking.picking_type_id.name in ('Pick', 'Pick Internal', 'Pick Components'):
                picking._check_validate_requirements()
                picking._check_pick_quantity_vs_demand()
                picking._check_pick_confirmation_quantity()
            if picking.picking_type_id.name in ('Pack'):
                picking._check_pick_quantity_vs_demand()
            if picking.picking_type_id.name in ('Receipts', 'Receipt Internal'):
                picking._check_putaway_status_requirements()
                picking._check_picker_status_requirements()

            if picking.picking_type_id.name not in ('Pick', 'Receipts', 'Receipt Internal'):
                print(f"Run validate all except pick and receipt")
                # Lakukan perulangan untuk setiap stock.move yang ada di dalam picking
                for move in picking.move_ids:
                    # Jika move memiliki move_line_ids, lakukan update massal di level DB
                    for line in move.move_line_ids:
                        loc_code = str(line.location_id.unique_code or '').strip()
                        product_code = str(line.lot_id.name or '').strip()
                        vals = {
                            'confirmation_location_code': loc_code,
                            'confirmation_lot_code': product_code,
                            'matching': 'match',
                        }
                        print(f"Write vals = {vals}")

                        line.write(vals)

                        print(f"After write = {line.matching}")

                        print(f"After write line {line.id} = {line.matching} for picking: {picking.id}")

        if document_only_pickings:
            res = super(StockPicking, self.with_context(skip_sanity_check=True)).button_validate()
        else:
            res = super().button_validate()
        document_only_pickings._adt_preserve_document_only_destination()

        for rec in self:

            is_document_only = rec.adt_is_document_only or rec.picking_type_id.is_document_only_api
            if is_document_only:
                continue
            print(rec.picking_type_id.name)
            is_receipt_putaway = rec.picking_type_id.name in ('Receipts', 'Receipt Internal')
            for line in rec.move_line_ids:
                print(f">>> Validating line {line.id} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id},Picking id: {line.picking_id.id}, Picking Type: {line.picking_id.picking_type_id.name}, Status product: {line.picking_id.picking_type_id.operation_category}, Matching Status: {line.matching}") # Cek di terminal Odoo
                if not is_receipt_putaway:
                    line.lot_name = line.lot_id.name if line.lot_id else line.lot_name
                if not is_receipt_putaway and not line.lot_name:
                    print(f"Missing lot: {line}")
                    raise UserError(_("Validation blocked.\n Lot not Found Please generate lot for all lines before validating the picking."))
                
            if is_receipt_putaway:
                rec._check_putaway_status_requirements()
                rec._check_picker_status_requirements()
            else:
                rec._check_validate_requirements()
            operation_category = rec.picking_type_id.operation_category
            print(f">>> Validating picking {rec.id} - Picking Type: {rec.picking_type_id.name}, Operation Category: {operation_category}") # Cek di terminal Odoo

            # Hanya enforce untuk PUT dan DELIVERY
            if not is_receipt_putaway and operation_category in ['put', 'delivery']:
                for line in rec.move_line_ids:
                    # Jika belum dicek (invisible), tidak dianggap ok
                    print(f">>> Checking line {line.matching} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id.name if line.lot_id else 'N/A'}") # Cek di terminal Odoo
                    # line.matching = 'match'
                    print(f">>> Matching status for line {line.id}: {line.matching}") # Cek di terminal Odoo
                    if line.matching != 'match':
                        raise UserError(_(
                            "Validation blocked.\n\n"
                            "Line:\n"
                            f"- Product: {line.product_id.display_name}\n"
                            f"- Qty: {line.quantity or line.product_uom_qty}\n\n"
                            "Status: ❌ NOT MATCH\n\n"
                            "Silakan pastikan scan location dan/atau lot sudah benar."
                        ))

            if "Pick" in rec.picking_type_name:
                for move in rec.move_ids:
                    confirmation_qty = move.confirmation_quantity

                    for dest_move in move.move_dest_ids:
                        dest_move.write({
                            'product_uom_qty': confirmation_qty,
                            'quantity': confirmation_qty
                        })
            
            elif 'Pack' in rec.picking_type_name:
                for move in rec.move_ids:
                    for dest_move in move.move_dest_ids:
                        packaged_qty = sum(
                            ml.quantity
                            for ml in dest_move.move_line_ids
                            if ml.package_id
                        )
                        
                        dest_move.write({
                            "unpack_quantity": dest_move.quantity - packaged_qty
                        })
                                    
            if rec.picking_type_name in ['Delivery Orders'] and rec.adt_type in ['Sales Order Shipment', 'SO Shipment']:
                rec.wms_state = 'waiting_response'

            if (
                rec.state == "done"
                and rec.return_id
                and rec.return_id.wms_state == "return_shipment"
            ):
                
                rec.return_id.wms_state = "done"
                                             
            pickings = self.env["stock.picking"].search([])
            if rec.picking_type_id.code != "incoming":
                continue

            rec._check_putaway_quantity_vs_demand()

            storage_pickings = self.env["stock.picking"].search([
                ("origin", "ilike", rec.origin or rec.name),
                ("picking_type_id.code", "=", "internal"),
            ], limit=1)
            total_qty = sum(rec.move_ids.move_line_ids.mapped("quantity"))
            rec.write({
                'adt_total_qty': total_qty
            })

            storage_pickings.write({
                "adt_dest_location_id": rec.adt_dest_location_id,
                "adt_type": rec.adt_type,
                "note" : rec.note,
            })

            for storage in storage_pickings:
                for storage_move in storage.move_ids:
                    receipt_move = rec.move_ids.filtered(
                        lambda m: m.product_id == storage_move.product_id
                    )[:1]

                    if receipt_move:
                        storage_move.write({
                            "product_note": receipt_move.product_note,
                        })

        return res

    def _check_pick_quantity_vs_demand(self):
        for picking in self:
            has_discrepancy = False
            for move in picking.move_ids.filtered(lambda item: item.state != 'cancel'):
                diff_qty = move.difference_quantity
                demand_qty = move.product_uom_qty
                picked_qty = move.quantity
                rounding = move.product_uom.rounding if move.product_uom else 0.01
                comparison = float_compare(
                    picked_qty,
                    demand_qty,
                    precision_rounding=rounding,
                )
                if comparison > 0:
                    raise UserError(
                        _(
                            "Product: %s\n"
                            "Lot: %s\n"
                            "Stored Qty: %s\n"
                            "Demand: %s\n\n"
                            "Quantity exceeds demand."
                        ) % (
                            move.product_id.display_name,
                            move.lot_ids.name or "-",
                            picked_qty,
                            demand_qty,
                        )
                    )
                
                if not float_is_zero(
                    diff_qty,
                    precision_rounding=rounding,
                ):
                    has_discrepancy = True

            picking.status_ba = 'discrepancy' if has_discrepancy else 'conform'

    def _check_pick_confirmation_quantity(self):
        for picking in self:

            for line in picking.move_line_ids:
                if line.confirmation_quantity <= 0:
                    raise UserError(_(
                        "Qty Diambil tidak boleh 0.\n\n"
                        "Product: %s"
                    ) % line.product_id.display_name)

                if line.confirmation_quantity > line.quantity:
                    raise UserError(_(
                        "Qty Diambil tidak boleh lebih besar "
                        "dari Qty Diterima.\n\n"
                        "Product: %s\n"
                        "Qty Diterima: %s\n"
                        "Qty Diambil: %s"
                    ) % (
                        line.product_id.display_name,
                        line.quantity,
                        line.confirmation_quantity,
                    ))
    
    def _check_putaway_quantity_vs_demand(self):
        for picking in self:
            if picking.picking_type_id.name not in ('Receipts', 'Receipt Internal'):
                continue

            has_discrepancy = False
            for move in picking.move_ids.filtered(lambda item: item.state != 'cancel'):
                demand_qty = move.product_uom_qty
                putaway_qty = move.confirmation_quantity
                rounding = move.product_uom.rounding if move.product_uom else 0.01
                comparison = float_compare(
                    putaway_qty,
                    demand_qty,
                    precision_rounding=rounding,
                )
                if comparison > 0:
                    raise UserError(
                        _(
                            "Product: %s\n"
                            "Lot: %s\n"
                            "Stored Qty: %s\n"
                            "Demand: %s\n\n"
                            "Quantity exceeds demand."
                        ) % (
                            move.product_id.display_name,
                            move.lot_ids.name or "-",
                            putaway_qty,
                            demand_qty,
                        )
                    )
                if comparison < 0:
                    has_discrepancy = True

            picking.status_ba = 'discrepancy' if has_discrepancy else 'conform'

    def _check_validate_requirements(self):
        self.ensure_one()
        _logger.info("Check Validate on = %s", self.id)
        if self.picking_type_id.name in ('Receipts', 'Receipt Internal', 'Internal Transfers'):
            return self._check_putaway_status_requirements() and self._check_picker_status_requirements()

        if self.picking_type_name not in ['Pick', 'Pick Internal']:
            return

        active_moves = self.move_ids.filtered(
            lambda move: move.state != "cancel"
        )

        unpicked_moves = active_moves.filtered(
            lambda move: not move.picked
        )

        unmatched_move_lines = active_moves.move_line_ids.filtered(
            lambda line: line.matching != "match"
        )

        error_messages = []

        if unpicked_moves:
            products = "\n".join(
                f"- {move.product_id.display_name}"
                for move in unpicked_moves
            )

            error_messages.append(
                (
                    "Semua product harus dalam kondisi picked.\n"
                    "Produk yang belum Terambil:\n%s"
                )
                % products
            )

        if unmatched_move_lines:
            lines = "\n".join(
                "- %s | Lot/Serial: %s | Matching: %s"
                % (
                    line.product_id.display_name,
                    line.lot_id.name or line.lot_name or "-",
                    dict(line._fields["matching"].selection).get(
                        line.matching,
                        line.matching or "-"
                    ),
                )
                for line in unmatched_move_lines
            )

            error_messages.append(
                (
                    "Semua product harus memiliki status matching "
                    "'Match'.\n"
                    "Detail produk yang belum match:\n%s"
                )
                % lines
            )

        if error_messages:
            raise UserError("\n\n".join(error_messages))

    def _get_acumatica_config(self):

        config = self.env["ir.config_parameter"].sudo()

        return {
            "auth_url": config.get_param("tijari.acumatica_auth_url"),
            "api_url": config.get_param("tijari.acumatica_api_url"),
            "login_endpoint": config.get_param("tijari.acumatica_endpoint_login"),
            "shipment_endpoint": config.get_param("tijari.acumatica_endpoint_shipment"),
            "username": config.get_param("tijari.acumatica_username"),
            "password": config.get_param("tijari.acumatica_password"),
            "company": config.get_param("tijari.acumatica_company"),
        }

    def action_login_acumatica(self):
        """Authenticate to Acumatica and return authenticated session."""

        config = self._get_acumatica_config()

        required = (
            "auth_url",
            "login_endpoint",
            "username",
            "password",
            "company",
        )

        for key in required:
            if not config.get(key):
                raise UserError(
                    _("Acumatica configuration '%s' is missing.") % key
                )

        login_url = (
            config["auth_url"]
            + config["login_endpoint"]
        )

        payload = {
            "name": config["username"],
            "password": config["password"],
            "company": config["company"],
        }

        session = requests.Session()

        _logger.info("=" * 80)
        _logger.info("ACUMATICA LOGIN")
        _logger.info("POST %s", login_url)

        try:

            response = session.post(
                login_url,
                json=payload,
                timeout=60,
            )

            _logger.info("Status Code : %s", response.status_code)
            _logger.info("Response    : %s", response.text)
            _logger.info("=" * 80)

            response.raise_for_status()

            return session

        except requests.exceptions.RequestException as exc:

            error_message = ""

            try:
                error_message = response.text
            except Exception:
                pass

            raise UserError(_(
                "Failed to login to Acumatica.\n\n%s"
            ) % (error_message or str(exc)))

    def action_get_shipment_completed_staging(self):
        self.ensure_one()

        ShipmentCompleted = self.env['acumatica.shipment.completed.staging']
        shipment_nbr = self.origin

        staging_data = ShipmentCompleted.search([('shipment_nbr','=',shipment_nbr)], limit=1)
        staging_data_line = staging_data.line_ids

        all_match = True
        for move in self.move_ids:
            staging_lines_for_product = staging_data_line.filtered(
                lambda line:
                    line.line_inventory_id == move.product_id.default_code
            )

            staging_qty = sum(
                staging_lines_for_product.mapped('line_quantity')
            )

            if not staging_qty:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Gagal Melakukan Update',
                        'message': f'Quantity {move.product_id.display_name} yang diupdate tidak memiliki quantity',
                        'type': 'warning',
                        'sticky': False,
                    }
                }

            if staging_qty < move.quantity:
                all_match = False
            
            elif staging_qty > move.quantity:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Gagal Melakukan Update',
                        'message': f'Quantity {move.product_id.display_name} yang diupdate tidak boleh melebihi quatity barang yang dikirim',
                        'type': 'warning',
                        'sticky': False,
                    }
                }
            
            move.shipped_qty = staging_qty

        self.shipment_information = (
            "full_shipment"
            if all_match
            else "partial"
        )

        self.action_confirm_shipment()   

    def action_fetch_actual_qty(self):
        self.ensure_one()

        data = self._get_actual_qty_data()

        self._apply_actual_qty(data)

    def action_fetch_partial_shipment(self):
        self.ensure_one()

        data = self._get_actual_qty_data(is_match=False)

        self._apply_actual_qty(data)


    def _get_actual_qty_data(self, is_match=True):
        """
        Temporary mock implementation.
        Replace with Acumatica API once available.
        """

        import random

        result = []

        for move in self.move_ids:

            planned_qty = move.product_uom_qty

            # is_match = random.random() < 0.5

            if is_match:
                actual_qty = planned_qty
            else:
                # shortage = random.randint(
                #     1,
                #     min(5, int(planned_qty))
                # )
                actual_qty = planned_qty - 1

            result.append({
                "inventory_id": move.product_id.default_code,
                "actual_qty": actual_qty,
            })

        return result
    
    def _apply_actual_qty(self, data):

        mapping = {
            item["inventory_id"]: item
            for item in data
        }

        all_match = True

        for move in self.move_ids:

            api = mapping.get(move.product_id.default_code)

            if not api:
                continue

            actual_qty = api["actual_qty"]

            move.shipped_qty = actual_qty

            if actual_qty != move.product_uom_qty:
                all_match = False

        self.shipment_information = "full_shipment" if all_match else "partial"

    def _generate_return_from_actual_qty(self):
        ReturnWizard = self.env["stock.return.picking"]

        wizard = ReturnWizard.with_context(
            active_id=self.id,
            active_ids=self.ids,
            active_model="stock.picking",
        ).create({})

        for line in wizard.product_return_moves:

            move = line.move_id

            actual = move.shipped_qty

            planned = move.quantity

            line.quantity = max(planned - actual, 0)

        result = wizard.action_create_returns()

        return result


    def _check_putaway_status_requirements(self):
        self.ensure_one()
        move_lines = self.move_line_ids.filtered(
            lambda line: line.state != "cancel" and line.quantity > 0
        )
        unfinished_lines = move_lines.filtered(
            lambda line: line.putaway_status != "finished"
        )

        if not unfinished_lines:
            return

        lines = "\n".join(
            "- %s | Qty: %s | Status: %s"
            % (
                line.product_id.display_name,
                line.quantity,
                dict(line._fields["putaway_status"].selection).get(
                    line.putaway_status,
                    line.putaway_status or "-"
                ),
            )
            for line in unfinished_lines
        )
        raise UserError(_(
            "Validation blocked.\n\n"
            "Semua move line putaway harus memiliki status 'Finished'.\n"
            "Move line yang belum finish:\n%s"
        ) % lines)

    def _check_picker_status_requirements(self):
        self.ensure_one()
        move_lines = self.move_line_ids.filtered(
            lambda line: line.state != "cancel" and line.quantity > 0
        )
        unfinished_lines = move_lines.filtered(
            lambda line: line.picker_status != "finished"
        )

        if not unfinished_lines:
            return

        lines = "\n".join(
            "- %s | Qty: %s | Status: %s"
            % (
                line.product_id.display_name,
                line.quantity,
                dict(line._fields["picker_status"].selection).get(
                    line.picker_status,
                    line.picker_status or "-"
                ),
            )
            for line in unfinished_lines
        )
        raise UserError(_(
            "Validation blocked.\n\n"
            "Semua move line picker harus memiliki status 'Finished'.\n"
            "Move line yang belum finish:\n%s"
        ) % lines)


    # ================================================================================================
# Temp Storage function create move line qr code        
# ================================================================================================

    def action_print_lot_number_line(self):
        self.ensure_one()

        if not self.lot_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Lot Number belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        lot_names = list({
            lot.name for lot in self.lot_ids if lot.name
        })

        if not lot_names:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Lot Number belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        self.create_qrcode_name()

        return {
            'type': 'ir.actions.act_url',
            'url': '/print/lot_number_move_line?ids=%s' % self.id,
            'target': 'new',
        }

    def create_qrcode_name(self):
        for rec in self:
            lot_names = list(set(
                rec.lot_ids.mapped('name')
            ))

            text = ', '.join(filter(None, lot_names))

            if text:
                rec.qr_code_image = rec.create_qrcode(text)

    def create_qrcode(self, text):
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../static/src/img/logo-company.png')
        )

        logo = Image.open(logo_path)

        basewidth = 80
        wpercent = basewidth / float(logo.size[0])
        hsize = int(float(logo.size[1]) * wpercent)

        logo = logo.resize((basewidth, hsize))

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H
        )

        qr.add_data(text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        img = img.resize((300, 300))

        pos = (
            (img.size[0] - logo.size[0]) // 2,
            (img.size[1] - logo.size[1]) // 2
        )

        img.paste(logo, pos)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        return base64.b64encode(buffer.getvalue()).decode()

    
class StockRule(models.Model):
    _inherit = "stock.rule"

    # Override method _push_prepare_move_copy_values untuk mengubah lokasi tujuan push berdasarkan adt_dest_location_id di stock.picking jika picking type incoming dan adt_dest_location_id terisi, sehingga bisa push ke lokasi selain location_dest_id yang sudah ditentukan di stock.rule
    def _push_prepare_move_copy_values(self, move_to_copy, new_date,):
        vals = super(StockRule, self)._push_prepare_move_copy_values(move_to_copy, new_date)
        print('='*300)
        print("_push_prepare_move_copy_values")
        print(f"Vals to create new picking: {vals}")
        # print(f"Parent Picking: {move_to_copy}")

        picking = move_to_copy.picking_id

        print(picking)
        if picking:
            # print("=== DAFTAR FIELD DAN NILAI ===")
            # for field_name, field_object in picking._fields.items():
            #     # Mengambil nilai field
            #     val = picking[field_name]
            
            #     if field_object.type == 'many2one' and val:
            #         print(f"{field_name}: {val.display_name} (ID: {val.id})")
            #     else:
            #         print(f"{field_name}: {val}")

            adt_type = picking.adt_type


            if adt_type:
                vals.update({
                    "adt_type": picking.adt_type if picking.adt_type else picking.name,
                    "transaction_type": picking.transaction_type,
                    # "adt_type": picking.adt_type
                })

        if (picking and picking.adt_dest_location_id and picking._allow_custom_push_destination()):
            vals.update({
                "location_dest_id": picking.adt_dest_location_id.id,
                "adt_dest_location_id": picking.adt_dest_location_id.id,
                # "adt_dest_location_id": picking.move_ids.adt_dest_location_id.id,
                "origin": picking.origin if picking.origin else picking.name
            })

        print(f"vals to update: {vals}")

        return vals


class StockPickingAcumaticaError(models.Model):
    _name = 'stock.picking.acumatica.error'
    _description = 'Error log untuk data picking yang diimport dari Acumatica'

    partner = fields.Char(string='Contact')
    operation_type = fields.Selection([
        ('receipt', 'Receipt'),
        ('delivery', 'Delivery'),
        ('internal', 'Internal'),
        ('manufacturing', 'Manufacturing'),
        ('inventory', 'Inventory'),
    ], string='Operation Type')

    location = fields.Char(string='Source Location')
    location_dest = fields.Char(string='Destination Location')
    scheduled_date = fields.Datetime(string='Scheduled Date')
    origin = fields.Char(string='Source Document')
    adt_total_qty = fields.Float(string='Total Qty (Acumatica)')
    adt_actual_qty = fields.Float(string='Actual Qty (Acumatica)')
    state = fields.Selection([
        ('new', 'New'),
        ('resolved', 'Resolved')
    ], default='new')

    api_acumatica = fields.Selection([
        ('po_receipt', 'PO Receipt'),
        ('so_transfer', 'SOTR Receipt'),
        ('receipt_change_item', 'Receipt Type Change Item'),
        ('inventory_received', 'Inventory Receive'),
        ('shipment_so', 'Shipment SO Return'),
        ('so_shipment', 'Sales Order Shipment'),
        ('transfer_shipment', 'Transfer Shipment'),
        ('issue_change_item', 'Issue Type Change Item'),
        ('inventory_issue', 'Inventory Issue'),
        ('issue_po_return', 'Issue Type PO Return'),
        ('transfer_one_step', 'Transfer Pinjaman (1 Step)'),
        ('transfer_two_step', 'Transfer Pinjaman (2 Step)'),
        ('direct_transfer', 'Direct Transfer'),
        ('vendor_return', 'Vendor Return'),
        ('credit_memo_consignment', 'Credit Memo Consignment'),
        ('invoice_consignment', 'Invoice Consignment'),
        ('toko_pegang_do', 'Toko Pegang DO'),
        ('inventory_receipt_transfer_wh_in', 'Inventory Receipt Transfer WH In'),
        ('kit_assembly', 'Kit Assembly'),
        ('inventory_stock', 'Inventory Stock'),
    ], string='API Acumatica', required=True)

    error_message = fields.Text(string='Error Message')
    line_ids = fields.One2many('stock.picking.acumatica.error.line', 'error_id', string='Error Lines')
    payload = fields.Json()

class StockPickingAcumaticaErrorLine(models.Model):
    _name = "stock.picking.acumatica.error.line"

    error_id = fields.Many2one(
        "stock.picking.acumatica.error",
        ondelete="cascade"
    )
    inventory_id = fields.Char(string="Product")
    product_name = fields.Char()
    qty = fields.Float(string="Demand")
    uom = fields.Char()
    payload = fields.Json()
