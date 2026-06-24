from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging
import time


_logger = logging.getLogger(__name__)


class AcumaticaCustomerLine(models.Model):
    """
    Tabel staging: hasil tarikan data Customer dari Acumatica.
    Setelah fetch, user bisa preview & pilih mana yang diimport ke res.partner.

    Mapping:
      CustomerID            → company_registry        (Mandatory)
      BAccountID            → property_b_account_id   (Mandatory, to be)
      CustomerName          → complete_name / name     (Mandatory)
      CustomerClass         → property_class           (Optional, to be)
      Status                → property_state_acumatica (Mandatory, to be)
      CurrencyID            → property_currency_acumatica (Optional, to be)
      WarehouseID           → property_stock_customer  (Mandatory, to be)
      ShippingZoneID        → property_shipping_zone_id (Mandatory, to be)
      FOBPoint              → property_fob_point       (Mandatory, to be)
      CreatedDateTime       → property_created_datetime (Optional, to be)
      LastModifiedDateTime  → property_last_modified_datetime (Optional, to be)
      NoteID                → acumatica_note_id        (Optional, to be)
      Note                  → acumatica_note           (Optional, to be)
      LocationName          → name (contact/location)  (Optional)
    """
    _name = 'acumatica.customer.line'
    _description = 'Data Customer dari Acumatica (Staging)'
    _order = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number             = fields.Integer(string='No', readonly=True)
    external_id            = fields.Char(string='UUID Acumatica', readonly=True)

    # Mandatory fields
    customer_id            = fields.Char(string='CustomerID', readonly=True)
    b_account_id           = fields.Char(string='BAccountID', readonly=True)
    customer_name          = fields.Char(string='CustomerName', readonly=True)
    status                 = fields.Char(string='Status', readonly=True)
    warehouse_id           = fields.Char(string='WarehouseID', readonly=True)
    shipping_zone_id       = fields.Char(string='ShippingZoneID', readonly=True)
    fob_point              = fields.Char(string='FOBPoint', readonly=True)

    # Optional fields
    customer_class         = fields.Char(string='CustomerClass', readonly=True)
    currency_id            = fields.Char(string='CurrencyID', readonly=True)
    created_datetime       = fields.Char(string='CreatedDateTime', readonly=True)
    tax_registration_id    = fields.Char(string='TaxRegistrationID', readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime', readonly=True)
    note_id                = fields.Char(string='NoteID', readonly=True)
    note                   = fields.Text(string='Note', readonly=True)
    location_name          = fields.Char(string='LocationName', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('skipped',  'Dilewati (Sudah Ada)'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message    = fields.Char(string='Keterangan', readonly=True)
    odoo_partner_id   = fields.Many2one('res.partner', string='Partner di Odoo', readonly=True)

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # ─── Computed: sudah ada di Odoo? ────────────────
    exists_in_odoo = fields.Boolean(
        string='Sudah Ada di Odoo',
        compute='_compute_exists_in_odoo',
        store=False,
    )

    @api.depends('customer_id', 'external_id')
    def _compute_exists_in_odoo(self):
        for rec in self:
            existing = self._find_existing_partner(rec)
            rec.exists_in_odoo = bool(existing)

    def _find_existing_partner(self, rec):
        """Cari partner yang sudah ada berdasarkan UUID dulu, lalu CustomerID."""
        Partner = self.env['res.partner']
        if rec.b_account_id:
            found = Partner.search([('adt_b_account_id', '=', rec.b_account_id)], limit=1)
            if found:
                return found
        if rec.customer_id:
            found = Partner.search([('company_registry', '=', rec.customer_id)], limit=1)
            if found:
                return found
        return Partner

    # ─── Helpers parse datetime ──────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        """Parse ISO datetime string dari Acumatica, return datetime atau False."""
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    # ─── Import Actions ──────────────────────────────
    def action_import_selected(self):
        lines = self.filtered(lambda l: l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        print('MULAI IMPORT CUSTOMER')
        """
        Import/update data Customer ke res.partner Odoo.
        - Field standar Odoo: langsung diisi
        - Field "to be": diisi ke field custom di res.partner
        """
        imported = updated = skipped = error = 0

        for line in self:
            try:
                if not line.customer_name:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'CustomerName kosong',
                    })
                    error += 1
                    continue

                # ── Siapkan values ──────────────────────────
                vals = {
                    # Field standar Odoo
                    'name':             line.customer_name,
                    'company_registry': line.customer_id or False,
                    # 'customer_rank':    1,
                    'is_company':       True,

                    # Field "to be" (custom) - semua diprefix acumatica_
                    # agar tidak conflict dengan field bawaan Odoo
                    'adt_external_id':              line.external_id or False,
                    'adt_note':                     line.note or False,
                    'adt_b_account_id':             line.b_account_id or False,
                    'adt_customer_class':           line.customer_class or False,
                    'adt_fob_point':                line.fob_point or False,
                    'adt_acumatica_write_date':     self._parse_dt(line.last_modified_datetime),
                    'adt_location_name':            line.location_name or False,
                    'adt_note_id':                  line.note_id or False,
                    'adt_shipping_zone_id':         line.shipping_zone_id or False,
                    'adt_status':                   line.status or False,
                    'adt_tax_registration_id':      line.tax_registration_id or False,
                    'adt_warehouse_id':             line.warehouse_id or False,
                    'partner_type':                 'customer',
                }

                # Map Status → selection field
                if line.status:
                    status_map = {
                        'active':     'Active',
                        'inactive':   'Inactive',
                        'hold':       'Hold',
                        'credithold': 'CreditHold',
                        'onetime':    'OneTime',
                    }
                    normalized = line.status.lower().replace(' ', '')
                    vals['adt_status'] = status_map.get(normalized, line.status)

                # ── Cek existing partner ────────────────────
                existing = self._find_existing_partner(line)

                if existing:
                    existing.write(vals)
                    line.write({
                        'import_state':   'updated',
                        'import_message': f'Diupdate: {existing.name} (ID: {existing.id})',
                        'odoo_partner_id': existing.id,
                    })
                    updated += 1
                else:
                    new_partner = self.env['res.partner'].create(vals)
                    line.write({
                        'import_state':   'imported',
                        'import_message': f'Dibuat: {new_partner.name} (ID: {new_partner.id})',
                        'odoo_partner_id': new_partner.id,
                    })
                    imported += 1

                print(f'PROCESSED LINE {line.row_number}: {line.customer_name} → {line.import_message}')
            except Exception as e:
                _logger.error("Error import Customer line %s: %s", line.customer_id, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {skipped} dilewati, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Customer',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Misc Actions ─────────────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state in ('skipped', 'error')).write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_partner(self):
        self.ensure_one()
        if not self.odoo_partner_id:
            raise UserError('Belum diimport, belum ada partner di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.odoo_partner_id.id,
            'view_mode': 'form',
        }
