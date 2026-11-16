# -*- coding: utf-8 -*-
from ast import literal_eval

from odoo import fields, models
from odoo.osv import expression


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _get_gather_domain(
        self,
        product_id,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=False,
    ):
        domain = super()._get_gather_domain(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
        )
        exact_source_location_id = self.env.context.get(
            'tijari_ito_exact_source_location_id'
        )
        if (
            exact_source_location_id
            and not strict
            and location_id.id == exact_source_location_id
        ):
            domain = expression.AND([
                domain,
                [('location_id', '=', exact_source_location_id)],
            ])
        return domain

    product_default_code = fields.Char(
        string='SKU',
        related='product_id.default_code',
        readonly=True,
    )
    product_name = fields.Char(
        string='Description',
        related='product_id.name',
        readonly=True,
    )

    def action_view_stock_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_move_line_action")
        action['domain'] = [
            '|',
                ('location_id.warehouse_id', '=', self.location_id.warehouse_id.id),
                ('location_dest_id.warehouse_id', '=', self.location_id.warehouse_id.id),
            ('lot_id', '=', self.lot_id.id),
            # '|',
        ]
        action['context'] = literal_eval(action.get('context'))
        action['context']['search_default_product_id'] = self.product_id.id
        return action
