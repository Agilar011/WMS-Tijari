# -*- coding: utf-8 -*-
import json

from dateutil import parser as dateutil_parser
from odoo import _, fields
from odoo.exceptions import UserError


class TransactionMappingMixin:
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
        inventory_id = str(self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id").rstrip())
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
            "inventory_id": inventory_id,
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
        picking_type = self._search_outbound_pick_picking_type(
            warehouse_code,
            document_only=document_only,
            api_acumatica="issue_po_return",
        )
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "building_code": self._first_value(item, "BuildingID", "building_code"),
            "change_item_ref_nbr": self._first_value(item, "ChangeItemRefNbr", "change_item_ref_nbr"),
            "customer_id": self._first_value(item, "CustomerID", "customer_id"),
            "customer_location_id": self._first_value(item, "CustomerLocationID", "customer_location_id"),
            "customer_location_name": self._first_value(item, "CustomerLocationName", "customer_location_name"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "document_only": document_only,
            "doc_type": self._first_value(item, "DocType", "doc_type"),
            "external_ref": self._first_value(item, "ExternalRef", "external_ref"),
            "inventory_ref": self._first_value(item, "InventoryRefNbr", "inventory_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "Location", "header_location_code"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "receipt_nbr": self._first_value(item, "ReceiptNbr", "ReferenceNbr", "TransferOrderNbr", "receipt_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "receipt_type": self._first_value(item, "Type", "receipt_type"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "transfer_nbr": self._first_value(item, "TransferNbr", "transfer_nbr"),
            "trans_type": self._first_value(item, "TransType", "trans_type"),
            "line_inventory_name": self._first_value(item, "LineInventoryName", "line_inventory_name"),
            "line_location_name": self._first_value(item, "LineLocationName", "line_location_name"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "line_warehouse": self._first_value(item, "LineWarehouse", "line_warehouse"),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
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
            "line_description": self._first_value(item, "LineInventoryName", "LineDescription", "Description", "line_description"),
            "line_inventory_name": self._first_value(item, "LineInventoryName", "line_inventory_name"),
            "line_location_name": self._first_value(item, "LineLocationName", "line_location_name"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "inventory_id": self._first_value(item, "InventoryID", "LineInventoryID", "inventory_id"),
            "line_nbr": self._int_value(item, "LineNumber", "LineNbr", "line_nbr", "line_rowNumber"),
            "location_code": self._first_value(item, "Location", "LineLocation", "location_code"),
            "order_qty": self._first_value(item, "LineOrderedQty", "OrderedQty", "order_qty"),
            "product_uom_qty": self._float_value(item, "LineQuantity", "LineReceiptQty", "Qty", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "UOM", "LineUOM", "uom_code"),
            "warehouse_code": self._first_value(item, "LineWarehouse", "WarehouseID", "Warehouse", "LineWarehouseID", "warehouse_code"),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
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
            "date": self._date_value(item, "Date", "date"),
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
            "date": header.date,
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

    def _shipment_transfer_completed_header_vals(self, item, row_number, acumatica_config):
        return {
            "config_id": acumatica_config.id,
            "acumatica_id": item.get("id") or item.get("acumatica_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "note", "Note"),
            "building_id": self._first_value(item, "BuildingID", "building_id"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "inventory_nbr": self._first_value(item, "InvtRefNbr", "inventory_nbr"),
            "location_id": self._first_value(item, "LocationID", "location_id"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "note_header": self._first_value(item, "NoteHeader", "note_header"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "ship_date": self._datetime_value(item, "ShipDate", "ship_date"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "shipment_qty": self._float_value(item, "ShipmentQty", "shipment_qty"),
            "shipment_type": self._first_value(item, "ShipmentType", "shipment_type"),
            "shipment_volume": self._float_value(item, "ShipmentVolume", "shipment_volume"),
            "shipment_weight": self._float_value(item, "ShipmentWeight", "shipment_weight"),
            "site_id_description": self._first_value(item, "SiteIDDescription", "site_id_description"),
            "status": self._first_value(item, "Status", "status"),
            "to_warehouse_id": self._first_value(item, "ToWarehouseID", "to_warehouse_id"),
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _shipment_transfer_completed_line_vals(self, item, header):
        return {
            "staging_id": header.id,
            "acumatica_id": item.get("line_id") or item.get("id") or item.get("acumatica_id") or "",
            "row_number": self._int_value(item, "line_rowNumber", "rowNumber", "row_number"),
            "note": self._first_value(item, "LineNote", "note", "Note"),
            "line_description": self._first_value(item, "LineDescription", "Description", "line_description"),
            "line_inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "line_inventory_id"),
            "line_location": self._first_value(item, "LineLocation", "Location", "line_location"),
            "line_nbr": self._int_value(item, "LineNbr", "LineNumber", "line_nbr"),
            "line_note": self._first_value(item, "LineNote", "line_note"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "line_quantity": self._float_value(item, "LineQuantity", "Quantity", "line_quantity"),
            "line_uom": self._first_value(item, "LineUOM", "UOM", "line_uom"),
        }

    def _shipment_completed_header_vals(self, item, row_number, acumatica_config):
        return {
            "config_id": acumatica_config.id,
            "acumatica_id": item.get("id") or item.get("acumatica_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "note", "Note"),
            "issue_nbr": self._first_value(item, "IssueNbr", "issue_nbr"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "fob_point_description": self._first_value(item, "FOBPointDescription", "fob_point_description"),
            "location_id": self._first_value(item, "LocationID", "location_id"),
            "note_header": self._first_value(item, "NoteHeader", "note_header"),
            "note_header_id": self._first_value(item, "NoteHeaderID", "note_header_id"),
            "phone": self._first_value(item, "Phone", "phone"),
            "site_id_description": self._first_value(item, "SiteIDDescription", "site_id_description"),
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
        # SOTR adalah internal transfer: operation type-nya Receipt Internal
        # (code=internal + operation_category=receive), bukan Transfer Internal.
        picking_type = self._search_picking_type(
            building_code or warehouse_code,
            "internal",
            document_only=document_only,
            api_acumatica="so_transfer",
            operation_category="receive",
        )
        vals.update({
            "warehouse_code": warehouse_code,
            "warehouse_dest_code": self._first_value(item, "ToWarehouseID", "Warehouse", "LineWarehouseID", "warehouse_dest_code"),
            "location_dest_code": self._first_value(item, "LineLocation", "Location", "location_dest_code"),
            "transfer_order_number": self._first_value(item, "TransferOrderNbr", "transfer_order_number"),
            "stock_lebih": self._bool_value(item, "WMSRelated", "wms_related", "StockLebih", "stock_lebih"),
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
            required=False,
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
            "customer_location_id": self._first_value(item, "CustomerLocationID", "customer_location_id"),
            "customer_location_name": self._first_value(item, "CustomerLocationName", "customer_location_name"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "description": self._first_value(item, "Description", "description"),
            "doc_type": self._first_value(item, "DocType", "doc_type"),
            "document_only": document_only,
            "stock_lebih": self._bool_value(item, "WMSRelated", "wms_related", "StockLebih", "stock_lebih"),
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
            "warehouse_dest_code": self._first_value(
                item,
                "ToWarehouseID",
                "LineToWarehouseID",
                "LineWarehouseID",
                "LineWarehouse",
                "Warehouse",
                "WarehouseID",
                "warehouse_dest_code",
            ),
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
            "warehouse_dest_code": self._first_value(
                item,
                "ToWarehouseID",
                "LineToWarehouseID",
                "LineWarehouseID",
                "LineWarehouse",
                "Warehouse",
                "WarehouseID",
                "warehouse_dest_code",
            ),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
        }

    def _inventory_receipt_header_vals(self, item, row_number):
        vals = self._inventory_receipt_base_header_vals(item, row_number)

        transfer_type = self._first_value(
            item,
            "TransferType",
            "TransType",
            "transfer_type",
        )

        config = (
            self._env()["acumatica.config"]
            .sudo()
            ._get_default_config_for_type("inventory_received")
        )

        warehouse_code = (
            vals.get("warehouse_dest_code")
            or vals.get("warehouse_code")
        )

        picking_type = config._resolve_inventory_receive_picking_type(
            transfer_type=transfer_type,
            document_only=vals.get("document_only"),
            warehouse_code=warehouse_code,
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
        trans_type = self._first_value(item, "TransType", "trans_type")
        is_toko_pegang_do = (trans_type or "").strip().casefold() == "toko pegang do"
        document_only = self._bool_value(item, "DocumentOnly", "document_only")
        picking_type = self._env()["stock.picking.type"].sudo().browse()
        if (trans_type or "").strip().casefold() != "disposal":
            if is_toko_pegang_do:
                picking_type = self._search_toko_pegang_do_picking_type(warehouse_code)
            else:
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
            "line_inventory_name": self._first_value(item, "LineInventoryName", "line_inventory_name"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "location_code": self._first_value(item, "LineLocation", "Location", "location_code"),
            "line_location_name": self._first_value(item, "LineLocationName", "line_location_name"),
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "product_uom_qty": self._first_value(item, "LineQuantity", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_code": warehouse_code,
            "line_warehouse": self._first_value(item, "LineWarehouse", "line_warehouse"),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "line_note": self._first_value(item, "LineNote", "line_note"),
            "customer_id": self._first_value(item, "CustomerID", "customer_id"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "customer_location_id": self._first_value(item, "CustomerLocationID", "customer_location_id"),
            "customer_location_name": self._first_value(item, "CustomerLocationName", "customer_location_name"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "transfer_nbr": self._first_value(item, "TransferNbr", "transfer_nbr"),
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
            "line_note_id": self._first_value(item, "LineNoteID", "line_note_id"),
            "line_location_name": self._first_value(item, "LineLocationName", "line_location_name"),
            "product_uom_qty": self._first_value(item, "LineQuantity", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_code": self._first_value(item, "LineWarehouse", "Warehouse", "WarehouseID", "LineWarehouseID", "warehouse_code"),
            "line_warehouse_name": self._first_value(item, "LineWarehouseName", "line_warehouse_name"),
            "customer_id": self._first_value(item, "CustomerID", "customer_id"),
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
        building_id = self._first_value(item, "BuildingID", "adt_BuildingID")
        warehouse_code = self._first_value(
            item,
            "LineWarehouse",
            "Warehouse",
            "LineWarehouseID",
            "adt_Warehouse",
        )
        picking_type_warehouse = building_id or warehouse_code
        if not building_id and isinstance(picking_type_warehouse, str):
            picking_type_warehouse = picking_type_warehouse.split("-", 1)[0].strip()
        picking_type = self._search_picking_type(
            picking_type_warehouse,
            "internal",
            api_acumatica="credit_memo_consignment",
            operation_category="pick",
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
        vals["adt_NoteID"] = self._first_value(item, "NoteID", "adt_NoteID")
        warehouse_code = self._first_value(
            item,
            "LineWarehouse",
            "Warehouse",
            "WarehouseID",
            "adt_Warehouse",
        )
        document_only = self._bool_value(item, "DocumentOnly", "adt_DocumentOnly")
        picking_type = self._search_picking_type(
            warehouse_code,
            "outgoing",
            document_only=True,
            api_acumatica="invoice_consignment",
            target_operation_type="direct_delivery_order",
            operation_category="delivery",
        )
        vals["picking_type_id"] = picking_type.id if picking_type else False
        vals["adt_DocumentOnly"] = document_only
        return vals

    def _invoice_consignment_product_vals(self, item, header):
        vals = self._credit_memo_consignment_product_vals(item, header)
        vals["adt_external_id"] = header.adt_id or False
        vals["adt_LineBranchName"] = self._first_value(item, "LineBranchName", "adt_LineBranchName")
        vals["adt_NoteID"] = self._first_value(item, "NoteID", "adt_NoteID")
        return vals

    def _so_shipment_header_vals(self, item, row_number, picking_code="internal", operation_category="pick"):
        # Acumatica webhook ini tidak mengirim row-level ``id``.  NoteHeaderID
        # adalah identifier stabil untuk header shipment.
        acumatica_id = self._first_value(
            item,
            "NoteHeaderID",
            "acumatica_id",
            "id",
        )
        if not acumatica_id:
            raise UserError(_(
                "SO Shipment payload tidak memiliki NoteHeaderID "
                "atau Acumatica ID header."
            ))

        warehouse_code = self._first_value(item, "WarehouseID", "Warehouse", "adt_WarehouseID")
        document_only = self._bool_value(item, "DocumentOnly", "adt_DocumentOnly")
        picking_type = self._search_picking_type(
            warehouse_code,
            picking_code,
            document_only=document_only,
            api_acumatica="so_shipment",
            operation_category=operation_category,
        )
        return {
            "acumatica_id": acumatica_id,
            "adt_rowNumber": self._first_value(item, "rowNumber", "adt_rowNumber") or row_number,
            "adt_note": self._first_value(item, "note", "Note", "adt_note"),
            "adt_Description": self._first_value(item, "Description", "adt_Description"),
            "adt_BuildingID": self._first_value(item, "BuildingID", "adt_BuildingID"),
            "adt_CustomerID": self._first_value(item, "CustomerID", "adt_CustomerID"),
            "adt_CustomerName": self._first_value(item, "CustomerName", "adt_CustomerName"),
            "adt_DocumentOnly": document_only,
            "adt_FOBPoint": self._first_value(item, "FOBPoint", "adt_FOBPoint"),
            "adt_FOBPointDescription": self._first_value(item, "FOBPointDescription", "adt_FOBPointDescription"),
            "adt_LocationID": self._first_value(item, "LocationID", "adt_LocationID"),
            "adt_LocationName": self._first_value(item, "LocationName", "adt_LocationName"),
            "adt_NoteHeader": self._first_value(item, "NoteHeader", "adt_NoteHeader"),
            "adt_NoteHeaderID": self._first_value(item, "NoteHeaderID", "adt_NoteHeaderID"),
            "adt_OrderType": self._first_value(item, "OrderType", "adt_OrderType"),
            "adt_ShipDate": self._first_value(item, "ShipDate", "ShipmentDate", "adt_ShipDate"),
            "adt_IssueNbr": self._first_value(item, "IssueNbr", "adt_IssueNbr"),
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
        return self._so_shipment_header_vals(
            item,
            row_number,
            picking_code="internal",
            operation_category="pick",
        )

    def _so_shipment_line_vals(self, item, header):
        acumatica_id = self._first_value(
            item,
            "LineNoteID",
            "line_id",
            "line_external_id",
            "acumatica_id",
            "id",
        )
        if not acumatica_id:
            raise UserError(_(
                "SO Shipment line payload tidak memiliki LineNoteID "
                "atau Acumatica ID line."
            ))

        return {
            "gi_id": header.id,
            "acumatica_id": acumatica_id,
            "adt_rowNumber": self._first_value(item, "line_rowNumber", "rowNumber", "adt_rowNumber"),
            "adt_LineInventoryID": self._first_value(item, "LineInventoryID", "InventoryID", "adt_LineInventoryID"),
            "adt_LineDescription": self._first_value(item, "LineDescription", "Description", "adt_LineDescription"),
            "adt_LineNote": self._first_value(item, "LineNote", "note", "adt_LineNote"),
            "adt_LineNoteID": self._first_value(item, "LineNoteID", "adt_LineNoteID"),
            "adt_LineLocation": self._first_value(item, "LineLocation", "Location", "adt_LineLocation"),
            "adt_LineNbr": self._first_value(item, "LineNbr", "adt_LineNbr"),
            "adt_LineQuantity": self._first_value(item, "LineQuantity", "Quantity", "ShipmentQty", "ShippedQty", "adt_ShipmentQty"),
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
                "label": "SO Consignment",
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
            "shipment_transfer_completed": {
                "label": "Shipment Transfer Completed",
                "records_keys": ("Inserted",),
                "detail_keys": (
                    "ShipmentTransferCompletedGIDetails",
                    "ShipmentTransferGIDetails",
                    "Details",
                    "details",
                ),
                "processor": self._process_shipment_transfer_completed_webhook,
            },
            "inventory_adjustment": {
                "label": "Inventory Adjustment",
                "records_keys": ("Inserted",),
                "processor": self._process_inventory_adjustment_webhook,
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
            "inventoryadjustmentgi": "inventory_adjustment",
            "inventory_adjustment_gi": "inventory_adjustment",
            "inventory_receipt": "inventory_receipt",
            "inventory_received": "inventory_receipt",
            "shipment_so_return": "shipment_return",
            "so_shipment_return": "shipment_return",
            "shipment_so": "shipment_return",
            "shipment_completed": "so_shipment_completed",
            "so_shipment_complete": "so_shipment_completed",
            "shipment_complete": "so_shipment_completed",
            "shipment_transfer_complete": "shipment_transfer_completed",
            "transfer_shipment_completed": "shipment_transfer_completed",
            "transfer_shipment_complete": "shipment_transfer_completed",
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
            "inventory_adjustment": "inventory_adjustment",
            "shipment_return": "shipment_so",
            "po_return": "issue_po_return",
            "vendor_return": "vendor_return_direct_transfer",
            "vendor_return_document": "vendor_return_document_direct_transfer",
            "so_shipment_completed": "shipment_completed",
            "shipment_transfer_completed": "shipment_transfer_completed",
        }
        return aliases.get(config_key, config_key)
