from odoo import models, fields, api
from odoo.exceptions import UserError
from markupsafe import Markup, escape
import logging

_logger = logging.getLogger(__name__)


class AcumaticaUomLine(models.Model):
    """
    Tabel staging: hasil tarikan data UoM dari Acumatica
    Mapping:
      - UnitID      → uom.uom.code
      - Description → uom.uom.name
    """
    _name = 'acumatica.uom.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data UoM dari Acumatica (Staging)'
    _order = 'row_number asc, unit_id asc'

    # ─── Data dari Acumatica ─────────────────────────
    row_number  = fields.Integer(string='No')
    unit_id = fields.Char(string='UnitID (→ Code)', required=True)
    description = fields.Char(string='Description (→ Nama UoM)')
    external_id = fields.Char(string='UUID Acumatica')
    last_modified_datetime = fields.Char(string='Last Modified')

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected',  'Rejected'),
        ('error',    'Error'),
    ], string='Status', default='staged')

    import_message = fields.Char(string='Generation Message')
    odoo_uom_id = fields.Many2one('uom.uom', string='Document Reference')
    odoo_categ_id = fields.Many2one('uom.category', string='Document Reference')
    selected = fields.Boolean(string='Pilih', default=True)
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync')


    def _clean_uom_value(self, value):
        return (value or '').strip()

    def _find_uom_by_name(self, name, category=False):
        name = self._clean_uom_value(name)
        if not name:
            return self.env['uom.uom'].browse()

        domain = [('name', '=ilike', name)]
        if category:
            domain.append(('category_id', '=', category.id))
        return self.env['uom.uom'].search(domain, limit=1)

    def _find_uom_by_code(self, code, category=False):
        code = self._clean_uom_value(code)
        if not code:
            return self.env['uom.uom'].browse()

        domain = [('code', '=ilike', code)]
        if category:
            domain.append(('category_id', '=', category.id))
        return self.env['uom.uom'].search(domain, limit=1)

    # ─── Computed: sudah ada di Odoo? ────────────────
    exists_in_odoo = fields.Boolean(
        string='Sudah Ada di Odoo',
        compute='_compute_exists_in_odoo',
        store=False,
    )

    @api.depends('unit_id', 'description')
    def _compute_exists_in_odoo(self):
        for rec in self:
            rec.exists_in_odoo = bool(
                rec._find_uom_by_code(rec.unit_id)
                or rec._find_uom_by_name(rec.description)
            )

    # ─── Action: Import baris yang dipilih ───────────
    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        """Import 1 baris saja (dari tombol di list)"""
        self.ensure_one()
        result = self._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _handle_acumatica_error(self, err_msg=False):
        AcumaticaError = self.env['acumatica.error.master']
        acumatica_err_id = self.acumatica_err_id
        if not err_msg:
            if acumatica_err_id:
                acumatica_err_id.import_state = 'solved'
                return
            return

        state = 'error'
        if not acumatica_err_id:
            acumatica_err_id = AcumaticaError.create({
                'name': f'UoM-{self.id}',
                'data_type': self._name,
                'import_state': state,
                'data_id': self.id,
                'error_msg': err_msg
            })
            self.acumatica_err_id = acumatica_err_id

        acumatica_err_id.import_state = state
        acumatica_err_id.error_msg = err_msg

    def _do_import(self):
        """
        Logika import:
          - UnitID      → uom.uom.code
          - Description → uom.uom.name di dalam kategori Unit
        """
        created = updated = skipped = error = 0

        for line in self:
            try:
                uom_name = line._clean_uom_value(line.description or line.unit_id)
                if not uom_name:

                    err_msg = 'Description kosong, tidak bisa jadi nama UoM'
                    line.write({
                        'import_state':   'error',
                        'import_message': err_msg,
                    })

                    line._handle_acumatica_error(err_msg)

                    line._log_import_result(
                        'error',
                        f'Gagal mengimpor data: {err_msg}',
                        False,
                        False
                    )

                    error += 1
                    continue

                # ── 1. Cari Kategori Unit ──
                uom_categ = self.env['uom.category'].search([
                    ('name', '=ilike', 'Unit')
                ], limit=1)
                if not uom_categ:
                    uom_categ = self.env['uom.category'].create({'name': 'Unit'})
                    _logger.info("Kategori UoM baru dibuat: %s", 'Unit')

                # ── 2. Cari berdasarkan Code, lalu fallback ke nama lama ──
                uom_code = line._clean_uom_value(line.unit_id)
                existing = line._find_uom_by_code(uom_code)
                if not existing:
                    existing = line._find_uom_by_name(uom_name)

                if existing:
                    old_name = existing.name
                    code_changed = bool(uom_code and existing.code != uom_code)
                    name_changed = existing.name != uom_name
                    if code_changed or name_changed:
                        existing.write({
                            'code': uom_code or existing.code,
                            'name': uom_name,
                        })
                        line.write({
                            'import_state': 'updated',
                            'import_message': f'Diperbarui: {old_name} → {uom_name} (Code: {uom_code or existing.code})',
                            'odoo_uom_id': existing.id,
                            'odoo_categ_id': existing.category_id.id,
                        })
                        line._handle_acumatica_error()
                        line._log_import_result(
                            'updated',
                            f'Data {existing.display_name} berhasil diperbarui berdasarkan UnitID/Code.',
                            existing,
                            False,
                        )
                        updated += 1
                        continue
                    line.write({
                        'import_state':   'rejected',
                        'import_message': f'Sudah ada: {existing.name} (kategori: {existing.category_id.name})',
                        'odoo_uom_id':    existing.id,
                        'odoo_categ_id':  existing.category_id.id,
                    })

                    skipped += 1
                else:
                    # Cek apakah kategori sudah punya reference unit
                    has_reference = self.env['uom.uom'].search([
                        ('category_id', '=', uom_categ.id),
                        ('uom_type', '=', 'reference'),
                    ], limit=1)

                    # ── 3. Buat uom.uom baru ──
                    new_uom = self.env['uom.uom'].create({
                        'code':        uom_code,
                        'name':        uom_name,
                        'category_id': uom_categ.id,
                        'uom_type':    'smaller' if has_reference else 'reference',
                        'factor':      1.0,
                        'rounding':    0.01,
                        'active':      True,
                    })
                    line.write({
                        'import_state':   'created',
                        'import_message': f'Dibuat: {new_uom.name} → kategori: {uom_categ.name}',
                        'odoo_uom_id':    new_uom.id,
                        'odoo_categ_id':  uom_categ.id,
                    })

                    line._handle_acumatica_error()

                    line._log_import_result(
                        'created',
                        f'Data {new_uom.display_name} berhasil dibuat.',
                        new_uom,
                        False
                    )
                    
                    created += 1

            except Exception as e:
                _logger.error("Error import UoM line %s / %s: %s", line.unit_id, line.description, str(e))

                err_msg = str(e)[:200]
                line.write({
                    'import_state':   'error',
                    'import_message': err_msg,
                })

                line._handle_acumatica_error(err_msg)

                line._log_import_result(
                    'error',
                    f'Gagal mengimpor data: {err_msg}',
                    False,
                    False
                )

                error += 1

        # Notifikasi hasil
        msg = f'Import selesai: {created} dibuat, {updated} diperbarui, {skipped} dilewati, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import UoM',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Action: Reset status ─────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state': 'staged',
            'import_message': False,
        })

    def _log_import_result(
        self,
        state,
        message,
        record=False,
        changed_fields=None,
    ):
        titles = {
            'created': '✅ Import Berhasil',
            'updated': '🔄 Data Diperbarui',
            'error': '❌ Import Gagal',
        }

        body = Markup("""
            <p>
                <strong>{}</strong>
            </p>
            <p>{}</p>
        """).format(
            titles.get(state, 'Import Log'),
            message,
        )

        if changed_fields:
            body += Markup("""
                <p><strong>Perubahan:</strong></p>
                <ul>
            """)

            for change in changed_fields:
                old_value = change['old_value'] or '-'
                new_value = change['new_value'] or '-'

                body += Markup("""
                    <li>
                        <strong>{}</strong>:
                        {} → {}
                    </li>
                """).format(
                    escape(change['field_label']),
                    escape(str(old_value)),
                    escape(str(new_value)),
                )

            body += Markup("</ul>")

        if record:
            body += Markup("""
                <p>
                    Record Odoo:
                    <a href="#"
                    data-oe-model="{}"
                    data-oe-id="{}">
                        {}
                    </a>
                </p>
            """).format(
                escape(record._name),
                record.id,
                escape(record.display_name),
            )

        self.with_context(
            mail_create_nosubscribe=True,
            mail_post_autofollow=False,
        ).message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
