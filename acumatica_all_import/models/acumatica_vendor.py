from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from markupsafe import Markup, escape
import logging

_logger = logging.getLogger(__name__)


class AcumaticaVendorLine(models.Model):
    """
    Tabel staging: hasil tarikan data Vendor dari Acumatica.
    Setelah fetch, user bisa preview & pilih mana yang diimport ke res.partner.

    Mapping ke res.partner:
      note                  → internal_notes         (Mandatory)
      FOBPoint              → adt_fob_point           (Mandatory)
      LastModifiedDateTime  → last_modified_datetime (Mandatory)
      LeadTimedays          → sale_delay              (Mandatory)
      LocationName          → name                    (Mandatory)
      Status                → adt_state               (Mandatory, to be)
      VendorClass           → adt_class               (Optional,  to be)
      VendorID              → company_registry        (Mandatory)
      VendorName            → complete_name / name    (Mandatory)
    """
    _name        = 'acumatica.vendor.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Vendor dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No')
    external_id            = fields.Char(string='UUID Acumatica')

    # Mandatory
    vendor_id              = fields.Char(string='VendorID')
    vendor_name            = fields.Char(string='VendorName')
    location_name          = fields.Char(string='LocationName')
    status                 = fields.Char(string='Status')
    lead_time_days         = fields.Integer(string='LeadTimedays')
    fob_point              = fields.Char(string='FOBPoint')
    last_modified_datetime = fields.Char(string='LastModifiedDateTime')
    note                   = fields.Text(string='Note')
    account_ref            = fields.Char(string='AccountRef')
    b_account_id          = fields.Char(string='BAccountID')

    # Optional
    vendor_class           = fields.Char(string='VendorClass')

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated',  'Updated'),
        ('rejected',  'Rejected'),
        ('error',    'Error'),
    ], string='Status', default='staged')

    import_message  = fields.Char(string='Generation Message')
    odoo_partner_id = fields.Many2one('res.partner', string='Document Reference')
    selected        = fields.Boolean(string='Pilih',          default=True)
    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync')

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

    def _find_existing_partner(self, rec):
        """Cari vendor berdasarkan External ID lalu BAccount ID Acumatica."""
        Partner = self.env['res.partner']
        if rec.external_id:
            found = Partner.search([('adt_external_id', '=', rec.external_id)], limit=1)
            if found:
                return found
        if rec.b_account_id:
            found = Partner.search([('adt_b_account_id', '=', rec.b_account_id)], limit=1)
            if found:
                return found
        return Partner.browse()

    def _sync_vendor_id_history(self, partner, old_vendor_id=False, new_vendor_id=False):
        """Simpan riwayat perubahan VendorID Acumatica."""
        self.ensure_one()
        old_vendor_id = (old_vendor_id or '').strip()
        new_vendor_id = (new_vendor_id or '').strip()
        if not partner or not new_vendor_id:
            return

        History = self.env['vendor.id.history']
        current_history = History.search([
            ('partner_id', '=', partner.id),
            ('is_current', '=', True),
        ])

        if old_vendor_id == new_vendor_id and current_history.filtered(
            lambda history: history.vendor_id == new_vendor_id
        ):
            return

        now = fields.Datetime.now()
        if current_history:
            current_history.write({
                'date_end': now,
                'is_current': False,
            })

        History.create({
            'partner_id': partner.id,
            'vendor_id': new_vendor_id,
            'date_start': now,
            'is_current': True,
        })

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
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
                'name': f'Vendor-{self.id}',
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
        Import/update data Vendor ke res.partner Odoo.

        Mapping:
          VendorName   → name
          VendorID     → company_registry
          note         → internal_notes (comment field di res.partner)
          LeadTimedays → sale_delay
          LocationName → (diabaikan jika sama dengan VendorName, else disimpan di adt_location_name future)
          FOBPoint     → adt_fob_point
          LastModifiedDateTime → adt_acumatica_write_date
          Status       → adt_state
          VendorClass  → adt_class
        """
        created = updated = error = 0
        total = len(self)

        print(f'[MASTER IMPORT][Vendor] START total={total}', flush=True)

        STATUS_MAP = {
            'active':   'Active',
            'inactive': 'Inactive',
            'hold':     'Hold',
            'onetime':  'OneTime',
        }

        for line in self:
            try:
                if not line.vendor_name:

                    err_msg = 'VendorName kosong'
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

                normalized_status = line.status.lower().replace(' ', '') if line.status else ''
                adt_state_val = STATUS_MAP.get(normalized_status, line.status or False)

                vals = {
                    # ── Field standar Odoo ──────────────────
                    'name':             line.vendor_name,
                    'company_registry': line.vendor_id or False,
                    'supplier_rank':    1,
                    'is_company':       True,
                    'comment':          line.note or False,       # internal_notes

                    # ── Field custom adt_ ───────────────────
                    'adt_external_id': line.external_id or False,
                    'adt_fob_point': line.fob_point or False,
                    'adt_lead_time_days': line.lead_time_days or 0,
                    'adt_acumatica_write_date': self._parse_dt(line.last_modified_datetime),
                    'adt_vendor_id': line.vendor_id or False,
                    # 'adt_account_ref': line.account_ref or False,
                    'adt_note': line.note or False,
                    'adt_b_account_id': line.b_account_id or False,
                    'adt_location_name': line.location_name or False,
                    'adt_status': line.status or False,
                    'partner_type': 'vendor',
                }

                existing = self._find_existing_partner(line)

                if existing:
                    old_vendor_id = existing.adt_vendor_id or False

                    changed_fields = line._get_changed_fields(
                        existing,
                        vals,
                    )
                    existing.write(vals)
                    line._sync_vendor_id_history(
                        existing,
                        old_vendor_id,
                        line.vendor_id,
                    )
                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Updated: {existing.name} (ID: {existing.id})',
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
                    line._sync_vendor_id_history(
                        new_partner,
                        new_vendor_id=line.vendor_id,
                    )
                    line.write({
                        'import_state':    'created',
                        'import_message':  f'Dibuat: {new_partner.name} (ID: {new_partner.id})',
                        'odoo_partner_id': new_partner.id,
                    })

                    line._handle_acumatica_error()

                    line._log_import_result(
                        'created',
                        f'Data {new_partner.display_name} berhasil dibuat.',
                        new_partner,
                        False
                    )
                    created += 1

            except Exception as e:
                _logger.error("Error import Vendor line %s: %s", line.vendor_id, str(e))

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

        msg = f'Import selesai: {created} dibuat, {updated} diupdate, {error} error.'
        print(
            f'[MASTER IMPORT][Vendor] FINISH total={total} '
            f'created={created} updated={updated} error={error}',
            flush=True,
        )
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag':  'display_notification',
        #     'params': {
        #         'title':   'Import Vendor',
        #         'message': msg,
        #         'type':    'success' if error == 0 else 'warning',
        #         'sticky':  True,
        #     },
        # }

    # ─── Misc Actions ────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'staged',
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

    def _get_changed_fields(self, record, vals):
        changed_fields = []

        for field_name, new_value in vals.items():
            field = record._fields.get(field_name)

            if not field:
                continue

            old_value = record[field_name]

            if field.type == 'many2one':
                old_value = old_value.id if old_value else False
                
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
