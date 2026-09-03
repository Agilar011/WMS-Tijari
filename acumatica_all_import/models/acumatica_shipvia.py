from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from markupsafe import Markup, escape
import logging

_logger = logging.getLogger(__name__)


class AcumaticaShipViaLine(models.Model):
    """
    Tabel staging: hasil tarikan data ShipVia dari Acumatica.
    Setelah fetch, user bisa preview & pilih mana yang diimport ke res.partner.

    Mapping ke res.partner:
          note                  → internal_notes
          Address               → street
          CarrierID             → carrier_code
          City                  → city
          Description           → name
          NoteID                → note_id
          Phone                 → phone
    """
    _name        = 'acumatica.shipvia.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data ShipVia dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No',           readonly=True)
    external_id            = fields.Char(string='UUID Acumatica',  readonly=True)

    # Mandatory
    note                   = fields.Text(string='Note',            readonly=True)
    address                = fields.Char(string='Address',         readonly=True)
    carrier_id             = fields.Char(string='Carrier ID',    readonly=True)
    city                   = fields.Char(string='City',    readonly=True)
    description            = fields.Char(string='Description',          readonly=True)
    note_id                = fields.Char(string='Note ID', readonly=True)
    phone                  = fields.Char(string='Phone',        readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('skipped',  'Dilewati'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message  = fields.Char(string='Keterangan',       readonly=True)
    odoo_partner_id = fields.Many2one('res.partner', string='Partner di Odoo', readonly=True)
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # ─── Helpers ─────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        """Parse ISO datetime string dari Acumatica, return datetime atau False."""
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    def _find_existing_shipvia(self, rec):
        """Cari ShipVia by UUID dulu, fallback by Shipvia (company_registry)."""
        Partner = self.env['res.partner']
        if rec.carrier_id:
            found = Partner.search([('company_registry', '=', rec.carrier_id)], limit=1)
            if found:
                return found
        return Partner.browse()

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

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
                'name': f'Shipvia-{self.id}',
                'data_type': self._name,
                'import_state': state,
                'data_id': self.id,
                'error_msg': err_msg
            })
            self.acumatica_err_id = acumatica_err_id
            
        acumatica_err_id.error_msg = err_msg
        acumatica_err_id.import_state = state

    def _get_changed_fields(self, record, vals):
        changed_fields = []

        for field_name, new_value in vals.items():
            field = record._fields.get(field_name)

            if not field:
                continue

            old_value = record[field_name]

            # Normalisasi nilai
            old_value = old_value or False
            new_value = new_value or False

            if old_value != new_value:
                changed_fields.append({
                    'field_name': field_name,
                    'field_label': field.string,
                    'old_value': old_value,
                    'new_value': new_value,
                })

        return changed_fields
    
    def _log_import_result(
        self,
        state,
        message,
        record=False,
        changed_fields=None,
    ):
        titles = {
            'imported': '✅ Import Berhasil',
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

        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
    
    def _do_import(self):
        """
        Import/update data ShipVia ke res.partner Odoo.
         Field mapping:
          note                  → internal_notes
          Address               → street
          CarrierID             → carrier_code
          City                  → city
          Description           → name
          NoteID                → note_id
          phone                 → phone
        """
        imported = updated = error = 0


        for line in self:
            try:
                if not line.description:

                    err_msg = 'Name kosong'
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

                vals = {
                    # ── Field standar Odoo ──────────────────
                    'adt_external_id': line.external_id,
                    'comment': line.note or False, # internal_notes
                    'street': line.address or False,
                    'name': line.description or False, # name
                    'phone': line.phone or False,
                    'mobile': line.phone or False,
                    'city': line.city or False,
                    'is_company': True,

                    # ── Field custom adt_ ───────────────────
                    'company_registry': line.carrier_id or False,
                    'partner_type': 'shipvia',
                }

                existing = self._find_existing_shipvia(line)

                if existing:
                    changed_fields = line._get_changed_fields(
                        existing,
                        vals,
                    )

                    existing.write(vals)
                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Diupdate: {existing.name} (ID: {existing.id})',
                        'odoo_partner_id': existing.id,
                    })

                    line._log_import_result(
                        'updated',
                        f'Data {existing.display_name} berhasil diperbarui.',
                        existing,
                        changed_fields,
                    )
                    
                    updated += 1
                else:
                    new_partner = self.env['res.partner'].create(vals)
                    line.write({
                        'import_state':    'imported',
                        'import_message':  f'Dibuat: {new_partner.name} (ID: {new_partner.id})',
                        'odoo_partner_id': new_partner.id,
                    })
                    line._handle_acumatica_error()
                    line._log_import_result(
                        'imported',
                        f'Data {new_partner.display_name} berhasil dibuat.',
                        new_partner,
                        False
                    )

                    imported += 1

            except Exception as e:
                _logger.error("Error import ShipVia line %s: %s", line.carrier_id, str(e))

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
                    False,
                )

                error += 1

        msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   'Import ShipVia',
                'message': msg,
                'type':    'success' if error == 0 else 'warning',
                'sticky':  True,
            },
        }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state in ('error', 'skipped')).write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_partner(self):
        self.ensure_one()
        if not self.odoo_partner_id:
            raise UserError('Belum diimport, belum ada partner di Odoo.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id':    self.odoo_partner_id.id,
            'view_mode': 'form',
        }