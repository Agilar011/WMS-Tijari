from odoo import models, fields


class StockLocation(models.Model):
    """
    Extend stock.location dengan field baru dari Acumatica.
    Semua field baru diprefix 'adt_' untuk menghindari conflict.

    Field standar yang sudah ada di Odoo (TIDAK perlu dibuat):
      - name  → LocationID (dipakai sebagai display name / complete_name)
      - usage → 'internal' untuk location dalam warehouse
    """
    _inherit = 'stock.location'

    adt_external_id = fields.Char(string='UUID Acumatica', index=True)
    adt_note        = fields.Text(string='Note (Acumatica)')
    adt_state       = fields.Boolean(string='Active (Acumatica)',
                                     help='Active status dari Acumatica WMS')
    adt_description = fields.Char(string='Description (Acumatica)',
                                  help='Description dari Acumatica, berbeda dari LocationID')
    adt_location_id = fields.Char(string='Location ID (Acumatica)',
                                  help='LocationID string dari Acumatica WMS')
