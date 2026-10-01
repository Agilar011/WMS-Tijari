from odoo import fields, models


class AcumaticaShipmentTransferCompletedStaging(models.Model):
    _name = 'acumatica.shipment.transfer.completed.staging'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Staging Shipment Transfer Completed dari Acumatica'
    _rec_name = 'shipment_nbr'
    _order = 'id desc'

    acumatica_id = fields.Char(string='Acumatica ID', required=True, index=True)
    row_number = fields.Integer(string='Row Number')
    note = fields.Text(string='Note')
    building_id = fields.Char(string='Building ID', index=True)
    customer_name = fields.Char(string='Customer Name')
    inventory_nbr = fields.Char(string='Inventory Number')
    location_id = fields.Char(string='Location ID')
    location_name = fields.Char(string='Location Name')
    note_header = fields.Text(string='Note Header')
    note_header_id = fields.Char(string='Note Header ID')
    ship_date = fields.Datetime(string='Shipment Date')
    shipment_nbr = fields.Char(string='Shipment Number', index=True)
    shipment_qty = fields.Float(string='Shipment Quantity')
    shipment_type = fields.Char(string='Shipment Type', index=True)
    shipment_volume = fields.Float(string='Shipment Volume')
    shipment_weight = fields.Float(string='Shipment Weight')
    site_id_description = fields.Char(string='Site ID Description')
    status = fields.Char(string='Status', index=True)
    to_warehouse_id = fields.Char(string='To Warehouse ID')
    line_ids = fields.One2many('acumatica.shipment.transfer.completed.staging.line', 'staging_id', string='Details')
    selected = fields.Boolean(string='Pilih', default=True)
    import_state = fields.Selection([
        ('staged', 'Staged'), ('created', 'Created'), ('updated', 'Updated'),
        ('rejected', 'Rejected'), ('error', 'Error'),
    ], string='Status Import', default='staged', index=True)
    import_message = fields.Text(string='Generation Message')
    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null', index=True)
    sync_date = fields.Datetime(string='Tanggal Sync')

    _sql_constraints = [
        ('shipment_transfer_completed_unique', 'unique(shipment_nbr, config_id)',
         'Data Shipment Transfer Completed dari Acumatica sudah ada!'),
    ]

    def action_reset_pending(self):
        self.filtered(lambda record: record.import_state == 'error').write({
            'import_state': 'staged', 'import_message': False,
        })
        return True


class AcumaticaShipmentTransferCompletedStagingLine(models.Model):
    _name = 'acumatica.shipment.transfer.completed.staging.line'
    _description = 'Detail Staging Shipment Transfer Completed dari Acumatica'
    _order = 'staging_id, line_nbr'

    staging_id = fields.Many2one('acumatica.shipment.transfer.completed.staging', string='Shipment Transfer Completed', required=True, ondelete='cascade', index=True)
    acumatica_id = fields.Char(string='Acumatica ID', index=True)
    row_number = fields.Integer(string='Row Number')
    note = fields.Text(string='Note')
    line_description = fields.Text(string='Description')
    line_location = fields.Char(string='Line Location')
    line_nbr = fields.Integer(string='Line Number')
    line_note = fields.Text(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')
    line_quantity = fields.Float(string='Quantity')
    line_uom = fields.Char(string='UOM')
    config_id = fields.Many2one(related='staging_id.config_id', store=True, index=True)
    sync_date = fields.Datetime(related='staging_id.sync_date', store=True)
