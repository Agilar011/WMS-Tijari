from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging
from odoo.tools import split_every

_logger = logging.getLogger(__name__)


class AcumaticaCustomerLocation(models.Model):
    """
    Model master untuk Customer Location dari Acumatica.
    Bukan extend res.partner — disimpan sebagai tabel tersendiri.

    Foreign Key ke tabel yang sudah ada:
      - partner_id   → res.partner      (lookup by company_registry = Customer)
      - warehouse_id → stock.warehouse  (lookup by code = Warehouse)

    Mapping:
      note                → adt_note
      Active              → adt_is_active
      AddressOverride     → adt_address_override
      CreatedDateTime     → adt_created_datetime
      Customer            → partner_id (FK)
      Default             → adt_default
      EntityUsageType     → adt_usage_type
      ExtRefNbr           → adt_ext_ref_number
      FedExGroundCollect  → adt_fed_ex_ground_collect
      FOBPoint            → adt_fob_point
      Insurance           → adt_insurance
      LastModifiedDateTime → adt_last_modified_datetime
      LeadTimeDays        → adt_lead_time_days
      LocationID          → adt_location_id
      LocationName        → name
      NoteID              → adt_note_id
      OrderPriority       → adt_order_priority
      ShippingBranch      → adt_shipping_branch
      ShippingZone        → adt_shipping_zone
      ShipVia             → adt_ship_via
      Status              → adt_status
      Warehouse           → warehouse_id (FK)

      LocationContact/Address:
        AddressLine1      → street
        City              → city
        State             → adt_state_code
        Country           → adt_country_code
        PostalCode        → zip
    """
    _name        = 'acumatica.customer.location'
    _description = 'Customer Location dari Acumatica'
    _rec_name    = 'name'
    _order       = 'partner_id, name'

    # ── Identitas ────────────────────────────────────
    adt_external_id  = fields.Char(string='UUID Acumatica', index=True)
    adt_location_id  = fields.Char(string='LocationID (Acumatica)')
    name             = fields.Char(string='Location Name', required=True)

    # ── Foreign Keys ─────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        index=True,
        ondelete='cascade',
        help='Customer Odoo (linked by CustomerID → company_registry)',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        index=True,
        ondelete='set null',
        help='Warehouse Odoo (linked by Warehouse code)',
    )

    # ── Field Mandatory ──────────────────────────────
    adt_is_active          = fields.Boolean(string='Active (Acumatica)', default=True)
    adt_address_override   = fields.Boolean(string='Address Override')
    adt_fob_point          = fields.Char(string='FOB Point')
    adt_shipping_branch    = fields.Char(string='Shipping Branch')
    adt_status             = fields.Selection([
        ('Active',   'Active'),
        ('Inactive', 'Inactive'),
    ], string='Status (Acumatica)')

    # ── Field Optional ───────────────────────────────
    adt_default            = fields.Boolean(string='Default Location')
    adt_usage_type         = fields.Char(string='Entity Usage Type')
    adt_ext_ref_number     = fields.Char(string='Ext Ref Number')
    adt_fed_ex_ground_collect = fields.Boolean(string='FedEx Ground Collect')
    adt_insurance          = fields.Boolean(string='Insurance')
    adt_lead_time_days     = fields.Integer(string='Lead Time Days')
    adt_note_id            = fields.Char(string='Note ID (Acumatica)')
    adt_note               = fields.Text(string='Note (Acumatica)')
    adt_order_priority     = fields.Integer(string='Order Priority')
    adt_shipping_zone      = fields.Char(string='Shipping Zone')
    adt_ship_via           = fields.Char(string='Ship Via')
    adt_created_datetime   = fields.Datetime(string='Created Date (Acumatica)')
    adt_last_modified_datetime = fields.Datetime(string='Last Modified (Acumatica)')

    # ── Address dari LocationContact/Address ─────────
    street    = fields.Char(string='Address Line 1')
    city      = fields.Char(string='City')
    zip       = fields.Char(string='Postal Code')
    adt_state_code   = fields.Char(string='State Code')
    adt_country_code = fields.Char(string='Country Code')

    # ── Computed: nama lengkap untuk display ─────────
    display_name_full = fields.Char(
        string='Display Name',
        compute='_compute_display_name_full',
        store=True,
    )

    @api.depends('partner_id', 'name', 'adt_location_id')
    def _compute_display_name_full(self):
        for rec in self:
            parts = []
            if rec.partner_id:
                parts.append(rec.partner_id.name)
            if rec.adt_location_id:
                parts.append(f'[{rec.adt_location_id}]')
            if rec.name:
                parts.append(rec.name)
            rec.display_name_full = ' / '.join(parts)


class AcumaticaCustomerLocationLine(models.Model):
    """
    Tabel staging: hasil tarikan Customer Location dari Acumatica.
    Setelah fetch, data diimport ke acumatica.customer.location.
    """
    _name        = 'acumatica.customer.location.line'
    _description = 'Data Customer Location dari Acumatica (Staging)'
    _order       = 'row_number asc'

    # ── Data mentah dari Acumatica ────────────────────
    row_number             = fields.Integer(string='No',           readonly=True)
    external_id            = fields.Char(string='UUID Acumatica',  readonly=True)

    # Mandatory
    customer               = fields.Char(string='Customer',        readonly=True)
    location_id_acumatica  = fields.Char(string='LocationID',      readonly=True)
    location_name          = fields.Char(string='LocationName',    readonly=True)
    is_active              = fields.Boolean(string='Active',       readonly=True)
    address_override       = fields.Boolean(string='AddressOverride', readonly=True)
    fob_point              = fields.Char(string='FOBPoint',        readonly=True)
    shipping_branch        = fields.Char(string='ShippingBranch',  readonly=True)
    status                 = fields.Char(string='Status',          readonly=True)
    warehouse              = fields.Char(string='Warehouse',       readonly=True)

    # Optional
    is_default             = fields.Boolean(string='Default',      readonly=True)
    usage_type             = fields.Char(string='EntityUsageType', readonly=True)
    ext_ref_number         = fields.Char(string='ExtRefNbr',       readonly=True)
    fed_ex_ground_collect  = fields.Boolean(string='FedExGroundCollect', readonly=True)
    insurance              = fields.Boolean(string='Insurance',    readonly=True)
    lead_time_days         = fields.Integer(string='LeadTimeDays', readonly=True)
    note_id                = fields.Char(string='NoteID',          readonly=True)
    note                   = fields.Text(string='Note',            readonly=True)
    order_priority         = fields.Integer(string='OrderPriority', readonly=True)
    shipping_zone          = fields.Char(string='ShippingZone',    readonly=True)
    ship_via               = fields.Char(string='ShipVia',         readonly=True)
    created_datetime       = fields.Char(string='CreatedDateTime', readonly=True)
    last_modified_datetime = fields.Char(string='LastModifiedDateTime', readonly=True)
    tax_exemption_number   = fields.Char(string='TaxExemptionNbr', readonly=True)
    tax_registration_id    = fields.Char(string='TaxRegistrationID', readonly=True)

    # Address dari LocationContact/Address
    address_line1          = fields.Char(string='AddressLine1',    readonly=True)
    address_line2          = fields.Char(string='AddressLine2',    readonly=True)
    city                   = fields.Char(string='City',            readonly=True)
    postal_code            = fields.Char(string='PostalCode',      readonly=True)
    state_code             = fields.Char(string='State',           readonly=True)
    country_code           = fields.Char(string='Country',         readonly=True)
    country_name           = fields.Char(string='CountryName',     readonly=True)

    # ── Status Import ─────────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated',  'Diupdate'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message   = fields.Char(string='Keterangan', readonly=True)
    odoo_location_id = fields.Many2one(
        'acumatica.customer.location',
        string='Location di Odoo',
        readonly=True,
    )
    odoo_partner_id  = fields.Many2one(
        'res.partner',
        string='Customer di Odoo',
        readonly=True,
    )
    selected  = fields.Boolean(string='Pilih', default=True)
    config_id = fields.Many2one(
        'acumatica.customer.location.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # ── Helpers ──────────────────────────────────────
    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    def _find_existing_location(self, rec):
        """Cari by UUID dulu, fallback by LocationID + partner."""
        Loc = self.env['res.partner']
        if rec.location_id_acumatica:
            found = Loc.search([
                ('name', '=', rec.location_id_acumatica),
                ('parent_id.company_registry', '=', rec.customer),
            ], limit=1)
            if found:
                return found
        return Loc.browse()

    def _resolve_partner(self, customer_code):
        """Lookup res.partner by company_registry = Customer."""
        if not customer_code:
            return self.env['res.partner'].browse()
        return self.env['res.partner'].search([
            ('company_registry', '=', customer_code)
        ], limit=1)

    def _resolve_warehouse(self, warehouse_code):
        """Lookup stock.warehouse by code = Warehouse."""
        if not warehouse_code:
            return self.env['stock.warehouse'].browse()
        return self.env['stock.warehouse'].search([
            ('code', '=', warehouse_code)
        ], limit=1)

    # ── Import Actions ────────────────────────────────
    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    # def _do_import(self):
    #     imported = updated = error = 0

    #     STATUS_MAP = {'Active': 'Active', 'Inactive': 'Inactive'}

    #     for line in self:
    #         try:
    #             if not line.customer:
    #                 line.write({
    #                     'import_state':   'error',
    #                     'import_message': 'Customer kosong',
    #                 })
    #                 error += 1
    #                 continue

    #             # ── Resolve FK ───────────────────────────────
    #             partner  = self._resolve_partner(line.customer)
    #             warehouse = self._resolve_warehouse(line.warehouse)

    #             if not partner:
    #                 line.write({
    #                     'import_state':   'error',
    #                     'import_message': f'Customer "{line.customer}" tidak ditemukan di Odoo. Import Customer dulu.',
    #                 })
    #                 error += 1
    #                 continue
    #             country_id = self.env['res.country'].search([('code', '=', line.country_code)], limit=1).id if line.country_code else False
    #             vals = {
    #                 # Identitas
    #                 'adt_external_id':  line.external_id or False,
    #                 'name':             line.location_id_acumatica or False,
    #                 'type':             'other',
    #                 'company_type':     'person',
    #                 'is_company':       False,

    #                 'adt_note':                  line.note or False,
    #                 # 'adt_is_active':             line.is_active,
    #                 'adt_address_override':      line.address_override,
    #                 'adt_created_datetime':      self._parse_dt(line.created_datetime),
    #                 'parent_id':                 partner.id,
    #                 'adt_default':               line.is_default,
    #                 'adt_entity_usage_type':            line.usage_type or False,
    #                 'adt_ext_ref_nbr':        line.ext_ref_number or False,
    #                 'adt_fedex_ground_collect': line.fed_ex_ground_collect,
    #                 'adt_fob_point':             line.fob_point or False,
    #                 'adt_shipping_branch':       line.shipping_branch or False,
    #                 'adt_insurance':             line.insurance,
    #                 'adt_acumatica_write_date':  self._parse_dt(line.last_modified_datetime),
    #                 'adt_lead_time_days':        line.lead_time_days or 0,

    #                 'adt_note_id':               line.note_id or False,
    #                 'adt_order_priority':        line.order_priority or 0,
    #                 'adt_shipping_zone_id':         line.shipping_zone or False,
    #                 'adt_ship_via':              line.ship_via or False,
    #                 'adt_status':                STATUS_MAP.get(line.status or '', False),
    #                 'adt_tax_exemption_number':  line.tax_exemption_number or False,
    #                 'adt_tax_registration_id':   line.tax_registration_id or False,
    #                 'vat':                       line.tax_registration_id or False,  # untuk mempermudah pencarian di res.partner
    #                 'adt_warehouse_id':          warehouse.id if warehouse else False,

    #                 # Address
    #                 'street':          line.address_line1 or False,
    #                 'street2':         line.address_line2 or False,
    #                 'city':            line.city or False,
    #                 'zip':             line.postal_code or False,
    #                 'country_id':      country_id,
    #             }

    #             existing = self._find_existing_location(line)

    #             if existing:
    #                 existing.write(vals)
    #                 line.write({
    #                     'import_state':    'updated',
    #                     'import_message':  f'Diupdate: {existing.name}',
    #                     'odoo_partner_id': existing.id,
    #                 })
    #                 updated += 1
    #             else:
    #                 new_loc = self.env['res.partner'].create(vals)
    #                 line.write({
    #                     'import_state':    'imported',
    #                     'import_message':  f'Dibuat: {new_loc.name}',
    #                     'odoo_partner_id': new_loc.id,
    #                 })
    #                 imported += 1

    #         except Exception as e:
    #             _logger.error("Error import CustomerLocation %s-%s: %s",
    #                           line.customer, line.location_id_acumatica, str(e))
    #             line.write({
    #                 'import_state':   'error',
    #                 'import_message': str(e)[:200],
    #             })
    #             error += 1

    #     msg = f'Import selesai: {imported} dibuat, {updated} diupdate, {error} error.'
    #     return {
    #         'type': 'ir.actions.client',
    #         'tag':  'display_notification',
    #         'params': {
    #             'title':   'Import Customer Location',
    #             'message': msg,
    #             'type':    'success' if error == 0 else 'warning',
    #             'sticky':  True,
    #         },
    #     }


    def _do_import(self):
        BATCH_SIZE = 1000
        imported = 0
        updated = 0
        error = 0

        STATUS_MAP = {
            'Active': 'Active',
            'Inactive': 'Inactive'
        }

        ctx = {
            'tracking_disable': True,
            'mail_create_nolog': True,
            'mail_notrack': True,
            'mail_create_nosubscribe': True,
        }

        Partner = self.env['res.partner'].with_context(**ctx)

        # =====================================================
        # CACHE COUNTRY
        # =====================================================

        country_map = {}

        countries = self.env['res.country'].search([])

        for c in countries:
            country_map[(c.code or '').upper()] = c.id

        # =====================================================
        # CACHE WAREHOUSE
        # =====================================================

        warehouse_map = {}

        warehouses = self.env['stock.warehouse'].search([])

        for wh in warehouses:
            warehouse_map[wh.name] = wh.id

        # =====================================================
        # CACHE CUSTOMER
        # =====================================================

        customer_names = list(set([
            x.customer
            for x in self
            if x.customer
        ]))

        customer_map = {}

        if customer_names:

            customers = Partner.search([
                ('name', 'in', customer_names)
            ])

            for c in customers:
                customer_map[c.name] = c.id

        # =====================================================
        # CACHE EXISTING LOCATION
        # =====================================================

        external_ids = list(set([
            x.external_id
            for x in self
            if x.external_id
        ]))

        existing_map = {}

        if external_ids:

            self.env.cr.execute("""
                SELECT id, adt_external_id
                FROM res_partner
                WHERE adt_external_id IN %s
            """, [tuple(external_ids)])

            for row in self.env.cr.fetchall():

                existing_map[row[1]] = row[0]

        # =====================================================
        # PROCESS CHUNK
        # =====================================================

        for chunk in split_every(BATCH_SIZE, self):

            try:

                create_vals = []

                update_params = []

                staging_success = []

                staging_error = []

                # =============================================
                # PREPARE
                # =============================================

                for line in chunk:

                    try:

                        # =====================================
                        # VALIDATION
                        # =====================================

                        if not line.customer:

                            staging_error.append((
                                'error',
                                'Customer kosong',
                                line.id
                            ))

                            error += 1
                            continue

                        partner_id = customer_map.get(
                            line.customer
                        )

                        if not partner_id:

                            staging_error.append((
                                'error',
                                f'Customer "{line.customer}" tidak ditemukan',
                                line.id
                            ))

                            error += 1
                            continue

                        warehouse_id = warehouse_map.get(
                            line.warehouse
                        )

                        country_id = country_map.get(
                            (line.country_code or '').upper()
                        )

                        vals = {
                            'adt_external_id':
                                line.external_id or False,

                            'name':
                                line.location_id_acumatica or False,

                            'type':
                                'other',

                            'company_type':
                                'person',

                            'is_company':
                                False,

                            'adt_note':
                                line.note or False,

                            'adt_address_override':
                                line.address_override,

                            'adt_created_datetime':
                                self._parse_dt(
                                    line.created_datetime
                                ),

                            'parent_id':
                                partner_id,

                            'adt_default':
                                line.is_default,

                            'adt_entity_usage_type':
                                line.usage_type or False,

                            'adt_ext_ref_nbr':
                                line.ext_ref_number or False,

                            'adt_fedex_ground_collect':
                                line.fed_ex_ground_collect,

                            'adt_fob_point':
                                line.fob_point or False,

                            'adt_shipping_branch':
                                line.shipping_branch or False,

                            'adt_insurance':
                                line.insurance,

                            'adt_acumatica_write_date':
                                self._parse_dt(
                                    line.last_modified_datetime
                                ),

                            'adt_lead_time_days':
                                line.lead_time_days or 0,

                            'adt_note_id':
                                line.note_id or False,

                            'adt_order_priority':
                                line.order_priority or 0,

                            'adt_shipping_zone_id':
                                line.shipping_zone or False,

                            'adt_ship_via':
                                line.ship_via or False,

                            'adt_status':
                                STATUS_MAP.get(
                                    line.status or '',
                                    False
                                ),

                            'adt_tax_exemption_number':
                                line.tax_exemption_number or False,

                            'adt_tax_registration_id':
                                line.tax_registration_id or False,

                            'vat':
                                line.tax_registration_id or False,

                            'adt_warehouse_id':
                                warehouse_id or False,

                            # ADDRESS
                            'street':
                                line.address_line1 or False,

                            'street2':
                                line.address_line2 or False,

                            'city':
                                line.city or False,

                            'zip':
                                line.postal_code or False,

                            'country_id':
                                country_id or False,
                        }

                        existing_id = existing_map.get(
                            line.external_id
                        )

                        # =====================================
                        # CREATE
                        # =====================================

                        if not existing_id:

                            vals['_line_id'] = line.id

                            create_vals.append(vals)

                        # =====================================
                        # UPDATE
                        # =====================================

                        else:

                            update_params.append((
                                line.location_id_acumatica or False,
                                line.note or False,
                                line.address_override,
                                self._parse_dt(
                                    line.created_datetime
                                ),
                                partner_id,
                                line.is_default,
                                line.usage_type or False,
                                line.ext_ref_number or False,
                                line.fed_ex_ground_collect,
                                line.fob_point or False,
                                line.shipping_branch or False,
                                line.insurance,
                                self._parse_dt(
                                    line.last_modified_datetime
                                ),
                                line.lead_time_days or 0,
                                line.note_id or False,
                                line.order_priority or 0,
                                line.shipping_zone or False,
                                line.ship_via or False,
                                STATUS_MAP.get(
                                    line.status or '',
                                    False
                                ),
                                line.tax_exemption_number or False,
                                line.tax_registration_id or False,
                                line.tax_registration_id or False,
                                warehouse_id or False,
                                line.address_line1 or False,
                                line.address_line2 or False,
                                line.city or False,
                                line.postal_code or False,
                                country_id or False,
                                existing_id
                            ))

                            staging_success.append((
                                'updated',
                                f'Diupdate: {line.location_id_acumatica}',
                                existing_id,
                                line.id
                            ))

                            updated += 1

                    except Exception as e:

                        staging_error.append((
                            'error',
                            str(e)[:200],
                            line.id
                        ))

                        error += 1

                # =============================================
                # BULK CREATE ORM
                # =============================================

                if create_vals:

                    clean_vals = []

                    line_map = {}

                    for vals in create_vals:

                        line_id = vals.pop('_line_id')

                        line_map[
                            vals['adt_external_id']
                        ] = line_id

                        clean_vals.append(vals)

                    new_locations = Partner.create(
                        clean_vals
                    )

                    for loc in new_locations:

                        staging_success.append((
                            'imported',
                            f'Dibuat: {loc.name}',
                            loc.id,
                            line_map[loc.adt_external_id]
                        ))

                        imported += 1

                # =============================================
                # BULK SQL UPDATE
                # =============================================

                if update_params:

                    self.env.cr.executemany("""
                        UPDATE res_partner
                        SET name = %s,
                            adt_note = %s,
                            adt_address_override = %s,
                            adt_created_datetime = %s,
                            parent_id = %s,
                            adt_default = %s,
                            adt_entity_usage_type = %s,
                            adt_ext_ref_nbr = %s,
                            adt_fedex_ground_collect = %s,
                            adt_fob_point = %s,
                            adt_shipping_branch = %s,
                            adt_insurance = %s,
                            adt_acumatica_write_date = %s,
                            adt_lead_time_days = %s,
                            adt_note_id = %s,
                            adt_order_priority = %s,
                            adt_shipping_zone_id = %s,
                            adt_ship_via = %s,
                            adt_status = %s,
                            adt_tax_exemption_number = %s,
                            adt_tax_registration_id = %s,
                            vat = %s,
                            adt_warehouse_id = %s,
                            street = %s,
                            street2 = %s,
                            city = %s,
                            zip = %s,
                            country_id = %s
                        WHERE id = %s
                    """, update_params)

                # =============================================
                # BULK STAGING SUCCESS
                # =============================================

                if staging_success:

                    self.env.cr.executemany("""
                        UPDATE acumatica_customer_location_line
                        SET import_state = %s,
                            import_message = %s,
                            odoo_partner_id = %s
                        WHERE id = %s
                    """, staging_success)

                # =============================================
                # BULK STAGING ERROR
                # =============================================

                if staging_error:

                    self.env.cr.executemany("""
                        UPDATE acumatica_customer_location_line
                        SET import_state = %s,
                            import_message = %s
                        WHERE id = %s
                    """, staging_error)

                # =============================================
                # COMMIT PER CHUNK
                # =============================================

                self.env.cr.commit()

                self.env.clear()

            except Exception as e:

                self.env.cr.rollback()

                _logger.exception(
                    "IMPORT CUSTOMER LOCATION ERROR: %s",
                    str(e)
                )

                for line in chunk:

                    self.env.cr.execute("""
                        UPDATE acumatica_customer_location_line
                        SET import_state = 'error',
                            import_message = %s
                        WHERE id = %s
                    """, (
                        str(e)[:200],
                        line.id
                    ))

                self.env.cr.commit()

        # =====================================================
        # RESULT
        # =====================================================

        msg = (
            f'Import selesai: '
            f'{imported} dibuat, '
            f'{updated} diupdate, '
            f'{error} error.'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Customer Location',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            },
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({
            'import_state':   'pending',
            'import_message': False,
        })

    def action_open_location(self):
        self.ensure_one()
        if not self.odoo_partner_id:
            raise UserError('Belum diimport.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id':    self.odoo_partner_id.id,
            'view_mode': 'form',
        }
