# -*- coding: utf-8 -*-
import json
import logging

from dateutil import parser as dateutil_parser
from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request

from .webhook import AcumaticaWebhookController


_logger = logging.getLogger(__name__)


class AcumaticaTransactionWebhookController(AcumaticaWebhookController):
    def _datetime_value(self, item, *keys):
        value = self._first_value(item, *keys)
        if not value:
            return False
        try:
            return fields.Datetime.to_string(dateutil_parser.parse(value).replace(tzinfo=None))
        except (TypeError, ValueError):
            return value

    def _date_value(self, item, *keys):
        value = self._first_value(item, *keys)
        if not value:
            return False
        try:
            return fields.Date.to_string(dateutil_parser.parse(value).date())
        except (TypeError, ValueError):
            return value

    def _search_warehouse(self, warehouse_code):
        if not warehouse_code:
            return self._env()["stock.warehouse"].sudo().browse()

        mapping = self._env()["stock.location.acumatica"].sudo().search([
            ("code", "=", warehouse_code)
        ], limit=1)
        warehouse = mapping.odoo_building_id if mapping else False
        if warehouse:
            return warehouse

        return self._env()["stock.warehouse"].sudo().search([
            ("code", "=", warehouse_code)
        ], limit=1)

    def _search_picking_type(
        self,
        warehouse_code,
        picking_code="incoming",
        document_only=False,
        api_acumatica=False,
        target_operation_type=False,
    ):
        PickingType = self._env()["stock.picking.type"].sudo()
        target_picking_type = PickingType.resolve_document_only_picking_type(
            target_operation_type=target_operation_type,
            api_acumatica=api_acumatica,
            document_only=document_only,
            warehouse_code=warehouse_code,
        )
        if target_picking_type:
            return target_picking_type

        if not warehouse_code:
            return PickingType.browse()

        warehouse = self._search_warehouse(warehouse_code)
        if not warehouse:
            return PickingType.browse()

        return PickingType.search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", picking_code),
            ("is_default_api", "=", True),
        ], limit=1)

    def _search_incoming_picking_type(self, warehouse_code, document_only=False, api_acumatica=False):
        return self._search_picking_type(
            warehouse_code,
            "incoming",
            document_only=document_only,
            api_acumatica=api_acumatica,
        )

    def _search_internal_picking_type(self, warehouse_code, document_only=False, api_acumatica=False):
        return self._search_picking_type(
            warehouse_code,
            "internal",
            document_only=document_only,
            api_acumatica=api_acumatica,
        )

    def _search_outgoing_picking_type(self, warehouse_code, document_only=False, api_acumatica=False):
        return self._search_picking_type(
            warehouse_code,
            "outgoing",
            document_only=document_only,
            api_acumatica=api_acumatica,
        )

    def _search_outbound_pick_picking_type(self, warehouse_code, document_only=False, api_acumatica=False):
        PickingType = self._env()["stock.picking.type"].sudo()
        target_picking_type = PickingType.resolve_document_only_picking_type(
            api_acumatica=api_acumatica,
            document_only=document_only,
            warehouse_code=warehouse_code,
        )
        if target_picking_type:
            return target_picking_type

        if not warehouse_code:
            return PickingType.browse()

        warehouse = self._search_warehouse(warehouse_code)
        if not warehouse:
            return PickingType.browse()

        return warehouse.pick_type_id or PickingType.search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", "internal"),
            ("operation_category", "=", "pick"),
        ], limit=1) or PickingType.search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", "internal"),
            ("name", "ilike", "Pick"),
        ], limit=1)

    def _receipt_header_vals(self, item, row_number):
        building_code = self._first_value(item, "BuildingID", "building_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._search_incoming_picking_type(
            building_code,
            document_only=document_only,
            api_acumatica="po_receipt",
        )
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "building_code": building_code,
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "document_only": document_only,
            "inventory_ref": self._first_value(item, "InventoryRefNbr", "inventory_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "Location", "header_location_code"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "receipt_nbr": self._first_value(item, "ReceiptNbr", "ReferenceNbr", "POReceiptNbr", "receipt_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "receipt_type": self._first_value(item, "Type", "receipt_type"),
            "vendor_code": self._first_value(item, "VendorID", "vendor_code"),
            "vendor_name": self._first_value(item, "VendorName", "vendor_name"),
            "partner_ref": self._first_value(item, "VendorRef", "partner_ref"),
            "warehouse_code": self._first_value(item, "LineWarehouseID", "Warehouse", "warehouse_code"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _receipt_product_vals(self, item, receipt):
        return {
            "header_external_id": item.get("id") or item.get("external_id") or "",
            "receipt_line_id": receipt.id,
            "receipt_nbr": receipt.receipt_nbr,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "line_branch": self._first_value(item, "LineBranch", "line_branch"),
            "description": self._first_value(item, "LineDescription", "Description", "description"),
            "transaction_description": self._first_value(item, "TransactionDescription", "transaction_description"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "line_nbr": self._first_value(item, "LineNbr", "LineNumber", "line_nbr"),
            "line_type": self._first_value(item, "LineType", "line_type"),
            "location_dest_code": self._first_value(item, "LineLocation", "Location", "location_dest_code"),
            "open_qty": self._first_value(item, "LineOpenQty", "OpenQty", "open_qty"),
            "order_qty": self._first_value(item, "LineOrderedQty", "OrderedQty", "order_qty"),
            "po_line_number": self._first_value(item, "LinePOLineNbr", "POLineNbr", "po_line_number"),
            "po_number": self._first_value(item, "LinePOOrderNbr", "PONbr", "po_number"),
            "po_type": self._first_value(item, "LinePOOrderType", "POType", "po_type"),
            "po_receipt_line_number": self._first_value(item, "LinePOReceiptLineNbr", "POReceiptLineNbr", "po_receipt_line_number"),
            "po_receipt_number": self._first_value(item, "LinePOReceiptNbr", "POReceiptNbr", "po_receipt_number"),
            "product_uom_qty": self._first_value(item, "LineReceiptQty", "ReceiptQty", "product_uom_qty"),
            "transfer_order_line_number": self._first_value(item, "TransferOrderLineNbr", "transfer_order_line_number"),
            "transfer_order_number": self._first_value(item, "TransferOrderNbr", "transfer_order_number"),
            "transfer_order_type": self._first_value(item, "TransferOrderType", "transfer_order_type"),
            "transfer_shipment_number": self._first_value(item, "LineTransferShipmentNbr", "TransferShipmentNbr", "transfer_shipment_number"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_dest_code": self._first_value(item, "LineWarehouseID", "WarehouseID", "warehouse_dest_code"),
        }

    def _po_return_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "Warehouse", "WarehouseID", "LineWarehouseID", "warehouse_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._search_outgoing_picking_type(
            warehouse_code,
            document_only=document_only,
            api_acumatica="issue_po_return",
        )
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "document_only": document_only,
            "inventory_ref": self._first_value(item, "InventoryRefNbr", "inventory_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "Location", "header_location_code"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "receipt_nbr": self._first_value(item, "ReceiptNbr", "ReferenceNbr", "TransferOrderNbr", "receipt_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "receipt_type": self._first_value(item, "Type", "receipt_type"),
            "po_type": self._first_value(item, "Type", "po_type"),
            "vendor_code": self._first_value(item, "VendorID", "vendor_code"),
            "partner_ref": self._first_value(item, "VendorName", "VendorRef", "partner_ref"),
            "warehouse_code": warehouse_code,
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": "Data API Imported",
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _po_return_product_vals(self, item, receipt):
        return {
            "receipt_line_id": receipt.id,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "line_description": self._first_value(item, "LineDescription", "Description", "line_description"),
            "inventory_id": self._first_value(item, "InventoryID", "LineInventoryID", "inventory_id"),
            "line_nbr": self._int_value(item, "LineNbr", "line_nbr", "line_rowNumber"),
            "location_code": self._first_value(item, "Location", "LineLocation", "location_code"),
            "product_uom_qty": self._float_value(item, "ReceiptQty", "Qty", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "UOM", "LineUOM", "uom_code"),
            "warehouse_code": self._first_value(item, "WarehouseID", "Warehouse", "LineWarehouseID", "warehouse_code"),
        }

    def _kit_assembly_header_vals(self, item, row_number):
        return {
            "name": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "description": self._first_value(item, "Description", "description"),
            "document_only": self._bool_value(item, "DocumentOnly", "document_only"),
            "building_id": self._first_value(item, "BuildingID", "building_id"),
            "inventory_id": self._first_value(item, "InventoryID", "inventory_id"),
            "last_modified_datetime": self._datetime_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "location": self._first_value(item, "Location", "location"),
            "note_header": self._first_value(item, "NoteHeader", "note_header"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "quantity": self._float_value(item, "Qty", "Quantity", "quantity"),
            "reason_code": self._first_value(item, "ReasonCode", "reason_code"),
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "requested_on": self._date_value(item, "RequestedOn", "requested_on"),
            "revision": self._first_value(item, "Revision", "revision"),
            "status": self._first_value(item, "Status", "status"),
            "type": self._first_value(item, "Type", "type"),
            "uom": self._first_value(item, "UOM", "uom"),
            "warehouse": self._first_value(item, "Warehouse", "WarehouseID", "warehouse"),
        }

    def _kit_assembly_component_vals(self, item, header):
        return {
            "assembly_id": header.id,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "line_inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "line_inventory_id"),
            "line_component_qty": self._float_value(item, "ComponentQty", "line_component_qty"),
            "line_nbr": self._int_value(item, "LineNbr", "LineNumber", "line_nbr", "line_rowNumber"),
            "line_location_id": self._first_value(item, "LineLocationID", "LocationID", "line_location_id"),
            "line_quantity": self._float_value(item, "LineQty", "Qty", "Quantity", "line_quantity"),
            "line_reason_code": self._first_value(item, "ReasonCode", "LineReasonCode", "line_reason_code"),
            "stock_inventory_id": self._first_value(item, "LineStockInventoryID", "StockInventoryID", "stock_inventory_id"),
            "line_uom": self._first_value(item, "LineUOM", "UOM", "line_uom"),
        }

    def _kit_assembly_staging_vals(self, item, header, row_number):
        component_vals = self._kit_assembly_component_vals(item, header)
        return {
            "row_number": row_number,
            "external_id": header.external_id,
            "inventory_id": header.inventory_id,
            "description": header.description,
            "last_modified_datetime": header.last_modified_datetime,
            "location": header.location,
            "BuildingID": header.building_id,
            "note_header": header.note_header,
            "note_header_id": header.note_header_id,
            "post_period": header.post_period,
            "quantity": str(header.quantity or ""),
            "reason_code": header.reason_code,
            "reference_nbr": header.reference_nbr,
            "requested_on": header.requested_on,
            "revision": header.revision,
            "status": header.status,
            "type": header.type,
            "uom": header.uom,
            "warehouse": header.warehouse,
            "line_external_id": component_vals["line_external_id"],
            "line_note": component_vals["line_note"],
            "line_note_id": component_vals["line_note_id"],
            "line_inventory_id": component_vals["line_inventory_id"],
            "line_component_qty": str(component_vals["line_component_qty"] or ""),
            "line_nbr": component_vals["line_nbr"],
            "line_location_id": component_vals["line_location_id"],
            "line_quantity": str(component_vals["line_quantity"] or ""),
            "line_reason_code": component_vals["line_reason_code"],
            "stock_inventory_id": component_vals["stock_inventory_id"],
            "line_uom": component_vals["line_uom"],
            "warehouse_code": header.warehouse,
            "location_dest_code": header.location,
            "header_location_code": header.location,
            "uom_code": header.uom,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _process_kit_assembly_webhook(self, payload, config):
        records = self._records_from_transaction_payload(payload, config)
        if not records:
            raise UserError(_("No Kit Assembly records found in payload."))

        grouped = {}
        for index, item in enumerate(records, start=1):
            reference_nbr = self._first_value(item, "ReferenceNbr", "reference_nbr")
            if reference_nbr:
                grouped.setdefault(reference_nbr, []).append((index, item))
        if not grouped:
            raise UserError(_("No valid ReferenceNbr found in payload."))

        Header = self._env()["acumatica.kit.assembly"].sudo()
        Component = self._env()["acumatica.kit.assembly.component"].sudo()
        Staging = self._env()["acumatica.kit.assembly.line"].sudo()
        created = updated = component_lines = staging_lines = imported = errors = 0
        staging_ids = []

        for reference_nbr, document_records in grouped.items():
            first_index, first_item = document_records[0]
            header_vals = self._kit_assembly_header_vals(first_item, first_index)
            header = Header.search([("reference_nbr", "=", reference_nbr)], limit=1)
            if header:
                header.write({field: value for field, value in header_vals.items() if field in Header._fields})
                updated += 1
            else:
                header = Header.create({field: value for field, value in header_vals.items() if field in Header._fields})
                created += 1

            header.component_ids.unlink()
            Staging.search([("reference_nbr", "=", reference_nbr)]).unlink()

            component_vals = []
            staging_vals = []
            for row_number, item in document_records:
                component_val = {
                    field: value
                    for field, value in self._kit_assembly_component_vals(item, header).items()
                    if field in Component._fields
                }
                if not component_val.get("line_external_id"):
                    component_val["line_external_id"] = "%s-%s" % (reference_nbr, row_number)
                component_vals.append(component_val)

                staging_val = {
                    field: value
                    for field, value in self._kit_assembly_staging_vals(item, header, row_number).items()
                    if field in Staging._fields
                }
                if not staging_val.get("line_external_id"):
                    staging_val["line_external_id"] = component_val["line_external_id"]
                staging_vals.append(staging_val)

            if component_vals:
                Component.create(component_vals)
                component_lines += len(component_vals)
            if staging_vals:
                created_staging = Staging.create(staging_vals)
                staging_ids.extend(created_staging.ids)
                staging_lines += len(staging_vals)

        # Webhook hanya menyiapkan staging. Import Manufacturing dijalankan
        # dari tombol Import This agar sama dengan alur staging manual.

        return {
            "transaction_type": "kit_assembly",
            "model": "acumatica.kit.assembly.line",
            "created": created,
            "updated": updated,
            "imported": imported,
            "errors": errors,
            "header_ids": staging_ids,
            "component_lines": component_lines,
            "product_lines": staging_lines,
        }

    def _process_so_shipment_completed_webhook(self, payload, config):
        records = self._records_from_transaction_payload(payload, config)
        if not records:
            raise UserError(_("No Shipment Completed records found in payload."))

        Config = self._env()["acumatica.config"].sudo()
        acumatica_config = Config._get_default_config_for_type("shipment_completed")
        if not acumatica_config:
            raise UserError(_("No active Acumatica config found for Shipment Completed."))

        Staging = self._env()["acumatica.shipment.completed.staging"].sudo()
        Line = self._env()["acumatica.shipment.completed.staging.line"].sudo()
        grouped = {}
        for index, item in enumerate(records, start=1):
            shipment_nbr = self._first_value(item, "ShipmentNbr", "shipment_nbr")
            if shipment_nbr:
                grouped.setdefault(shipment_nbr, []).append((index, item))
        if not grouped:
            raise UserError(_("No valid ShipmentNbr found in payload."))

        created = updated = product_lines = 0
        header_ids = []
        for shipment_nbr, document_records in grouped.items():
            first_index, first_item = document_records[0]
            header_vals = self._shipment_completed_header_vals(first_item, first_index, acumatica_config)
            header = Staging.search([
                ("config_id", "=", acumatica_config.id),
                ("shipment_nbr", "=", shipment_nbr),
            ], limit=1)
            if header:
                changed = self._changed_values(header, header_vals)
                if changed:
                    header.write(changed)
                header.line_ids.unlink()
                updated += 1
            else:
                header = Staging.create(header_vals)
                created += 1

            line_vals = [
                {
                    field_name: value
                    for field_name, value in self._shipment_completed_line_vals(item, header).items()
                    if field_name in Line._fields
                }
                for _, item in document_records
                if isinstance(item, dict)
            ]
            if line_vals:
                Line.create(line_vals)
                product_lines += len(line_vals)
            header_ids.append(header.id)

        return {
            "transaction_type": "shipment_completed",
            "model": "acumatica.shipment.completed.staging",
            "created": created,
            "updated": updated,
            "imported": 0,
            "errors": 0,
            "header_ids": header_ids,
            "product_lines": product_lines,
        }

    def _shipment_completed_header_vals(self, item, row_number, acumatica_config):
        return {
            "config_id": acumatica_config.id,
            "acumatica_id": item.get("id") or item.get("acumatica_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "note", "Note"),
            "order_type": self._first_value(item, "OrderType", "order_type"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "inventory_nbr": self._first_value(item, "InvtRefNbr", "inventory_nbr"),
            "ship_date": self._datetime_value(item, "ShipDate", "ship_date"),
            "shipment_qty": self._float_value(item, "ShipmentQty", "shipment_qty"),
            "shipment_type": self._first_value(item, "ShipmentType", "shipment_type"),
            "shipment_volume": self._float_value(item, "ShipmentVolume", "shipment_volume"),
            "shipment_weight": self._float_value(item, "ShipmentWeight", "shipment_weight"),
            "shipment_via": self._first_value(item, "ShipVia", "shipment_via"),
            "status": self._first_value(item, "Status", "status"),
            "customer_id": self._first_value(item, "CustomerID", "customer_id"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "warehouse_id": self._first_value(item, "WarehouseID", "warehouse_id"),
            "to_warehouse_id": self._first_value(item, "ToWarehouseID", "to_warehouse_id"),
            "address_id": self._first_value(item, "AddressID", "address_id"),
            "address_line": self._first_value(item, "AddressLine", "address_line"),
            "building_id": self._first_value(item, "BuildingID", "building_id"),
            "city": self._first_value(item, "City", "city"),
            "country": self._first_value(item, "Country", "country"),
            "country_name": self._first_value(item, "CountryName", "country_name"),
            "state": self._first_value(item, "State", "state"),
            "state_name": self._first_value(item, "StateName", "state_name"),
            "postal_code": self._first_value(item, "PostalCode", "postal_code"),
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _shipment_completed_line_vals(self, item, header):
        return {
            "staging_id": header.id,
            "acumatica_id": item.get("line_id") or item.get("id") or item.get("acumatica_id") or "",
            "row_number": self._int_value(item, "line_rowNumber", "rowNumber", "row_number"),
            "note": self._first_value(item, "LineNote", "note", "Note"),
            "line_nbr": self._int_value(item, "LineNbr", "LineNumber", "line_nbr"),
            "line_inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "line_inventory_id"),
            "line_description": self._first_value(item, "LineDescription", "Description", "line_description"),
            "line_free_item": self._bool_value(item, "LineFreeItem", "FreeItem", "line_free_item"),
            "line_quantity": self._float_value(item, "LineQuantity", "Quantity", "line_quantity"),
            "line_uom": self._first_value(item, "LineUOM", "UOM", "line_uom"),
            "location_id": self._first_value(item, "LineLocation", "Location", "location_id"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "line_note": self._first_value(item, "LineNote", "line_note"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
        }

    def _so_transfer_header_vals(self, item, row_number):
        vals = self._receipt_header_vals(item, row_number)
        building_code = self._first_value(item, "BuildingID", "building_code")
        warehouse_code = self._first_value(item, "FromWarehouseID", "WarehouseID", "LineFromWarehouseID", "warehouse_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._search_internal_picking_type(
            building_code or warehouse_code,
            document_only=document_only,
            api_acumatica="so_transfer",
        )
        vals.update({
            "warehouse_code": warehouse_code,
            "warehouse_dest_code": self._first_value(item, "ToWarehouseID", "Warehouse", "LineWarehouseID", "warehouse_dest_code"),
            "location_dest_code": self._first_value(item, "LineLocation", "Location", "location_dest_code"),
            "transfer_order_number": self._first_value(item, "TransferOrderNbr", "transfer_order_number"),
            "transfer_order_line_number": self._first_value(item, "TransferOrderLineNbr", "transfer_order_line_number"),
            "transfer_order_type": self._first_value(item, "TransferOrderType", "transfer_order_type"),
            "transfer_shipment_number": self._first_value(item, "LineTransferShipmentNbr", "TransferShipmentNbr", "transfer_shipment_number"),
            "picking_type_id": picking_type.id if picking_type else False,
        })
        return vals

    def _so_transfer_product_vals(self, item, transfer):
        vals = self._receipt_product_vals(item, transfer)
        vals.pop("receipt_line_id", None)
        vals["transfer_line_id"] = transfer.id
        vals["transfer_order_number"] = self._first_value(item, "TransferOrderNbr", "transfer_order_number")
        vals["transfer_shipment_number"] = self._first_value(item, "LineTransferShipmentNbr", "TransferShipmentNbr", "transfer_shipment_number")
        vals["warehouse_dest_code"] = self._first_value(item, "ToWarehouseID", "Warehouse", "LineWarehouseID", "warehouse_dest_code")
        return vals

    def _direct_transfer_header_vals(self, item, row_number, api_acumatica=False):
        from_warehouse = self._first_value(item, "FromWarehouseID", "adt_FromWarehouseID")
        document_only = self._bool_value(item, "DocumentOnly", "adt_DocumentOnly")
        picking_type = self._search_internal_picking_type(
            from_warehouse,
            document_only=document_only,
            api_acumatica=api_acumatica,
        )
        return {
            "adt_id": item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._int_value(item, "rowNumber", "adt_rowNumber") or row_number,
            "adt_note": self._first_value(item, "NoteHeader", "note", "Note", "adt_note"),
            "adt_Date": self._first_value(item, "Date", "adt_Date"),
            "adt_Description": self._first_value(item, "Description", "adt_Description"),
            "adt_DocumentOnly": document_only,
            "adt_ExternalRef": self._first_value(item, "ExternalRef", "adt_ExternalRef"),
            "adt_FromWarehouseID": from_warehouse,
            "adt_FromWarehouseName": self._first_value(item, "FromWarehouseName", "adt_FromWarehouseName"),
            "adt_Hold": self._bool_value(item, "Hold", "adt_Hold"),
            "adt_LastModifiedDateTime": self._first_value(item, "LastModifiedDateTime", "adt_LastModifiedDateTime"),
            "adt_NoteID": self._first_value(item, "NoteID", "adt_NoteID"),
            "adt_NoteHeaderID": self._first_value(item, "NoteHeaderID", "NoteID", "adt_NoteHeaderID"),
            "adt_PostPeriod": self._first_value(item, "PostPeriod", "adt_PostPeriod"),
            "adt_ReferenceNbr": self._first_value(item, "ReferenceNbr", "adt_ReferenceNbr"),
            "adt_ReturnType": self._first_value(item, "ReturnType", "adt_ReturnType"),
            "adt_Status": self._first_value(item, "Status", "adt_Status"),
            "adt_TotalQty": self._float_value(item, "TotalQty", "adt_TotalQty"),
            "adt_ToWarehouseID": self._first_value(item, "ToWarehouseID", "adt_ToWarehouseID"),
            "adt_ToWarehouseName": self._first_value(item, "ToWarehouseName", "adt_ToWarehouseName"),
            "adt_TransferType": self._first_value(item, "TransferType", "adt_TransferType"),
            "adt_TransType": self._first_value(item, "TransType", "adt_TransType"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": "Data API Imported",
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _vendor_return_direct_transfer_header_vals(self, item, row_number):
        vals = self._direct_transfer_header_vals(
            item,
            row_number,
            api_acumatica="vendor_return",
        )
        from_warehouse = vals.get("adt_FromWarehouseID")
        document_only = vals.get("adt_DocumentOnly")
        picking_type = self._search_picking_type(
            from_warehouse,
            "outgoing",
            document_only=document_only,
            api_acumatica="vendor_return",
            target_operation_type="direct_delivery_order",
        )
        vals["picking_type_id"] = picking_type.id if picking_type else False
        return vals

    def _vendor_return_document_direct_transfer_header_vals(self, item, row_number):
        vals = self._direct_transfer_header_vals(
            item,
            row_number,
            api_acumatica="vendor_return",
        )
        from_warehouse = vals.get("adt_FromWarehouseID")
        document_only = vals.get("adt_DocumentOnly")
        picking_type = self._env()["stock.picking.type"].sudo().resolve_document_only_picking_type(
            target_operation_type="direct_delivery_order",
            api_acumatica="vendor_return",
            document_only=document_only,
            warehouse_code=from_warehouse,
            required=True,
        )
        vals["picking_type_id"] = picking_type.id if picking_type else False
        return vals

    def _direct_transfer_product_vals(self, item, header):
        return {
            "receipt_line_id": header.id,
            "adt_id": item.get("line_id") or item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._int_value(item, "LineNumber", "line_rowNumber", "rowNumber", "adt_rowNumber"),
            "adt_note": self._first_value(item, "LineNote", "note", "adt_note"),
            "adt_Description": self._first_value(item, "LineDescription", "Description", "adt_Description"),
            "adt_FromLocationID": self._first_value(item, "LineFromLocationID", "FromLocationID", "adt_FromLocationID"),
            "adt_InventoryID": self._first_value(item, "InventoryID", "LineInventoryID", "adt_InventoryID"),
            "adt_LineNumber": self._int_value(item, "LineNumber", "LineNbr", "adt_LineNumber"),
            "adt_NoteID": self._first_value(item, "LineNoteID", "NoteID", "adt_NoteID"),
            "adt_LineNoteID": self._first_value(item, "LineNoteID", "NoteID", "adt_LineNoteID"),
            "adt_Quantity": self._float_value(item, "Quantity", "LineQuantity", "adt_Quantity"),
            "adt_SOOrderNbr": self._first_value(item, "LineSOOrderNbr", "SOOrderNbr", "adt_SOOrderNbr"),
            "adt_SOOrderType": self._first_value(item, "LineSOOrderType", "SOOrderType", "adt_SOOrderType"),
            "adt_SOShipmentNbr": self._first_value(item, "LineSOShipmentNbr", "SOShipmentNbr", "adt_SOShipmentNbr"),
            "adt_ToLocationID": self._first_value(item, "LineToLocationID", "ToLocationID", "adt_ToLocationID"),
            "adt_UOM": self._first_value(item, "UOM", "LineUOM", "adt_UOM"),
        }

    def _shipment_return_header_vals(self, item, row_number):
        building_code = self._first_value(item, "BuildingID", "building_code")
        picking_type = self._search_incoming_picking_type(building_code)
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "building_code": building_code,
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "partner_code": self._first_value(item, "CustomerID", "partner_code"),
            "partner_name": self._first_value(item, "CustomerName", "partner_name"),
            "description": self._first_value(item, "Description", "description"),
            "document_only": self._bool_value(item, "DocumentOnly", "document_only"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "fob_point_description": self._first_value(item, "FOBPointDescription", "fob_point_description"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "LocationID", "header_location_code"),
            "header_location_name": self._first_value(item, "LocationName", "header_location_name"),
            "header_location_code_2": self._first_value(item, "LocationID_2", "header_location_code_2"),
            "header_location_name_2": self._first_value(item, "LocationName_2", "header_location_name_2"),
            "operation": self._first_value(item, "Operation", "operation"),
            "package_count": self._first_value(item, "PackageCount", "package_count"),
            "package_weight": self._first_value(item, "PackageWeight", "package_weight"),
            "scheduled_date": self._first_value(item, "ShipmentDate", "scheduled_date"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "shipped_qty": self._first_value(item, "ShippedQty", "shipped_qty"),
            "shipped_volume": self._first_value(item, "ShippedVolume", "shipped_volume"),
            "shipped_weight": self._first_value(item, "ShippedWeight", "shipped_weight"),
            "shipping_terms": self._first_value(item, "ShippingTerms", "shipping_terms"),
            "shipping_zone": self._first_value(item, "ShippingZoneID", "shipping_zone"),
            "ship_via": self._first_value(item, "ShipVia", "ship_via"),
            "status": self._first_value(item, "Status", "status"),
            "warehouse_dest_code": self._first_value(item, "ToWarehouseID", "warehouse_dest_code"),
            "shipment_type": self._first_value(item, "Type", "shipment_type"),
            "unlimited_packages": self._first_value(item, "UnlimitedPackages", "unlimited_packages"),
            "warehouse_code": self._first_value(item, "WarehouseID", "warehouse_code"),
            "warehouse_name": self._first_value(item, "WarehouseName", "warehouse_name"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _shipment_return_product_vals(self, item, shipment):
        return {
            "header_external_id": item.get("id") or item.get("external_id") or "",
            "shipment_line_id": shipment.id,
            "shipment_nbr": shipment.shipment_nbr,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "note": self._first_value(item, "LineNote", "note") or self._note_value(item),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "description": self._first_value(item, "LineDescription", "description"),
            "is_free_item": self._first_value(item, "LineFreeItem", "is_free_item"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "line_nbr": self._first_value(item, "LineNbr", "line_nbr"),
            "location_dest_code": self._first_value(item, "LineLocation", "location_dest_code"),
            "open_qty": self._first_value(item, "LineOpenOrderQty", "open_qty"),
            "order_qty": self._first_value(item, "LineOrderedQty", "order_qty"),
            "order_line_number": self._first_value(item, "LineOrderLineNbr", "order_line_number"),
            "order_number": self._first_value(item, "LineOrderNbr", "order_number"),
            "order_type": self._first_value(item, "LineOrderType", "order_type"),
            "shipped_qty": self._first_value(item, "ShippedQty", "shipped_qty"),
            "shipped_weight": self._first_value(item, "LineShippedWeight", "shipped_weight"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "original_qty": self._first_value(item, "LineOriginalQty", "original_qty"),
            "warehouse_dest_code": self._first_value(item, "LineWarehouseID", "warehouse_dest_code"),
            "warehouse_dest_name": self._first_value(item, "LineWarehouseName", "warehouse_dest_name"),
        }

    def _inventory_receipt_base_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "LineWarehouse", "Warehouse", "WarehouseID", "warehouse_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._search_incoming_picking_type(
            warehouse_code,
            document_only=document_only,
            api_acumatica="inventory_receipt",
        )
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "building_code": self._first_value(item, "BuildingID", "building_code"),
            "change_item_ref_nbr": self._first_value(item, "ChangeItemRefNbr", "change_item_ref_nbr"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "customer_code": self._first_value(item, "CustomerID", "customer_code"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "description": self._first_value(item, "Description", "description"),
            "doc_type": self._first_value(item, "DocType", "doc_type"),
            "document_only": document_only,
            "external_ref": self._first_value(item, "ExternalRef", "external_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "location_code": self._first_value(item, "Location", "location_code"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "transfer_nbr": self._first_value(item, "TransferNbr", "transfer_nbr"),
            "transfer_type": self._first_value(item, "TransType", "TransferType", "transfer_type"),
            "vendor_code": self._first_value(item, "VendorID", "vendor_code"),
            "vendor_name": self._first_value(item, "VendorName", "vendor_name"),
            "warehouse_code": warehouse_code,
            "warehouse_dest_code": self._first_value(item, "LineWarehouse", "WarehouseID", "warehouse_dest_code"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _inventory_receipt_product_vals(self, item, header):
        return {
            "header_external_id": item.get("id") or item.get("external_id") or "",
            "inventory_line_id": header.id,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "line_description": self._first_value(item, "LineInventoryName", "LineDescription", "Description", "line_description"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "line_nbr": self._first_value(item, "LineNumber", "LineNbr", "line_nbr"),
            "location_code": self._first_value(item, "LineLocation", "Location", "location_code"),
            "line_location_name": self._first_value(item, "LineLocationName", "line_location_name"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "product_uom_qty": self._first_value(item, "LineQuantity", "Quantity", "Qty", "product_uom_qty"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_dest_code": self._first_value(item, "LineWarehouse", "Warehouse", "WarehouseID", "warehouse_dest_code"),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
        }

    def _inventory_receipt_header_vals(self, item, row_number):
        vals = self._inventory_receipt_base_header_vals(item, row_number)
        transfer_type = self._first_value(item, "TransferType", "TransType", "transfer_type")
        transfer_type_key = str(transfer_type or "").strip().lower().replace("-", "_").replace(" ", "_")
        picking_code = "internal" if transfer_type_key in ("transfer_in", "transfer_receipt") else "incoming"
        picking_type = self._search_picking_type(
            vals.get("warehouse_code"),
            picking_code,
            document_only=vals.get("document_only"),
            api_acumatica="inventory_receipt",
        )
        vals["transfer_type"] = transfer_type
        vals["picking_type_id"] = picking_type.id if picking_type else False
        return vals

    def _transfer_shipment_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "WarehouseID", "Warehouse", "warehouse_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._search_internal_picking_type(
            warehouse_code,
            document_only=document_only,
            api_acumatica="transfer_shipment",
        )
        custom_payload = item.get("custom")
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "building_code": self._first_value(item, "BuildingID", "building_code"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "TransferShipmentNbr", "ReferenceNbr", "shipment_nbr"),
            "partner_code": self._first_value(item, "CustomerID", "partner_code"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "description": self._first_value(item, "Description", "description"),
            "document_only": document_only,
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "is_insurance": self._first_value(item, "Insurance", "is_insurance"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "LocationID", "Location", "header_location_code"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "operation": self._first_value(item, "Operation", "operation"),
            "package_count": self._first_value(item, "PackageCount", "package_count"),
            "package_weight": self._first_value(item, "PackageWeight", "package_weight"),
            "is_picked": self._first_value(item, "Picked", "is_picked"),
            "scheduled_date": self._first_value(item, "ShipmentDate", "ShipDate", "scheduled_date"),
            "shipped_qty": self._first_value(item, "ShippedQty", "ShipmentQty", "shipped_qty"),
            "shipped_volume": self._first_value(item, "ShippedVolume", "ShipmentVolume", "shipped_volume"),
            "shipped_weight": self._first_value(item, "ShippedWeight", "ShipmentWeight", "shipped_weight"),
            "shipping_terms": self._first_value(item, "ShippingTerms", "shipping_terms"),
            "shipping_zone": self._first_value(item, "ShippingZoneID", "shipping_zone"),
            "ship_via": self._first_value(item, "ShipVia", "ship_via"),
            "site_id_description": self._first_value(item, "SiteIDDescription", "site_id_description"),
            "status": self._first_value(item, "Status", "status"),
            "warehouse_dest_code": self._first_value(item, "ToWarehouseID", "warehouse_dest_code"),
            "shipment_type": self._first_value(item, "ShipmentType", "Type", "shipment_type"),
            "warehouse_code": warehouse_code,
            "is_unlimited_packages": self._first_value(item, "UnlimitedPackages", "is_unlimited_packages"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "custom_json": json.dumps(custom_payload) if custom_payload is not None else "",
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _transfer_shipment_product_vals(self, item, header):
        custom_payload = item.get("custom")
        return {
            "shipment_id": header.id,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
            "line_row_number": self._first_value(item, "line_rowNumber", "rowNumber", "line_row_number"),
            "line_nbr": self._first_value(item, "LineNbr", "line_nbr"),
            "line_description": self._first_value(item, "LineDescription", "Description", "line_description"),
            "is_free_item": self._first_value(item, "FreeItem", "is_free_item"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "location_dest_code": self._first_value(item, "LineLocation", "Location", "location_dest_code"),
            "open_qty": self._first_value(item, "OpenOrderQty", "LineOpenQty", "open_qty"),
            "order_qty": self._first_value(item, "OrderedQty", "LineOrderedQty", "order_qty"),
            "order_line_number": self._first_value(item, "OrderLineNbr", "LineOrderLineNbr", "order_line_number"),
            "order_number": self._first_value(item, "OrderNbr", "LineOrderNbr", "order_number"),
            "order_type": self._first_value(item, "OrderType", "LineOrderType", "order_type"),
            "original_qty": self._first_value(item, "OriginalQty", "LineOriginalQty", "original_qty"),
            "product_uom_qty": self._first_value(item, "ShippedQty", "LineQuantity", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "UOM", "LineUOM", "uom_code"),
            "line_warehouse_code": self._first_value(item, "WarehouseID", "LineWarehouseID", "line_warehouse_code"),
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "custom_json": json.dumps(custom_payload) if custom_payload is not None else "",
        }

    def _inventory_issue_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "LineWarehouse", "Warehouse", "WarehouseID", "LineWarehouseID", "warehouse_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        trans_type = self._first_value(item, "TransType", "trans_type")
        picking_type = self._env()["stock.picking.type"].sudo().browse()
        if (trans_type or "").strip().casefold() != "disposal":
            picking_type = self._search_outbound_pick_picking_type(
                warehouse_code,
                document_only=document_only,
                api_acumatica="inventory_issue",
            )
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "building_code": self._first_value(item, "BuildingID", "building_code"),
            "description": self._first_value(item, "Description", "description"),
            "doc_type": self._first_value(item, "DocType", "doc_type"),
            "document_only": document_only,
            "external_ref": self._first_value(item, "ExternalRef", "external_ref"),
            "status": self._first_value(item, "Status", "status"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "trans_type": trans_type,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "change_item_ref_nbr": self._first_value(item, "ChangeItemRefNbr", "change_item_ref_nbr"),
            "header_location_code": self._first_value(item, "Location", "header_location_code"),
            "line_nbr": self._first_value(item, "LineNumber", "LineNbr", "line_nbr"),
            "line_description": self._first_value(item, "LineInventoryName", "LineDescription", "line_description"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "location_code": self._first_value(item, "LineLocation", "Location", "location_code"),
            "product_uom_qty": self._first_value(item, "LineQuantity", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_code": warehouse_code,
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "line_note": self._first_value(item, "LineNote", "line_note"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _inventory_issue_product_vals(self, item, header):
        return {
            "receipt_line_id": header.id,
            "header_external_id": header.external_id or False,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note"),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "line_description": self._first_value(item, "LineInventoryName", "LineDescription", "line_description"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "line_nbr": self._first_value(item, "LineNumber", "LineNbr", "line_nbr"),
            "location_code": self._first_value(item, "LineLocation", "Location", "location_code"),
            "line_location_name": self._first_value(item, "LineLocationName", "line_location_name"),
            "product_uom_qty": self._first_value(item, "LineQuantity", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_code": self._first_value(item, "LineWarehouse", "Warehouse", "WarehouseID", "LineWarehouseID", "warehouse_code"),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
            "customer_id": self._first_value(item, "CustomerID", "customer_id"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
        }

    def _transfer_one_step_header_vals(self, item, row_number, api_acumatica="transfer_one_step"):
        from_warehouse = self._first_value(item, "FromWarehouseID", "from_warehouse_code")
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._search_internal_picking_type(
            from_warehouse,
            document_only=document_only,
            api_acumatica=api_acumatica,
        )
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "description": self._first_value(item, "Description", "description"),
            "document_only": document_only,
            "external_ref": self._first_value(item, "ExternalRef", "external_ref"),
            "from_warehouse_code": from_warehouse,
            "from_warehouse_name": self._first_value(item, "FromWarehouseName", "from_warehouse_name"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "return_type": self._first_value(item, "ReturnType", "return_type"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "to_warehouse_code": self._first_value(item, "ToWarehouseID", "to_warehouse_code"),
            "to_warehouse_name": self._first_value(item, "ToWarehouseName", "to_warehouse_name"),
            "transfer_type": self._first_value(item, "TransferType", "transfer_type"),
            "trans_type": self._first_value(item, "TransType", "trans_type"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _transfer_one_step_product_vals(self, item, header):
        return {
            "header_id": header.id,
            "acumatica_header_id": header.external_id or False,
            "line_nbr": self._int_value(item, "LineNbr", "LineNumber", "line_nbr", "line_rowNumber"),
            "inventory_id": self._first_value(item, "InventoryID", "LineInventoryID", "inventory_id"),
            "line_description": self._first_value(item, "LineDescription", "Description", "line_description"),
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "from_location_code": self._first_value(item, "LineFromLocationID", "FromLocationID", "from_location_code"),
            "to_location_code": self._first_value(item, "LineToLocationID", "ToLocationID", "to_location_code"),
            "so_order_nbr": self._first_value(item, "LineSOOrderNbr", "SOOrderNbr", "so_order_nbr"),
            "so_order_type": self._first_value(item, "LineSOOrderType", "SOOrderType", "so_order_type"),
            "so_shipment_nbr": self._first_value(item, "LineSOShipmentNbr", "SOShipmentNbr", "so_shipment_nbr"),
            "quantity": self._float_value(item, "Quantity", "LineQuantity", "quantity"),
            "uom_code": self._first_value(item, "UOM", "LineUOM", "uom_code"),
        }

    def _transfer_two_step_header_vals(self, item, row_number):
        return self._transfer_one_step_header_vals(
            item,
            row_number,
            api_acumatica="transfer_two_step",
        )

    def _transfer_two_step_product_vals(self, item, header):
        return {
            "header_id": header.id,
            "acumatica_header_id": header.external_id or False,
            "adt_rowNumber": self._first_value(item, "LineNbr", "LineNumber", "line_rowNumber", "adt_rowNumber"),
            "adt_note": self._first_value(item, "LineNote", "line_note", "adt_note") or self._note_value(item),
            "adt_Description": self._first_value(item, "LineDescription", "Description", "line_description", "adt_Description"),
            "adt_FromLocationID": self._first_value(item, "LineFromLocationID", "FromLocationID", "from_location_code", "adt_FromLocationID"),
            "adt_InventoryID": self._first_value(item, "InventoryID", "LineInventoryID", "inventory_id", "adt_InventoryID"),
            "adt_LineNumber": self._first_value(item, "LineNbr", "LineNumber", "line_nbr", "adt_LineNumber"),
            "adt_NoteID": self._first_value(item, "LineNoteID", "NoteID", "adt_NoteID"),
            "adt_LineNoteID": self._first_value(item, "LineNoteID", "NoteID", "adt_LineNoteID"),
            "adt_Quantity": self._first_value(item, "Quantity", "LineQuantity", "quantity", "adt_Quantity"),
            "adt_SOOrderNbr": self._first_value(item, "LineSOOrderNbr", "SOOrderNbr", "adt_SOOrderNbr"),
            "adt_SOOrderType": self._first_value(item, "LineSOOrderType", "SOOrderType", "adt_SOOrderType"),
            "adt_SOShipmentNbr": self._first_value(item, "LineSOShipmentNbr", "SOShipmentNbr", "adt_SOShipmentNbr"),
            "adt_ToLocationID": self._first_value(item, "LineToLocationID", "ToLocationID", "to_location_code", "adt_ToLocationID"),
            "adt_UOM": self._first_value(item, "UOM", "LineUOM", "uom_code", "adt_UOM"),
        }

    def _credit_memo_consignment_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "LineWarehouse", "Warehouse", "LineWarehouseID", "adt_Warehouse")
        picking_type = self._env()["stock.picking.type"].sudo().resolve_document_only_picking_type(
            target_operation_type="direct_delivery_order",
            api_acumatica="credit_memo_consignment",
            document_only=True,
            warehouse_code=warehouse_code,
        )
        return {
            "adt_id": item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._first_value(item, "rowNumber", "adt_rowNumber") or row_number,
            "adt_note": self._first_value(item, "NoteHeader", "note", "Note", "adt_note"),
            "adt_BuildingID": self._first_value(item, "BuildingID", "adt_BuildingID"),
            "adt_ConsignmentType": self._first_value(item, "ConsignmentType", "adt_ConsignmentType"),
            "adt_CreatedDateTime": self._first_value(item, "CreatedDateTime", "adt_CreatedDateTime"),
            "adt_CustomerID": self._first_value(item, "CustomerID", "adt_CustomerID"),
            "adt_CustomerName": self._first_value(item, "CustomerName", "adt_CustomerName"),
            "adt_CustomerOrder": self._first_value(item, "CustomerOrder", "adt_CustomerOrder"),
            "adt_Date": self._first_value(item, "Date", "adt_Date"),
            "adt_Description": self._first_value(item, "Description", "adt_Description"),
            "adt_DocumentOnly": True,
            "adt_DueDate": self._first_value(item, "DueDate", "adt_DueDate"),
            "adt_ExternalRef": self._first_value(item, "ExternalRef", "adt_ExternalRef"),
            "adt_LastModifiedDateTime": self._first_value(item, "LastModifiedDateTime", "adt_LastModifiedDateTime"),
            "adt_LocationID": self._first_value(item, "LocationID", "adt_LocationID"),
            "adt_LocationName": self._first_value(item, "LocationName", "adt_LocationName"),
            "adt_NoteHeaderID": self._first_value(item, "NoteHeaderID", "adt_NoteHeaderID"),
            "adt_OrigRefNbr": self._first_value(item, "OrigRefNbr", "adt_OrigRefNbr"),
            "adt_PostPeriod": self._first_value(item, "PostPeriod", "adt_PostPeriod"),
            "adt_ReferenceNbr": self._first_value(item, "ReferenceNbr", "adt_ReferenceNbr"),
            "adt_Status": self._first_value(item, "Status", "adt_Status"),
            "adt_TotalQty": self._float_value(item, "TotalQty", "adt_TotalQty"),
            "adt_Type": self._first_value(item, "Type", "adt_Type"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": "Data API Imported",
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _credit_memo_consignment_product_vals(self, item, header):
        return {
            "receipt_line_id": header.id,
            "adt_id": item.get("line_id") or item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._first_value(item, "line_rowNumber", "rowNumber", "adt_rowNumber"),
            "adt_note": self._first_value(item, "LineNote", "line_note", "adt_note") or self._note_value(item),
            "adt_Branch": self._first_value(item, "LineBranch", "Branch", "adt_Branch"),
            "adt_InventoryID": self._first_value(item, "InventoryID", "LineInventoryID", "adt_InventoryID"),
            "adt_LineNoteID": self._first_value(item, "LineNoteID", "adt_LineNoteID"),
            "adt_Qty": self._first_value(item, "LineQty", "Qty", "Quantity", "LineQuantity", "adt_Qty"),
            "adt_TransactionDescription": self._first_value(item, "LineTransactionDescription", "TransactionDescription", "LineDescription", "Description", "adt_TransactionDescription"),
            "adt_UOM": self._first_value(item, "UOM", "LineUOM", "adt_UOM"),
            "adt_Warehouse": self._first_value(item, "LineWarehouse", "Warehouse", "LineWarehouseID", "adt_Warehouse"),
        }

    def _invoice_consignment_header_vals(self, item, row_number):
        vals = self._credit_memo_consignment_header_vals(item, row_number)
        warehouse_code = self._first_value(
            item,
            "LineWarehouse",
            "Warehouse",
            "WarehouseID",
            "adt_Warehouse",
        )
        document_only = self._bool_value(item, "DocumentOnly", "adt_DocumentOnly")
        picking_type = self._search_outbound_pick_picking_type(
            warehouse_code,
            document_only=document_only,
            api_acumatica="invoice_consignment",
        )
        vals["picking_type_id"] = picking_type.id if picking_type else False
        vals["adt_DocumentOnly"] = document_only
        return vals

    def _invoice_consignment_product_vals(self, item, header):
        vals = self._credit_memo_consignment_product_vals(item, header)
        vals["adt_external_id"] = header.adt_id or False
        return vals

    def _so_shipment_header_vals(self, item, row_number, picking_code="outgoing"):
        warehouse_code = self._first_value(item, "WarehouseID", "Warehouse", "adt_WarehouseID")
        document_only = self._bool_value(item, "DocumentOnly", "adt_DocumentOnly")
        picking_type = self._search_picking_type(
            warehouse_code,
            picking_code,
            document_only=document_only,
            api_acumatica="so_shipment",
        )
        return {
            "acumatica_id": item.get("id") or item.get("acumatica_id") or "",
            "adt_rowNumber": self._first_value(item, "rowNumber", "adt_rowNumber") or row_number,
            "adt_note": self._first_value(item, "note", "Note", "adt_note"),
            "adt_BuildingID": self._first_value(item, "BuildingID", "adt_BuildingID"),
            "adt_CustomerID": self._first_value(item, "CustomerID", "adt_CustomerID"),
            "adt_CustomerName": self._first_value(item, "CustomerName", "adt_CustomerName"),
            "adt_DocumentOnly": document_only,
            "adt_FOBPoint": self._first_value(item, "FOBPoint", "adt_FOBPoint"),
            "adt_FOBPointDescription": self._first_value(item, "FOBPointDescription", "adt_FOBPointDescription"),
            "adt_LineDescription": self._first_value(item, "LineDescription", "Description", "adt_LineDescription"),
            "adt_LineFreeItem": self._first_value(item, "LineFreeItem", "FreeItem", "adt_LineFreeItem"),
            "adt_LineInventoryID": self._first_value(item, "LineInventoryID", "InventoryID", "adt_LineInventoryID"),
            "adt_LineLocation": self._first_value(item, "LineLocation", "Location", "adt_LineLocation"),
            "adt_LineNbr": self._first_value(item, "LineNbr", "adt_LineNbr"),
            "adt_LineNote": self._first_value(item, "LineNote", "adt_LineNote"),
            "adt_LineNoteID": self._first_value(item, "LineNoteID", "adt_LineNoteID"),
            "adt_LineQuantity": self._first_value(item, "LineQuantity", "Quantity", "ShippedQty", "adt_LineQuantity"),
            "adt_LineUOM": self._first_value(item, "LineUOM", "UOM", "adt_LineUOM"),
            "adt_LocationID": self._first_value(item, "LocationID", "adt_LocationID"),
            "adt_LocationName": self._first_value(item, "LocationName", "adt_LocationName"),
            "adt_NoteHeader": self._first_value(item, "NoteHeader", "adt_NoteHeader"),
            "adt_NoteHeaderID": self._first_value(item, "NoteHeaderID", "adt_NoteHeaderID"),
            "adt_OrderType": self._first_value(item, "OrderType", "adt_OrderType"),
            "adt_ShipDate": self._first_value(item, "ShipDate", "ShipmentDate", "adt_ShipDate"),
            "adt_ShipmentNbr": self._first_value(item, "ShipmentNbr", "adt_ShipmentNbr"),
            "adt_ShipmentQty": self._first_value(item, "ShipmentQty", "ShippedQty", "adt_ShipmentQty"),
            "adt_ShipmentType": self._first_value(item, "ShipmentType", "Type", "adt_ShipmentType"),
            "adt_ShipmentVolume": self._first_value(item, "ShipmentVolume", "ShippedVolume", "adt_ShipmentVolume"),
            "adt_ShipmentWeight": self._first_value(item, "ShipmentWeight", "ShippedWeight", "adt_ShipmentWeight"),
            "adt_ShipVia": self._first_value(item, "ShipVia", "adt_ShipVia"),
            "adt_SiteIDDescription": self._first_value(item, "SiteIDDescription", "adt_SiteIDDescription"),
            "adt_Status": self._first_value(item, "Status", "adt_Status"),
            "adt_ToWarehouseID": self._first_value(item, "ToWarehouseID", "adt_ToWarehouseID"),
            "adt_WarehouseID": warehouse_code,
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _so_shipment_consignment_header_vals(self, item, row_number):
        return self._so_shipment_header_vals(item, row_number, picking_code="internal")

    def _so_shipment_outgoing_header_vals(self, item, row_number):
        return self._so_shipment_header_vals(item, row_number, picking_code="outgoing")

    def _so_shipment_line_vals(self, item, header):
        return {
            "gi_id": header.id,
            "acumatica_id": item.get("line_id") or item.get("line_external_id") or item.get("id") or "",
            "adt_rowNumber": self._first_value(item, "line_rowNumber", "rowNumber", "adt_rowNumber"),
            "adt_LineInventoryID": self._first_value(item, "LineInventoryID", "InventoryID", "adt_LineInventoryID"),
            "adt_LineDescription": self._first_value(item, "LineDescription", "Description", "adt_LineDescription"),
            "adt_LineLocation": self._first_value(item, "LineLocation", "Location", "adt_LineLocation"),
            "adt_LineNbr": self._first_value(item, "LineNbr", "adt_LineNbr"),
            "adt_ShipmentQty": self._first_value(item, "LineQuantity", "Quantity", "ShipmentQty", "ShippedQty", "adt_ShipmentQty"),
            "adt_LineUOM": self._first_value(item, "LineUOM", "UOM", "adt_LineUOM"),
            "adt_WarehouseID": self._first_value(item, "WarehouseID", "LineWarehouseID", "adt_WarehouseID"),
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _transaction_configs(self):
        return {
            "po_receipt": {
                "label": "PO Receipt",
                "records_keys": ("Inserted",),
                "document_keys": ("ReceiptNbr", "ReferenceNbr", "POReceiptNbr", "receipt_nbr"),
                "document_field": "receipt_nbr",
                "header_model": "acumatica.receipt.line",
                "product_model": "acumatica.receipt.product.line",
                "header_vals": self._receipt_header_vals,
                "product_vals": self._receipt_product_vals,
            },
            "po_return": {
                "label": "PO Return",
                "records_keys": ("Inserted",),
                "document_keys": ("ReceiptNbr", "ReferenceNbr", "POReceiptNbr", "receipt_nbr"),
                "document_field": "receipt_nbr",
                "header_model": "acumatica.issue.po.return.line",
                "product_model": "acumatica.issue.po.return.product",
                "header_vals": self._po_return_header_vals,
                "product_vals": self._po_return_product_vals,
            },
            "inventory_receipt": {
                "label": "Inventory Receipt",
                "records_keys": ("Inserted",),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "header_model": "acumatica.inventory.recieved.line",
                "product_model": "acumatica.inventory.recieved.product.line",
                "header_vals": self._inventory_receipt_header_vals,
                "product_vals": self._inventory_receipt_product_vals,
            },
            "so_transfer": {
                "label": "SO Transfer",
                "records_keys": ("Inserted",),
                "document_keys": ("ReceiptNbr", "ReferenceNbr", "TransferOrderNbr", "receipt_nbr"),
                "document_field": "receipt_nbr",
                "header_model": "acumatica.transfer.line",
                "product_model": "acumatica.transfer.product.line",
                "header_vals": self._so_transfer_header_vals,
                "product_vals": self._so_transfer_product_vals,
            },
            "transfer_shipment": {
                "label": "Transfer Shipment",
                "records_keys": ("Inserted",),
                "document_keys": ("ShipmentNbr", "TransferShipmentNbr", "ReferenceNbr", "shipment_nbr"),
                "document_field": "shipment_nbr",
                "header_model": "acumatica.transfer.shipment.line",
                "product_model": "acumatica.transfer.shipment.line.product",
                "line_relation": "shipment_line_ids",
                "header_vals": self._transfer_shipment_header_vals,
                "product_vals": self._transfer_shipment_product_vals,
            },
            "inventory_issue": {
                "label": "Inventory Issue",
                "records_keys": ("Inserted",),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "header_model": "acumatica.inventory.issue.line",
                "product_model": "acumatica.inventory.issue.product",
                "header_vals": self._inventory_issue_header_vals,
                "product_vals": self._inventory_issue_product_vals,
            },
            "so_shipment": {
                "label": "SO Shipment",
                "records_keys": ("Inserted",),
                "detail_keys": ("ShipmentGIDetails", "Details", "details"),
                "document_keys": ("ShipmentNbr", "adt_ShipmentNbr"),
                "document_field": "adt_ShipmentNbr",
                "header_model": "acumatica.shipment.gi.staging",
                "product_model": "acumatica.sales.order.shipment.staging.line",
                "line_relation": "all_line_ids",
                "header_vals": self._so_shipment_outgoing_header_vals,
                "product_vals": self._so_shipment_line_vals,
            },
            "so_shipment_consignment": {
                "label": "SO Shipment Consignment",
                "records_keys": ("Inserted",),
                "detail_keys": ("ShipmentGIDetails", "Details", "details"),
                "document_keys": ("ShipmentNbr", "adt_ShipmentNbr"),
                "document_field": "adt_ShipmentNbr",
                "header_model": "acumatica.shipment.gi.staging",
                "product_model": "acumatica.sales.order.shipment.staging.line",
                "line_relation": "all_line_ids",
                "header_vals": self._so_shipment_consignment_header_vals,
                "product_vals": self._so_shipment_line_vals,
            },
            "so_shipment_completed": {
                "label": "SO Shipment Completed",
                "records_keys": ("Inserted",),
                "processor": self._process_so_shipment_completed_webhook,
            },
            "vendor_return": {
                "label": "Vendor Return",
                "records_keys": ("Inserted",),
                "detail_keys": ("TransferOrderGIDetails", "Details", "details"),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.vendor.return.direct.transfer.staging",
                "product_model": "acumatica.vendor.return.direct.transfer.staging.line",
                "line_relation": "line_ids",
                "header_vals": self._vendor_return_direct_transfer_header_vals,
                "product_vals": self._direct_transfer_product_vals,
            },
            "vendor_return_document": {
                "label": "Vendor Return Document",
                "records_keys": ("Inserted",),
                "detail_keys": ("TransferOrderGIDetails", "Details", "details"),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.direct.transfer.staging",
                "product_model": "acumatica.direct.transfer.staging.line",
                "line_relation": "line_ids",
                "header_vals": self._vendor_return_document_direct_transfer_header_vals,
                "product_vals": self._direct_transfer_product_vals,
            },
            "transfer_one_step": {
                "label": "Transfer Intra Warehouse Out (1 Step)",
                "records_keys": ("Inserted",),
                "detail_keys": ("TransferOrderGIDetails", "Details", "details"),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "header_model": "acumatica.transfer.one.step.line",
                "product_model": "acumatica.transfer.one.step.product",
                "line_relation": "line_ids",
                "header_vals": self._transfer_one_step_header_vals,
                "product_vals": self._transfer_one_step_product_vals,
            },
            "transfer_two_step": {
                "label": "Transfer Intra Warehouse Out (2 Step)",
                "records_keys": ("Inserted",),
                "detail_keys": ("TransferOrderGIDetails", "Details", "details"),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "header_model": "acumatica.transfer.two.step.line",
                "product_model": "acumatica.transfer.two.step.line.product",
                "line_relation": "line_ids",
                "header_vals": self._transfer_two_step_header_vals,
                "product_vals": self._transfer_two_step_product_vals,
            },
            "credit_memo_consignment": {
                "label": "Credit Memo Consignment",
                "records_keys": ("Inserted",),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.credit.memo.consignment.staging",
                "product_model": "acumatica.credit.memo.consignment.staging.line",
                "line_relation": "line_ids",
                "header_vals": self._credit_memo_consignment_header_vals,
                "product_vals": self._credit_memo_consignment_product_vals,
            },
            "invoice_credit_memo_consignment": {
                "label": "Invoice Credit Memo Consignment",
                "records_keys": ("Inserted",),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.credit.memo.consignment.staging",
                "product_model": "acumatica.credit.memo.consignment.staging.line",
                "line_relation": "line_ids",
                "header_vals": self._credit_memo_consignment_header_vals,
                "product_vals": self._credit_memo_consignment_product_vals,
            },
            "invoice_consignment": {
                "label": "Invoice Consignment",
                "records_keys": ("Inserted",),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.invoice.consignment.staging",
                "product_model": "acumatica.invoice.consignment.staging.line",
                "header_vals": self._invoice_consignment_header_vals,
                "product_vals": self._invoice_consignment_product_vals,
            },
            "kit_assembly": {
                "label": "Kit Assembly",
                "records_keys": ("Inserted",),
                "detail_keys": ("KitAssemblyGIDetails", "StockComponents", "stock_components", "Components", "components", "Details", "details"),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "processor": self._process_kit_assembly_webhook,
            },
            "shipment_return": {
                "label": "Shipment Return",
                "records_keys": ("Inserted",),
                "document_keys": ("ShipmentNbr", "shipment_nbr"),
                "document_field": "shipment_nbr",
                "header_model": "acumatica.shipment.line",
                "product_model": "acumatica.shipment.product.line",
                "header_vals": self._shipment_return_header_vals,
                "product_vals": self._shipment_return_product_vals,
            },
        }

    def _normalize_transaction_type(self, transaction_type):
        key = (transaction_type or "").strip().lower().replace("-", "_")
        aliases = {
            "inventory_receipt": "inventory_receipt",
            "inventory_received": "inventory_receipt",
            "shipment_so_return": "shipment_return",
            "so_shipment_return": "shipment_return",
            "shipment_so": "shipment_return",
            "shipment_completed": "so_shipment_completed",
            "so_shipment_complete": "so_shipment_completed",
            "shipment_complete": "so_shipment_completed",
            "sotr": "so_transfer",
            "inventory_issue_change_item": "inventory_issue",
            "issue_change_item": "inventory_issue",
            "issue_po_return": "po_return",
            "vendor_return": "vendor_return",
            "vendor_return_direct": "vendor_return",
            "vendor_return_direct_transfer": "vendor_return",
            "vendor_return_document_direct_transfer": "vendor_return_document",
            "invoicecreditmemo": "invoice_credit_memo_consignment",
            "invoicecreditmemoconsignment": "invoice_credit_memo_consignment",
            "invoicecreditmemoconsignmentgi": "invoice_credit_memo_consignment",
            "invoice_credit_memo": "invoice_credit_memo_consignment",
            "invoice_credit_memo_consignment_gi": "invoice_credit_memo_consignment",
        }
        return aliases.get(key, key)

    def _config_type_for_transaction_key(self, config_key):
        aliases = {
            "inventory_receipt": "inventory_received",
            "shipment_return": "shipment_so",
            "po_return": "issue_po_return",
            "vendor_return": "vendor_return_direct_transfer",
            "vendor_return_document": "vendor_return_document_direct_transfer",
            "so_shipment_completed": "shipment_completed",
        }
        return aliases.get(config_key, config_key)

    def _changed_values(self, record, vals):
        changed = {}
        for field_name, value in vals.items():
            field = record._fields.get(field_name)
            if not field:
                continue
            current = record[field_name]
            if field.type == "many2one":
                current = current.id or False
                value = value.id if hasattr(value, "id") else value or False
            elif field.type in ("char", "text", "selection", "html"):
                current = current or False
                value = value or False
            if current != value:
                changed[field_name] = value
        return changed

    def _upsert_header(self, model_name, document_field, vals):
        Header = self._env()[model_name].sudo()
        vals = {
            field_name: value
            for field_name, value in vals.items()
            if field_name in Header._fields
        }
        header = Header.search([(document_field, "=", vals[document_field])], limit=1)
        if header:
            workflow_fields = {"import_state", "import_message", "odoo_picking_id"}
            business_vals = {
                field_name: value
                for field_name, value in vals.items()
                if field_name not in workflow_fields
            }
            business_changed = self._changed_values(header, business_vals)
            if not business_changed:
                return header, "unchanged"

            changed = self._changed_values(header, vals)
            if changed:
                header.write(changed)
            return header, "updated"
        return Header.create(vals), "created"

    def _replace_product_lines(self, header, product_model, product_vals_getter, records, line_relation="product_line_ids"):
        ProductLine = self._env()[product_model].sudo()
        if line_relation in header._fields:
            header[line_relation].unlink()
        product_vals = [
            {
                field_name: value
                for field_name, value in product_vals_getter(item, header).items()
                if field_name in ProductLine._fields
            }
            for item in records
            if isinstance(item, dict)
        ]
        if product_vals:
            ProductLine.create(product_vals)
        return len(product_vals)

    def _detail_rows(self, item, detail_keys=("Details", "details")):
        details = []
        for key in detail_keys:
            details = item.get(key)
            if details:
                break
        if isinstance(details, dict):
            details = details.get("value") or []
        return details if isinstance(details, list) else []

    def _merge_header_detail(self, header, detail):
        merged = dict(header)
        for key in (
            "Details",
            "details",
            "TransferOrderGIDetails",
            "KitAssemblyGIDetails",
            "StockComponents",
            "stock_components",
            "Components",
            "components",
        ):
            merged.pop(key, None)
        if isinstance(detail, dict):
            for key, value in detail.items():
                if key == "id":
                    merged["line_id"] = value
                elif key == "rowNumber":
                    merged["line_rowNumber"] = value
                elif key in ("note", "Note"):
                    merged["LineNote"] = value
                elif key == "Description" and key in merged:
                    merged["LineDescription"] = value
                elif key in merged:
                    merged["Line%s" % key[:1].upper() + key[1:]] = value
                else:
                    merged[key] = value
        return merged

    def _records_from_transaction_payload(self, payload, config):
        records = self._records_from_payload_keys(payload, config["records_keys"])
        normalized = []
        for item in records:
            if not isinstance(item, dict):
                continue

            details = self._detail_rows(item, config.get("detail_keys", ("Details", "details")))
            if details:
                normalized.extend(
                    self._merge_header_detail(item, detail)
                    for detail in details
                    if isinstance(detail, dict)
                )
            else:
                normalized.append(item)
        return normalized

    def _process_transaction_payload(self, transaction_type, payload):
        config_key = self._normalize_transaction_type(transaction_type)
        config = self._transaction_configs().get(config_key)
        if not config:
            raise UserError(_("Unknown transaction type: %s") % transaction_type)

        if config.get("processor"):
            return config["processor"](payload, config)

        acumatica_config = self._env()["acumatica.config"].sudo()._get_default_config_for_type(
            self._config_type_for_transaction_key(config_key)
        )
        if not acumatica_config:
            raise UserError(_("No active Acumatica config found for transaction type: %s") % config_key)

        records = self._records_from_transaction_payload(payload, config)
        if not records:
            raise UserError(_("No transaction records found in payload."))

        grouped = {}
        for index, item in enumerate(records, start=1):
            if not isinstance(item, dict):
                continue
            document_nbr = self._first_value(item, *config["document_keys"])
            if not document_nbr:
                continue
            grouped.setdefault(document_nbr, []).append((index, item))

        if not grouped:
            raise UserError(_("No valid document number found in payload."))

        created = updated = product_lines = imported = errors = 0
        header_ids = []

        for document_records in grouped.values():
            first_index, first_item = document_records[0]
            header_vals = config["header_vals"](first_item, first_index)
            if not header_vals.get(config["document_field"]):
                continue
            header_vals["config_id"] = acumatica_config.id

            header, state = self._upsert_header(
                config["header_model"],
                config["document_field"],
                header_vals,
            )
            if state == "created":
                created += 1
            elif state == "updated":
                updated += 1
            else:
                continue

            product_lines += self._replace_product_lines(
                header,
                config["product_model"],
                config["product_vals"],
                [item for _, item in document_records],
                config.get("line_relation", "product_line_ids"),
            )
            header_ids.append(header.id)

        headers = self._env()[config["header_model"]].sudo().browse(header_ids)
        if headers:
            headers._do_import()
            Header = self._env()[config["header_model"]].sudo()
            imported = Header.search_count([
                ("id", "in", header_ids),
                ("import_state", "in", ("created", "updated")),
            ])
            errors = Header.search_count([
                ("id", "in", header_ids),
                ("import_state", "=", "error"),
            ])

        return {
            "transaction_type": config_key,
            "model": config["header_model"],
            "created": created,
            "updated": updated,
            "imported": imported,
            "errors": errors,
            "header_ids": header_ids,
            "product_lines": product_lines,
        }

    def _transaction_webhook(self, transaction_type, **kwargs):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_response("error", err, http_status=401)

        try:
            config_key = self._normalize_transaction_type(transaction_type)
            if config_key not in self._transaction_configs():
                raise UserError(_("Unknown transaction type: %s") % transaction_type)
            payload = self._raw_payload(kwargs)
            log = self._create_webhook_log("transaction", config_key, payload)
            return self._json_response(
                "success",
                _("Webhook logged. Process it from Webhook Logs."),
                log_id=log.id,
                webhook_type="transaction",
                webhook_name=config_key,
            )
        except UserError as exc:
            return self._json_response("error", str(exc), http_status=400)
        except Exception as exc:
            _logger.exception("Unexpected error in transaction webhook")
            return self._json_response("error", _("Unexpected server error: %s") % str(exc), http_status=500)

    @http.route("/acumatica/webhook/<string:transaction_type>", type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_flat_transaction_webhook(self, transaction_type, **kwargs):
        return self._transaction_webhook(transaction_type, **kwargs)
