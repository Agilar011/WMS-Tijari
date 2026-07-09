from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import date


class AcumaticaUnifiedImportWizard(models.TransientModel):
    _name = 'acumatica.unified.import.wizard'
    _description = 'Unified Wizard Import Acumatica'

    IMPORT_MAP = {

        'uom': {
            'label': 'UoM',
            'wizard_model': 'import.uom.wizard',
            'config_field': 'uom_config_id',
            'line_model': 'acumatica.uom.line',
            'result_name': 'Hasil Import UoM',
            'staging_name': 'Data UoM dari Acumatica',
            'extra_fields': [],
        },
        'customer': {
            'label': 'Customer',
            'wizard_model': 'import.customer.wizard',
            'config_field': 'customer_config_id',
            'line_model': 'acumatica.customer.line',
            'result_name': 'Hasil Import Customer',
            'staging_name': 'Data Customer dari Acumatica',
            'extra_fields': [],
        },
        'vendor': {
            'label': 'Vendor',
            'wizard_model': 'import.vendor.wizard',
            'config_field': 'vendor_config_id',
            'line_model': 'acumatica.vendor.line',
            'result_name': 'Hasil Import Vendor',
            'staging_name': 'Data Vendor dari Acumatica',
            'extra_fields': [],
        },
        'warehouse': {
            'label': 'Warehouse & Location',
            'wizard_model': 'import.warehouse.wizard',
            'config_field': 'warehouse_config_id',
            'line_model': 'acumatica.warehouse.line',
            'result_name': 'Hasil Import Warehouse & Location',
            'staging_name': 'Data Warehouse & Location dari Acumatica',
            'extra_fields': [],
        },
        'stock_item': {
            'label': 'Stock Item',
            'wizard_model': 'import.stock.item.wizard',
            'config_field': 'stock_item_config_id',
            'line_model': 'acumatica.stock.item.line',
            'result_name': 'Hasil Import Stock Item',
            'staging_name': 'Data Stock Item dari Acumatica',
            'extra_fields': [],
        },
        'non_stock_item': {
            'label': 'Non-Stock Item',
            'wizard_model': 'import.non.stock.item.wizard',
            'config_field': 'non_stock_item_config_id',
            'line_model': 'acumatica.non.stock.item.line',
            'result_name': 'Hasil Import Non-Stock Item',
            'staging_name': 'Data Non-Stock Item dari Acumatica',
            'extra_fields': [],
        },
        'customer_location': {
            'label': 'Customer Location',
            'wizard_model': 'import.customer.location.wizard',
            'config_field': 'customer_location_config_id',
            'line_model': 'acumatica.customer.location.line',
            'result_name': 'Hasil Import Customer Location',
            'staging_name': 'Data Customer Location dari Acumatica',
            'extra_fields': [],
        },
        'shipvia': {
            'label': 'Shipping Carrier',
            'wizard_model': 'import.shipvia.wizard',
            'config_field': 'shipvia_config_id',
            'line_model': 'acumatica.shipvia.line',
            'result_name': 'Hasil Import Shipping Carrier',
            'staging_name': 'Data Shipping Carrier dari Acumatica',
            'extra_fields': [],
        },
        'po_receipt': {
            'label': 'PO Receipt',
            'wizard_model': 'import.receipt.wizard',
            'config_field': 'receipt_config_id',
            'line_model': 'acumatica.receipt.line',
            'result_name': 'Hasil Import PO Receipt',
            'staging_name': 'Data PO Receipt dari Acumatica',
            'extra_fields': ['receipt_nbr', 'last_modified_from', 'odata_filter'],
        },
        'issue_po_return': {
            'label': 'PO Return',
            'wizard_model': 'import.issue.po.return.wizard',
            'config_field': 'issue_po_return_config_id',
            'line_model': 'acumatica.issue.po.return.line',
            'result_name': 'Hasil Import PO Return',
            'staging_name': 'Data PO Return dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'transfer_one_step': {
            'label': 'Transfer - Intra Warehouse : OUT',
            'wizard_model': 'import.transfer.one.step.wizard',
            'config_field': 'transfer_one_step_config_id',
            'line_model': 'acumatica.transfer.one.step.line',
            'result_name': 'Hasil Import Transfer - Intra Warehouse : OUT',
            'staging_name': 'Data Transfer - Intra Warehouse : OUT dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'transfer_two_step': {
            'label': 'Transfer - 2 Step : OUT',
            'wizard_model': 'import.transfer.two.step.wizard',
            'config_field': 'transfer_two_step_config_id',
            'line_model': 'acumatica.transfer.two.step.line',
            'result_name': 'Hasil Import Transfer - 2 Step : OUT',
            'staging_name': 'Data Transfer - 2 Step : OUT dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'receipt_external': {
            'label': 'Receipt External (Change Item & Inventory Receive)',
            'wizard_model': 'import.receipt.external.wizard',
            'line_model': 'acumatica.receipt.external.line',
            'result_name': 'Hasil Import Receipt External (Change Item & Inventory Receive)',
            'staging_name': 'Data Receipt External (Change Item & Inventory Receive) dari Acumatica',
        },
        'inventory_received': {
            'label': 'Receipt : Inventory Receipt',
            'wizard_model': 'import.inventory.recieved.wizard',
            'config_field': 'inventory_received_config_id',
            'line_model': 'acumatica.inventory.recieved.line',
            'result_name': 'Hasil Import Receipt : Inventory Receipt',
            'staging_name': 'Data Receipt : Inventory Receipt dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'toko_pegang_do': {
            'label': 'Receipt : Toko Pegang DO',
            'wizard_model': 'import.toko.pegang.do.wizard',
            'line_model': 'acumatica.toko.pegang.do.line',
            'result_name': 'Hasil Import Receipt : Toko Pegang DO',
            'staging_name': 'Data Receipt : Toko Pegang DO dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'inventory_issue': {
            'label': 'Issue : Inventory Issue',
            'wizard_model': 'import.inventory.issue.wizard',
            'config_field': 'inventory_issue_config_id',
            'line_model': 'acumatica.inventory.issue.line',
            'result_name': 'Hasil Import Issue : Inventory Issue',
            'staging_name': 'Data Issue : Inventory Issue dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'receipt_change_item': {
            'label': 'Receipt : Change Item',
            'wizard_model': 'import.receipt.change.item.wizard',
            'config_field': 'receipt_change_item_config_id',
            'line_model': 'acumatica.receipt.change.item.line',
            'result_name': 'Hasil Import Receipt : Change Item',
            'staging_name': 'Data Receipt : Change Item dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'issue_change_item': {
            'label': 'Issue : Change Item',
            'wizard_model': 'import.issue.wizard',
            'config_field': 'issue_config_id',
            'line_model': 'acumatica.issue.line',
            'result_name': 'Hasil Import Issue : Change Item',
            'staging_name': 'Data Issue : Change Item dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'shipment_so': {
            'label': 'SO Return',
            'wizard_model': 'import.shipment.wizard',
            'config_field': 'shipment_config_id',
            'line_model': 'acumatica.shipment.line',
            'result_name': 'Hasil Import SO Return',
            'staging_name': 'Data SO Return dari Acumatica',
            'extra_fields': ['shipment_nbr', 'last_modified_from', 'odata_filter'],
        },
        'so_shipment': {
            'label': 'SO Shipment',
            'wizard_model': 'import.so.shipment.wizard',
            'config_field': 'so_shipment_config_id',
            'line_model': 'acumatica.shipment.gi.staging',
            'result_name': 'Hasil Import SO Shipment',
            'staging_name': 'Data SO Shipment dari Acumatica',
            'extra_fields': ['shipment_nbr', 'last_modified_from', 'odata_filter'],
        },
        'so_transfer': {
            'label': 'Transfer - Inter Warehouse : IN',
            'wizard_model': 'import.transfer.wizard',
            'config_field': 'transfer_config_id',
            'line_model': 'acumatica.transfer.line',
            'result_name': 'Hasil Import Transfer - Inter Warehouse : IN',
            'staging_name': 'Data Transfer - Inter Warehouse : IN dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'transfer_shipment': {
            'label': 'Transfer - Inter Warehouse : OUT',
            'wizard_model': 'import.transfer.shipment.wizard',
            'config_field': 'transfer_shipment_config_id',
            'line_model': 'acumatica.transfer.shipment.line',
            'result_name': 'Hasil Import Transfer - Inter Warehouse : OUT',
            'staging_name': 'Data Transfer - Inter Warehouse : OUT dari Acumatica',
            'extra_fields': ['shipment_nbr', 'last_modified_from', 'odata_filter'],
        },
        'kit_assembly': {
            'label': 'Manufacturing Order',
            'wizard_model': 'import.kit.assembly.wizard',
            'config_field': 'kit_assembly_config_id',
            'line_model': 'acumatica.kit.assembly.line',
            'result_name': 'Hasil Import Manufacturing Order',
            'staging_name': 'Data Manufacturing Order dari Acumatica',
            'extra_fields': [],
        },
        'inventory_stock': {
            'label': 'Detail Stock Acumatica',
            'wizard_model': 'import.inventory.stock.wizard',
            'config_field': 'inventory_stock_config_id',
            'line_model': 'acumatica.inventory.stock.line',
            'result_name': 'Hasil Import Detail Stock Acumatica',
            'staging_name': 'Data Detail Stock Acumatica dari Acumatica',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        'invoice_consignment': {
            'label': 'Invoice Consignment',
            'wizard_model': 'import.invoice.consignment.wizard',
            'config_field': 'invoice_consignment_config_id',
            'line_model': 'acumatica.invoice.consignment.staging',
            'result_name': 'Hasil Import Detail Invoice Consignment',
            'staging_name': 'Data Detail Invoice Consignment dari Acumatica',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        'inventory_issue_toko_pegang_do': {
            'label': 'Inventory Issue Toko Pegang DO',
            'wizard_model': 'import.inventory.issue.toko.pegang.do.wizard',
            'line_model': 'acumatica.inventory.issue.toko.pegang.do.staging',
            'result_name': 'Hasil Import Inventory Issue Toko Pegang DO',
            'staging_name': 'Data Inventory Issue Toko Pegang DO dari Acumatica',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        
        'vendor_return_direct_transfer': {
            'label': 'Vendor Return Direct Transfer',
            'wizard_model': 'import.vendor.return.direct.transfer.wizard',
            'line_model': 'acumatica.vendor.return.direct.transfer.staging',
            'result_name': 'Hasil Import Direct Transfer',
            'staging_name': 'Data Direct Transfer Acumatica',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        'vendor_return_document_direct_transfer': {
            'label': 'Vendor Return Document Direct Transfer',
            'wizard_model': 'import.direct.transfer.wizard',
            'line_model': 'acumatica.direct.transfer.staging',
            'result_name': 'Hasil Import Direct Transfer',
            'staging_name': 'Data Direct Transfer Acumatica',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        'credit_memo_consignment': {
            'label': 'Credit Memo Consignment',
            'wizard_model': 'import.credit.memo.consignment.wizard',
            'line_model': 'acumatica.credit.memo.consignment.staging',
            'result_name': 'Hasil Import Credit Memo Consignment',
            'staging_name': 'Data Credit Memo Consignment Acumatica',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        'inventory_receipt_transfer_wh_in': {
            'label': 'Inventory Receipt : Transfer In',
            'wizard_model': 'import.inventory.receipt.transfer.wh.in.wizard',
            'line_model': 'acumatica.inventory.receipt.transfer.wh.in.staging',
            'result_name': 'Hasil Import Inventory Receipt : Transfer WH IN',
            'staging_name': 'Data Inventory Receipt : Transfer WH IN',
            'extra_fields': ['warehouse_value', 'inventory_id_value', 'odata_expand', 'odata_top'],
        },
        
    }

    MASTER_DATA_TYPES = [
        'customer',
        'customer_location',
        'shipvia',
        'warehouse',
        'stock_item',
        'non_stock_item',
        'uom',
        'vendor',
        'inventory_stock',
    ]

    TRANSACTION_TYPES = [
        'po_receipt',
        'so_transfer',
        'receipt_change_item',
        'receipt_external',
        'inventory_received',
        'toko_pegang_do',
        'shipment_so',
        'so_shipment',
        'transfer_shipment',
        'issue_change_item',
        'inventory_issue',
        'issue_po_return',
        'transfer_one_step',
        'transfer_two_step',
        'kit_assembly',
        'invoice_consignment',
        'inventory_issue_toko_pegang_do',
        'vendor_return_direct_transfer',
        'vendor_return_document_direct_transfer',
        'credit_memo_consignment',
        'inventory_receipt_transfer_wh_in'
    ]

    def _get_import_type_selection(self):
        selection = []
        selection += [
            (key, self.IMPORT_MAP[key]['label'])
            for key in self.TRANSACTION_TYPES
            if key in self.IMPORT_MAP
        ]
        selection += [
            (key, self.IMPORT_MAP[key]['label'])
            for key in self.MASTER_DATA_TYPES
            if key in self.IMPORT_MAP
        ]
        print(selection)
        return selection

    def _get_import_type_selection_transaction(self):
        selection = []
        selection += [
            (key, self.IMPORT_MAP[key]['label'])
            for key in self.TRANSACTION_TYPES
            if key in self.IMPORT_MAP
        ]

        print(selection)
        return selection

    def _get_import_type_selection_master(self):
        selection = []
        selection += [
            (key, self.IMPORT_MAP[key]['label'])
            for key in self.MASTER_DATA_TYPES
            if key in self.IMPORT_MAP
        ]
        
        return selection

    def _get_default_config_for_import_type(self, import_type):
        return self.env['acumatica.config']._get_default_config_for_type(import_type)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        import_type = res.get('import_type')
        if not import_type:
            if res.get('import_category') == 'master':
                import_type = res.get('import_type_master') or 'customer'
            else:
                import_type = res.get('import_type_transaction') or 'po_receipt'

        if 'config_id' in fields_list and not res.get('config_id'):
            config = self._get_default_config_for_import_type(import_type)
            if config:
                res['config_id'] = config.id

        return res

    @api.onchange('import_category', 'import_type_transaction', 'import_type_master')
    def _onchange_import_type_value(self):
        if self.import_category == 'transaction':
            self.import_type = self.import_type_transaction

        if self.import_category == 'master':
            self.import_type = self.import_type_master

        config = self._get_default_config_for_import_type(self.import_type)
        self.config_id = config if config else False

    import_category = fields.Selection([
        ('transaction', 'Transaction'),
        ('master', 'Master Data'),
    ], string='Import Category', required=True, default='transaction')

    import_type = fields.Selection(
        selection=_get_import_type_selection,
        string='Data to Import',
        required=True,
        default='po_receipt',
    )
    import_type_transaction = fields.Selection(
        selection=_get_import_type_selection_transaction,
        string='Data to Import',
        required=True,
        default='po_receipt',
    )
    import_type_master = fields.Selection(
        selection=_get_import_type_selection_master,
        string='Data to Import',
        required=True,
        default='customer',
    )
    fetch_limit = fields.Integer(string='Maximum Records', default=5000, required=True)
    batch_size = fields.Integer(string='Import Batch Size', default=50, required=True)
    fetch_skip = fields.Integer(string='Records to Skip', default=0, required=True, help='Jumlah data yang dilewati sebelum memulai fetch.')
    skip_size = fields.Integer(string='Skip Size ', default=0, required=True, help='Jumlah data yang dilewati sebelum memulai import.')
    auto_commit_batch = fields.Boolean(
        string='Commit setiap batch',
        default=False,
        help='Aktifkan untuk import data besar agar setiap batch tersimpan. Gunakan dengan hati-hati karena rollback tidak lagi menyeluruh.',
    )

    reference_nbr = fields.Char(string='Reference Number Filter')
    receipt_nbr = fields.Char(string='Receipt Number Filter')
    shipment_nbr = fields.Char(string='Shipment Number Filter')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    warehouse_value = fields.Char(string='Warehouse Value', default='WH33-FG')
    inventory_id_value = fields.Char(string='InventoryID Value')
    odata_expand = fields.Char(string='OData Expand', default='InventorySiteInquiryDetails')
    odata_top = fields.Integer(string='OData Top', default=1)
    wh33_filter = fields.Boolean(string='WH33 Only', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    date_period = fields.Boolean(string="Enable Date Filter", help="Aktifkan filter berdasarkan tanggal. Start Date otomatis diisi 1 Januari tahun berjalan dan End Date diisi tanggal hari ini.")
    start_date = fields.Date(string='Start Date Filter', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='End Date Filter', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    # OLD: one config field per import type.
    # uom_config_id = fields.Many2one('acumatica.config', string='UoM Configuration', domain=[('active', '=', True)])
    # customer_config_id = fields.Many2one('acumatica.customer.config', string='Customer Configuration', domain=[('active', '=', True)])
    # vendor_config_id = fields.Many2one('acumatica.vendor.config', string='Vendor Configuration', domain=[('active', '=', True)])
    # warehouse_config_id = fields.Many2one('acumatica.warehouse.config', string='Warehouse Configuration', domain=[('active', '=', True)])
    # stock_item_config_id = fields.Many2one('acumatica.stock.item.config', string='Stock Item Configuration', domain=[('active', '=', True)])
    # non_stock_item_config_id = fields.Many2one('acumatica.non.stock.item.config', string='Non-Stock Item Configuration', domain=[('active', '=', True)])
    # customer_location_config_id = fields.Many2one('acumatica.customer.location.config', string='Customer Location Configuration', domain=[('active', '=', True)])
    # shipvia_config_id = fields.Many2one('acumatica.shipvia.config', string='ShipVia Configuration', domain=[('active', '=', True)])
    # receipt_config_id = fields.Many2one('acumatica.receipt.config', string='Receipt Configuration', domain=[('active', '=', True)])
    # issue_po_return_config_id = fields.Many2one('acumatica.issue.po.return.config', string='Issue PO Return Configuration', domain=[('active', '=', True)])
    # transfer_one_step_config_id = fields.Many2one('acumatica.transfer.one.step.config', string='Transfer One Step Configuration', domain=[('active', '=', True)])
    # transfer_two_step_config_id = fields.Many2one('acumatica.transfer.two.step.config', string='Transfer Two Step Configuration', domain=[('active', '=', True)])
    # inventory_received_config_id = fields.Many2one('acumatica.inventory.recieved.config', string='Inventory Received Configuration', domain=[('active', '=', True)])
    # inventory_issue_config_id = fields.Many2one('acumatica.inventory.issue.config', string='Inventory Issue Configuration', domain=[('active', '=', True)])
    # receipt_change_item_config_id = fields.Many2one('acumatica.receipt.change.item.config', string='Receipt Change Item Configuration', domain=[('active', '=', True)])
    # issue_config_id = fields.Many2one('acumatica.issue.config', string='Issue Change Item Configuration', domain=[('active', '=', True)])
    # shipment_config_id = fields.Many2one('acumatica.shipment.config', string='Shipment SO Configuration', domain=[('active', '=', True)])
    # so_shipment_config_id = fields.Many2one('acumatica.so.shipment.config', string='SO Shipment Configuration', domain=[('active', '=', True)])
    # transfer_config_id = fields.Many2one('acumatica.transfer.config', string='SO Transfer Configuration', domain=[('active', '=', True)])
    # transfer_shipment_config_id = fields.Many2one('acumatica.transfer.shipment.config', string='Transfer Shipment Configuration', domain=[('active', '=', True)])
    # kit_assembly_config_id = fields.Many2one('acumatica.kit.assembly.config', string='Kit Assembly Configuration', domain=[('active', '=', True)])
    # inventory_stock_config_id = fields.Many2one('acumatica.inventory.stock.config', string='Inventory Stock Configuration', domain=[('active', '=', True)])
    config_id = fields.Many2one(
        'acumatica.config',
        string='API Configuration',
        required=True,
        domain=[('active', '=', True)],
    )

    state = fields.Selection([('draft', 'Siap'), ('fetched', 'Data Sudah Ditarik'), ('done', 'Selesai')], default='draft')
    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_pending = fields.Integer(string='Total Pending Dipilih', readonly=True)
    total_imported = fields.Integer(string='Total Diproses Batch', readonly=True)
    batch_count = fields.Integer(string='Jumlah Batch', readonly=True)
    last_message = fields.Text(string='Pesan Terakhir', readonly=True)


    @api.onchange("date_period")
    def _onchange_date_period(self):
        today = fields.Date.today()
        if self.date_period:
            self.start_date = date(today.year, 1, 1)  # 1 Januari tahun ini
            self.end_date = today                      # Hari ini
        else:
            self.start_date = None
            self.end_date = None 

    def _get_import_info(self):
        self.ensure_one()
        if not self.import_type or self.import_type not in self.IMPORT_MAP:
            raise UserError(_('Pilih data yang ingin diimport terlebih dahulu.'))
        
        
        return self.IMPORT_MAP[self.import_type]

    def _get_selected_config(self, info):
        config = self.config_id
        if not config:
            raise UserError(_('Pilih konfigurasi API untuk %s terlebih dahulu.') % info['label'])
        if not config.config_type or config.config_type != self.import_type:
            raise UserError(
                _('Konfigurasi API yang dipilih tidak sesuai dengan tipe import %s.')
                % info['label']
            )
        
        return config

    def _prepare_source_wizard_vals(self, info, config):
        vals = {
            'config_id': config.id,
            'fetch_limit': self.fetch_limit,
            'batch_size': self.batch_size,
            'fetch_skip': self.fetch_skip,
        }
        if self.import_type in ('po_receipt', 'so_transfer', 'shipment_so', 'so_shipment', 'inventory_received', 'toko_pegang_do', 'transfer_shipment'):
            vals['wh33_filter'] = self.wh33_filter
            vals['start_date'] = self.start_date
            vals['end_date'] = self.end_date     
        if self.import_type in ('customer'):
            vals['start_date'] = self.start_date
            vals['end_date'] = self.end_date     
        for field_name in info.get('extra_fields', []):
            if field_name in self.env[info['wizard_model']]._fields:
                vals[field_name] = self[field_name]
        return vals

    def _get_pending_lines(self, info, config):
        return self.env[info['line_model']].search([
            ('import_state', '=', 'pending'),
        ], order='id')
    
    def _get_pending_domain(self, config):
        return [
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
        ]


    def _get_pending_lines_batch(self, info, config, limit, last_id=0):
        domain = self._get_pending_domain(config)
        if last_id:
            domain.append(('id', '>', last_id))

        return self.env[info['line_model']].search(
            domain,
            order='id',
            limit=limit,
        )

    def action_fetch_data(self):
        
        self.ensure_one()

        print(f"Fetch limit: {self.fetch_limit}")
        message = False

        if self.fetch_limit <= 0:
            raise UserError(_('Maximum Records must be greater than 0.'))

        elif self.batch_size <= 0:
            raise UserError(_('Import Batch Size must be greater than 0.'))

        elif self.fetch_skip < 0:
            raise UserError(_('Records to Skip cannot be less than 0.'))

        elif self.batch_size > self.fetch_limit:
            raise UserError(_('Import Batch Size cannot be greater than Maximum Records.'))

        else:
            info = self._get_import_info()
            print(f"Import info: {info}")

            config = self._get_selected_config(info)
            print(f"Config: {config}")

            source_wizard = self.env[info['wizard_model']].create(self._prepare_source_wizard_vals(info, config))
            print(f"Source wizard created: {source_wizard}")

            source_wizard.action_fetch_data()
            print("Fetch data action called on source wizard")

            pending_lines = self._get_pending_lines(info, config)
            print(f"Pending lines fetched: {len(pending_lines)}")

            print(f"Model: {info['line_model']}")
            print(f"Config ID: {config}")

            total_data = len(self.env[info['line_model']].search([]))
            print(f"Total Data in staging: {total_data}")

            total_fetched = source_wizard.total_fetched
            print(f"Total fetched: {total_fetched}")


            self.write({
                'state': 'fetched',
                'total_fetched': total_fetched,
                'total_pending': len(pending_lines),
                'total_imported': 0,
                'batch_count': 0,
                'last_message': _('Fetch complete. %s data is already in staging, %s data has been retrieved, and %s data in staging is ready to be imported.') % (total_data, total_fetched, len(pending_lines)),
            })
            return self._reopen()

    def action_view_staging(self):
        self.ensure_one()
        info = self._get_import_info()
        config = self._get_selected_config(info)
        return {
            'type': 'ir.actions.act_window',
            'name': info['staging_name'],
            'res_model': info['line_model'],
            'view_mode': 'list,form',
            'domain': [('config_id', '=', config.id)],
            'context': {'default_config_id': config.id},
        }

    def action_import_pending_batch(self):
        self.ensure_one()

        info = self._get_import_info()
                
        config = self._get_selected_config(info)

        Line = self.env[info['line_model']]
        print(Line)
        pending_domain = self._get_pending_domain(config)

        total_pending_before = Line.search_count(pending_domain)
        if not total_pending_before:
            raise UserError(_('Tidak ada data pending di staging yang dapat diimport.'))

        processed = 0
        batch_count = 0
        last_id = 0

        while True:
            batch = self._get_pending_lines_batch(
                info=info,
                config=config,
                limit=self.batch_size,
                last_id=last_id,
            )

            if not batch:
                break

            last_id = batch[-1].id
            batch_count += 1

            # with self.env.cr.savepoint():
            batch._do_import()

            processed += len(batch)

            if self.auto_commit_batch:
                self.env.cr.commit()
                self.env.invalidate_all()

        remaining_count = Line.search_count(pending_domain)

        self.write({
            'state': 'done' if not remaining_count else 'fetched',
            'total_pending': remaining_count,
            'total_imported': processed,
            'batch_count': batch_count,
            'last_message': _(
                'Import batch selesai. %s data diproses dalam %s batch. Sisa pending: %s.'
            ) % (processed, batch_count, remaining_count),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': info['result_name'],
            'res_model': info['line_model'],
            'view_mode': 'list,form',
            'domain': [('config_id', '=', config.id)],
        }

    def action_fetch_and_import_batch(self):
        self.ensure_one()

        
        self.ensure_one()
        if self.fetch_limit <= 0:
            raise UserError(_('Maks Data Ditarik harus lebih besar dari 0.'))
        info = self._get_import_info()
        config = self._get_selected_config(info)
        source_wizard = self.env[info['wizard_model']].create(self._prepare_source_wizard_vals(info, config))
        source_wizard.action_fetch_data_import_batch()
        pending_lines = self._get_pending_lines(info, config)
        total_fetched = len(self.env[info['line_model']].search([('config_id', '=', config.id)]))
        self.write({
            'state': 'fetched',
            'total_fetched': total_fetched,
            'total_pending': len(pending_lines),
            'total_imported': 0,
            'batch_count': 0,
            'last_message': _('Fetch selesai. %s line staging dibuat, %s line pending terpilih siap diimport.') % (total_fetched, len(pending_lines)),
        })



        # self.action_fetch_data()
        # return self.action_import_pending_batch()

    def action_reset(self):
        self.write({
            'state': 'draft',
            'total_fetched': 0,
            'total_pending': 0,
            'total_imported': 0,
            'batch_count': 0,
            'last_message': False,
        })
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
