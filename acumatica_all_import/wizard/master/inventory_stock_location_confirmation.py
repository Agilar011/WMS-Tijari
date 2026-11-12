from odoo import _, fields, models
from odoo.exceptions import UserError


class AcumaticaInventoryStockLocationConfirmation(models.TransientModel):
    _name = 'acumatica.inventory.stock.location.confirmation'
    _description = 'Generate Missing Inventory Stock Locations'

    operation = fields.Selection(
        [('receipt', 'Create Receipt'), ('opname', 'Create Opname')],
        required=True,
        readonly=True,
    )
    comparison_ids = fields.Many2many(
        'acumatica.inventory.stock.quant',
        'acum_stock_location_confirm_rel',
        'wizard_id',
        'comparison_id',
        string='Inventory Stock Comparison Lines',
        readonly=True,
    )
    confirmation_message = fields.Text(
        string='Confirmation',
        readonly=True,
    )

    def action_confirm_generate(self):
        self.ensure_one()
        comparison = self.comparison_ids.exists()
        if not comparison:
            raise UserError(_('The selected Inventory Stock Comparison lines are no longer available.'))

        rows = comparison.read(['warehouse_code', 'location_id', 'location_mapping_id'])
        comparison_model = self.env['acumatica.inventory.stock.quant']
        location_context = comparison_model._get_consignment_location_context(rows)
        if location_context['ambiguous_codes']:
            raise UserError(_(
                'More than one consignment location matches these codes: %(warehouse_codes)s.',
                warehouse_codes=', '.join(location_context['ambiguous_codes']),
            ))
        if location_context['missing_source_codes']:
            raise UserError(_(
                'These locations have no Consignment source row for automatic generation: %(warehouse_codes)s.',
                warehouse_codes=', '.join(location_context['missing_source_codes']),
            ))

        WarehouseLine = self.env['acumatica.warehouse.line'].sudo()
        generated = {}
        for code in location_context['missing_codes']:
            source_line = location_context['source_line_by_code'].get(code)
            if not source_line:
                continue
            location = WarehouseLine._create_location_consignment(source_line)
            if location:
                generated[code] = location
        if len(generated) != len(location_context['missing_codes']):
            unresolved = sorted(set(location_context['missing_codes']) - set(generated))
            raise UserError(_(
                'The system could not generate these locations: %(warehouse_codes)s.',
                warehouse_codes=', '.join(unresolved),
            ))

        if self.operation == 'receipt':
            return comparison.action_create_inventory()
        return comparison.action_create_opname()
