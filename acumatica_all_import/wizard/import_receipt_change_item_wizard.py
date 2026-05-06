from odoo import fields, models
from odoo.exceptions import UserError


class ImportReceiptChangeItemWizard(models.TransientModel):
    _name = 'import.receipt.change.item.wizard'
    _description = 'Wizard Import Receipt Type Change Item dari Acumatica'

    config_id = fields.Many2one('acumatica.receipt.change.item.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter', default="TransType eq 'Change Item'", help='Filter tambahan untuk query OData. Contoh: TransDate ge 2026-01-01T00:00:00Z')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Picking Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)

    def action_fetch_data(self):
        self.ensure_one()
        self.env['acumatica.receipt.change.item.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = i * self.batch_size
            batch_data = self.config_id.fetch_receipt_data(
                limit=self.batch_size,
                reference_nbr=self.reference_nbr,
                offset=offset,
                receipt_nbr=self.receipt_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        existing_keys = set()
        new_keys = set()
        lines_to_create = []

        for item in raw_list:
            origin = item.get('origin')
            exists = bool(origin and Picking.search_count([('origin', '=', origin)]))
            if exists:
                existing_keys.add(origin)
                msg = 'Sudah ada → move akan ditambahkan jika belum ada'
            else:
                new_keys.add(origin)
                msg = ''

            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': msg,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })
            lines_to_create.append(vals)

        self.env['acumatica.receipt.change.item.line'].create(lines_to_create)
        self.write({
            'state': 'fetched',
            'total_fetched': len(raw_list),
            'total_new': len([x for x in new_keys if x]),
            'total_existing': len([x for x in existing_keys if x]),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.receipt.change.item.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Receipt Type Change Item dari Acumatica',
            'res_model': 'acumatica.receipt.change.item.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.receipt.change.item.line'].search([
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
            'name': 'Hasil Import Receipt Type Change Item',
            'res_model': 'acumatica.receipt.change.item.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
