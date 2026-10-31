# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TransactionProcessingMixin:
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
        Manufacturing = self._env()["mrp.production"].sudo()
        created = updated = component_lines = staging_lines = imported = errors = 0
        staging_ids = []
        already_generated = {}

        for reference_nbr, document_records in grouped.items():
            first_index, first_item = document_records[0]
            header_vals = self._kit_assembly_header_vals(first_item, first_index)
            header = Header.search([("reference_nbr", "=", reference_nbr)], limit=1)
            if header:
                header.write({field: value for field, value in header_vals.items() if field in Header._fields})
                updated += 1
            else:
                # Webhook staging is a system import.  Do not let mail.thread
                # auto-subscribe the current API user (or log a creation
                # message) here: mail.thread creates that follower with
                # check_existing=False, which can violate the followers
                # unique key when a delivery is retried/replayed.
                header = Header.with_context(
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                ).create({field: value for field, value in header_vals.items() if field in Header._fields})
                created += 1

            # Decide whether this webhook reference has already generated its MO.
            # Lock the header so concurrent webhook deliveries cannot both generate it.
            self._env().cr.execute(
                f'SELECT id FROM "{header._table}" WHERE id = %s FOR UPDATE',
                (header.id,),
            )
            header.invalidate_recordset(['mrp_production_id'])
            existing_manufacturing = header.mrp_production_id or Manufacturing.search(
                [('origin', '=', reference_nbr)], limit=1,
            )
            if existing_manufacturing:
                already_generated[reference_nbr] = existing_manufacturing

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

        # Generate/update Manufacturing Orders as part of webhook processing,
        # using the same importer as the manual "Import This" action.
        staged_records = Staging.browse(staging_ids)
        import_logs = []
        if staged_records:
            for reference_nbr, manufacturing in already_generated.items():
                product = manufacturing.product_id
                message = "Manufacturing Order already generated: %s" % manufacturing.display_name
                header = Header.search([("reference_nbr", "=", reference_nbr)], limit=1)
                header.write({
                    "import_state": "created",
                    "import_message": message,
                    "mrp_production_id": manufacturing.id,
                })
                staged_records.filtered(
                    lambda line: line.reference_nbr == reference_nbr
                ).write({
                    "import_state": "created",
                    "import_message": message,
                    "odoo_product_id": product.product_tmpl_id.id if product else False,
                })

            pending_records = staged_records.filtered(
                lambda line: line.reference_nbr not in already_generated
            )
            if pending_records:
                pending_records._do_import()
            ErrorLog = self._env()["acumatica.error.transaction"].sudo()
            ErrorLog._handle_acumatica_created(staged_records)
            error_logs = ErrorLog.search([
                ("data_type", "=", "acumatica.kit.assembly.line"),
                ("data_id", "in", staged_records.ids),
            ])
            error_messages = {log.data_id: log.error_msg for log in error_logs}

            for line in staged_records:
                import_logs.append({
                    "reference_nbr": line.reference_nbr,
                    "status": line.import_state,
                    "message": error_messages.get(line.id) or line.import_message or "",
                })

            for reference_nbr in grouped:
                reference_records = staged_records.filtered(
                    lambda line: line.reference_nbr == reference_nbr
                )
                states = set(reference_records.mapped("import_state"))
                if states.intersection({"created", "updated"}):
                    imported += 1
                elif states.intersection({"error", "rejected"}):
                    errors += 1

        return {
            "transaction_type": "kit_assembly",
            "model": "acumatica.kit.assembly.line",
            "created": created,
            "updated": updated,
            "imported": imported,
            "errors": errors,
            "logs": import_logs,
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

        created = updated = product_lines = imported = errors = 0
        header_ids = []
        for shipment_nbr, document_records in grouped.items():
            first_index, first_item = document_records[0]
            header_vals = self._shipment_completed_header_vals(first_item, first_index, acumatica_config)
            header = Staging.search([
                ("config_id", "=", acumatica_config.id),
                ("shipment_nbr", "=", shipment_nbr),
            ], limit=1)
            previously_processed = False
            previous_import_state = False
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
            if header.action_update_stock_picking():
                imported += 1
            else:
                errors += 1

        return {
            "transaction_type": "shipment_completed",
            "model": "acumatica.shipment.completed.staging",
            "created": created,
            "updated": updated,
            "imported": imported,
            "errors": errors,
            "header_ids": header_ids,
            "product_lines": product_lines,
        }

    def _process_shipment_transfer_completed_webhook(self, payload, config):
        records = self._records_from_transaction_payload(payload, config)
        if not records:
            raise UserError(_("No Shipment Transfer Completed records found in payload."))

        env = self._env()
        acumatica_config = env["acumatica.config"].sudo()._get_default_config_for_type(
            "shipment_transfer_completed"
        )
        if not acumatica_config:
            raise UserError(_("No active Acumatica config found for Shipment Transfer Completed."))

        Staging = env["acumatica.shipment.transfer.completed.staging"].sudo()
        Line = env["acumatica.shipment.transfer.completed.staging.line"].sudo()
        Picking = env["stock.picking"].sudo()
        grouped = {}
        for index, item in enumerate(records, start=1):
            shipment_nbr = self._first_value(item, "ShipmentNbr", "shipment_nbr")
            if shipment_nbr:
                grouped.setdefault(shipment_nbr, []).append((index, item))
        if not grouped:
            raise UserError(_("No valid ShipmentNbr found in payload."))

        created = updated = product_lines = imported = errors = 0
        header_ids = []
        for shipment_nbr, document_records in grouped.items():
            first_index, first_item = document_records[0]
            header_vals = self._shipment_transfer_completed_header_vals(
                first_item, first_index, acumatica_config
            )
            header = Staging.search([
                ("config_id", "=", acumatica_config.id),
                ("shipment_nbr", "=", shipment_nbr),
            ], limit=1)
            if header:
                if header.import_state in ("created", "updated"):
                    header_ids.append(header.id)
                    imported += 1
                    continue
                import_state = "updated"
                header.write(header_vals)
                header.line_ids.unlink()
                updated += 1
            else:
                import_state = "created"
                header = Staging.create(header_vals)
                created += 1

            line_vals = [
                self._shipment_transfer_completed_line_vals(item, header)
                for _, item in document_records
                if isinstance(item, dict)
            ]
            if line_vals:
                Line.create(line_vals)
                product_lines += len(line_vals)
            header_ids.append(header.id)

            picking = Picking.search([
                ("origin", "=", shipment_nbr),
                ("internal_transfer_leg", "=", "delivery"),
                ("picking_type_id.code", "=", "internal"),
                ("adt_type", "=", "Transfer Shipment"),
                ("wms_state", "=", "waiting_response"),
            ], limit=1)
            if not picking:
                header.write({
                    "import_state": "error",
                    "import_message": f"Transfer Shipment {shipment_nbr} tidak ditemukan dalam status menunggu konfirmasi.",
                })
                errors += 1
                continue

            try:
                # Use the existing WMS transfer completion flow. This confirms
                # the transfer shipment and does not create a return document.
                with env.cr.savepoint():
                    picking.action_complete_transfer_shipment()
                    header.write({
                        "import_state": import_state,
                        "import_message": "Transfer Shipment berhasil dikonfirmasi dari webhook.",
                    })
                imported += 1
            except Exception as error:
                header.write({
                    "import_state": "error",
                    "import_message": str(error),
                })
                errors += 1
                _logger.exception(
                    "Shipment Transfer Completed webhook failed for %s",
                    shipment_nbr,
                )

        return {
            "transaction_type": "shipment_transfer_completed",
            "model": "acumatica.shipment.transfer.completed.staging",
            "created": created,
            "updated": updated,
            "imported": imported,
            "errors": errors,
            "header_ids": header_ids,
            "product_lines": product_lines,
        }

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
        domain = [(document_field, "=", vals[document_field])]
        if "config_id" in Header._fields and vals.get("config_id"):
            domain.append(("config_id", "=", vals["config_id"]))
        header = Header.search(domain, limit=1)
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

    def _process_inventory_adjustment_webhook(self, payload, config):
        config_record = self._env()["acumatica.config"].sudo()._get_default_config_for_type("inventory_adjustment")
        if not config_record:
            raise UserError(_("No active Acumatica config found for transaction type: inventory_adjustment"))
        records = self._records_from_payload_keys(payload, config["records_keys"])
        if not records and isinstance(payload, dict) and payload.get("id"):
            records = [payload]
        if not records:
            raise UserError(_("No Inventory Adjustment records found in payload."))
        Staging = self._env()["acumatica.inventory.adjustment.staging"].sudo()
        ids = []
        created = updated = 0
        for item in records:
            if not isinstance(item, dict):
                continue
            details = item.get("InventoryAdjustmentGIDetails") or []
            if isinstance(details, dict):
                details = details.get("value") or []
            parent_id = str(item.get("id") or item.get("RefNbr") or "")

            for detail_index, detail in enumerate(details, start=1):
                if not isinstance(detail, dict):
                    continue
                row_number = detail.get("rowNumber") or detail_index
                external_id = str(
                    detail.get("id") or f'{parent_id or "inventory-adjustment"}:{row_number}'
                )
                reference = detail.get("RefNbr")
                if isinstance(reference, dict):
                    reference = reference.get("value")
                vals = {
                    "acumatica_id": external_id,
                    "row_number": row_number,
                    "ref_nbr": reference or False,
                    "note": detail.get("note") or False,
                    "raw_data": json.dumps(detail, ensure_ascii=False),
                    "config_id": config_record.id,
                    "sync_date": fields.Datetime.now(),
                    "import_state": "staged",
                    "import_message": False,
                }
                record = Staging.search([
                    ("acumatica_id", "=", external_id),
                    ("config_id", "=", config_record.id),
                ], limit=1)
                # Reuse the old header record for the first detail on refetch.
                if not record and detail_index == 1 and parent_id:
                    record = Staging.search([
                        ("acumatica_id", "=", parent_id),
                        ("config_id", "=", config_record.id),
                    ], limit=1)
                if record:
                    record.write(vals)
                    updated += 1
                else:
                    record = Staging.create(vals)
                    created += 1
                ids.append(record.id)
        return {"transaction_type": "inventory_adjustment", "model": "acumatica.inventory.adjustment.staging",
                "created": created, "updated": updated, "imported": 0, "errors": 0, "header_ids": ids,
                "product_lines": len(ids)}
