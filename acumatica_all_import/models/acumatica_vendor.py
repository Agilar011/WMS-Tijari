from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
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
    _description = 'Data Vendor dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No',           readonly=True)
    external_id            = fields.Char(string='UUID Acumatica',  readonly=True)

    # Mandatory
    vendor_id              = fields.Char(string='VendorID',        readonly=True)
    vendor_name            = fields.Char(string='VendorName',      readonly=True)
    location_name          = fields.Char(string='LocationName',    readonly=True)
    status                 = fields.Char(string='Status',          readonly=True)
    lead_time_days         = fields.Integer(string='LeadTimedays', readonly=True)
    fob_point              = fields.Char(string='FOBPoint',        readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime', readonly=True)
    note                   = fields.Text(string='Note',            readonly=True)
    account_ref            = fields.Char(string='AccountRef',      readonly=True)
    b_account_id          = fields.Char(string='BAccountID',     readonly=True)

    # Optional
    vendor_class           = fields.Char(string='VendorClass',     readonly=True)

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
    selected        = fields.Boolean(string='Pilih',          default=True)

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

    def _find_existing_partner(self, rec):
        """Cari partner by UUID dulu, fallback by VendorID (company_registry)."""
        Partner = self.env['res.partner']
        if rec.external_id:
            found = Partner.search([('adt_external_id', '=', rec.external_id)], limit=1)
            if found:
                return found
        if rec.vendor_id:
            found = Partner.search([('company_registry', '=', rec.vendor_id)], limit=1)
            if found:
                return found
        return Partner.browse()

    # ─── Import Actions ──────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

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
        imported = updated = error = 0

        STATUS_MAP = {
            'active':   'Active',
            'inactive': 'Inactive',
            'hold':     'Hold',
            'onetime':  'OneTime',
        }

        for line in self:
            try:
                if not line.vendor_name:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'VendorName kosong',
                    })
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
                    existing.write(vals)
                    line.write({
                        'import_state':    'updated',
                        'import_message':  f'Diupdate: {existing.name} (ID: {existing.id})',
                        'odoo_partner_id': existing.id,
                    })
                    updated += 1
                else:
                    new_partner = self.env['res.partner'].create(vals)
                    line.write({
                        'import_state':    'imported',
                        'import_message':  f'Dibuat: {new_partner.name} (ID: {new_partner.id})',
                        'odoo_partner_id': new_partner.id,
                    })
                    imported += 1

            except Exception as e:
                _logger.error("Error import Vendor line %s: %s", line.vendor_id, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   'Import Vendor',
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