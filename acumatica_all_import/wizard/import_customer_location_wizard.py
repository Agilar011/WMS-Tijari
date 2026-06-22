from odoo import models, fields
from odoo.exceptions import UserError

import requests
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
    batch_size = fields.Integer(
        string='Batch Size untuk Import',
        default=20,
        help='Jumlah record yang diproses per batch saat import. Sesuaikan dengan performa server dan jumlah data. Default 20.',
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
    # ACTION FETCH
    # =========================
    def action_fetch_data(self):
        self.ensure_one()

        if not self.config_id:
            raise UserError('Pilih API terlebih dahulu')

        # cleanup staging
        self.env['acumatica.customer.location.line'].search([
            ('config_id', '=', self.config_id.id)
        ]).unlink()

        # fetch dari API
        import math

        raw_list = 0
        raw_list_count = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_customer_location_data(
                limit=self.batch_size,
                offset=offset,
            )
            raw_list_count += batch_data

            if not batch_data:
                break
            # print(f"Batch {i+1} - Data Diterima: {len(batch_data)} - Total so far: {raw_list_count}")
            # raw_list.extend(batch_data)

        if not raw_list_count:
            raise UserError('Tidak ada data dari API')

        # Partner = self.env['res.partner']

        # new_count = existing_count = no_customer_count = 0
        # lines = []

        # batch_num = 0
        # for item in raw_list:
        #     batch_num += 1
        #     existing = Partner.search([
        #         ('name', '=', item['location_id_acumatica']),
        #         ('parent_id.company_registry', '=', item['customer'])
        #     ], limit=1)

        #     partner = Partner.search([
        #         ('company_registry', '=', item['customer'])
        #     ], limit=1)

        #     if existing:
        #         existing_count += 1
        #         msg = 'Update'
        #     elif not partner:
        #         no_customer_count += 1
        #         msg = 'Customer tidak ditemukan'
        #     else:
        #         new_count += 1
        #         msg = 'New'
            
        #     query = """
        #         INSERT INTO acumatica_customer_location_line (config_id, row_number, external_id, customer, location_id_acumatica, location_name, import_state, import_message, selected) 
        #         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        #     """
        #     params = (
        #         self.config_id.id,
        #         item['row_number'],
        #         item['external_id'],
        #         item['customer'],
        #         item['location_id_acumatica'],
        #         item['location_name'],
        #         'pending',
        #         msg,
        #          True if msg in ['Update', 'New'] else False
        #     )
        #     self.env.cr.execute(query, params)

        #     self.env['acumatica.customer.location.line']._invalidate_cache()
        #     print(f"DATA BERHASIL NAMBAH NIH - BATCH {batch_num}")

        #     lines.append({
        #         **item,
        #         'config_id': self.config_id.id,
        #         'external_id': item['external_id'],
        #         'customer': item['customer'],
        #         'location_id_acumatica': item['location_id_acumatica'],
        #         'location_name': item['location_name'],
        #         'import_state': 'pending',
        #         'import_message': msg,
        #         'selected': bool(partner),
        #     })

        # self.env['acumatica.customer.location.line'].create(lines)

        # self.write({
        #     'state': 'fetched',
        #     'total_fetched': len(raw_list),
        #     'total_new': new_count,
        #     'total_existing': existing_count,
        #     'total_no_customer': no_customer_count,
        # })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.customer.location.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # =========================
    # IMPORT
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

        lines._do_import()
        self.state = 'done'


    def fetch_customer_location_data(self, limit=100, offset=0):
        self.ensure_one()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/CustomerLocation"

            all_results = []
            params = {
                "$expand": "Contact/Address",
                "$top": limit,
                "$skip": offset,
            }

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data Customer Location '
                    f'(HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()

            # =========================
            # HELPER
            # =========================
            def val(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "") or ""
                return ""

            def bval(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    return bool(v.get("value", False))
                return False

            def ival(item, key):
                v = item.get(key, {})
                if isinstance(v, dict):
                    try:
                        return int(v.get("value", 0) or 0)
                    except:
                        return 0
                return 0

            # =========================
            # PARSE
            # =========================
            for item in raw_data:
                contact = item.get("Contact", {}) or {}
                address = contact.get("Address", {}) or {}

                def aval(key):
                    v = address.get(key, {})
                    if isinstance(v, dict):
                        return v.get("value", "") or ""
                    return ""

                all_results.append({
                    'external_id':          item.get("id", "") or "",
                    'row_number':           item.get("rowNumber", 0),
                    'note':                 item.get("note", {}).get("value", "") or "",
                    'is_active':            bval(item, "Active"),
                    'address_override':     bval(item, "AddressOverride"),
                    'created_datetime':     val(item, "CreatedDateTime"),
                    'customer':             val(item, "Customer"),
                    'is_default':           bval(item, "Default"),
                    'usage_type':           val(item, "EntityUsageType"),
                    'ext_ref_number':       val(item, "ExtRefNbr"),
                    'fed_ex_ground_collect': bval(item, "FedExGroundCollect"),
                    'fob_point':            val(item, "FOBPoint"),
                    'insurance':            bval(item, "Insurance"),
                    'last_modified_datetime': val(item, "LastModifiedDateTime"),
                    'lead_time_days':       ival(item, "LeadTimeDays"),
                    'location_id_acumatica': val(item, "LocationID"),
                    'location_name':        val(item, "LocationName"),
                    'order_priority':       ival(item, "OrderPriority"),
                    'shipping_branch':      val(item, "ShippingBranch"),
                    'shipping_zone':        val(item, "ShippingZone"),
                    'ship_via':             val(item, "ShipVia"),
                    'status':               val(item, "Status"),
                    'tax_exemption_number': val(item, "TaxExemptionNbr"),
                    'tax_registration_id':   val(item, "TaxRegistrationID"),
                    'warehouse':            val(item, "Warehouse"),

                    'note_id':              val(item, "NoteID"),
                    'address_line1':        aval("AddressLine1"),
                    'address_line2':        aval("AddressLine2"),
                    'city':                 aval("City"),
                    'country_code':         aval("Country"),
                    'country_name':         aval("CountryName"),
                    'postal_code':          aval("PostalCode"),
                    'state_code':           aval("State"),
                })

            _logger.info("TOTAL FINAL: %d records", len(all_results))
            Partner = self.env['res.partner']

            new_count = existing_count = no_customer_count = 0
            lines = []

            batch_num = 0
            for item in all_results:
                batch_num += 1
                existing = Partner.search([
                    ('name', '=', item['location_id_acumatica']),
                    ('parent_id.company_registry', '=', item['customer'])
                ], limit=1)

                partner = Partner.search([
                    ('company_registry', '=', item['customer'])
                ], limit=1)

                if existing:
                    existing_count += 1
                    msg = 'Update'
                elif not partner:
                    no_customer_count += 1
                    msg = 'Customer tidak ditemukan'
                else:
                    new_count += 1
                    msg = 'New'
                
                query = """
                    INSERT INTO acumatica_customer_location_line 
                    (
                    config_id,
                    external_id,
                    row_number,
                    customer,
                    
                    is_active,
                    address_override,
                    created_datetime,

                    is_default,
                    usage_type,
                    ext_ref_number,
                    fed_ex_ground_collect,
                    fob_point,
                    insurance,
                    last_modified_datetime,
                    lead_time_days,

                    order_priority,
                    shipping_branch,
                    shipping_zone,
                    ship_via,
                    status,
                    tax_exemption_number,
                    tax_registration_id,
                    warehouse,

                    note_id,
                    address_line1,
                    address_line2,
                    city,
                    country_code,
                    country_name,
                    postal_code,
                    state_code,


                    location_id_acumatica,
                    location_name,
                    import_state, 
                    import_message, 
                    selected
                    ) 
                    VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s)
                """
                params = (
                    self.config_id.id,
                    item['external_id'],
                    item['row_number'],
                    item['customer'],

                    item['is_active'],
                    item['address_override'],
                    item['created_datetime'],

                    item['is_default'],
                    item['usage_type'],
                    item['ext_ref_number'],
                    item['fed_ex_ground_collect'],
                    item['fob_point'],
                    item['insurance'],
                    item['last_modified_datetime'],
                    item['lead_time_days'],

                    item['order_priority'],
                    item['shipping_branch'],
                    item['shipping_zone'],
                    item['ship_via'],
                    item['status'],
                    item['tax_exemption_number'],
                    item['tax_registration_id'],
                    item['warehouse'],

                    item['note_id'],
                    item['address_line1'],
                    item['address_line2'],
                    item['city'],
                    item['country_code'],
                    item['country_name'],
                    item['postal_code'],
                    item['state_code'],

                    item['location_id_acumatica'],
                    item['location_name'],
                    'pending',
                    msg,
                    True if msg in ['Update', 'New'] else False
                )
                self.env.cr.execute(query, params)

                self.env['acumatica.customer.location.line']._invalidate_cache()
                print(f"DATA BERHASIL NAMBAH NIH - BATCH {batch_num}")

            return len(all_results)

        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

