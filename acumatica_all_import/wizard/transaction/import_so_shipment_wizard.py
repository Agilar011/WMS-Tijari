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
from ...utils import acumatica_data as _data


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
        self.ensure_one()
        # print(f"Self config: {self.config_id}")

        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/Shipment"

            # =====================================================
            # 1. SIAPKAN FILTER SHIPMENT DALAM SATU REQUEST
            # =====================================================
            clean_shipment_numbers = list(set([nbr for nbr in shipment_numbers if nbr])) if shipment_numbers else []

            params = {}
            filters = []
            if self.config_id.odata_expand:
                params["$expand"] = self.config_id.odata_expand
            if self.config_id.odata_select:
                params["$select"] = self.config_id.odata_select
            if clean_shipment_numbers:
                shipment_filter = " or ".join(
                    f"ShipmentNbr eq '{nbr}'" for nbr in clean_shipment_numbers
                )
                filters.append(f"({shipment_filter})")
            if odata_filter:
                filters.append(f"({odata_filter})")
            elif self.config_id.odata_filter:
                filters.append(f"({self.config_id.odata_filter})")
            if filters:
                params["$filter"] = " and ".join(filters)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                self.env["acumatica.webhook.error.service"].send_error(
                    webhook_type="fetch",
                    webhook_name="Shipment",
                    error=f"Gagal fetch Shipment dari Acumatica (HTTP {response.status_code}).",
                    error_type="http",
                )
                raise UserError(
                    f"Gagal ambil Shipment (HTTP {response.status_code}): {response.text}"
                )

            all_raw_data = _data.acumatica_rows(response.json())

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
                        "note":_data.acumatica_value(item, "note"),
                        "controlqty":_data.acumatica_value(item, "ControlQty"),
                        "customerid":_data.acumatica_value(item, "CustomerID"),
                        "description":_data.acumatica_value(item, "Description"),
                        "fobpoint":_data.acumatica_value(item, "FOBPoint"),
                        "fobpointdescription":_data.acumatica_value(item,"FOBPointDescription"),
                        "hold":_data.acumatica_value(item, "Hold"),
                        "insurance":_data.acumatica_value(item, "Insurance"),
                        "lastmodifieddatetime":_data.acumatica_value(item,"LastModifiedDateTime"),
                        "locationid":_data.acumatica_value(item, "LocationID"),
                        "locationname":_data.acumatica_value(item, "LocationName"),
                        "operation":_data.acumatica_value(item, "Operation"),
                        "packagecount":_data.acumatica_value(item, "PackageCount"),
                        "packageweight":_data.acumatica_value(item, "PackageWeight"),
                        "shipmentdate":_data.acumatica_datetime(_data.acumatica_value(item,"ShipmentDate")),
                        "shipmentnbr":_data.acumatica_value(item, "ShipmentNbr"),
                        "shippedqty":_data.acumatica_value(item, "ShippedQty"),
                        "shippedvolume":_data.acumatica_value(item, "ShippedVolume"),
                        "shippedweight":_data.acumatica_value(item, "ShippedWeight"),
                        "shippingzoneid":_data.acumatica_value(item, "ShippingZoneID"),
                        "shipvia":_data.acumatica_value(item, "ShipVia"),
                        "status":_data.acumatica_value(item, "Status"),
                        "towarehouseid":_data.acumatica_value(item, "ToWarehouseID"),
                        "type":_data.acumatica_value(item, "Type"),
                        "unlimitedpackages":_data.acumatica_value(item, "UnlimitedPackages"),
                        "warehouseid":_data.acumatica_value(item, "WarehouseID"),
                        "warehousename":_data.acumatica_value(item, "WarehouseName"),
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
                        "addressline1":_data.acumatica_value(shipto,"AddressLine1"),
                        "addressline2":_data.acumatica_value(shipto,"AddressLine2"),
                        "city":_data.acumatica_value(shipto,"City"),
                        "country":_data.acumatica_value(shipto,"Country"),
                        "countryname":_data.acumatica_value(shipto,"CountryName"),
                        "postalcode":_data.acumatica_value(shipto,"PostalCode"),
                        "state":_data.acumatica_value(shipto,"State"),
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
                            "note": _data.acumatica_value(detail, "note"),
                            "description": _data.acumatica_value(detail, "Description"),
                            "freeitem": _data.acumatica_value(detail, "FreeItem"),
                            "inventoryid": _data.acumatica_value(detail, "InventoryID"),
                            "linenbr": _data.acumatica_value(detail, "LineNbr"),
                            "location": _data.acumatica_value(detail, "Location"),
                            "openorderqty": _data.acumatica_value(detail, "OpenOrderQty"),
                            "orderedqty": _data.acumatica_value(detail, "OrderedQty"),
                            "orderlinenbr": _data.acumatica_value(detail, "OrderLineNbr"),
                            "ordernbr": _data.acumatica_value(detail, "OrderNbr"),
                            "ordertype": _data.acumatica_value(detail, "OrderType"),
                            "shippedqty": _data.acumatica_value(detail, "ShippedQty"),
                            "uom": _data.acumatica_value(detail, "UOM"),
                            "warehouseid": _data.acumatica_value(detail, "WarehouseID"),
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
                            "note": _data.acumatica_value(alloc, "note"),
                            "description": _data.acumatica_value(alloc, "Description"),
                            "inventoryid": _data.acumatica_value(alloc, "InventoryID"),
                            "location": _data.acumatica_value(alloc, "Location"),
                            "quantity": _data.acumatica_value(alloc, "Quantity"),
                            "splitlinenbr": _data.acumatica_value(alloc, "SplitLineNbr"),
                            "uom": _data.acumatica_value(alloc, "UOM"),
                        })

                    shipment_dict["details"].append(detail_dict)

                result.append(shipment_dict)

            return result

        finally:
            self.config_id._do_logout(session)


# Function Get and create staging data

    def fetch_shipment_gi_data(self):

        # self.env['acumatica.shipment.gi.staging'].search([]).unlink()


        self.ensure_one()
        # session = self._do_login()
        session = self.config_id._do_login()

        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"

            params = {}
            if self.shipment_gi_expand:
                params["$expand"] = self.shipment_gi_expand

            session.headers.update({
                "Accept": "application/json",
                "Content-Type": "application/json",
            })



            response = session.put(
                endpoint,
                params=params,
                json={},
                timeout=300
            )


            if response.status_code != 200:
                self.env["acumatica.webhook.error.service"].send_error(
                    webhook_type="fetch",
                    webhook_name="Shipment GI",
                    error=f"Gagal fetch Shipment GI dari Acumatica (HTTP {response.status_code}).",
                    error_type="http",
                )
                raise UserError(
                    f"Gagal ambil data Shipment GI "
                    f"(HTTP {response.status_code}): {response.text}"
                )

            api_data = response.json()

            details = api_data.get("ShipmentGIDetails", [])


            shipment_gi_data = []
            shipment_numbers = []

            for item in details:
                ship_date = _data.acumatica_value(item, "ShipDate")
                phrase_date = dateutil_parser.parse(ship_date).replace(tzinfo=None)
                warehouse_id = _data.acumatica_value(item, "WarehouseID")
                building_id = _data.acumatica_value(item, "BuildingID") or warehouse_id
                OrderType = _data.acumatica_value(item, "OrderType")
                # print(f"Warehouse ID : {warehouse_id}")

                # if OrderType == 'CO':
                #     code = 'incoming'
                # else:
                #     code = 'outgoing'

                # print(f"Transaction Type: {code}")

                document_only = _data.acumatica_bool(item, 'DocumentOnly')
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
                    'adt_Description' : _data.acumatica_value(item, "Description"),
                    'adt_AddressID' : _data.acumatica_value(item, "AddressID"),
                    'adt_AddressLine' : _data.acumatica_value(item, "AddressLine"),
                    'adt_BuildingID' : _data.acumatica_value(item, "BuildingID"),
                    'adt_City' : _data.acumatica_value(item, "City"),
                    'adt_Country' : _data.acumatica_value(item, "Country"),
                    'adt_CountryName' : _data.acumatica_value(item, "CountryName"),
                    'adt_CustomerID' : _data.acumatica_value(item, "CustomerID"),
                    'adt_CustomerName' : _data.acumatica_value(item, "CustomerName"),
                    'adt_DocumentOnly' : _data.acumatica_bool(item, "DocumentOnly"),
                    'adt_FOBPoint' : _data.acumatica_value(item, "FOBPoint"),
                    'adt_FOBPointDescription' : _data.acumatica_value(item, "FOBPointDescription"),
                    'adt_LineDescription' : _data.acumatica_value(item, "LineDescription"),
                    'adt_LineFreeItem' : _data.acumatica_value(item, "LineFreeItem"),
                    'adt_LineInventoryID' : _data.acumatica_value(item, "LineInventoryID"),
                    'adt_LineLocation' : _data.acumatica_value(item, "LineLocation"),
                    'adt_LineNbr' : _data.acumatica_value(item, "LineNbr"),
                    'adt_LineNote' : _data.acumatica_value(item, "LineNote"),
                    'adt_LineNoteID' : _data.acumatica_value(item, "LineNoteID"),
                    'adt_LineQuantity' : _data.acumatica_value(item, "LineQuantity"),
                    'adt_LineUOM' : _data.acumatica_value(item, "LineUOM"),
                    'adt_LocationID' : _data.acumatica_value(item, "LocationID"),
                    'adt_LocationName' : _data.acumatica_value(item, "LocationName"),
                    'adt_NoteHeader' : _data.acumatica_value(item, "NoteHeader"),
                    'adt_NoteHeaderID' : _data.acumatica_value(item, "NoteHeaderID"),
                    'adt_OrderType' : _data.acumatica_value(item, "OrderType"),
                    'adt_Phone' : _data.acumatica_value(item, "Phone"),
                    'adt_PostalCode' : _data.acumatica_value(item, "PostalCode"),
                    'adt_ShipDate' : _data.acumatica_value(item, "ShipDate"),
                    'adt_IssueNbr' : _data.acumatica_value(item, "IssueNbr"),
                    'adt_ShipmentNbr' : _data.acumatica_value(item, "ShipmentNbr"),
                    'adt_ShipmentQty' : _data.acumatica_value(item, "ShipmentQty"),
                    'adt_LineQty' : _data.acumatica_value(item, "LineQuantity"),
                    'adt_ShipmentType' : _data.acumatica_value(item, "ShipmentType"),
                    'adt_ShipmentVolume' : _data.acumatica_value(item, "ShipmentVolume"),
                    'adt_ShipmentWeight' : _data.acumatica_value(item, "ShipmentWeight"),
                    'adt_ShipVia' : _data.acumatica_value(item, "ShipVia"),
                    'adt_SiteIDDescription' : _data.acumatica_value(item, "SiteIDDescription"),
                    'adt_State' : _data.acumatica_value(item, "State"),
                    'adt_StateName' : _data.acumatica_value(item, "StateName"),
                    'adt_Status' : _data.acumatica_value(item, "Status"),
                    'lastmodifieddatetime' : _data.acumatica_value(item, "LastModifiedDateTime"),
                    'adt_ToWarehouseID' : _data.acumatica_value(item, "ToWarehouseID"),
                    'adt_WarehouseID' : _data.acumatica_value(item, "WarehouseID"),
                    'picking_type_id' : picking_type_id,

                }

                shipment_numbers.append(_data.acumatica_value(item, "ShipmentNbr"))

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
                    'adt_IssueNbr': row.get("adt_IssueNbr"),
                    'adt_PostalCode': row.get("adt_PostalCode"),
                    'adt_ShipVia': row.get("adt_ShipVia"),
                    'adt_FOBPoint': row.get("adt_FOBPoint"),
                    'adt_FOBPointDescription': row.get("adt_FOBPointDescription"),
                    'adt_OrderType': row.get("adt_OrderType"),
                    'adt_SiteIDDescription': row.get("adt_SiteIDDescription"),
                    'adt_ToWarehouseID': row.get("adt_ToWarehouseID"),
                    'adt_NoteHeader': row.get("adt_NoteHeader"),
                    'adt_note': row.get("adt_note"),
                    'adt_Description': row.get("adt_Description"),
                    'picking_type_id': row.get("picking_type_id"),
                    'adt_ShipmentQty': row.get("adt_ShipmentQty") or row.get("adt_LineQty"),
                    'adt_ShipmentVolume': row.get("adt_ShipmentVolume"),
                    'adt_ShipmentWeight': row.get("adt_ShipmentWeight"),
                }

            line_data = {
                'acumatica_id': row.get("acumatica_id"),
                'adt_rowNumber': row.get("adt_rowNumber"),
                'adt_LineInventoryID': row.get("adt_LineInventoryID"),
                'adt_LineDescription': row.get("adt_LineDescription"),
                'adt_LineNote': row.get("adt_LineNote"),
                'adt_LineNoteID': row.get("adt_LineNoteID"),
                'adt_LineLocation': row.get("adt_LineLocation"),
                'adt_LineNbr': row.get("adt_LineNbr"),
                'adt_LineQuantity': row.get("adt_LineQuantity"),
                # Simpan ShipmentQty untuk payload staging/kompatibilitas lama;
                # pembuatan stock move menggunakan LineQuantity sebagai acuan.
                'adt_ShipmentQty': row.get("adt_ShipmentQty") or row.get("adt_LineQty"),
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
        # STEP 3: CLASSIFY HEADER SNAPSHOTS LIKE RECEIPT
        # =====================================================
        to_update = []
        to_create = []
        for shipment_nbr, data in grouped_shipments.items():
            header_vals = data['header']
            header_vals.update({
                'import_state': 'staged',
                'import_message': 'Data API Imported',
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })

            existing = existing_map.get(shipment_nbr)
            if not existing:
                to_create.append((shipment_nbr, data))
                continue

            incoming_last_modified = header_vals.get('lastmodifieddatetime')
            if (
                not incoming_last_modified
                or existing.lastmodifieddatetime == incoming_last_modified
            ):
                continue

            to_update.append((shipment_nbr, existing, data))

        # =====================================================
        # STEP 4: UPDATE HEADER AND REPLACE THE FULL DETAIL SNAPSHOT
        # =====================================================
        for shipment_nbr, existing_gi, data in to_update:
            gi_vals = data['header']
            lines_vals = data['lines']

            # Buka savepoint SQL baru khusus untuk record ini agar aman dari batasan database
            # Jika baris ini error, Odoo hanya membatalkan savepoint ini, bukan seluruh fungsi
            with self.env.cr.savepoint():
                try:
                    existing_gi.write(gi_vals)
                    existing_gi.all_line_ids.unlink()

                    for line in lines_vals:
                        line.update({'gi_id': existing_gi.id})
                        LineStaging.create(line)

                except Exception as e:
                    error_msg = f"!!! DATABASE CRASH ON STAGING RECORD {shipment_nbr}: {str(e)}"
                    _logger.error(error_msg)
                    continue

        # =====================================================
        # STEP 5: CREATE NEW HEADER WITH ITS COMPLETE SNAPSHOT
        # =====================================================
        for shipment_nbr, data in to_create:
            gi_vals = data['header']
            lines_vals = data['lines']

            with self.env.cr.savepoint():
                try:
                    line_commands = [(0, 0, line) for line in lines_vals]
                    GIStaging.create({**gi_vals, 'all_line_ids': line_commands})

                except Exception as e:
                    error_msg = f"!!! DATABASE CRASH ON STAGING RECORD {shipment_nbr}: {str(e)}"
                    _logger.error(error_msg)
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
        operation_category = 'internal' if code == 'CO' else 'pick'
        transaction_key = 'so_shipment_co' if code == 'CO' else 'so_shipment'
        return self.env['acumatica.config']._resolve_transaction_picking_type(
            config=self.config_id,
            building_id=building_id,
            code='internal',
            operation_category=operation_category,
            api_acumatica='so_shipment',
            transaction_key=transaction_key,
            document_only=document_only,
            config_policy='matching',
        ) or None








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
