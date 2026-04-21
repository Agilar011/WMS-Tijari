from odoo import models, fields
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


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
    # FETCH DATA
    # =========================
    def action_fetch_data(self):
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih API terlebih dahulu')

        _logger.info(
            "START FETCH: batch=%s, skip=%s, target=%s",
            self.fetch_limit,
            self.fetch_skip,
            self.total_target or 'ALL'
        )

        # cleanup staging
        self.env['acumatica.customer.location.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # fetch dari API
        raw_list = self.config_id.fetch_customer_location_data(
            batch_size=self.fetch_limit,
            start_skip=self.fetch_skip,
            target_total=self.total_target or None
        )

        if not raw_list:
            raise UserError('Tidak ada data dari API')

        _logger.info("FETCH DONE: total=%s", len(raw_list))

        Loc     = self.env['acumatica.customer.location']
        Partner = self.env['res.partner']

        # =========================
        # OPTIMASI: PRELOAD DATA
        # =========================
        external_ids = [x['external_id'] for x in raw_list if x.get('external_id')]
        customers    = [x['customer'] for x in raw_list if x.get('customer')]

        existing_map = {
            r.adt_external_id: r.id
            for r in Loc.search([('adt_external_id', 'in', external_ids)])
        }

        partner_map = {
            r.company_registry: r.id
            for r in Partner.search([('company_registry', 'in', customers)])
        }

        _logger.info(
            "PRELOAD DONE: existing=%s, partners=%s",
            len(existing_map), len(partner_map)
        )

        new_count = existing_count = no_customer_count = 0
        lines = []

        _logger.info("BUILD STAGING START...")

        for i, item in enumerate(raw_list, start=1):
            existing = existing_map.get(item['external_id'])
            partner  = partner_map.get(item['customer'])

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
                'config_id': self.config_id.id,
                'external_id': item['external_id'],
                'customer': item['customer'],
                'location_id_acumatica': item['location_id_acumatica'],
                'location_name': item['location_name'],
                'import_state': 'pending',
                'import_message': msg,
                'selected': bool(partner),
            })

            if i % 1000 == 0:
                _logger.info("Prepared %s staging records", i)

        self.env['acumatica.customer.location.line'].create(lines)

        _logger.info(
            "STAGING CREATED: total=%s | new=%s | existing=%s | no_customer=%s",
            len(lines), new_count, existing_count, no_customer_count
        )

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
    # IMPORT ALL (HATI-HATI)
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

        _logger.info("IMPORT ALL START: %s records", len(lines))

        lines._do_import()

        _logger.info("IMPORT ALL DONE")

        self.state = 'done'

    # =========================
    # IMPORT BATCH (RECOMMENDED)
    # =========================
    def action_import_batch(self):
        self.ensure_one()

        Line = self.env['acumatica.customer.location.line']

        remaining = Line.search_count([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])

        _logger.info("REMAINING BEFORE IMPORT: %s", remaining)

        lines = Line.search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ], limit=1000)

        if not lines:
            raise UserError('Tidak ada data untuk diimport.')

        _logger.info("IMPORT BATCH START (limit=1000)")

        lines._do_import()

        _logger.info("IMPORT BATCH DONE")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Batch Import',
                'message': f'{len(lines)} data berhasil diproses',
                'type': 'success',
                'sticky': False,
            }
        }