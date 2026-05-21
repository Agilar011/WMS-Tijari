from odoo import models, fields
from odoo.exceptions import UserError


class ImportCustomerLocationWizard(models.TransientModel):
    _name = 'import.customer.location.wizard'
    _description = 'Wizard Import Customer Location dari Acumatica'

    # =========================
    # INPUT USER
    # =========================
    config_id = fields.Many2one(
        'acumatica.customer.location.config',
        string='API Digunakan',
        required=True,
        domain=[('active', '=', True)],
    )

    fetch_limit = fields.Integer(
        string='Batch Size',
        default=100,
        help='Jumlah data per request ke API'
    )
    batch_size = fields.Integer(
        string='Batch Size untuk Import',
        default=20,
        help='Jumlah record yang diproses per batch saat import. Sesuaikan dengan performa server dan jumlah data. Default 20.',
    )

    fetch_skip = fields.Integer(
        string='Mulai dari Data ke-',
        default=0
    )

    total_target = fields.Integer(
        string='Total Data Diambil',
        help='Kosongkan / 0 untuk ambil semua data'
    )

    # =========================
    # STATE
    # =========================
    state = fields.Selection([
        ('draft', 'Draft'),
        ('fetched', 'Fetched'),
        ('done', 'Done'),
    ], default='draft')

    # =========================
    # SUMMARY
    # =========================
    total_fetched     = fields.Integer(readonly=True)
    total_new         = fields.Integer(readonly=True)
    total_existing    = fields.Integer(readonly=True)
    total_no_customer = fields.Integer(readonly=True)

    # =========================
    # ACTION FETCH
    # =========================
    def action_fetch_data(self):
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih API terlebih dahulu')

        # cleanup staging
        self.env['acumatica.customer.location.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # fetch dari API
        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.config_id.fetch_customer_location_data(
                limit=self.batch_size,
                offset=offset,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data dari API')

        Partner = self.env['res.partner']

        new_count = existing_count = no_customer_count = 0
        lines = []

        for item in raw_list:
            existing = Partner.search([
                ('name', '=', item['location_id_acumatica']),
                ('parent_id.company_registry', '=', item['customer'])
            ], limit=1)

            partner = Partner.search([
                ('company_registry', '=', item['customer'])
            ], limit=1)

            if existing:
                existing_count += 1
                msg = 'Update'
            elif not partner:
                no_customer_count += 1
                msg = 'Customer tidak ditemukan'
            else:
                new_count += 1
                msg = 'New'

            lines.append({
                **item,
                'config_id': self.config_id.id,
                'external_id': item['external_id'],
                'customer': item['customer'],
                'location_id_acumatica': item['location_id_acumatica'],
                'location_name': item['location_name'],
                'import_state': 'pending',
                'import_message': msg,
                'selected': bool(partner),
            })

        self.env['acumatica.customer.location.line'].create(lines)

        self.write({
            'state': 'fetched',
            'total_fetched': len(raw_list),
            'total_new': new_count,
            'total_existing': existing_count,
            'total_no_customer': no_customer_count,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.customer.location.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # =========================
    # IMPORT
    # =========================
    def action_import_all_pending(self):
        self.ensure_one()

        lines = self.env['acumatica.customer.location.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])

        if not lines:
            raise UserError('Tidak ada data untuk diimport')

        lines._do_import()
        self.state = 'done'