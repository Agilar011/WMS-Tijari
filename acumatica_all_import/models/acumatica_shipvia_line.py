from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
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
    selected        = fields.Boolean(string='Pilih',          default=True)

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.shipvia.config',
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
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

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
                    line.write({
                        'import_state':   'error',
                        'import_message': 'Name kosong',
                    })
                    error += 1
                    continue

                vals = {
                    # ── Field standar Odoo ──────────────────
                    'comment': line.note or False, # internal_notes
                    'name': line.description or False, # name
                    'street': line.address or False,
                    'phone': line.phone or False,
                    'city': line.city or False,

                    # ── Field custom adt_ ───────────────────
                    'company_registry': line.carrier_id or False,
                    'partner_type': 'shipvia',
                }

                existing = self._find_existing_shipvia(line)

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
                _logger.error("Error import ShipVia line %s: %s", line.carrier_id, str(e))
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