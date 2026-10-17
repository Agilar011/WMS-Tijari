from odoo import fields, models


class AcumaticaInventoryAdjustmentStaging(models.Model):
    _name = 'acumatica.inventory.adjustment.staging'
    _description = 'Staging Inventory Adjustment dari Acumatica'
    _order = 'id desc'

    acumatica_id = fields.Char(string='Acumatica ID', required=True, index=True)
    row_number = fields.Integer(string='Row Number')
    note = fields.Text(string='Note')
    detail_ids = fields.One2many(
        'acumatica.inventory.adjustment.staging.detail', 'staging_id', string='Details'
    )
    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')
    import_state = fields.Selection([
        ('staged', 'Staged'), ('error', 'Error'),
    ], default='staged', index=True)
    import_message = fields.Text(string='Import Message')


class AcumaticaInventoryAdjustmentStagingDetail(models.Model):
    _name = 'acumatica.inventory.adjustment.staging.detail'
    _description = 'Detail Staging Inventory Adjustment dari Acumatica'
    _order = 'staging_id, row_number'

    staging_id = fields.Many2one(
        'acumatica.inventory.adjustment.staging', required=True, ondelete='cascade', index=True
    )
    acumatica_id = fields.Char(string='Acumatica ID')
    row_number = fields.Integer(string='Row Number')
    note = fields.Text(string='Note')
    ref_nbr = fields.Char(string='Reference Number', index=True)
    raw_data = fields.Text(string='Data Acumatica')
