# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    operation_category = fields.Selection([
        ('pick', 'Pick'),
        ('put', 'Put'),
        ('pack', 'Pack'),
        ('internal', 'Internal Transfer'),
        ('receive', 'Receive'),
        ('delivery', 'Delivery'),
        ('others', 'Others')
    ], string='Operation Category', required=False, default='others')

    is_default_api = fields.Boolean(string="Default Picking Type For API")
    is_document_only_api = fields.Boolean(string="Document Only API")

    @api.model
    def _normalize_document_only_operation(self, value):
        if not value:
            return False
        normalized = str(value).strip().lower().replace('-', '_').replace(' ', '_')
        aliases = {
            'direct_receipt': 'direct_receipt',
            'receipt': 'direct_receipt',
            'receive': 'direct_receipt',
            'incoming': 'direct_receipt',
            'direct_delivery_order': 'direct_delivery_order',
            'delivery': 'direct_delivery_order',
            'delivery_order': 'direct_delivery_order',
            'outgoing': 'direct_delivery_order',
        }
        return aliases.get(normalized)

    @api.model
    def _normalize_api_acumatica(self, value):
        if not value:
            return False
        return str(value).strip().lower().replace('-', '_').replace(' ', '_')

    @api.model
    def _get_document_only_operation_by_api(self):
        return {
            'po_receipt': 'direct_receipt',
            'receipt_change_item': 'direct_receipt',
            'inventory_received': 'direct_receipt',
            'inventory_receive': 'direct_receipt',
            'receipt_toko_pegang_do': 'direct_receipt',
            'transfer_in': 'direct_receipt',
            'so_transfer': 'direct_receipt',
            'sotr': 'direct_receipt',
            'vendor_return': 'direct_delivery_order',
            'so_shipment': 'direct_delivery_order',
            'so_shipment_toko_pegang_do': 'direct_delivery_order',
            'so_shipment_co': 'direct_delivery_order',
            'transfer_shipment': 'direct_delivery_order',
            'issue_change_item': 'direct_delivery_order',
            'inventory_issue': 'direct_delivery_order',
            'issue_change_item_discontinue': 'direct_delivery_order',
            'issue_po_return': 'direct_delivery_order',
            'po_return': 'direct_delivery_order',
            'transfer_one_step': 'direct_delivery_order',
            'transfer_two_step': 'direct_delivery_order',
            'credit_memo_consignment': 'direct_delivery_order',
        }

    @api.model
    def _get_document_only_picking_type(self, operation, warehouse_code=False, required=True):
        operation = self._normalize_document_only_operation(operation)
        operation_vals = {
            'direct_receipt': ('Direct Receipt', 'DRC'),
            'direct_delivery_order': ('Direct Delivery Order', 'DDO'),
        }
        if operation not in operation_vals:
            if required:
                raise UserError(_("Unsupported document only operation: %s") % operation)
            return self.browse()

        name, _sequence_code = operation_vals[operation]
        domain = [
            ('name', '=', name),
        ]
        if warehouse_code:
            warehouse = self.env['stock.warehouse'].sudo().search([
                ('code', '=', warehouse_code),
            ], limit=1)
            if warehouse:
                domain.append(('warehouse_id', '=', warehouse.id))
        picking_type = self.sudo().search(domain, limit=1)
        if not picking_type and warehouse_code:
            picking_type = self.sudo().search([
                ('name', '=', name),
            ], limit=1)
        if not picking_type and required:
            raise UserError(_("No document only picking type configured for %s") % name)
        return picking_type

    @api.model
    def resolve_document_only_picking_type(
        self,
        target_picking_type_id=False,
        target_operation_type=False,
        api_acumatica=False,
        document_only=False,
        warehouse_code=False,
        required=False,
    ):
        if target_picking_type_id:
            picking_type = self.sudo().browse(int(target_picking_type_id)).exists()
            if picking_type:
                return picking_type
            if required:
                raise UserError(_("Target picking type not found: %s") % target_picking_type_id)

        operation = self._normalize_document_only_operation(target_operation_type)
        if not operation and document_only:
            operation = self._get_document_only_operation_by_api().get(
                self._normalize_api_acumatica(api_acumatica)
            )
        if operation:
            return self._get_document_only_picking_type(
                operation,
                warehouse_code=warehouse_code,
                required=required,
            )
        if required:
            raise UserError(_("Document only operation type is not provided"))
        return self.browse()

    # def get_action_picking_tree_draft(self):
    #     self.ensure_one()

    #     action = self._get_action("stock.stock_picking_action_picking_type")

    #     ctx = action.get("context", {})
    #     if isinstance(ctx, str):
    #         from odoo.tools.safe_eval import safe_eval
    #         ctx = safe_eval(ctx)

    #     ctx.update({
    #         "search_default_draft": 1,
    #     })

    #     action["context"] = ctx

    #     return action
