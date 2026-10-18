from odoo import fields, models


class AcumaticaInventoryAdjustmentStaging(models.Model):
    _name = 'acumatica.inventory.adjustment.staging'
    _description = 'Staging Inventory Adjustment dari Acumatica'
    _order = 'id desc'

    acumatica_id = fields.Char(string='Acumatica ID', required=True, index=True)
    row_number = fields.Integer(string='Row Number')
    note = fields.Text(string='Note')
    ref_nbr = fields.Char(string='Reference Number', index=True)
    raw_data = fields.Text(string='Data InventoryAdjustmentGIDetails')
    is_used = fields.Boolean(string='Used', default=False, index=True)
    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')
    import_state = fields.Selection([
        ('staged', 'Staged'), ('error', 'Error'),
    ], default='staged', index=True)
    import_message = fields.Text(string='Import Message')
