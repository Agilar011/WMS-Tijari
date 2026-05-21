from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AcumaticaUnifiedImportWizard(models.TransientModel):
    _name = 'acumatica.unified.import.wizard'
    _description = 'Unified Wizard Import Acumatica'

    IMPORT_MAP = {

        'uom': {
            'label': 'UoM', 'wizard_model': 'import.uom.wizard', 'config_field': 'uom_config_id',
            'line_model': 'acumatica.uom.line', 'result_name': 'Hasil Import UoM',
            'staging_name': 'Data UoM dari Acumatica', 'extra_fields': [],
        },
        'customer': {
            'label': 'Customer', 'wizard_model': 'import.customer.wizard', 'config_field': 'customer_config_id',
            'line_model': 'acumatica.customer.line', 'result_name': 'Hasil Import Customer',
            'staging_name': 'Data Customer dari Acumatica', 'extra_fields': [],
        },
        'vendor': {
            'label': 'Vendor', 'wizard_model': 'import.vendor.wizard', 'config_field': 'vendor_config_id',
            'line_model': 'acumatica.vendor.line', 'result_name': 'Hasil Import Vendor',
            'staging_name': 'Data Vendor dari Acumatica', 'extra_fields': [],
        },
        'warehouse': {
            'label': 'Warehouse', 'wizard_model': 'import.warehouse.wizard', 'config_field': 'warehouse_config_id',
            'line_model': 'acumatica.warehouse.line', 'result_name': 'Hasil Import Warehouse',
            'staging_name': 'Data Warehouse dari Acumatica', 'extra_fields': [],
        },
        'stock_item': {
            'label': 'Stock Item', 'wizard_model': 'import.stock.item.wizard', 'config_field': 'stock_item_config_id',
            'line_model': 'acumatica.stock.item.line', 'result_name': 'Hasil Import Stock Item',
            'staging_name': 'Data Stock Item dari Acumatica', 'extra_fields': [],
        },
        'non_stock_item': {
            'label': 'Non-Stock Item', 'wizard_model': 'import.non.stock.item.wizard', 'config_field': 'non_stock_item_config_id',
            'line_model': 'acumatica.non.stock.item.line', 'result_name': 'Hasil Import Non-Stock Item',
            'staging_name': 'Data Non-Stock Item dari Acumatica', 'extra_fields': [],
        },
        'customer_location': {
            'label': 'Customer Location', 'wizard_model': 'import.customer.location.wizard', 'config_field': 'customer_location_config_id',
            'line_model': 'acumatica.customer.location.line', 'result_name': 'Hasil Import Customer Location',
            'staging_name': 'Data Customer Location dari Acumatica', 'extra_fields': [],
        },
        'shipvia': {
            'label': 'ShipVia', 'wizard_model': 'import.shipvia.wizard', 'config_field': 'shipvia_config_id',
            'line_model': 'acumatica.shipvia.line', 'result_name': 'Hasil Import ShipVia',
            'staging_name': 'Data ShipVia dari Acumatica', 'extra_fields': [],
        },
        'po_receipt': {
            'label': 'PO / Inventory Receipt',
            'wizard_model': 'import.receipt.wizard',
            'config_field': 'receipt_config_id',
            'line_model': 'acumatica.receipt.line',
            'result_name': 'Hasil Import Receipt',
            'staging_name': 'Data Receipt dari Acumatica',
            'extra_fields': ['receipt_nbr', 'last_modified_from', 'odata_filter'],
        },
        'issue_po_return': {
            'label': 'Issue PO Return',
            'wizard_model': 'import.issue.po.return.wizard',
            'config_field': 'issue_po_return_config_id',
            'line_model': 'acumatica.issue.po.return.line',
            'result_name': 'Hasil Import Issue PO Return',
            'staging_name': 'Data Issue PO Return dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'transfer_one_step': {
            'label': 'Transfer One Step',
            'wizard_model': 'import.transfer.one.step.wizard',
            'config_field': 'transfer_one_step_config_id',
            'line_model': 'acumatica.transfer.one.step.line',
            'result_name': 'Hasil Import Transfer One Step',
            'staging_name': 'Data Transfer One Step dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'transfer_two_step': {
            'label': 'Transfer Two Step',
            'wizard_model': 'import.transfer.two.step.wizard',
            'config_field': 'transfer_two_step_config_id',
            'line_model': 'acumatica.transfer.two.step.line',
            'result_name': 'Hasil Import Transfer Two Step',
            'staging_name': 'Data Transfer Two Step dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'inventory_received': {
            'label': 'Inventory Received',
            'wizard_model': 'import.inventory.recieved.wizard',
            'config_field': 'inventory_received_config_id',
            'line_model': 'acumatica.inventory.recieved.line',
            'result_name': 'Hasil Import Inventory Received',
            'staging_name': 'Data Inventory Received dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'inventory_issue': {
            'label': 'Inventory Issue',
            'wizard_model': 'import.inventory.issue.wizard',
            'config_field': 'inventory_issue_config_id',
            'line_model': 'acumatica.inventory.issue.line',
            'result_name': 'Hasil Import Inventory Issue',
            'staging_name': 'Data Inventory Issue dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'receipt_change_item': {
            'label': 'Receipt Change Item',
            'wizard_model': 'import.receipt.change.item.wizard',
            'config_field': 'receipt_change_item_config_id',
            'line_model': 'acumatica.receipt.change.item.line',
            'result_name': 'Hasil Import Receipt Change Item',
            'staging_name': 'Data Receipt Change Item dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'issue_change_item': {
            'label': 'Issue Change Item',
            'wizard_model': 'import.issue.wizard',
            'config_field': 'issue_config_id',
            'line_model': 'acumatica.issue.line',
            'result_name': 'Hasil Import Issue Change Item',
            'staging_name': 'Data Issue Change Item dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'shipment_so': {
            'label': 'Shipment SO',
            'wizard_model': 'import.shipment.wizard',
            'config_field': 'shipment_config_id',
            'line_model': 'acumatica.shipment.line',
            'result_name': 'Hasil Import Shipment SO',
            'staging_name': 'Data Shipment SO dari Acumatica',
            'extra_fields': ['shipment_nbr', 'last_modified_from', 'odata_filter'],
        },
        'so_shipment': {
            'label': 'SO Shipment',
            'wizard_model': 'import.so.shipment.wizard',
            'config_field': 'so_shipment_config_id',
            'line_model': 'acumatica.so.shipment.line',
            'result_name': 'Hasil Import SO Shipment',
            'staging_name': 'Data SO Shipment dari Acumatica',
            'extra_fields': ['shipment_nbr', 'last_modified_from', 'odata_filter'],
        },
        'so_transfer': {
            'label': 'SO Transfer',
            'wizard_model': 'import.transfer.wizard',
            'config_field': 'transfer_config_id',
            'line_model': 'acumatica.transfer.line',
            'result_name': 'Hasil Import SO Transfer',
            'staging_name': 'Data SO Transfer dari Acumatica',
            'extra_fields': ['reference_nbr', 'last_modified_from', 'odata_filter'],
        },
        'transfer_shipment': {
            'label': 'Transfer Shipment',
            'wizard_model': 'import.transfer.shipment.wizard',
            'config_field': 'transfer_shipment_config_id',
            'line_model': 'acumatica.transfer.shipment.line',
            'result_name': 'Hasil Import Transfer Shipment',
            'staging_name': 'Data Transfer Shipment dari Acumatica',
            'extra_fields': ['shipment_nbr', 'last_modified_from', 'odata_filter'],
        },
        'kit_assembly': {
            'label': 'Kit Assembly',
            'wizard_model': 'import.kit.assembly.wizard',
            'config_field': 'kit_assembly_config_id',
            'line_model': 'acumatica.kit.assembly.line',
            'result_name': 'Hasil Import Kit Assembly',
            'staging_name': 'Data Kit Assembly dari Acumatica',
            'extra_fields': [],
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
    ]

    TRANSACTION_TYPES = [
        'po_receipt',
        'so_transfer',
        'receipt_change_item',
        'inventory_received',
        'shipment_so',
        'so_shipment',
        'transfer_shipment',
        'issue_change_item',
        'inventory_issue',
        'issue_po_return',
        'transfer_one_step',
        'transfer_two_step',
        'kit_assembly',
    ]

    def _get_import_type_selection(self):
        selection = [
            ('__trx_header__', '──── Transaksi ────'),
        ]

        selection += [
            (key, self.IMPORT_MAP[key]['label'])
            for key in self.TRANSACTION_TYPES
            if key in self.IMPORT_MAP
        ]

        selection += [
            ('__master_header__', '──── Master Data ────'),
        ]

        selection += [
            (key, self.IMPORT_MAP[key]['label'])
            for key in self.MASTER_DATA_TYPES
            if key in self.IMPORT_MAP
        ]
        print(selection)
        return selection

    @api.onchange('import_type')
    def _onchange_import_type_header(self):
        if self.import_type in ('__trx_header__', '__master_header__'):
            self.import_type = False

    @api.constrains('import_type')
    def _check_import_type_not_header(self):
        for rec in self:
            if rec.import_type in ('__trx_header__', '__master_header__'):
                raise ValidationError('Silakan pilih jenis import, bukan kategori.')

    import_type = fields.Selection(
        selection=_get_import_type_selection,
        string='Data yang ingin diimport',
        required=True,
        default='po_receipt',
    )
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=5000, required=True)
    batch_size = fields.Integer(string='Batch Size Import', default=50, required=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, required=True, help='Jumlah data yang dilewati sebelum memulai fetch.')
    skip_size = fields.Integer(string='Skip Size ', default=0, required=True, help='Jumlah data yang dilewati sebelum memulai import.')
    auto_commit_batch = fields.Boolean(
        string='Commit setiap batch',
        default=False,
        help='Aktifkan untuk import data besar agar setiap batch tersimpan. Gunakan dengan hati-hati karena rollback tidak lagi menyeluruh.',
    )

    reference_nbr = fields.Char(string='Filter Reference Number')
    receipt_nbr = fields.Char(string='Filter Receipt Number')
    shipment_nbr = fields.Char(string='Filter Shipment Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')


    uom_config_id = fields.Many2one('acumatica.config', string='Konfigurasi UoM', domain=[('active', '=', True)])
    customer_config_id = fields.Many2one('acumatica.customer.config', string='Konfigurasi Customer', domain=[('active', '=', True)])
    vendor_config_id = fields.Many2one('acumatica.vendor.config', string='Konfigurasi Vendor', domain=[('active', '=', True)])
    warehouse_config_id = fields.Many2one('acumatica.warehouse.config', string='Konfigurasi Warehouse', domain=[('active', '=', True)])
    stock_item_config_id = fields.Many2one('acumatica.stock.item.config', string='Konfigurasi Stock Item', domain=[('active', '=', True)])
    non_stock_item_config_id = fields.Many2one('acumatica.non.stock.item.config', string='Konfigurasi Non-Stock Item', domain=[('active', '=', True)])
    customer_location_config_id = fields.Many2one('acumatica.customer.location.config', string='Konfigurasi Customer Location', domain=[('active', '=', True)])
    shipvia_config_id = fields.Many2one('acumatica.shipvia.config', string='Konfigurasi ShipVia', domain=[('active', '=', True)])

    receipt_config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi Receipt', domain=[('active', '=', True)])
    issue_po_return_config_id = fields.Many2one('acumatica.issue.po.return.config', string='Konfigurasi Issue PO Return', domain=[('active', '=', True)])
    transfer_one_step_config_id = fields.Many2one('acumatica.transfer.one.step.config', string='Konfigurasi Transfer One Step', domain=[('active', '=', True)])
    transfer_two_step_config_id = fields.Many2one('acumatica.transfer.two.step.config', string='Konfigurasi Transfer Two Step', domain=[('active', '=', True)])
    inventory_received_config_id = fields.Many2one('acumatica.inventory.recieved.config', string='Konfigurasi Inventory Received', domain=[('active', '=', True)])
    inventory_issue_config_id = fields.Many2one('acumatica.inventory.issue.config', string='Konfigurasi Inventory Issue', domain=[('active', '=', True)])
    receipt_change_item_config_id = fields.Many2one('acumatica.receipt.change.item.config', string='Konfigurasi Receipt Change Item', domain=[('active', '=', True)])
    issue_config_id = fields.Many2one('acumatica.issue.config', string='Konfigurasi Issue Change Item', domain=[('active', '=', True)])
    shipment_config_id = fields.Many2one('acumatica.shipment.config', string='Konfigurasi Shipment SO', domain=[('active', '=', True)])
    so_shipment_config_id = fields.Many2one('acumatica.so.shipment.config', string='Konfigurasi SO Shipment', domain=[('active', '=', True)])
    transfer_config_id = fields.Many2one('acumatica.transfer.config', string='Konfigurasi SO Transfer', domain=[('active', '=', True)])
    transfer_shipment_config_id = fields.Many2one('acumatica.transfer.shipment.config', string='Konfigurasi Transfer Shipment', domain=[('active', '=', True)])
    kit_assembly_config_id = fields.Many2one('acumatica.kit.assembly.config', string='Konfigurasi Kit Assembly', domain=[('active', '=', True)])

    state = fields.Selection([('draft', 'Siap'), ('fetched', 'Data Sudah Ditarik'), ('done', 'Selesai')], default='draft')
    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_pending = fields.Integer(string='Total Pending Dipilih', readonly=True)
    total_imported = fields.Integer(string='Total Diproses Batch', readonly=True)
    batch_count = fields.Integer(string='Jumlah Batch', readonly=True)
    last_message = fields.Text(string='Pesan Terakhir', readonly=True)

    def _get_import_info(self):
        self.ensure_one()
        if not self.import_type or self.import_type not in self.IMPORT_MAP:
            raise UserError(_('Pilih data yang ingin diimport terlebih dahulu.'))
        print(self.import_type)
        return self.IMPORT_MAP[self.import_type]

    def _get_selected_config(self, info):
        config = self[info['config_field']]
        if not config:
            raise UserError(_('Pilih konfigurasi API untuk %s terlebih dahulu.') % info['label'])
        print(config)
        return config

    def _prepare_source_wizard_vals(self, info, config):
        vals = {
            'config_id': config.id,
            'fetch_limit': self.fetch_limit,
            'batch_size': self.batch_size,
            'fetch_skip': self.fetch_skip,
        }
        for field_name in info.get('extra_fields', []):
            if field_name in self.env[info['wizard_model']]._fields:
                vals[field_name] = self[field_name]
        return vals

    def _get_pending_lines(self, info, config):
        return self.env[info['line_model']].search([
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ], order='id')
    
    def _get_pending_domain(self, config):
        return [
            ('config_id', '=', config.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
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
        print('action_fetch_data called')
        self.ensure_one()
        if self.fetch_limit <= 0:
            raise UserError(_('Maks Data Ditarik harus lebih besar dari 0.'))
        info = self._get_import_info()
        config = self._get_selected_config(info)
        source_wizard = self.env[info['wizard_model']].create(self._prepare_source_wizard_vals(info, config))
        source_wizard.action_fetch_data()
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

        if self.batch_size <= 0:
            raise UserError(_('Batch Size Import harus lebih besar dari 0.'))

        info = self._get_import_info()
        config = self._get_selected_config(info)

        Line = self.env[info['line_model']]
        pending_domain = self._get_pending_domain(config)

        total_pending_before = Line.search_count(pending_domain)
        if not total_pending_before:
            raise UserError(_('Tidak ada data pending yang dipilih untuk diimport.'))

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

            with self.env.cr.savepoint():
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

        print('action_fetch_data & import called')
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
