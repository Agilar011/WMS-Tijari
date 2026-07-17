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
            return request.env["stock.picking.type"].sudo().browse()

        return request.env["stock.picking.type"].sudo().search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", "incoming"),
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

    def _upsert_receipt_header(self, vals):
        Receipt = request.env["acumatica.receipt.line"].sudo()
        receipt = Receipt.search([("receipt_nbr", "=", vals["receipt_nbr"])], limit=1)
        if receipt:
            receipt.write(vals)
            return receipt, "updated"
        return Receipt.create(vals), "created"

    def _replace_receipt_products(self, receipt, records):
        ProductLine = request.env["acumatica.receipt.product.line"].sudo()
        receipt.product_line_ids.unlink()
        product_vals = [
            self._receipt_product_vals(item, receipt)
            for item in records
            if isinstance(item, dict)
        ]
        if product_vals:
            ProductLine.create(product_vals)
        return len(product_vals)

    @http.route(["/acumatica/webhook/po-receipt", "/acumatica/po-receipt/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_po_receipt_webhook(self, **kwargs):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_response("error", err, http_status=401)

        try:
            payload = self._raw_payload(kwargs)
            records = self._records_from_payload_keys(payload, ("PurchaseReceiptGIDetails", "records", "data", "value"))
            if not records:
                raise UserError(_("No PO receipt records found in payload."))

            grouped = {}
            for index, item in enumerate(records, start=1):
                if not isinstance(item, dict):
                    continue
                receipt_nbr = self._first_value(item, "ReceiptNbr", "receipt_nbr")
                if not receipt_nbr:
                    continue
                grouped.setdefault(receipt_nbr, []).append((index, item))

            if not grouped:
                raise UserError(_("No valid ReceiptNbr found in payload."))

            created = updated = product_lines = imported = errors = 0
            receipt_ids = []

            for receipt_records in grouped.values():
                first_index, first_item = receipt_records[0]
                header_vals = self._receipt_header_vals(first_item, first_index)
                receipt, state = self._upsert_receipt_header(header_vals)
                if state == "created":
                    created += 1
                else:
                    updated += 1

                product_lines += self._replace_receipt_products(
                    receipt,
                    [item for _, item in receipt_records]
                )
                receipt_ids.append(receipt.id)

            receipts = request.env["acumatica.receipt.line"].sudo().browse(receipt_ids)
            if receipts:
                receipts._do_import()
                imported = len(receipts.filtered(lambda receipt: receipt.import_state in ("imported", "updated")))
                errors = len(receipts.filtered(lambda receipt: receipt.import_state == "error"))

            return self._json_response(
                "success",
                _("PO Receipt webhook processed."),
                model="acumatica.receipt.line",
                created=created,
                updated=updated,
                imported=imported,
                errors=errors,
                receipt_ids=receipt_ids,
                product_lines=product_lines,
            )
        except UserError as exc:
            return self._json_response("error", str(exc), http_status=400)
        except Exception as exc:
            _logger.exception("Unexpected error in PO Receipt webhook")
            return self._json_response("error", _("Unexpected server error: %s") % str(exc), http_status=500)
