import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportInventoryStockWizard(models.TransientModel):
    _name = 'import.inventory.stock.wizard'
    _description = 'Wizard Import Inventory Stock dari Acumatica'

    config_id = fields.Many2one(
        'acumatica.inventory.stock.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)],
    )
    warehouse_value = fields.Char(string='Warehouse', default='WH33-FG')
    inventory_id_value = fields.Char(string='InventoryID')
    odata_expand = fields.Char(string='OData Expand', default='InventorySiteInquiryDetails')
    odata_top = fields.Integer(string='OData Top', default=1)

    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')
    fetch_limit = fields.Integer(
        string='Maks Data Ditarik',
        default=50,
        help='Sesuai spesifikasi: default 50 data customer',
    )
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Data Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada', readonly=True)

    @api.onchange('config_id')
    def _onchange_config_id(self):
        if not self.config_id:
            return
        self.odata_expand = self.config_id.odata_expand or self.odata_expand
        self.odata_top = self.config_id.odata_top or self.odata_top
        self.warehouse_value = self.config_id.request_warehouse_value or self.warehouse_value
        self.inventory_id_value = self.config_id.request_inventory_id_value or self.inventory_id_value

    def action_fetch_data(self):
        self.ensure_one()
        raw_list = self.config_id.fetch_inventory_stock_data(
            warehouse=self.warehouse_value,
            inventory_id=self.inventory_id_value,
            odata_expand=self.odata_expand or None,
            odata_top=self.odata_top or None,
        )

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Line = self.env['acumatica.inventory.stock.line']
        new_count = 0
        existing_count = 0
        now = fields.Datetime.now()

        for item in raw_list:
            domain = [
                ('config_id', '=', self.config_id.id),
                ('external_id', '=', item.get('external_id', '') or ''),
                ('line_external_id', '=', item.get('line_external_id', '') or ''),
            ]
            existing = Line.search(domain, limit=1)
            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'selected': True,
                'sync_date': now,
            })
            if existing:
                existing.write(vals)
                existing_count += 1
            else:
                Line.create(vals)
                new_count += 1

        self.write({
            'state': 'fetched',
            'total_fetched': len(raw_list),
            'total_new': new_count,
            'total_existing': existing_count,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Inventory Stock',
            'res_model': 'acumatica.inventory.stock.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }
