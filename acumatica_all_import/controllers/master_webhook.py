# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, http
from odoo.exceptions import UserError

from .webhook import AcumaticaWebhookController


_logger = logging.getLogger(__name__)


class AcumaticaMasterWebhookController(AcumaticaWebhookController):
    def _customer_vals(self, item, row_number):
        b_account_id = self._first_value(item, "BAccountID", "b_account_id")
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._note_value(item),
            "b_account_id": str(b_account_id) if b_account_id else "",
            "customer_class": self._first_value(item, "CustomerClass", "customer_class"),
            "customer_id": self._first_value(item, "CustomerID", "customer_id"),
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "note_id": self._first_value(item, "NoteID", "note_id"),
            "shipping_zone_id": self._first_value(item, "ShippingZoneID", "shipping_zone_id"),
            "status": self._first_value(item, "Status", "status"),
            "warehouse_id": self._first_value(item, "WarehouseID", "warehouse_id"),
            "tax_registration_id": self._first_value(item, "TaxRegistrationID", "tax_registration_id"),
            "import_state": "pending",
            "import_message": False,
            "sync_date": fields.Datetime.now(),
        }

    def _vendor_vals(self, item, row_number):
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._note_value(item),
            "account_ref": self._first_value(item, "AccountRef", "account_ref"),
            "b_account_id": self._first_value(item, "BAccountID", "b_account_id"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "lead_time_days": self._int_value(item, "LeadTimedays", "LeadTimeDays", "lead_time_days"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "status": self._first_value(item, "Status", "status"),
            "vendor_id": self._first_value(item, "VendorID", "vendor_id"),
            "vendor_name": self._first_value(item, "VendorName", "vendor_name"),
            "vendor_class": self._first_value(item, "VendorClass", "vendor_class"),
            "import_state": "pending",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _uom_vals(self, item, row_number):
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "unit_id": self._first_value(item, "UnitID", "unit_id"),
            "description": self._first_value(item, "Description", "description"),
            "import_state": "pending",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _warehouse_vals(self, item, row_number):
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "building_id": self._first_value(item, "BuildingID", "building_id"),
            "note": self._note_value(item),
            "active": True,
            "is_active": self._bool_value(item, "Active", "is_active"),
            "description": self._first_value(item, "Description", "description"),
            "drop_ship_location_id": self._first_value(item, "DropShipLocationID", "drop_ship_location_id"),
            "last_modified_dt": self._first_value(item, "LastModifiedDateTime", "last_modified_dt"),
            "receiving_location_id": self._first_value(item, "ReceivingLocationID", "receiving_location_id"),
            "rma_location_id": self._first_value(item, "RMALocationID", "rma_location_id"),
            "shipping_location_id": self._first_value(item, "ShippingLocationID", "shipping_location_id"),
            "warehouse_id": self._first_value(item, "WarehouseID", "warehouse_id"),
            "import_state": "pending",
            "import_message": False,
            "sync_date": fields.Datetime.now(),
        }

    def _stock_item_vals(self, item, row_number):
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "inventory_id": self._first_value(item, "InventoryID", "inventory_id"),
            "description": self._first_value(item, "Description", "description"),
            "item_type": self._first_value(item, "ItemType", "item_type"),
            "item_class": self._first_value(item, "ItemClass", "item_class"),
            "item_status": self._first_value(item, "ItemStatus", "item_status"),
            "base_uom": self._first_value(item, "BaseUOM", "base_uom"),
            "valuation_method": self._first_value(item, "ValuationMethod", "valuation_method"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "import_state": "pending",
            "import_message": False,
            "sync_date": fields.Datetime.now(),
        }

    def _non_stock_item_vals(self, item, row_number):
        return {
            "external_id": item.get("id") or item.get("external_id") or "",
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "inventory_id": self._first_value(item, "InventoryID", "inventory_id"),
            "description": self._first_value(item, "Description", "description"),
            "item_type": self._first_value(item, "ItemType", "item_type"),
            "item_class": self._first_value(item, "ItemClass", "item_class"),
            "item_status": self._first_value(item, "ItemStatus", "item_status"),
            "base_unit": self._first_value(item, "BaseUnit", "base_unit"),
            "purchase_unit": self._first_value(item, "PurchaseUnit", "purchase_unit"),
            "sales_unit": self._first_value(item, "SalesUnit", "sales_unit"),
            "is_a_kit": self._bool_value(item, "IsAKit", "is_a_kit"),
            "is_kit": self._bool_value(item, "IsKit", "is_kit"),
            "note_id": self._first_value(item, "NoteID", "note_id"),
            "posting_class": self._first_value(item, "PostingClass", "posting_class"),
            "note": self._note_value(item),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "price_class": self._first_value(item, "PriceClass", "price_class"),
            "volume": self._float_value(item, "Volume", "volume"),
            "volume_uom": self._first_value(item, "VolumeUOM", "volume_uom"),
            "weight": self._float_value(item, "Weight", "weight"),
            "weight_uom": self._first_value(item, "WeightUOM", "weight_uom"),
            "import_state": "pending",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _master_webhook(self, model_name, vals_getter, lookup_fields, payload_keys, label, **kwargs):
        ok, err = self._check_api_key()
        if not ok:
            return self._json_response("error", err, http_status=401)

        try:
            payload = self._raw_payload(kwargs)
            records = self._records_from_payload_keys(payload, payload_keys)
            if not records:
                raise UserError(_("No records found in payload."))

            result = self._process_lines(model_name, records, vals_getter, lookup_fields)
            return self._json_response(
                "success",
                _("%s webhook processed.") % label,
                model=model_name,
                **result
            )
        except UserError as exc:
            return self._json_response("error", str(exc), http_status=400)
        except Exception as exc:
            _logger.exception("Unexpected error in %s webhook", label)
            return self._json_response("error", _("Unexpected server error: %s") % str(exc), http_status=500)

    @http.route(["/acumatica/webhook/customer", "/acumatica/customer/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_customer_webhook(self, **kwargs):
        return self._master_webhook(
            "acumatica.customer.line",
            self._customer_vals,
            [("b_account_id", "customer_id"), ("external_id",), ("customer_id",)],
            ("records", "data", "value"),
            "Customer",
            **kwargs
        )

    @http.route(["/acumatica/webhook/vendor", "/acumatica/vendor/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_vendor_webhook(self, **kwargs):
        return self._master_webhook(
            "acumatica.vendor.line",
            self._vendor_vals,
            [("vendor_id",), ("external_id",)],
            ("records", "data", "value"),
            "Vendor",
            **kwargs
        )

    @http.route(["/acumatica/webhook/uom", "/acumatica/uom/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_uom_webhook(self, **kwargs):
        return self._master_webhook(
            "acumatica.uom.line",
            self._uom_vals,
            [("unit_id",), ("external_id",)],
            ("records", "data", "value"),
            "UoM",
            **kwargs
        )

    @http.route(["/acumatica/webhook/warehouse", "/acumatica/warehouse/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_warehouse_webhook(self, **kwargs):
        return self._master_webhook(
            "acumatica.warehouse.line",
            self._warehouse_vals,
            [("warehouse_id",), ("external_id",)],
            ("records", "data", "value"),
            "Warehouse",
            **kwargs
        )

    @http.route(["/acumatica/webhook/stock-item", "/acumatica/stock-item/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_stock_item_webhook(self, **kwargs):
        return self._master_webhook(
            "acumatica.stock.item.line",
            self._stock_item_vals,
            [("external_id",), ("inventory_id",)],
            ("records", "data", "value"),
            "Stock Item",
            **kwargs
        )

    @http.route(["/acumatica/webhook/non-stock-item", "/acumatica/non-stock-item/line/webhook"], type="http", auth="public", methods=["POST"], csrf=False)
    def acumatica_non_stock_item_webhook(self, **kwargs):
        return self._master_webhook(
            "acumatica.non.stock.item.line",
            self._non_stock_item_vals,
            [("external_id",), ("inventory_id",)],
            ("records", "data", "value"),
            "Non-Stock Item",
            **kwargs
        )
