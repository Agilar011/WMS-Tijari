# -*- coding: utf-8 -*-
from odoo import _, fields
from odoo.exceptions import UserError


class MasterMappingMixin:
    def _customer_vals(self, item, row_number):
        b_account_id = self._first_value(item, "BAccountID", "b_account_id")
        b_account_id = str(b_account_id).strip() if b_account_id not in (False, None, "") else ""
        customer_id = str(self._first_value(item, "CustomerID", "customer_id")).strip()
        return {
            "external_id": self._first_value(item, "id", "external_id"),
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._note_value(item),
            "b_account_id": str(b_account_id) if b_account_id else "",
            "customer_class": self._first_value(item, "CustomerClass", "customer_class"),
            "customer_id": str(customer_id) if customer_id else "",
            "customer_name": self._first_value(item, "CustomerName", "customer_name"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "LastModifiedOn", "last_modified_datetime"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "note_id": self._first_value(item, "NoteID", "note_id"),
            "shipping_zone_id": self._first_value(item, "ShippingZoneID", "shipping_zone_id"),
            "status": self._first_value(item, "Status", "CustomerStatus", "status"),
            "warehouse_id": self._first_value(item, "WarehouseID", "warehouse_id"),
            "tax_registration_id": self._first_value(item, "TaxRegistrationID", "tax_registration_id"),
            "import_state": "staged",
            "import_message": False,
            "sync_date": fields.Datetime.now(),
        }

    def _vendor_vals(self, item, row_number):
        vendor_id = str(self._first_value(item, "VendorID", "vendor_id")).strip()
        return {
            "external_id": self._first_value(item, "id", "external_id"),
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "note": self._note_value(item),
            "account_ref": self._first_value(item, "AccountRef", "account_ref"),
            "b_account_id": self._first_value(item, "BAccountID", "b_account_id"),
            "fob_point": self._first_value(item, "FOBPoint", "fob_point"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "lead_time_days": self._int_value(item, "LeadTimedays", "LeadTimeDays", "lead_time_days"),
            "location_name": self._first_value(item, "LocationName", "location_name"),
            "status": self._first_value(item, "Status", "status"),
            "vendor_id": str(vendor_id) if vendor_id else "",
            "vendor_name": self._first_value(item, "VendorName", "vendor_name"),
            "vendor_class": self._first_value(item, "VendorClass", "vendor_class"),
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _uom_vals(self, item, row_number):
        return {
            "external_id": self._first_value(item, "id", "external_id"),
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "unit_id": self._first_value(item, "UnitID", "unit_id"),
            "description": self._first_value(item, "Description", "description"),
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _warehouse_vals(self, item, row_number):
        warehouse_id = str(self._first_value(item, "WarehouseID", "warehouse_id")).strip()
        return {
            "external_id": self._first_value(item, "id", "external_id"),
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
            "warehouse_id": warehouse_id,
            "import_state": "staged",
            "import_message": False,
            "sync_date": fields.Datetime.now(),
        }

    def _stock_item_vals(self, item, row_number):
        raw_inventory_id = self._first_value(item, "InventoryID", "inventory_id")
        inventory_id = str(raw_inventory_id).rstrip() if raw_inventory_id not in (False, None, "") else ""
        return {
            "external_id": self._first_value(item, "id", "external_id"),
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "inventory_id": inventory_id,
            "description": self._first_value(item, "Description", "description"),
            "item_type": self._first_value(item, "ItemType", "item_type"),
            "item_class": self._first_value(item, "ItemClass", "item_class"),
            "item_status": self._first_value(item, "ItemStatus", "item_status"),
            "base_uom": self._first_value(item, "BaseUOM", "base_uom"),
            "valuation_method": self._first_value(item, "ValuationMethod", "valuation_method"),
            "last_modified_datetime": self._first_value(item, "LastModifiedDateTime", "last_modified_datetime"),
            "import_state": "staged",
            "import_message": False,
            "sync_date": fields.Datetime.now(),
        }

    def _non_stock_item_vals(self, item, row_number):
        raw_inventory_id = self._first_value(item, "InventoryID", "inventory_id")
        inventory_id = str(raw_inventory_id).rstrip() if raw_inventory_id not in (False, None, "") else ""
        return {
            "external_id": self._first_value(item, "id", "external_id"),
            "row_number": item.get("rowNumber") or item.get("row_number") or row_number,
            "inventory_id": inventory_id,
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
            "import_state": "staged",
            "import_message": False,
            "selected": True,
            "sync_date": fields.Datetime.now(),
        }

    def _master_configs(self):
        return {
            "customer": {
                "model_name": "acumatica.customer.line",
                "vals_getter": self._customer_vals,
                "lookup_fields": [("b_account_id",), ("customer_id",)],
                "payload_keys": ("Updated", "Inserted", "records", "data", "value"),
                "label": "Customer",
            },
            "vendor": {
                "model_name": "acumatica.vendor.line",
                "vals_getter": self._vendor_vals,
                "lookup_fields": [("b_account_id",), ("vendor_id",)],
                "payload_keys": ("Inserted", "records", "data", "value"),
                "label": "Vendor",
            },
            "uom": {
                "model_name": "acumatica.uom.line",
                "vals_getter": self._uom_vals,
                "lookup_fields": [("unit_id",)],
                "payload_keys": ("Inserted", "records", "data", "value"),
                "label": "UoM",
            },
            "warehouse": {
                "model_name": "acumatica.warehouse.line",
                "vals_getter": self._warehouse_vals,
                "lookup_fields": [("external_id",), ("warehouse_id",)],
                "payload_keys": ("Inserted", "records", "data", "value"),
                "label": "Warehouse",
            },
            "stock_item": {
                "model_name": "acumatica.stock.item.line",
                "vals_getter": self._stock_item_vals,
                "lookup_fields": [("external_id",), ("inventory_id",)],
                "payload_keys": ("Inserted", "records", "data", "value"),
                "label": "Stock Item",
            },
            "non_stock_item": {
                "model_name": "acumatica.non.stock.item.line",
                "vals_getter": self._non_stock_item_vals,
                "lookup_fields": [("external_id",), ("inventory_id",)],
                "payload_keys": ("Inserted", "records", "data", "value"),
                "label": "Non-Stock Item",
            },
        }

    def _normalize_master_key(self, key):
        return (key or "").strip().lower().replace("-", "_")

    def _process_master_payload(self, master_key, payload):
        config_key = self._normalize_master_key(master_key)
        config = self._master_configs().get(config_key)
        if not config:
            raise UserError(_("Unknown master webhook: %s") % master_key)

        records = self._records_from_payload_keys(payload, config["payload_keys"])
        if not records:
            raise UserError(_("No records found in payload."))

        result = self._process_lines(
            config["model_name"],
            records,
            config["vals_getter"],
            config["lookup_fields"],
        )
        result.update({
            "model": config["model_name"],
            "label": config["label"],
        })
        return result
