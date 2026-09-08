from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging
import time

from markupsafe import Markup, escape

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
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Customer dari Acumatica (Staging)'
    _order = 'row_number asc'

    # ─── Data mentah dari Acumatica ──────────────────
    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Acumatica', readonly=True)

    # Mandatory fields
    customer_id = fields.Char(string='CustomerID')
    b_account_id = fields.Char(string='BAccountID', readonly=True)
    customer_name = fields.Char(string='CustomerName')
    status = fields.Char(string='Status', readonly=True)
    warehouse_id = fields.Char(string='WarehouseID', readonly=True)
    shipping_zone_id = fields.Char(string='ShippingZoneID', readonly=True)
    fob_point = fields.Char(string='FOBPoint', readonly=True)

    # Optional fields
    customer_class = fields.Char(string='CustomerClass', readonly=True)
    tax_registration_id  = fields.Char(string='TaxRegistrationID', readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime')
    note_id = fields.Char(string='NoteID', readonly=True)
    note = fields.Text(string='Note', readonly=True)
    location_name = fields.Char(string='LocationName', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('staged',  'Staged'),
        ('created', 'Created'),
        ('updated',  'Updated'),
        ('rejected',  'Rejected'),
        ('error',    'Error'),
    ], string='Status', default='staged', readonly=True, tracking=True)

    import_message = fields.Char(string='Generation Message', readonly=True)
    odoo_partner_id = fields.Many2one('res.partner', string='Document Reference', readonly=True)

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

    acumatica_err_id = fields.Many2one('acumatica.error.master', string='Error ID')

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
        # if rec.customer_id:
        #     found = Partner.search([('company_registry', '=', rec.customer_id)], limit=1)
        #     if found:
        #         return found
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
        lines = self.filtered(lambda l: l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        # self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _do_import(self):
        print('MULAI IMPORT CUSTOMER')
        """
        Import/update data Customer ke res.partner Odoo.
        - Field standar Odoo: langsung diisi
        - Field "to be": diisi ke field custom di res.partner
        """
        created = updated = skipped = error = 0
        total = len(self)

        _logger.info("START IMPORT CUSTOMER; TOTAL_LINES=%s", total)

        for line in self:
            try:
                
                if not line.customer_name:
                    err_msg = 'CustomerName kosong'
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

                # ── Siapkan values ──────────────────────────
                vals = {
                    # Field standar Odoo
                    'name':             line.customer_name,
                    'company_registry': line.customer_id or False,
                    # 'customer_rank':    1,
                    'is_company':       True,
                    # 'active': False if line.status == "Inactive" else True,

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
                        'credithold': 'CreditHold',
                    }
                    normalized = line.status.lower().replace(' ', '')
                    vals['adt_status'] = status_map.get(normalized, line.status)

                # ── Cek existing partner ────────────────────
                existing = self._find_existing_partner(line)

                if existing:

                    changed_fields = line._get_changed_fields(
                        existing,
                        vals,
                    )       

                    existing.write(vals)
                    line.write({
                        'import_state':   'updated',
                        'import_message': f'Updated: {existing.name} (ID: {existing.id})',
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
                        'import_state':   'created',
                        'import_message': f'Dibuat: {new_partner.name} (ID: {new_partner.id})',
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

                print(f'PROCESSED LINE {line.row_number}: {line.customer_name} → {line.import_message}')
            except Exception as e:
                _logger.error("Error import Customer line %s: %s", line.customer_id, str(e))
                err_msg = str(e)[:200]

                line._handle_acumatica_error(err_msg)

                line.write({
                    'import_state':   'error',
                    'import_message': err_msg,
                })

                line._log_import_result(
                    'error',
                    f'Gagal mengimpor data: {err_msg}',
                    False,
                    False,
                )

                error += 1

        msg = f'Import selesai: {created} dibuat, {updated} diupdate, {skipped} dilewati, {error} error.'
        _logger.info(
            "FINISH IMPORT CUSTOMER; TOTAL_LINES=%s, CREATED=%s, UPDATED=%s, SKIPPED=%s, ERROR=%s",
            total,
            created,
            updated,
            skipped,
            error,
        )
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
                'name': f'Customer-{self.id}',
                'data_type': self._name,
                'import_state': state,
                'data_id': self.id,
                'error_msg': err_msg
            })
            self.acumatica_err_id = acumatica_err_id
            
        acumatica_err_id.error_msg = err_msg
        acumatica_err_id.import_state = state

    # ─── Misc Actions ─────────────────────────────────
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
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.odoo_partner_id.id,
            'view_mode': 'form',
        }

    def unlink(self):
        if self.acumatica_err_id:
            self.acumatica_err_id.unlink()
        return super(AcumaticaCustomerLine, self).unlink()

    # @api.model_create_multi
    # def create(self, vals_list):
    #     records = super().create(vals_list)

    #     for record in records:
    #         record.message_post(
    #             body=f"""
    #                 <p>
    #                     Data staging Customer
    #                     <b>{record.customer_name}</b>
    #                     berhasil dibuat.
    #                 </p>
    #             """,
    #             subtype_xmlid='mail.mt_note',
    #         )

    #     return records

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

        self.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
