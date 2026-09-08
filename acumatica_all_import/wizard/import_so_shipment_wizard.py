import logging
import time
from dateutil import parser as dateutil_parser
from docutils.nodes import note
import requests
import ast
import json
from collections import defaultdict

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
    # config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
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
        print(f"Config id: {self.config_id}")
        print(f"Self Limit: {self.fetch_limit}")
        self.ensure_one()
        # self.env['acumatica.so.shipment.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        shipment_gi_data, shipment_numbers = self.fetch_shipment_gi_data()

        if not shipment_numbers:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        
        # batch_data = self.fetch_shipment_data(
        #     shipment_numbers=shipment_numbers,  # tambahan
        #     odata_filter=self.odata_filter,
        # )

        # if not batch_data:
        #     raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        total_count = 0
        
        created_sales_order_shipment_record = self.create_staging_data(shipment_gi_data, total_count)

        self.write({
            'state': 'fetched',
            'total_fetched': (created_sales_order_shipment_record),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.so.shipment.wizard',
            'res_id': self.config_id.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def fetch_shipment_data(self, shipment_numbers=None, odata_filter=None):
        print('Runnning fetch data')
        self.ensure_one()
        # print(f"Self config: {self.config_id}")

        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/Shipment"

            # =====================================================
            # 1. BERSIHKAN & PECAH DATA SHIPMENT (CHUNKING)
            # =====================================================
            # Hilangkan nomor duplikat dan nilai kosong/False
            clean_shipment_numbers = list(set([nbr for nbr in shipment_numbers if nbr])) if shipment_numbers else []
            
            # Potong daftar menjadi per 20 nomor shipment agar URL tidak kepanjangan
            chunk_size = 10
            shipment_chunks = [
                clean_shipment_numbers[i:i + chunk_size] 
                for i in range(0, len(clean_shipment_numbers), chunk_size)
            ]

            # Jika shipment_numbers kosong sejak awal, pastikan loop tetap berjalan 1 kali tanpa filter nomor
            if not shipment_chunks:
                shipment_chunks = [[]]

            # List untuk menampung seluruh row data mentah hasil normalisasi dari semua chunk
            all_raw_data = []

            # =====================================================
            # 2. LOOPING API REQUEST PER CHUNK
            # =====================================================
            for chunk in shipment_chunks:
                params = {}
                filters = []

                if self.config_id.odata_expand:
                    params["$expand"] = self.config_id.odata_expand

                if self.config_id.odata_select:
                    params["$select"] = self.config_id.odata_select

                # Terapkan filter nomor dokumen khusus untuk chunk ini saja
                if chunk:
                    shipment_filter = " or ".join([
                        f"ShipmentNbr eq '{nbr}'"
                        for nbr in chunk
                    ])
                    if shipment_filter:
                        filters.append(f"({shipment_filter})")

                if odata_filter:
                    filters.append(f"({odata_filter})")
                elif self.config_id.odata_filter:
                    filters.append(f"({self.config_id.odata_filter})")

                if filters:
                    params["$filter"] = " and ".join(filters)

                # print("--- Mengirim Request Chunk ---")
                # print("Endpoint: ", endpoint)
                # print("params: ", params)

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

                # Normalisasi data chunk ini dan gabungkan ke dalam penampung utama
                chunk_raw_data = self._normalize_rows(
                    response.json()
                )
                all_raw_data.extend(chunk_raw_data)

            # =====================================================
            # 3. PROSES PEMETAAN DATA (LOGIKA ASLI ANDA)
            # =====================================================
            result = []

            # Loop sekarang membaca 'all_raw_data' yang sudah mengumpulkan hasil semua chunk
            for item in all_raw_data:

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

                if not details:
                    raise UserError("Detail Tidak Boleh Kosong")

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

                        "allocations": []
                    }

                    allocations = (detail.get("Allocations") or [])

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
            self.config_id._do_logout(session)


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
                timeout=300
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
                if phrase_date:
                    print(phrase_date)
                warehouse_id = self._val(item, "WarehouseID")
                building_id = self._val(item, "BuildingID") or warehouse_id
                OrderType = self._val(item, "OrderType")
                # print(f"Warehouse ID : {warehouse_id}")

                # if OrderType == 'CO':
                #     code = 'incoming'
                # else:
                #     code = 'outgoing'

                # print(f"Transaction Type: {code}")

                document_only = self._bool_val(item, 'DocumentOnly')
                picking_type = self._search_picking_type(
                    building_id,
                    OrderType,
                    document_only=document_only,
                )
                picking_type_id = picking_type.id if picking_type else None
                # print(picking_type_id)
                

                vals = {
                    'acumatica_id' : item.get('id'),
                    'adt_rowNumber' : item.get('rowNumber'),
                    'adt_note' : item.get('note'),
                    'adt_AddressID' : self._val(item, "AddressID"),
                    'adt_AddressLine' : self._val(item, "AddressLine"),
                    'adt_BuildingID' : self._val(item, "BuildingID"),
                    'adt_City' : self._val(item, "City"),
                    'adt_Country' : self._val(item, "Country"),
                    'adt_CountryName' : self._val(item, "CountryName"),
                    'adt_CustomerID' : self._val(item, "CustomerID"),
                    'adt_CustomerName' : self._val(item, "CustomerName"),
                    'adt_DocumentOnly' : self._bool_val(item, "DocumentOnly"),
                    'adt_FOBPoint' : self._val(item, "FOBPoint"),
                    'adt_FOBPointDescription' : self._val(item, "FOBPointDescription"),
                    'adt_LineDescription' : self._val(item, "LineDescription"),
                    'adt_LineFreeItem' : self._val(item, "LineFreeItem"),
                    'adt_LineInventoryID' : self._val(item, "LineInventoryID"),
                    'adt_LineLocation' : self._val(item, "LineLocation"),
                    'adt_LineNbr' : self._val(item, "LineNbr"),
                    'adt_LineNote' : self._val(item, "LineNote"),
                    'adt_LineNoteID' : self._val(item, "LineNoteID"),
                    'adt_LineQuantity' : self._val(item, "LineQuantity"),
                    'adt_LineUOM' : self._val(item, "LineUOM"),
                    'adt_LocationID' : self._val(item, "LocationID"),
                    'adt_LocationName' : self._val(item, "LocationName"),
                    'adt_NoteHeader' : self._val(item, "NoteHeader"),
                    'adt_NoteHeaderID' : self._val(item, "NoteHeaderID"),
                    'adt_OrderType' : self._val(item, "OrderType"),
                    'adt_Phone' : self._val(item, "Phone"),
                    'adt_PostalCode' : self._val(item, "PostalCode"),
                    'adt_ShipDate' : self._val(item, "ShipDate"),
                    'adt_ShipmentNbr' : self._val(item, "ShipmentNbr"),
                    'adt_ShipmentQty' : self._val(item, "ShipmentQty"),
                    'adt_ShipmentType' : self._val(item, "ShipmentType"),
                    'adt_ShipmentVolume' : self._val(item, "ShipmentVolume"),
                    'adt_ShipmentWeight' : self._val(item, "ShipmentWeight"),
                    'adt_ShipVia' : self._val(item, "ShipVia"),
                    'adt_SiteIDDescription' : self._val(item, "SiteIDDescription"),
                    'adt_State' : self._val(item, "State"),
                    'adt_StateName' : self._val(item, "StateName"),
                    'adt_Status' : self._val(item, "Status"),
                    'adt_ToWarehouseID' : self._val(item, "ToWarehouseID"),
                    'adt_WarehouseID' : self._val(item, "WarehouseID"),
                    'picking_type_id' : picking_type_id,

                }

                shipment_numbers.append(self._val(item, "ShipmentNbr"))

                shipment_gi_data.append(vals)


            return shipment_gi_data, shipment_numbers

        except Exception as e:
            _logger.exception("Shipment GI Import Error")
            raise UserError(str(e))

        finally:
            self._do_logout(session)

    def create_staging_data(self, shipment_gi_data, total_count):
        if not shipment_gi_data:
            return total_count

        GIStaging = self.env['acumatica.shipment.gi.staging']
        LineStaging = self.env['acumatica.sales.order.shipment.staging.line']

        # =====================================================
        # STEP 1: GROUPING LINE DATA BERDASARKAN SHIPMENT NUMBER
        # =====================================================
        grouped_shipments = defaultdict(lambda: {'header': {}, 'lines': []})

        for row in shipment_gi_data:
            total_count += 1
            shipment_nbr = row.get("adt_ShipmentNbr")
            if not shipment_nbr:
                continue

            if not grouped_shipments[shipment_nbr]['header']:
                grouped_shipments[shipment_nbr]['header'] = {
                    'adt_ShipmentNbr': shipment_nbr,
                    'config_id': self.config_id.id,
                    'acumatica_id': row.get("acumatica_id"),
                    'adt_rowNumber': row.get("adt_rowNumber"),
                    'adt_CustomerID': row.get("adt_CustomerID"),
                    'adt_CustomerName': row.get("adt_CustomerName"),
                    'adt_WarehouseID': row.get("adt_WarehouseID"),
                    'adt_LocationID': row.get("adt_LocationID"),
                    'adt_LocationName': row.get("adt_LocationName"),
                    'lastmodifieddatetime': row.get("lastmodifieddatetime"),
                    'adt_AddressLine': row.get("adt_AddressLine"),
                    'adt_Status': row.get("adt_Status"),
                    'adt_ShipmentType': row.get("adt_ShipmentType"),
                    'adt_City': row.get("adt_City"),
                    'adt_State': row.get("adt_State"),
                    'adt_StateName': row.get("adt_StateName"),
                    'adt_Country': row.get("adt_Country"),
                    'adt_CountryName': row.get("adt_CountryName"),
                    'adt_ShipDate': row.get("adt_ShipDate"),
                    'adt_PostalCode': row.get("adt_PostalCode"),
                    'adt_ShipVia': row.get("adt_ShipVia"),
                    'adt_FOBPoint': row.get("adt_FOBPoint"),
                    'adt_FOBPointDescription': row.get("adt_FOBPointDescription"),
                    'adt_OrderType': row.get("adt_OrderType"),
                    'adt_SiteIDDescription': row.get("adt_SiteIDDescription"),
                    'adt_ToWarehouseID': row.get("adt_ToWarehouseID"),
                    'adt_NoteHeader': row.get("adt_NoteHeader"),
                    'picking_type_id': row.get("picking_type_id"),
                    'adt_ShipmentVolume': row.get("adt_ShipmentVolume"),
                    'adt_ShipmentWeight': row.get("adt_ShipmentWeight"),
                }

            line_data = {
                'acumatica_id': row.get("acumatica_id"),
                'adt_rowNumber': row.get("adt_rowNumber"),
                'adt_LineInventoryID': row.get("adt_LineInventoryID"),
                'adt_LineDescription': row.get("adt_LineDescription"),
                'adt_LineLocation': row.get("adt_LineLocation"),
                'adt_LineNbr': row.get("adt_LineNbr"),
                'adt_ShipmentQty': row.get("adt_ShipmentQty"),
                'adt_LineUOM': row.get("adt_LineUOM"),
                'adt_WarehouseID': row.get("adt_WarehouseID"),
            }

            grouped_shipments[shipment_nbr]['lines'].append(line_data)

        # =====================================================
        # STEP 2: OPTIMASI SEARCH EXISTING (MASSAL)
        # =====================================================
        all_shipment_numbers = list(grouped_shipments.keys())
        existing_records = GIStaging.search([
            ('config_id', '=', self.config_id.id),
            ('adt_ShipmentNbr', 'in', all_shipment_numbers)
        ])
        existing_map = {rec.adt_ShipmentNbr: rec for rec in existing_records}

        # =====================================================
        # STEP 3: PROSES SIMPAN / UPDATE & RECREATE LINE (DENGAN TRY-EXCEPT)
        # =====================================================
        for shipment_nbr, data in grouped_shipments.items():
            gi_vals = data['header']
            lines_vals = data['lines']

            # Cek memori RAM untuk data lama
            existing_gi = existing_map.get(shipment_nbr)

            # Buka savepoint SQL baru khusus untuk record ini agar aman dari batasan database
            # Jika baris ini error, Odoo hanya membatalkan savepoint ini, bukan seluruh fungsi
            with self.env.cr.savepoint():
                try:
                    if existing_gi:
                        if (
                            gi_vals.get('lastmodifieddatetime')
                            and existing_gi.lastmodifieddatetime == gi_vals.get('lastmodifieddatetime')
                        ):
                            continue

                        # -------------------------------------------------
                        # KONDISI A: DATA SUDAH ADA -> UPDATE & RECREATE
                        # -------------------------------------------------
                        existing_gi.write(gi_vals)
                        existing_gi.all_line_ids.unlink()

                        for line in lines_vals:
                            line.update({
                                'gi_id': existing_gi.id
                            })
                            LineStaging.create(line)

                        print(f"--> SUCCESS UPDATED SHIPMENT & RECREATED LINES: {shipment_nbr}")

                    else:
                        # -------------------------------------------------
                        # KONDISI B: DATA BARU -> CREATE FRESH ALL
                        # -------------------------------------------------
                        line_commands = [(0, 0, line) for line in lines_vals]
                        gi_vals.update({
                            'all_line_ids': line_commands
                        })
                        print(f"GI Vals: {gi_vals}")
                        GIStaging.create(gi_vals)
                        
                        print(f"--> SUCCESS CREATED NEW FRESH SHIPMENT: {shipment_nbr}")

                except Exception as e:
                    # Tangkap error agar tidak merusak perulangan dokumen lain
                    error_msg = f"!!! DATABASE CRASH ON STAGING RECORD {shipment_nbr}: {str(e)}"
                    _logger.error(error_msg)
                    print(error_msg)
                    
                    # Logika Opsional: Anda bisa memasukkan pesan error ini ke model log khusus jika diperlukan
                    continue

        return total_count

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
            ('import_state', '=', 'staged'),
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

    def _search_picking_type(self, building_id, code, document_only=False):
        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False
        if config_picking_type:
            return config_picking_type

        PickingType = self.env['stock.picking.type']

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='so_shipment',
            document_only=document_only,
            building_id=building_id,
        )
        if document_only_type:
            return document_only_type

        if code == 'CO':
            type = PickingType.resolve_picking_type(
                building_id=building_id,
                code='internal',
                operation_category='internal',
                api_acumatica='so_shipment',
                transaction_key='so_shipment_co',
                required=False,
            )

        else:
            type = PickingType.resolve_picking_type(
                building_id=building_id,
                code='internal',
                operation_category='pick',
                api_acumatica='so_shipment',
                transaction_key='so_shipment',
                required=False,
            )

        

        return type if type else None

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''    

    @staticmethod
    def _bool_value(value):
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, bool):
            return value
        if value in (False, None, ''):
            return False
        return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'document only')

    @classmethod
    def _bool_val(cls, item, key):
        return cls._bool_value(item.get(key, {}))

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False



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
