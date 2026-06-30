from odoo import fields, models
from odoo.exceptions import UserError


class ImportSOShipmentWizard(models.TransientModel):
    _name = 'import.so.shipment.wizard'
    _description = 'Wizard Import Shipment Receipt dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    receipt_nbr = fields.Char(string='Filter Shipment Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    wh33_filter = fields.Boolean(string='WH33 Only', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Char(string="Start Date")
    end_date = fields.Char(string="End Date")
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    def action_fetch_data(self):
        print(f"Self Limit: {self.fetch_limit}")
        self.ensure_one()
        self.env['acumatica.so.shipment.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        shipment_gi_data, shipment_numbers = self.config_id.fetch_shipment_gi_data()

        if not shipment_numbers:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')


        batch_data = self.config_id.fetch_shipment_data(
            shipment_numbers=shipment_numbers,  # tambahan
            odata_filter=self.odata_filter,
        )

        if not batch_data:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        
        created_sales_order_shipment_record = self.config_id.create_staging_data(shipment_gi_data, batch_data)

        self.write({
            'state': 'fetched',
            'total_fetched': len(batch_data),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.so.shipment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data SO Shipment Receipt dari Acumatica',
            'res_model': 'acumatica.so.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        print(self.config_id.id)
        lines = self.env['acumatica.shipment.gi.staging'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')
        lines._do_import()
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import SO Shipment Receipt',
            'res_model': 'acumatica.so.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
