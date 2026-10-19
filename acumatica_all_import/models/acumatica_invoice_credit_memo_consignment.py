from odoo import fields, models


class AcumaticaInvoiceCreditMemoConsignmentStaging(models.Model):
    _name = 'acumatica.invoice.credit.memo.consignment.staging'
    _description = 'Staging Invoice Credit Memo Consignment dari Acumatica'
    _order = 'id desc'
    _rec_name = 'adt_RefNbr'

    config_id = fields.Many2one('acumatica.config', required=True, ondelete='cascade')
    credit_memo_staging_id = fields.Many2one(
        'acumatica.credit.memo.consignment.staging',
        string='Credit Memo Consignment',
        ondelete='set null',
        index=True,
    )
    adt_OrigRefNbr = fields.Char(string='Credit Memo OrigRefNbr', index=True)
    adt_RefNbr = fields.Char(string='Invoice RefNbr', index=True)
    adt_id = fields.Char(string='Acumatica ID')
    adt_rowNumber = fields.Char(string='Acumatica Row Number')
    adt_BuildingID = fields.Char(string='Building ID')
    adt_ConsignmentType = fields.Char(string='Consignment Type')
    adt_CustomerName = fields.Char(string='Customer Name')
    adt_CustomerOrder = fields.Char(string='Customer Order')
    adt_Date = fields.Char(string='Date')
    adt_Description = fields.Char(string='Description')
    adt_LastModifiedDateTime = fields.Char(string='Last Modified')
    adt_LocationID = fields.Char(string='Location ID')
    adt_LocationName = fields.Char(string='Location Name')
    adt_NoteHeaderID = fields.Char(string='Note Header ID')
    adt_Status = fields.Char(string='Status')
    adt_Type = fields.Char(string='Type')
    sync_date = fields.Datetime(string='Tanggal Fetch', default=fields.Datetime.now)
    fetch_state = fields.Selection(
        [('staged', 'Fetched'), ('error', 'Error')],
        string='Fetch Status',
        default='staged',
        required=True,
    )
    fetch_message = fields.Text(string='Fetch Message')
    response_json = fields.Text(string='Respons API')
    line_ids = fields.One2many(
        'acumatica.invoice.credit.memo.consignment.staging.line',
        'staging_id',
        string='Details',
    )

    _sql_constraints = [
        (
            'unique_config_orig_ref',
            'unique(config_id, adt_OrigRefNbr)',
            'Data Invoice Credit Memo untuk OrigRefNbr ini sudah ada.',
        ),
    ]


class AcumaticaInvoiceCreditMemoConsignmentStagingLine(models.Model):
    _name = 'acumatica.invoice.credit.memo.consignment.staging.line'
    _description = 'Detail Staging Invoice Credit Memo Consignment dari Acumatica'
    _order = 'adt_rowNumber, id'

    staging_id = fields.Many2one(
        'acumatica.invoice.credit.memo.consignment.staging',
        required=True,
        ondelete='cascade',
        index=True,
    )
    adt_id = fields.Char(string='Acumatica ID')
    adt_rowNumber = fields.Char(string='Row Number')
    adt_Branch = fields.Char(string='Branch')
    adt_InventoryID = fields.Char(string='Inventory ID')
    adt_LineNoteID = fields.Char(string='Line Note ID')
    adt_Qty = fields.Float(string='Quantity')
    adt_TransactionDescription = fields.Char(string='Transaction Description')
    adt_UOM = fields.Char(string='UOM')
    adt_Warehouse = fields.Char(string='Warehouse')
    adt_LocationID = fields.Char(string='Location ID')
    adt_LocationName = fields.Char(string='Location Name')
    adt_NoteHeaderID = fields.Char(string='Note Header ID')
    adt_ReferenceNbr = fields.Char(string='Reference Number')
    adt_OrigRefNbr = fields.Char(string='OrigRefNbr')
    adt_Status = fields.Char(string='Status')
    adt_Type = fields.Char(string='Type')
    response_json = fields.Text(string='Data API')
