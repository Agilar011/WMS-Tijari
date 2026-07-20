# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request

from .webhook import AcumaticaWebhookController


_logger = logging.getLogger(__name__)


class AcumaticaTransactionWebhookController(AcumaticaWebhookController):
    def _search_picking_type(self, building_code):
        if not building_code:
            return request.env["stock.picking.type"].sudo().browse()

        warehouse = request.env["stock.warehouse"].sudo().search([
            ("code", "=", building_code)
        ], limit=1)
        if not warehouse:
            mapping = request.env["stock.location.acumatica"].sudo().search([
                ("code", "=", building_code)
            ], limit=1)
            warehouse = mapping.odoo_building_id if mapping else False
        if not warehouse:
            return request.env["stock.picking.type"].sudo().browse()

        return request.env["stock.picking.type"].sudo().search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", "incoming"),
            ("is_default_api", "=", True),
        ], limit=1)

    def _search_internal_picking_type(self, warehouse_code):
        if not warehouse_code:
            return request.env["stock.picking.type"].sudo().browse()

        mapping = request.env["stock.location.acumatica"].sudo().search([
            ("code", "=", warehouse_code)
        ], limit=1)
        warehouse = mapping.odoo_building_id if mapping else False
        if not warehouse:
            warehouse = request.env["stock.warehouse"].sudo().search([
                ("code", "=", warehouse_code)
            ], limit=1)
        if not warehouse:
            return request.env["stock.picking.type"].sudo().browse()

        return request.env["stock.picking.type"].sudo().search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", "internal"),
            ("is_default_api", "=", True),
        ], limit=1)

    def _receipt_header_vals(self, item, row_number):
        building_code = self._first_value(item, "BuildingID", "building_code")
        picking_type = self._search_picking_type(building_code)
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "building_code": building_code,
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "inventory_ref": self._first_value(item, "InventoryRefNbr", "inventory_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "Location", "header_location_code"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "receipt_nbr": self._first_value(item, "ReceiptNbr", "receipt_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "receipt_type": self._first_value(item, "Type", "receipt_type"),
            "vendor_code": self._first_value(item, "VendorID", "vendor_code"),
            "vendor_name": self._first_value(item, "VendorName", "vendor_name"),
            "partner_ref": self._first_value(item, "VendorRef", "partner_ref"),
            "warehouse_code": self._first_value(item, "LineWarehouseID", "Warehouse", "warehouse_code"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _receipt_product_vals(self, item, receipt):
        return {
            "header_external_id": item.get("id") or item.get("external_id") or "",
            "receipt_line_id": receipt.id,
            "receipt_nbr": receipt.receipt_nbr,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "description": self._first_value(item, "LineDescription", "Description", "description"),
            "transaction_description": self._first_value(item, "TransactionDescription", "transaction_description"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "line_nbr": self._first_value(item, "LineNbr", "line_nbr"),
            "line_type": self._first_value(item, "LineType", "line_type"),
            "location_dest_code": self._first_value(item, "LineLocation", "Location", "location_dest_code"),
            "open_qty": self._first_value(item, "LineOpenQty", "OpenQty", "open_qty"),
            "order_qty": self._first_value(item, "LineOrderedQty", "OrderedQty", "order_qty"),
            "po_line_number": self._first_value(item, "POLineNbr", "po_line_number"),
            "po_number": self._first_value(item, "PONbr", "po_number"),
            "po_type": self._first_value(item, "POType", "po_type"),
            "po_receipt_line_number": self._first_value(item, "POReceiptLineNbr", "po_receipt_line_number"),
            "po_receipt_number": self._first_value(item, "POReceiptNbr", "po_receipt_number"),
            "product_uom_qty": self._first_value(item, "LineReceiptQty", "ReceiptQty", "product_uom_qty"),
            "transfer_order_line_number": self._first_value(item, "TransferOrderLineNbr", "transfer_order_line_number"),
            "transfer_order_number": self._first_value(item, "TransferOrderNbr", "transfer_order_number"),
            "transfer_order_type": self._first_value(item, "TransferOrderType", "transfer_order_type"),
            "transfer_shipment_number": self._first_value(item, "TransferShipmentNbr", "transfer_shipment_number"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_dest_code": self._first_value(item, "LineWarehouseID", "WarehouseID", "warehouse_dest_code"),
        }

    def _po_return_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "Warehouse", "WarehouseID", "LineWarehouseID", "warehouse_code")
        picking_type = self._search_internal_picking_type(warehouse_code)
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "inventory_ref": self._first_value(item, "InventoryRefNbr", "inventory_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "Location", "header_location_code"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "receipt_nbr": self._first_value(item, "ReceiptNbr", "receipt_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "receipt_type": self._first_value(item, "Type", "receipt_type"),
            "po_type": self._first_value(item, "Type", "po_type"),
            "vendor_code": self._first_value(item, "VendorID", "vendor_code"),
            "partner_ref": self._first_value(item, "VendorName", "VendorRef", "partner_ref"),
            "warehouse_code": warehouse_code,
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
            "import_message": "Data API Imported",
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _po_return_product_vals(self, item, receipt):
        return {
            "receipt_line_id": receipt.id,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
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
            "inventory_id": self._first_value(item, "InventoryID", "inventory_id"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "location": self._first_value(item, "Location", "location"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "quantity": self._float_value(item, "Qty", "Quantity", "quantity"),
            "reason_code": self._first_value(item, "ReasonCode", "reason_code"),
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "requested_on": self._first_value(item, "RequestedOn", "requested_on"),
            "revision": self._first_value(item, "Revision", "revision"),
            "status": self._first_value(item, "Status", "status"),
            "type": self._first_value(item, "Type", "type"),
            "uom": self._first_value(item, "UOM", "uom"),
            "warehouse": self._first_value(item, "Warehouse", "WarehouseID", "warehouse"),
        }

    def _kit_assembly_component_vals(self, item, header):
        return {
            "assembly_id": header.id,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "line_inventory_id": self._first_value(item, "InventoryID", "LineInventoryID", "line_inventory_id"),
            "line_component_qty": self._float_value(item, "ComponentQty", "line_component_qty"),
            "line_nbr": self._int_value(item, "LineNbr", "line_nbr", "line_rowNumber"),
            "line_location_id": self._first_value(item, "LocationID", "line_location_id"),
            "line_quantity": self._float_value(item, "Qty", "Quantity", "line_quantity"),
            "line_reason_code": self._first_value(item, "ReasonCode", "line_reason_code"),
            "stock_inventory_id": self._first_value(item, "StockInventoryID", "stock_inventory_id"),
            "line_uom": self._first_value(item, "UOM", "LineUOM", "line_uom"),
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
            "import_state": "pending",
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

        Header = request.env["acumatica.kit.assembly"].sudo()
        Component = request.env["acumatica.kit.assembly.component"].sudo()
        Staging = request.env["acumatica.kit.assembly.line"].sudo()
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

        staging_records = Staging.browse(staging_ids)
        if staging_records:
            staging_records._do_import()
            imported = len(staging_records.filtered(lambda line: line.import_state in ("imported", "updated")))
            errors = len(staging_records.filtered(lambda line: line.import_state == "error"))

        return self._json_response(
            "success",
            _("Kit Assembly webhook processed."),
            transaction_type="kit_assembly",
            model="acumatica.kit.assembly.line",
            created=created,
            updated=updated,
            imported=imported,
            errors=errors,
            header_ids=staging_ids,
            component_lines=component_lines,
            product_lines=staging_lines,
        )

    def _so_transfer_header_vals(self, item, row_number):
        vals = self._receipt_header_vals(item, row_number)
        vals.update({
            "warehouse_dest_code": self._first_value(item, "Warehouse", "LineWarehouseID", "WarehouseID", "warehouse_dest_code"),
            "location_dest_code": self._first_value(item, "LineLocation", "Location", "location_dest_code"),
            "transfer_order_number": self._first_value(item, "TransferOrderNbr", "transfer_order_number"),
            "transfer_order_line_number": self._first_value(item, "TransferOrderLineNbr", "transfer_order_line_number"),
            "transfer_order_type": self._first_value(item, "TransferOrderType", "transfer_order_type"),
            "transfer_shipment_number": self._first_value(item, "TransferShipmentNbr", "transfer_shipment_number"),
        })
        return vals

    def _so_transfer_product_vals(self, item, transfer):
        vals = self._receipt_product_vals(item, transfer)
        vals.pop("receipt_line_id", None)
        vals["transfer_line_id"] = transfer.id
        vals["transfer_order_number"] = self._first_value(item, "TransferOrderNbr", "transfer_order_number")
        vals["warehouse_dest_code"] = self._first_value(item, "Warehouse", "LineWarehouseID", "WarehouseID", "warehouse_dest_code")
        return vals

    def _direct_transfer_header_vals(self, item, row_number):
        from_warehouse = self._first_value(item, "FromWarehouseID", "adt_FromWarehouseID")
        picking_type = self._search_internal_picking_type(from_warehouse)
        return {
            "adt_id": item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._int_value(item, "rowNumber", "adt_rowNumber") or row_number,
            "adt_note": self._first_value(item, "note", "Note", "adt_note"),
            "adt_Date": self._first_value(item, "Date", "adt_Date"),
            "adt_Description": self._first_value(item, "Description", "adt_Description"),
            "adt_DocumentOnly": self._first_value(item, "DocumentOnly", "adt_DocumentOnly"),
            "adt_ExternalRef": self._first_value(item, "ExternalRef", "adt_ExternalRef"),
            "adt_FromWarehouseID": from_warehouse,
            "adt_Hold": self._bool_value(item, "Hold", "adt_Hold"),
            "adt_LastModifiedDateTime": self._first_value(item, "LastModifiedDateTime", "adt_LastModifiedDateTime"),
            "adt_NoteID": self._first_value(item, "NoteID", "adt_NoteID"),
            "adt_PostPeriod": self._first_value(item, "PostPeriod", "adt_PostPeriod"),
            "adt_ReferenceNbr": self._first_value(item, "ReferenceNbr", "adt_ReferenceNbr"),
            "adt_ReturnType": self._first_value(item, "ReturnType", "adt_ReturnType"),
            "adt_Status": self._first_value(item, "Status", "adt_Status"),
            "adt_TotalQty": self._float_value(item, "TotalQty", "adt_TotalQty"),
            "adt_ToWarehouseID": self._first_value(item, "ToWarehouseID", "adt_ToWarehouseID"),
            "adt_TransferType": self._first_value(item, "TransferType", "adt_TransferType"),
            "adt_TransType": self._first_value(item, "TransType", "adt_TransType"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
            "import_message": "Data API Imported",
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _direct_transfer_product_vals(self, item, header):
        return {
            "receipt_line_id": header.id,
            "adt_id": item.get("line_id") or item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._int_value(item, "LineNumber", "line_rowNumber", "rowNumber", "adt_rowNumber"),
            "adt_note": self._first_value(item, "note", "LineNote", "adt_note"),
            "adt_Description": self._first_value(item, "LineDescription", "Description", "adt_Description"),
            "adt_FromLocationID": self._first_value(item, "FromLocationID", "adt_FromLocationID"),
            "adt_InventoryID": self._first_value(item, "InventoryID", "LineInventoryID", "adt_InventoryID"),
            "adt_LineNumber": self._int_value(item, "LineNumber", "LineNbr", "adt_LineNumber"),
            "adt_NoteID": self._first_value(item, "NoteID", "adt_NoteID"),
            "adt_Quantity": self._float_value(item, "Quantity", "LineQuantity", "adt_Quantity"),
            "adt_SOOrderNbr": self._first_value(item, "SOOrderNbr", "adt_SOOrderNbr"),
            "adt_SOOrderType": self._first_value(item, "SOOrderType", "adt_SOOrderType"),
            "adt_SOShipmentNbr": self._first_value(item, "SOShipmentNbr", "adt_SOShipmentNbr"),
            "adt_ToLocationID": self._first_value(item, "ToLocationID", "adt_ToLocationID"),
            "adt_UOM": self._first_value(item, "UOM", "LineUOM", "adt_UOM"),
        }

    def _receipt_external_header_vals(self, item, row_number):
        building_code = self._first_value(item, "BuildingID", "building_code")
        picking_type = self._search_picking_type(building_code)
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "building_code": building_code,
            "change_item_ref_nbr": self._first_value(item, "ChangeItemRefNbr", "change_item_ref_nbr"),
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "customer_code": self._first_value(item, "CustomerID", "customer_code"),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "description": self._first_value(item, "Description", "description"),
            "external_ref": self._first_value(item, "ExternalRef", "external_ref"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "location_code": self._first_value(item, "Location", "location_code"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "shipment_nbr": self._first_value(item, "ShipmentNbr", "shipment_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "transfer_nbr": self._first_value(item, "TransferNbr", "transfer_nbr"),
            "transfer_type": self._first_value(item, "TransType", "transfer_type"),
            "warehouse_code": self._first_value(item, "LineWarehouse", "warehouse_code"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _receipt_external_product_vals(self, item, receipt):
        return {
            "header_external_id": item.get("id") or item.get("external_id") or "",
            "inventory_line_id": receipt.id,
            "reference_nbr": receipt.reference_nbr,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
            "line_note": self._first_value(item, "LineNote", "line_note") or self._note_value(item),
            "branch_warehouse": self._first_value(item, "Branch", "branch_warehouse"),
            "line_description": self._first_value(item, "LineInventoryName", "LineDescription", "line_description"),
            "inventory_id": self._first_value(item, "LineInventoryID", "InventoryID", "inventory_id"),
            "line_nbr": self._first_value(item, "LineNbr", "line_nbr"),
            "location_code": self._first_value(item, "LineLocation", "Location", "location_code"),
            "product_uom_qty": self._first_value(item, "LineQuantity", "Quantity", "product_uom_qty"),
            "uom_code": self._first_value(item, "LineUOM", "UOM", "uom_code"),
            "warehouse_dest_code": self._first_value(item, "LineWarehouse", "Warehouse", "warehouse_dest_code"),
        }

    def _shipment_return_header_vals(self, item, row_number):
        building_code = self._first_value(item, "BuildingID", "building_code")
        picking_type = self._search_picking_type(building_code)
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._first_value(item, "NoteHeader", "note") or self._note_value(item),
            "building_code": building_code,
            "actual_qty": self._first_value(item, "ControlQty", "actual_qty"),
            "partner_code": self._first_value(item, "CustomerID", "partner_code"),
            "description": self._first_value(item, "Description", "description"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "fob_point_description": self._first_value(item, "FOBPointDescription", "fob_point_description"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "header_location_code": self._first_value(item, "LocationID", "header_location_code"),
            "header_location_name": self._first_value(item, "LocationName", "header_location_name"),
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
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _shipment_return_product_vals(self, item, shipment):
        return {
            "header_external_id": item.get("id") or item.get("external_id") or "",
            "shipment_line_id": shipment.id,
            "shipment_nbr": shipment.shipment_nbr,
            "line_external_id": item.get("line_id") or item.get("line_external_id") or "",
            "note": self._first_value(item, "LineNote", "note") or self._note_value(item),
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
        }

    def _transfer_one_step_header_vals(self, item, row_number):
        from_warehouse = self._first_value(item, "FromWarehouseID", "from_warehouse_code")
        picking_type = self._search_internal_picking_type(from_warehouse)
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._note_value(item),
            "scheduled_date": self._first_value(item, "Date", "scheduled_date"),
            "description": self._first_value(item, "Description", "description"),
            "from_warehouse_code": from_warehouse,
            "is_hold": self._first_value(item, "Hold", "is_hold"),
            "acumatica_write_date": self._first_value(item, "LastModifiedDateTime", "acumatica_write_date"),
            "post_period": self._first_value(item, "PostPeriod", "post_period"),
            "reference_nbr": self._first_value(item, "ReferenceNbr", "reference_nbr"),
            "status": self._first_value(item, "Status", "status"),
            "total_qty": self._first_value(item, "TotalQty", "total_qty"),
            "to_warehouse_code": self._first_value(item, "ToWarehouseID", "to_warehouse_code"),
            "transfer_type": self._first_value(item, "TransferType", "transfer_type"),
            "trans_type": self._first_value(item, "TransType", "trans_type"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
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
            "from_location_code": self._first_value(item, "FromLocationID", "from_location_code"),
            "to_location_code": self._first_value(item, "ToLocationID", "to_location_code"),
            "quantity": self._float_value(item, "Quantity", "LineQuantity", "quantity"),
            "uom_code": self._first_value(item, "UOM", "LineUOM", "uom_code"),
        }

    def _transfer_two_step_header_vals(self, item, row_number):
        return self._transfer_one_step_header_vals(item, row_number)

    def _transfer_two_step_product_vals(self, item, header):
        return {
            "header_id": header.id,
            "acumatica_header_id": header.external_id or False,
            "adt_rowNumber": self._first_value(item, "LineNbr", "LineNumber", "line_rowNumber", "adt_rowNumber"),
            "adt_note": self._first_value(item, "LineNote", "line_note", "adt_note") or self._note_value(item),
            "adt_Description": self._first_value(item, "LineDescription", "Description", "line_description", "adt_Description"),
            "adt_FromLocationID": self._first_value(item, "FromLocationID", "from_location_code", "adt_FromLocationID"),
            "adt_InventoryID": self._first_value(item, "InventoryID", "LineInventoryID", "inventory_id", "adt_InventoryID"),
            "adt_LineNumber": self._first_value(item, "LineNbr", "LineNumber", "line_nbr", "adt_LineNumber"),
            "adt_NoteID": self._first_value(item, "NoteID", "adt_NoteID"),
            "adt_Quantity": self._first_value(item, "Quantity", "LineQuantity", "quantity", "adt_Quantity"),
            "adt_SOOrderNbr": self._first_value(item, "SOOrderNbr", "adt_SOOrderNbr"),
            "adt_SOOrderType": self._first_value(item, "SOOrderType", "adt_SOOrderType"),
            "adt_SOShipmentNbr": self._first_value(item, "SOShipmentNbr", "adt_SOShipmentNbr"),
            "adt_ToLocationID": self._first_value(item, "ToLocationID", "to_location_code", "adt_ToLocationID"),
            "adt_UOM": self._first_value(item, "UOM", "LineUOM", "uom_code", "adt_UOM"),
        }

    def _credit_memo_consignment_header_vals(self, item, row_number):
        warehouse_code = self._first_value(item, "Warehouse", "adt_Warehouse")
        picking_type = self._search_picking_type(warehouse_code)
        return {
            "adt_id": item.get("id") or item.get("adt_id") or "",
            "adt_rowNumber": self._first_value(item, "rowNumber", "adt_rowNumber") or row_number,
            "adt_note": self._first_value(item, "note", "Note", "adt_note"),
            "adt_ConsignmentType": self._first_value(item, "ConsignmentType", "adt_ConsignmentType"),
            "adt_CreatedDateTime": self._first_value(item, "CreatedDateTime", "adt_CreatedDateTime"),
            "adt_CustomerID": self._first_value(item, "CustomerID", "adt_CustomerID"),
            "adt_CustomerName": self._first_value(item, "CustomerName", "adt_CustomerName"),
            "adt_CustomerOrder": self._first_value(item, "CustomerOrder", "adt_CustomerOrder"),
            "adt_Date": self._first_value(item, "Date", "adt_Date"),
            "adt_Description": self._first_value(item, "Description", "adt_Description"),
            "adt_DueDate": self._first_value(item, "DueDate", "adt_DueDate"),
            "adt_LastModifiedDateTime": self._first_value(item, "LastModifiedDateTime", "adt_LastModifiedDateTime"),
            "adt_LocationID": self._first_value(item, "LocationID", "adt_LocationID"),
            "adt_LocationName": self._first_value(item, "LocationName", "adt_LocationName"),
            "adt_OrigRefNbr": self._first_value(item, "OrigRefNbr", "adt_OrigRefNbr"),
            "adt_ReferenceNbr": self._first_value(item, "ReferenceNbr", "adt_ReferenceNbr"),
            "adt_Status": self._first_value(item, "Status", "adt_Status"),
            "adt_Type": self._first_value(item, "Type", "adt_Type"),
            "picking_type_id": picking_type.id if picking_type else False,
            "import_state": "pending",
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
            "adt_Branch": self._first_value(item, "Branch", "adt_Branch"),
            "adt_InventoryID": self._first_value(item, "InventoryID", "LineInventoryID", "adt_InventoryID"),
            "adt_Qty": self._first_value(item, "Qty", "Quantity", "LineQuantity", "adt_Qty"),
            "adt_TransactionDescription": self._first_value(item, "TransactionDescription", "LineDescription", "Description", "adt_TransactionDescription"),
            "adt_UOM": self._first_value(item, "UOM", "LineUOM", "adt_UOM"),
            "adt_Warehouse": self._first_value(item, "Warehouse", "LineWarehouseID", "adt_Warehouse"),
        }

    def _invoice_consignment_header_vals(self, item, row_number):
        return self._credit_memo_consignment_header_vals(item, row_number)

    def _invoice_consignment_product_vals(self, item, header):
        vals = self._credit_memo_consignment_product_vals(item, header)
        vals["adt_external_id"] = header.adt_id or False
        return vals

    def _transaction_configs(self):
        return {
            "po_receipt": {
                "label": "PO Receipt",
                "records_keys": ("PurchaseReceiptGIDetails", "records", "data", "value"),
                "document_keys": ("ReceiptNbr", "receipt_nbr"),
                "document_field": "receipt_nbr",
                "header_model": "acumatica.receipt.line",
                "product_model": "acumatica.receipt.product.line",
                "header_vals": self._receipt_header_vals,
                "product_vals": self._receipt_product_vals,
            },
            "po_return": {
                "label": "PO Return",
                "records_keys": ("PurchaseReceiptGIDetails", "records", "data", "value"),
                "document_keys": ("ReceiptNbr", "receipt_nbr"),
                "document_field": "receipt_nbr",
                "header_model": "acumatica.issue.po.return.line",
                "product_model": "acumatica.issue.po.return.product",
                "header_vals": self._po_return_header_vals,
                "product_vals": self._po_return_product_vals,
            },
            "so_transfer": {
                "label": "SO Transfer",
                "records_keys": ("TransferOrderGIDetails", "PurchaseReceiptGIDetails", "records", "data", "value"),
                "document_keys": ("ReceiptNbr", "receipt_nbr"),
                "document_field": "receipt_nbr",
                "header_model": "acumatica.transfer.line",
                "product_model": "acumatica.transfer.product.line",
                "header_vals": self._so_transfer_header_vals,
                "product_vals": self._so_transfer_product_vals,
            },
            "vendor_return_direct_transfer": {
                "label": "Vendor Return Direct Transfer",
                "records_keys": ("records", "data", "value"),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.vendor.return.direct.transfer.staging",
                "product_model": "acumatica.vendor.return.direct.transfer.staging.line",
                "line_relation": "line_ids",
                "header_vals": self._direct_transfer_header_vals,
                "product_vals": self._direct_transfer_product_vals,
            },
            "vendor_return_document_direct_transfer": {
                "label": "Vendor Return Document Direct Transfer",
                "records_keys": ("records", "data", "value"),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.direct.transfer.staging",
                "product_model": "acumatica.direct.transfer.staging.line",
                "line_relation": "line_ids",
                "header_vals": self._direct_transfer_header_vals,
                "product_vals": self._direct_transfer_product_vals,
            },
            "transfer_one_step": {
                "label": "Transfer Intra Warehouse Out (1 Step)",
                "records_keys": ("records", "data", "value"),
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
                "records_keys": ("records", "data", "value"),
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
                "records_keys": ("records", "data", "value"),
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
                "records_keys": ("records", "data", "value"),
                "document_keys": ("ReferenceNbr", "adt_ReferenceNbr"),
                "document_field": "adt_ReferenceNbr",
                "header_model": "acumatica.invoice.consignment.staging",
                "product_model": "acumatica.invoice.consignment.staging.line",
                "header_vals": self._invoice_consignment_header_vals,
                "product_vals": self._invoice_consignment_product_vals,
            },
            "kit_assembly": {
                "label": "Kit Assembly",
                "records_keys": ("records", "data", "value"),
                "detail_keys": ("StockComponents", "stock_components", "Components", "components", "Details", "details"),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "processor": self._process_kit_assembly_webhook,
            },
            "inventory_receipt_external": {
                "label": "Inventory Receipt External",
                "records_keys": ("InventoryReceiptExternalGIDetails", "records", "data", "value"),
                "document_keys": ("ReferenceNbr", "reference_nbr"),
                "document_field": "reference_nbr",
                "header_model": "acumatica.receipt.external.line",
                "product_model": "acumatica.receipt.external.product.line",
                "header_vals": self._receipt_external_header_vals,
                "product_vals": self._receipt_external_product_vals,
            },
            "shipment_return": {
                "label": "Shipment Return",
                "records_keys": ("ShipmentReturnGIDetails", "records", "data", "value"),
                "document_keys": ("ShipmentNbr", "shipment_nbr"),
                "document_field": "shipment_nbr",
                "header_model": "acumatica.shipment.line",
                "product_model": "acumatica.shipment.product.line",
                "header_vals": self._shipment_return_header_vals,
                "product_vals": self._shipment_return_product_vals,
            },
        }

    def _normalize_transaction_type(self, transaction_type):
        return (transaction_type or "").strip().lower().replace("-", "_")

    def _upsert_header(self, model_name, document_field, vals):
        Header = request.env[model_name].sudo()
        vals = {
            field_name: value
            for field_name, value in vals.items()
            if field_name in Header._fields
        }
        header = Header.search([(document_field, "=", vals[document_field])], limit=1)
        if header:
            header.write(vals)
            return header, "updated"
        return Header.create(vals), "created"

    def _replace_product_lines(self, header, product_model, product_vals_getter, records, line_relation="product_line_ids"):
        ProductLine = request.env[product_model].sudo()
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
        merged.pop("Details", None)
        merged.pop("details", None)
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

    def _transaction_webhook(self, transaction_type, **kwargs):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_response("error", err, http_status=401)

        try:
            config_key = self._normalize_transaction_type(transaction_type)
            config = self._transaction_configs().get(config_key)
            if not config:
                raise UserError(_("Unknown transaction type: %s") % transaction_type)

            payload = self._raw_payload(kwargs)
            if config.get("processor"):
                return config["processor"](payload, config)

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

                header, state = self._upsert_header(
                    config["header_model"],
                    config["document_field"],
                    header_vals,
                )
                if state == "created":
                    created += 1
                else:
                    updated += 1

                product_lines += self._replace_product_lines(
                    header,
                    config["product_model"],
                    config["product_vals"],
                    [item for _, item in document_records],
                    config.get("line_relation", "product_line_ids"),
                )
                header_ids.append(header.id)

            headers = request.env[config["header_model"]].sudo().browse(header_ids)
            if headers:
                headers._do_import()
                imported = len(headers.filtered(lambda header: header.import_state in ("imported", "updated")))
                errors = len(headers.filtered(lambda header: header.import_state == "error"))

            return self._json_response(
                "success",
                _("%s webhook processed.") % config["label"],
                transaction_type=config_key,
                model=config["header_model"],
                created=created,
                updated=updated,
                imported=imported,
                errors=errors,
                header_ids=header_ids,
                product_lines=product_lines,
            )
        except UserError as exc:
            return self._json_response("error", str(exc), http_status=400)
        except Exception as exc:
            _logger.exception("Unexpected error in transaction webhook")
            return self._json_response("error", _("Unexpected server error: %s") % str(exc), http_status=500)

    @http.route("/acumatica/webhook/transaction/<string:transaction_type>", type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_flat_transaction_webhook(self, transaction_type, **kwargs):
        return self._transaction_webhook(transaction_type, **kwargs)
