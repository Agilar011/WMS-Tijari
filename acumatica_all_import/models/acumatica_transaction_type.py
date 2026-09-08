from odoo import fields, models


class AcumaticaTransactionType(models.Model):
    _name = 'acumatica.transaction.type'
    _description = 'Acumatica API Transaction Type'
    _rec_name = 'name'
    _order = 'config_type, trans_type, source_field'

    name = fields.Char(required=True)
    config_id = fields.Many2one(
        'acumatica.config',
        string='API Config',
        required=True,
        ondelete='cascade',
    )
    config_type = fields.Selection(
        related='config_id.config_type',
        string='Config Type',
        store=True,
        readonly=True,
    )
    endpoint_name = fields.Char(readonly=True)
    source_field = fields.Char(
        string='Source Field',
        required=True,
        readonly=True,
        help='Nama field dari response API Hub yang berisi tipe transaksi.',
    )
    trans_type = fields.Char(
        string='Transaction Type',
        required=True,
        readonly=True,
    )
    code = fields.Char(
        string='Code',
        related='trans_type',
        store=True,
        readonly=True,
    )
    picking_type_ids = fields.Many2many(
        'stock.picking.type',
        string='Stock Picking Type',
        related='config_id.picking_type_ids',
        readonly=True,
    )
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)

    _sql_constraints = [
        (
            'unique_config_source_trans_type',
            'unique(config_id, source_field, trans_type)',
            'Transaction type untuk API config dan source field ini sudah ada.',
        ),
    ]
