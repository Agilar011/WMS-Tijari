import logging
import time
from dateutil import parser as dateutil_parser
from docutils.nodes import note
import requests
import ast
import json

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class ImportSOShipmentWizard(models.TransientModel):
    _name = 'import.so.shipment.wizard'
    _description = 'Wizard Import Shipment Receipt dari Acumatica'

    # base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity', default="http://staging.aditya.group/acumportal/entity")
    shipment_gi_endpoint = fields.Char(required=True, default="ShipmentGI")
    shipment_gi_expand = fields.Char(required=True, default="ShipmentGIDetails")
    endpoint_name = fields.Char(required=True, default='ShipmentGI')

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    receipt_nbr = fields.Char(string='Filter Shipment Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    wh33_filter = fields.Boolean(string='WH33 Only', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Char(string="Start Date")
    end_date = fields.Char(string="End Date")
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    def action_fetch_data(self):
        print(f"Self Limit: {self.fetch_limit}")
        self.ensure_one()
        # self.env['acumatica.so.shipment.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        shipment_gi_data, shipment_numbers = self.fetch_shipment_gi_data()

        if not shipment_numbers:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')


        batch_data = self.config_id.fetch_shipment_data(
            shipment_numbers=shipment_numbers,  # tambahan
            odata_filter=self.odata_filter,
        )

        if not batch_data:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        
        created_sales_order_shipment_record = self.config_id.create_staging_data(shipment_gi_data, batch_data)

        self.write({
            'state': 'fetched',
            'total_fetched': len(batch_data),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.so.shipment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


# Function Get and create staging data

    def fetch_shipment_gi_data(self):

        print("fetching shipment GI data")
        # self.env['acumatica.shipment.gi.staging'].search([]).unlink()


        self.ensure_one()
        # session = self._do_login()
        session = self.config_id._do_login()
        print("Login Success")

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"

            params = {}
            if self.shipment_gi_expand:
                params["$expand"] = self.shipment_gi_expand

            session.headers.update({
                "Accept": "application/json",
                "Content-Type": "application/json",
            })


            print("Endpoint: ")
            print(endpoint)
            print("params: ")
            print(params)

            response = session.put(
                endpoint,
                params=params,
                json={},
                timeout=90
            )


            if response.status_code != 200:
                raise UserError(
                    f"Gagal ambil data Shipment GI "
                    f"(HTTP {response.status_code}): {response.text}"
                )

            api_data = response.json()

            details = api_data.get("ShipmentGIDetails", [])


            shipment_gi_data = []
            shipment_numbers = []

            for item in details:
                ship_date = self._val(item, "ShipDate")
                phrase_date = dateutil_parser.parse(ship_date).replace(tzinfo=None)
                warehouse_id = self._val(item, "WarehouseID")
                picking_type = self._search_picking_type(warehouse_id)


                vals = {
                    "acumatica_id": item.get("id", ""),
                    "row_number": item.get("rowNumber", ""),

                    "address_id": self._val(item, "AddressID"),
                    "address_line1": self._val(item, "AddressLine1"),
                    "address_line2": self._val(item, "AddressLine2"),
                    "address_line3": self._val(item, "AddressLine3"),

                    "city": self._val(item, "City"),

                    "confirmed": self._val(item, "Confirmed"),

                    "country": self._val(item, "Country"),
                    "country_name": self._val(item, "CountryName"),

                    "customer": self._val(item, "Customer"),
                    "customer_name": self._val(item, "CustomerName"),

                    "document_only": self._val(item, "DocumentOnly"),

                    "fob_point": self._val(item, "FOBPoint"),
                    "fob_point_description": self._val(
                        item,
                        "FOBPointDescription"
                    ),

                    "hold": self._val(item, "Hold"),

                    "location": self._val(item, "Location"),
                    "location_name": self._val(item, "LocationName"),

                    "note_ship_via": self._val(item, "NoteShipVia"),

                    "order_type": self._val(item, "OrderType"),

                    "override_address": self._val(item, "OverrideAddress"),

                    "postal_code": self._val(item, "PostalCode"),

                    "ship_date": phrase_date,

                    "shipment_nbr": self._val(item, "ShipmentNbr"),

                    "shipped_quantity": self._val(item, "ShippedQuantity"),
                    "shipped_volume": self._val(item, "ShippedVolume"),
                    "shipped_weight": self._val(item, "ShippedWeight"),

                    "ship_via": self._val(item, "ShipVia"),
                    "ship_via_address": self._val(item, "ShipViaAddress"),
                    "ship_via_city": self._val(item, "ShipViaCity"),
                    "ship_via_description": self._val(
                        item,
                        "ShipViaDescription"
                    ),
                    "ship_via_phone": self._val(item, "ShipViaPhone"),
                    "ship_via_status": self._val(item, "ShipViaStatus"),

                    "site_id_description": self._val(
                        item,
                        "SiteIDDescription"
                    ),

                    "state": self._val(item, "State"),
                    "state_name": self._val(item, "StateName"),

                    "status": self._val(item, "Status"),

                    "to_warehouse_id": self._val(item, "ToWarehouseID"),

                    "shipment_type": self._val(item, "Type"),

                    "warehouse_id": warehouse_id,
                }

                shipment_numbers.append(self._val(item, "ShipmentNbr"))

                shipment_gi_data.append(vals)


            return shipment_gi_data, shipment_numbers

        except Exception as e:
            _logger.exception("Shipment GI Import Error")
            raise UserError(str(e))

        finally:
            self._do_logout(session)

    def fetch_shipment_data(
        self,
        shipment_numbers=None,
        odata_filter=None,
    ):
        self.ensure_one()

        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/{self.endpoint_name}"

            params = {}
            filters = []

            if self.odata_expand:
                params["$expand"] = self.odata_expand

            if self.odata_select:
                params["$select"] = self.odata_select

            # =====================================================
            # FILTER SHIPMENT NUMBER
            # =====================================================

            if shipment_numbers:

                shipment_filter = " or ".join([
                    f"ShipmentNbr eq '{nbr}'"
                    for nbr in shipment_numbers
                    if nbr
                ])

                if shipment_filter:
                    filters.append(f"({shipment_filter})")

            if odata_filter:
                filters.append(f"({odata_filter})")

            elif self.odata_filter:
                filters.append(f"({self.odata_filter})")

            if filters:
                params["$filter"] = " and ".join(filters)

            response = session.get(
                endpoint,
                params=params,
                timeout=90
            )

            if response.status_code != 200:
                raise UserError(
                    f"Gagal ambil Shipment "
                    f"(HTTP {response.status_code}): "
                    f"{response.text}"
                )

            raw_data = self._normalize_rows(
                response.json()
            )

            result = []

            # =====================================================
            # SHIPMENT LOOP
            # =====================================================

            for item in raw_data:

                shipment_dict = {

                    "header": {
                        "acumatica_id":item.get("id"),
                        "rownumber":item.get("rowNumber"),
                        "note":self._val(item, "note"),
                        "controlqty":self._val(item, "ControlQty"),
                        "customerid":self._val(item, "CustomerID"),
                        "description":self._val(item, "Description"),
                        "fobpoint":self._val(item, "FOBPoint"),
                        "fobpointdescription":self._val(item,"FOBPointDescription"),
                        "hold":self._val(item, "Hold"),
                        "insurance":self._val(item, "Insurance"),
                        "lastmodifieddatetime":self._parse_dt(self._val(item,"LastModifiedDateTime")),
                        "locationid":self._val(item, "LocationID"),
                        "locationname":self._val(item, "LocationName"),
                        "operation":self._val(item, "Operation"),
                        "packagecount":self._val(item, "PackageCount"),
                        "packageweight":self._val(item, "PackageWeight"),
                        "shipmentdate":self._parse_dt(self._val(item,"ShipmentDate")),
                        "shipmentnbr":self._val(item, "ShipmentNbr"),
                        "shippedqty":self._val(item, "ShippedQty"),
                        "shippedvolume":self._val(item, "ShippedVolume"),
                        "shippedweight":self._val(item, "ShippedWeight"),
                        "shippingzoneid":self._val(item, "ShippingZoneID"),
                        "shipvia":self._val(item, "ShipVia"),
                        "status":self._val(item, "Status"),
                        "towarehouseid":self._val(item, "ToWarehouseID"),
                        "type":self._val(item, "Type"),
                        "unlimitedpackages":self._val(item, "UnlimitedPackages"),
                        "warehouseid":self._val(item, "WarehouseID"),
                        "warehousename":self._val(item, "WarehouseName"),
                    },

                    "shipto_address": {},

                    "details": []
                }

                # =================================================
                # SHIP TO ADDRESS
                # =================================================

                shipping_settings = (
                    item.get("ShippingSettings")
                    or {}
                )

                shipto = (
                    shipping_settings.get(
                        "ShipToAddress"
                    )
                    or {}
                )

                if shipto:

                    shipment_dict[
                        "shipto_address"
                    ] = {
                        "addressline1":self._val(shipto,"AddressLine1"),
                        "addressline2":self._val(shipto,"AddressLine2"),
                        "city":self._val(shipto,"City"),
                        "country":self._val(shipto,"Country"),
                        "countryname":self._val(shipto,"CountryName"),
                        "postalcode":self._val(shipto,"PostalCode"),
                        "state":self._val(shipto,"State"),
                    }

                # =================================================
                # DETAILS
                # =================================================

                details = (
                    item.get("Details")
                    or []
                )

                for detail in details:

                    detail_dict = {

                        "detail": {
                            "acumatica_id": detail.get("id"),
                            "rownumber": detail.get("rowNumber"),
                            "note": self._val(detail, "note"),
                            "description": self._val(detail, "Description"),
                            "freeitem": self._val(detail, "FreeItem"),
                            "inventoryid": self._val(detail, "InventoryID"),
                            "linenbr": self._val(detail, "LineNbr"),
                            "location": self._val(detail, "Location"),
                            "openorderqty": self._val(detail, "OpenOrderQty"),
                            "orderedqty": self._val(detail, "OrderedQty"),
                            "orderlinenbr": self._val(detail, "OrderLineNbr"),
                            "ordernbr": self._val(detail, "OrderNbr"),
                            "ordertype": self._val(detail, "OrderType"),
                            "shippedqty": self._val(detail, "ShippedQty"),
                            "uom": self._val(detail, "UOM"),
                            "warehouseid": self._val(detail, "WarehouseID"),
                        },

                        "allocations": []}

                    allocations = (detail.get("Allocations")or [])

                    for alloc in allocations:

                        detail_dict[
                            "allocations"
                        ].append(
                        {
                            "acumatica_id": alloc.get("id"),
                            "rownumber": alloc.get("rowNumber"),
                            "note": self._val(alloc, "note"),
                            "description": self._val(alloc, "Description"),
                            "inventoryid": self._val(alloc, "InventoryID"),
                            "location": self._val(alloc, "Location"),
                            "quantity": self._val(alloc, "Quantity"),
                            "splitlinenbr": self._val(alloc, "SplitLineNbr"),
                            "uom": self._val(alloc, "UOM"),
                        })

                    shipment_dict["details"].append(detail_dict)

                result.append(shipment_dict)

            return result

        finally:
            self._do_logout(session)

    def create_staging_data(self, shipment_gi_data, batch_data):
        staging_shipment_gi = self.env['acumatica.shipment.gi.staging']
        staging_so_shipment= self.env['acumatica.sales.order.shipment.staging']
        staging_so_shipment_detail= self.env['acumatica.sales.order.shipment.staging.line']
        staging_so_shipment_allocation= self.env['acumatica.sales.order.shipment.staging.allocation']
        staging_so_shipment_ship_to_address= self.env['acumatica.sales.order.shipment.shiptoaddress.staging']

        # ==========================================================
        # AMBIL RECORD YANG SUDAH ADA
        # ==========================================================

        acumatica_ids = [
            vals.get('acumatica_id')
            for vals in shipment_gi_data
            if vals.get('acumatica_id')
        ]

        existing_records = staging_shipment_gi.search([
            ('acumatica_id', 'in', acumatica_ids)
        ])

        existing_map = {
            rec.acumatica_id: rec
            for rec in existing_records
        }

        created_count = 0
        updated_count = 0

        # ==========================================================
        # CREATE / UPDATE SHIPMENT GI
        # ==========================================================

        for item in shipment_gi_data:

            acumatica_id = item.get('acumatica_id')

            vals = {
                "acumatica_id": item.get('acumatica_id'),
                "row_number": item.get('row_number'),

                "address_id": item.get('address_id'),
                "address_line1": item.get('address_line1'),
                "address_line2": item.get('address_line2'),
                "address_line3": item.get('address_line3'),

                "city": item.get('city'),
                "state": item.get('state'),
                "state_name": item.get('state_name'),

                "country": item.get('country'),
                "country_name": item.get('country_name'),
                "postal_code": item.get('postal_code'),

                "customer": item.get('customer'),
                "customer_name": item.get('customer_name'),

                "confirmed": item.get('confirmed'),
                "hold": item.get('hold'),
                "document_only": item.get('document_only'),
                "override_address": item.get('override_address'),

                "fob_point": item.get('fob_point'),
                "fob_point_description": item.get('fob_point_description'),

                "location": item.get('location'),
                "location_name": item.get('location_name'),

                "note_ship_via": item.get('note_ship_via'),

                "order_type": item.get('order_type'),

                "ship_date": item.get('ship_date'),
                "shipment_nbr": item.get('shipment_nbr'),

                "shipped_quantity": item.get('shipped_quantity'),
                "shipped_volume": item.get('shipped_volume'),
                "shipped_weight": item.get('shipped_weight'),

                "ship_via": item.get('ship_via'),
                "ship_via_address": item.get('ship_via_address'),
                "ship_via_city": item.get('ship_via_city'),
                "ship_via_description": item.get('ship_via_description'),
                "ship_via_phone": item.get('ship_via_phone'),
                "ship_via_status": item.get('ship_via_status'),

                "site_id_description": item.get('site_id_description'),

                "status": item.get('status'),
                "shipment_type": item.get('shipment_type'),

                "to_warehouse_id": item.get('to_warehouse_id'),
                "warehouse_id": item.get('warehouse_id'),

                "note": item.get('note'),

                "config_id": self.id,
                "sync_date": fields.Datetime.now(),
            }

            existing = existing_map.get(acumatica_id)

            # ======================================================
            # UPDATE
            # ======================================================

            if existing:

                vals.update({
                    'import_message': 'Data staging diperbarui dari Acumatica',
                })

                existing.write(vals)

                updated_count += 1

                print(
                    f"UPDATED | "
                    f"ID={existing.id} | "
                    f"Shipment={existing.shipment_nbr} | "
                    f"Acumatica={acumatica_id}"
                )

            # ======================================================
            # CREATE
            # ======================================================

            else:

                vals.update({
                    'import_state': 'pending',
                    'import_message': 'Data baru dari Acumatica',
                })

                new_rec = staging_shipment_gi.create(vals)

                created_count += 1

                print(
                    f"CREATED | "
                    f"ID={new_rec.id} | "
                    f"Shipment={new_rec.shipment_nbr} | "
                    f"Acumatica={acumatica_id}"
                )

        # ==========================================================
        # SUMMARY
        # ==========================================================

        print(
            f"Sync Shipment GI selesai | "
            f"Created={created_count} | "
            f"Updated={updated_count}"
        )

        # ==================================================
        # SHIPMENT HEADER
        # ==================================================

        shipment_ids = [
            x["header"].get("acumatica_id")
            for x in batch_data
            if x["header"].get("acumatica_id")
        ]

        existing_shipments = staging_so_shipment.search([
            ("acumatica_id", "in", shipment_ids)
        ])

        shipment_map = {
            rec.acumatica_id: rec
            for rec in existing_shipments
        }        

        gi_map = {
            rec.shipment_nbr: rec.id
            for rec in staging_shipment_gi.search([])
        }

        for shipment in batch_data:

            shipment_vals = dict(
                shipment["header"]
            )

            shipment_nbr = shipment_vals.get(
                "shipmentnbr"
            )

            shipment_vals["gi_id"] = gi_map.get(
                shipment_nbr
            )

            shipment_vals.update({
                "config_id": self.id,
                "sync_date": fields.Datetime.now(),
            })

            existing = shipment_map.get(acumatica_id)
            for field, value in shipment_vals.items():
                print(f"{field}: {value}")

            # ======================================================
            # UPDATE
            # ======================================================

            if existing:

                shipment_vals.update({
                    'import_state': 'updated',
                    'import_message': 'Data diperbarui dari Acumatica',
                })

                existing.write(shipment_vals)
                shipment_rec = existing
                print(f"Shipment Updated: {existing.id} with row number {existing.rownumber}")
            
            else:
                shipment_rec = staging_so_shipment.create(
                    shipment_vals
                )
                print(
                    f"Shipment Created: "
                    f"{shipment_rec.id} "
                    f"{shipment_rec.shipmentnbr}"
                )



            # ==================================================
            # SHIP TO ADDRESS
            # ==================================================

            shipto_rec = False

            if shipment.get("shipto_address"):
                shipto_vals = dict(
                    shipment["shipto_address"]
                )

                shipto_vals["shipment_id"] = shipment_rec.id

                shipto_rec = staging_so_shipment_ship_to_address.create(
                    shipto_vals
                )

            # ==================================================
            # DETAILS
            # ==================================================

            for detail_data in shipment["details"]:

                detail_vals = dict(
                    detail_data["detail"]
                )

                detail_vals[
                    "shipment_id"
                ] = shipment_rec.id

                detail_rec = staging_so_shipment_detail.create(
                    detail_vals
                )

                print(
                    f"  Detail Created: "
                    f"{detail_rec.id}"
                )

                # ==============================================
                # ALLOCATIONS
                # ==============================================

                for alloc in detail_data[
                    "allocations"
                ]:

                    alloc_vals = dict(
                        alloc
                    )

                    alloc_vals[
                        "line_id"
                    ] = detail_rec.id

                    alloc_rec = staging_so_shipment_allocation.create(
                        alloc_vals
                    )

                    print(
                        f"    Allocation Created: "
                        f"{alloc_rec.id}"
                    )



    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data SO Shipment Receipt dari Acumatica',
            'res_model': 'acumatica.so.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        print(self.config_id.id)
        lines = self.env['acumatica.shipment.gi.staging'].search([
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
            'name': 'Hasil Import SO Shipment Receipt',
            'res_model': 'acumatica.so.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }

# Helper Function

    def _do_login(self):
        self.ensure_one()

        last_error = None

        for attempt in range(3):
            try:
                session = requests.Session()

                response = session.post(
                    self.login_url,
                    json={
                        'name': self.username,
                        'password': self.password,
                        'company': self.company_code,
                    },
                    headers={'Content-Type': 'application/json'},
                    timeout=30,
                )

                if response.status_code == 204:
                    return session

                last_error = (
                    f'Login gagal (HTTP {response.status_code}): '
                    f'{response.text}'
                )

            except Exception as e:
                last_error = str(e)

            # sleep 3 detik sebelum retry berikutnya
            if attempt < 2:
                time.sleep(3)

        raise UserError(
            f'Login gagal setelah 3 kali percobaan. Detail: {last_error}'
        )

    def _do_logout(self, session):
        self.ensure_one()

        last_error = None

        for attempt in range(3):
            try:
                response = session.post(
                    self.logout_url,
                    timeout=10,
                )

                if response.ok:
                    return

                last_error = (
                    f'Logout gagal (HTTP {response.status_code}): '
                    f'{response.text}'
                )

            except requests.exceptions.RequestException as e:
                last_error = str(e)

            if attempt < 2:
                time.sleep(3)

        # biasanya logout tidak perlu menggagalkan proses utama
        _logger.warning(
            "Logout gagal setelah 3 percobaan: %s",
            last_error,
        )

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']

        location = Location.search([
            ('code', '=', header['warehouse_code'])
        ])

        
        if location:
            print(f"Building id: {location.odoo_building_id.id}")
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'internal'),
                ('is_default_api', '=', True)
            ])

        return type if type else None

# Helper Atribut
    @property
    def api_url(self):
        return f"{self.config_id.base_url}/wms/{self.api_version}"

    @property
    def login_url(self):
        return f"{self.config_id.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.config_id.base_url}/auth/logout"