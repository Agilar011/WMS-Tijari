from odoo import _, api, fields, models

class AcumaticaErrorMaster(models.Model):
    _name = 'acumatica.error.master'
    _description = 'AcumaticaErrorMaster'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name')
    data_type = fields.Selection([
        ('acumatica.customer.line', 'Customer'),
        ('warehouse', 'Warehouse & Location'),
        ('stock_item', 'Stock Item'),
        ('non_stock_item', 'Non-Stock Item'),
        ('uom', 'UOM'),
        ('vendor', 'Vendor'),
        ('inventory_stock', 'Detail Stock Acumatica'),
    ], string='Tipe Data')
    data_id = fields.Integer('Data ID')
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated',  'Updated'),
        ('rejected',  'Rejected'),
        ('error',    'Error'),
        ('solved',   'Solved'),
    ], string='Status')
    error_msg = fields.Char('Log', tracking=True)

    def action_open_record(self):
        self.ensure_one()
        name = dict(
            self._fields['data_type'].selection
        ).get(self.data_type)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Detail',
            'res_model': self.data_type,
            'res_id': self.data_id,
            'view_mode': 'form',
            'target': 'current',
        }
