from odoo import models, fields
from odoo.exceptions import UserError


class ImportReceiptWizard(models.TransientModel):
    _name = 'import.receipt.wizard'
    _description = 'Wizard Import Inventory Receipt dari Acumatica'

    # =============================
    # Fields
    # =============================
    config_id = fields.Many2one(
        'acumatica.receipt.config',
        string='Konfigurasi API',
        required=True,
        domain=[('active', '=', True)]
    )

    receipt_nbr = fields.Char(string='Filter Receipt Number')
    last_modified_from = fields.Char(
        string='Filter Last Modified From',
        help="Contoh: 2025-01-01T00:00:00+07:00"
    )
    odata_filter = fields.Char(string='Custom OData Filter')

    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    batch_size = fields.Integer(string='Ukuran Batch', default=1000)
    total_limit = fields.Integer(string='Total Data Diambil', default=10000)

    processed = fields.Integer(string='Sudah Diproses', readonly=True)
    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)

    direct_import = fields.Boolean(
        string='Langsung Import',
        default=True,
        help='Jika aktif, data langsung diimport ke stock.picking tanpa menunggu staging manual.'
    )

    # =============================
    # MAIN: Fetch + Batch Processing
    # =============================
    def action_fetch_data(self):
        self.ensure_one()

        total = self.total_limit
        batch = self.batch_size
        offset = 0

        total_fetched = 0
        total_new = 0
        total_existing = 0

        # optional: bersihkan staging lama
        self.env['acumatica.receipt.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        session = self.config_id._do_login()

        try:
            while offset < total:
                current_limit = min(batch, total - offset)

                raw_list = self.config_id.fetch_receipt_data(
                    limit=current_limit,
                    skip=offset,
                    receipt_nbr=self.receipt_nbr,
                    last_modified_from=self.last_modified_from,
                    odata_filter=self.odata_filter,
                    session=session,
                    auto_logout=False
                )

                if not raw_list:
                    break

                try:
                    lines, batch_new, batch_existing = self._process_batch(raw_list)

                    if self.direct_import:
                        lines._do_import()

                except Exception as e:
                    raise UserError(f'Error saat batch offset {offset}: {str(e)}')

                # update counters
                total_fetched += len(raw_list)
                total_new += batch_new
                total_existing += batch_existing

                offset += current_limit
                self.processed = total_fetched

                # commit per batch (penting)
                self.env.cr.commit()

            self.write({
                'state': 'done' if self.direct_import else 'fetched',
                'total_fetched': total_fetched,
                'total_new': total_new,
                'total_existing': total_existing,
            })

        finally:
            self.config_id._do_logout(session)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.receipt.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # =============================
    # PROCESS PER BATCH
    # =============================
    def _process_batch(self, raw_list):
        Picking = self.env['stock.picking']

        receipt_numbers = list(set(
            r.get('receipt_nbr') for r in raw_list if r.get('receipt_nbr')
        ))

        existing = Picking.search([
            ('adt_receipt_nbr', 'in', receipt_numbers)
        ])
        existing_set = set(existing.mapped('adt_receipt_nbr'))

        lines_to_create = []
        new_count = 0
        existing_count = 0

        for item in raw_list:
            receipt_nbr = item.get('receipt_nbr')

            if receipt_nbr in existing_set:
                msg = 'Sudah ada → akan diupdate'
                existing_count += 1
            else:
                msg = ''
                new_count += 1

            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': msg,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })

            lines_to_create.append(vals)

        records = self.env['acumatica.receipt.line'].create(lines_to_create)

        return records, new_count, existing_count

    # =============================
    # VIEW STAGING DATA
    # =============================
    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Inventory Receipt dari Acumatica',
            'res_model': 'acumatica.receipt.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    # =============================
    # IMPORT MANUAL (Jika staging mode)
    # =============================
    def action_import_all_pending(self):
        self.ensure_one()

        lines = self.env['acumatica.receipt.line'].search([
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
            'name': 'Hasil Import Inventory Receipt',
            'res_model': 'acumatica.receipt.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }