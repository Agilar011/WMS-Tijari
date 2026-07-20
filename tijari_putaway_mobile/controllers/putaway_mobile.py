from datetime import datetime, time
from urllib.parse import quote, urlencode

import pytz

from odoo import fields, http
from odoo.tools.float_utils import float_compare
from odoo.http import request


class PutawayMobileController(http.Controller):
    DEFAULT_STATUS_FILTER = "draft"
    DEFAULT_LINE_STATUS_FILTER = "draft"
    OPERATION_FILTERS = {
        "receipt": {
            "label": "Penerimaan",
            "domain": [("picking_type_code", "=", "incoming")],
        },
        "delivery": {
            "label": "Pengiriman",
            "domain": [("picking_type_code", "=", "outgoing")],
        },
    }

    def _today_bounds(self):
        today = fields.Date.context_today(request.env.user)
        timezone = pytz.timezone(request.env.user.tz or "UTC")
        start = timezone.localize(datetime.combine(today, time.min)).astimezone(pytz.UTC)
        end = timezone.localize(datetime.combine(today, time.max)).astimezone(pytz.UTC)
        return fields.Datetime.to_string(start), fields.Datetime.to_string(end)

    def _redirect_to_login(self):
        redirect_url = request.httprequest.full_path.rstrip("?")
        return request.redirect(
            "/web/login?redirect=%s" % quote(redirect_url, safe="")
        )

    def _ensure_logged_in(self):
        return bool(request.session.uid)

    def _putaway_domain(self, operation=None):
        start, end = self._today_bounds()
        domain = [
            ("scheduled_date", ">=", start),
            ("scheduled_date", "<=", end),
            ("state", "!=", "cancel"),
            ("move_line_ids", "!=", False),
        ]
        domain += self.OPERATION_FILTERS.get(operation, {}).get("domain", [])
        return domain

    def _operation_kind(self, picking):
        if picking.picking_type_code == "incoming":
            return "receipt"
        if picking.picking_type_code == "outgoing":
            return "delivery"

        operation_category = picking.picking_type_id.operation_category
        if operation_category in ("receive", "put"):
            return "receipt"
        if operation_category == "delivery":
            return "delivery"
        return "receipt"

    def _operation_label(self, operation):
        return self.OPERATION_FILTERS.get(operation, {}).get("label", "Penerimaan")

    def _mobile_url(self, operation, status=None, query=None):
        params = {"operation": operation}
        if status and status != self.DEFAULT_STATUS_FILTER:
            params["status"] = status
        if query:
            params["q"] = query
        return "/putaway/mobile?%s" % urlencode(params)

    def _operation_tabs(self, active_operation, status=None, query=None):
        return [
            {
                "key": key,
                "label": config["label"],
                "active": key == active_operation,
                "url": self._mobile_url(key, status, query),
            }
            for key, config in self.OPERATION_FILTERS.items()
        ]

    def _validation_location(self, line):
        if self._operation_kind(line.picking_id) == "delivery":
            return line.location_id
        return line.location_dest_id

    def _picking_progress(self, picking):
        total_lines = len(picking.move_line_ids)
        matched_lines = len(
            picking.move_line_ids.filtered(lambda line: line.matching == "match")
        )
        return total_lines, matched_lines, bool(total_lines and matched_lines == total_lines)

    def _picking_status_key(self, picking):
        total_lines, matched_lines, is_putaway_valid = self._picking_progress(picking)
        if picking.state == "done":
            return "done"
        if is_putaway_valid:
            return "valid"
        if matched_lines:
            return "partial"
        return "todo"

    def _picking_status_label(self, picking, state_label):
        status_key = self._picking_status_key(picking)
        if status_key in ("valid", "done"):
            return "Done"
        return "Draft"

    def _sort_pickings(self, pickings):
        priority = {"todo": 0, "partial": 1, "valid": 2, "done": 3}
        return pickings.sorted(
            key=lambda picking: (
                priority.get(self._picking_status_key(picking), 9),
                picking.scheduled_date or fields.Datetime.now(),
                picking.id,
            )
        )

    def _search_matches(self, picking, query):
        if not query:
            return True

        needle = query.strip().lower()
        haystack = [
            picking.origin,
            picking.name,
            picking.partner_id.display_name,
            picking.picking_type_id.display_name,
        ]
        haystack += [
            line.product_id.default_code
            or line.product_id.barcode
            or line.product_id.display_name
            for line in picking.move_line_ids
        ]
        haystack += [
            line.lot_id.name or line.lot_name
            for line in picking.move_line_ids
        ]
        return any(needle in (value or "").lower() for value in haystack)

    def _filter_pickings(self, pickings, status, query=None):
        filtered = pickings.filtered(lambda picking: self._search_matches(picking, query))
        if status == "all":
            return filtered
        if status == "draft":
            return filtered.filtered(lambda picking: self._picking_status_key(picking) in ("todo", "partial"))
        if status == "done":
            return filtered.filtered(lambda picking: self._picking_status_key(picking) in ("valid", "done"))
        return filtered

    def _summary(self, pickings):
        summary = {"todo": 0, "partial": 0, "valid": 0, "done": 0}
        for picking in pickings:
            summary[self._picking_status_key(picking)] += 1
        summary["draft"] = summary["todo"] + summary["partial"]
        summary["done"] = summary["valid"] + summary["done"]
        summary["all"] = len(pickings)
        return summary

    def _status_filters(self, operation, active_status, summary, query=None):
        filters = [
            ("draft", "Draft", summary["draft"]),
            ("done", "Done", summary["done"]),
            ("all", "All", summary["all"]),
        ]
        return [
            {
                "key": key,
                "label": "%s %s" % (label, count),
                "active": key == active_status,
                "url": self._mobile_url(operation, key, query),
            }
            for key, label, count in filters
        ]

    def _line_status_key(self, line_values):
        if line_values["matching"] == "match":
            return "valid"
        if (
            line_values["location_ok"]
            or line_values["lot_ok"]
            or line_values["quantity_ok"]
        ):
            return "partial"
        return "todo"

    def _line_status_label(self, line_values):
        status_key = self._line_status_key(line_values)
        if status_key == "valid":
            return "Done"
        return "Draft"

    def _line_search_matches(self, line_values, query):
        if not query:
            return True

        needle = query.strip().lower()
        haystack = [
            line_values["product"],
            line_values["product_code"],
            line_values["product_label"],
            line_values["lot"],
            line_values["location"],
            line_values["location_code"],
            line_values["confirmation_location_code"],
            line_values["confirmation_lot_code"],
        ]
        return any(needle in (value or "").lower() for value in haystack)

    def _sort_line_values(self, line_values):
        priority = {"todo": 0, "partial": 1, "valid": 2}
        return sorted(
            line_values,
            key=lambda values: (
                priority.get(values["status_key"], 9),
                values["product_label"] or "",
                values["lot"] or "",
                values["id"],
            ),
        )

    def _filter_line_values(self, line_values, status, query=None):
        filtered = [
            values
            for values in line_values
            if self._line_search_matches(values, query)
        ]
        if status == "all":
            return filtered
        if status == "draft":
            return [
                values
                for values in filtered
                if values["status_key"] in ("todo", "partial")
            ]
        if status == "done":
            return [
                values
                for values in filtered
                if values["status_key"] == "valid"
            ]
        return [
            values for values in filtered
        ]

    def _line_summary(self, line_values):
        summary = {"todo": 0, "partial": 0, "valid": 0}
        for values in line_values:
            summary[values["status_key"]] += 1
        summary["draft"] = summary["todo"] + summary["partial"]
        summary["done"] = summary["valid"]
        summary["all"] = len(line_values)
        return summary

    def _line_status_filters(self, picking_id, active_status, summary, query=None):
        filters = [
            ("draft", "Draft", summary["draft"]),
            ("done", "Done", summary["done"]),
            ("all", "All", summary["all"]),
        ]
        return [
            {
                "key": key,
                "label": "%s %s" % (label, count),
                "active": key == active_status,
                "url": self._detail_url(picking_id, key, query),
            }
            for key, label, count in filters
        ]

    def _detail_url(self, picking_id, line_status=None, query=None):
        params = {}
        if line_status and line_status != self.DEFAULT_LINE_STATUS_FILTER:
            params["line_status"] = line_status
        if query:
            params["q"] = query
        query_string = urlencode(params)
        url = "/putaway/mobile/picking/%s" % picking_id
        return "%s?%s" % (url, query_string) if query_string else url

    def _prepare_picking_values(self, picking):
        operation = self._operation_kind(picking)
        state_label = dict(picking._fields["state"].selection).get(
            picking.state,
            picking.state,
        )
        move_lines = picking.move_line_ids.sorted(
            key=lambda line: (
                line.product_id.display_name or "",
                line.lot_id.name or line.lot_name or "",
                line.id,
            )
        )
        total_lines, matched_lines, is_putaway_valid = self._picking_progress(picking)
        status_label = self._picking_status_label(picking, state_label)

        return {
            "id": picking.id,
            "name": picking.name,
            "display_name": picking.origin or picking.name,
            "origin": picking.origin,
            "partner": picking.partner_id.display_name,
            "operation": picking.picking_type_id.display_name,
            "operation_key": operation,
            "operation_label": self._operation_label(operation),
            "scheduled_date": picking.scheduled_date,
            "state": picking.state,
            "state_label": state_label,
            "status_label": status_label,
            "is_done": picking.state == "done",
            "is_putaway_valid": is_putaway_valid,
            "total_lines": total_lines,
            "matched_lines": matched_lines,
        }

    def _prepare_move_line_values(self, line):
        operation = self._operation_kind(line.picking_id)
        expected_location = self._validation_location(line)
        expected_lot = self._expected_lot_code(line)
        confirmation_lot_code = self._confirmation_lot_code(line)
        quantity_ok = self._quantity_matches(
            line.confirmation_quantity,
            line.quantity,
            line.product_uom_id,
        )
        values = {
            "id": line.id,
            "product": line.product_id.display_name,
            "product_code": line.product_id.default_code or line.product_id.barcode,
            "product_label": (
                line.product_id.default_code
                or line.product_id.barcode
                or line.product_id.display_name
            ),
            "quantity": line.quantity,
            "confirmation_quantity": line.confirmation_quantity or 0,
            "uom": line.product_uom_id.name,
            "lot": expected_lot,
            "location": expected_location.display_name,
            "location_code": expected_location.unique_code,
            "location_label": "Source Location" if operation == "delivery" else "Destination Location",
            "confirmation_location_code": line.confirmation_location_code,
            "confirmation_lot_code": confirmation_lot_code,
            "location_ok": self._scan_matches(
                line.confirmation_location_code,
                self._location_codes(expected_location),
            ),
            "lot_ok": self._scan_matches(
                confirmation_lot_code,
                self._lot_codes(line),
            ),
            "quantity_ok": quantity_ok,
            "matching": line.matching,
        }
        values["status_key"] = self._line_status_key(values)
        values["status_label"] = self._line_status_label(values)
        return values

    def _location_codes(self, location):
        return [
            location.unique_code if "unique_code" in location._fields else False,
            location.barcode if "barcode" in location._fields else False,
            location.name,
            location.complete_name,
            location.display_name,
        ]

    def _lot_codes(self, line):
        expected_lot = self._expected_lot_code(line)
        return [
            expected_lot,
        ]

    def _expected_lot_code(self, line):
        return line.lot_id.name or line.lot_name or "0"

    def _confirmation_lot_code(self, line):
        return line.confirmation_lot_code or "0" if self._expected_lot_code(line) == "0" else line.confirmation_lot_code

    def _scan_matches(self, scanned_code, expected_codes):
        scanned = (scanned_code or "").strip().lower()
        expected = {
            (code or "").strip().lower()
            for code in expected_codes
            if code
        }
        return bool(scanned and scanned in expected)

    def _quantity_matches(self, confirmation_quantity, expected_quantity, uom):
        if not confirmation_quantity:
            return False
        precision = uom.rounding if uom else 0.01
        return float_compare(
            confirmation_quantity,
            expected_quantity,
            precision_rounding=precision,
        ) == 0

    @http.route("/putaway/mobile", type="http", auth="public")
    def putaway_today(self, **kwargs):
        if not self._ensure_logged_in():
            return self._redirect_to_login()

        operation = kwargs.get("operation") or "receipt"
        if operation not in self.OPERATION_FILTERS:
            operation = "receipt"
        status = kwargs.get("status") or self.DEFAULT_STATUS_FILTER
        if status not in ("draft", "done", "all"):
            status = self.DEFAULT_STATUS_FILTER
        query = (kwargs.get("q") or "").strip()

        pickings = request.env["stock.picking"].search(
            self._putaway_domain(operation),
            order="scheduled_date asc, id asc",
        )
        pickings = self._sort_pickings(pickings)
        searched_pickings = pickings.filtered(
            lambda picking: self._search_matches(picking, query)
        )
        summary = self._summary(searched_pickings)
        filtered_pickings = self._filter_pickings(searched_pickings, status)
        values = {
            "operation": operation,
            "operation_label": self._operation_label(operation),
            "operation_tabs": self._operation_tabs(operation, status, query),
            "status": status,
            "status_filters": self._status_filters(operation, status, summary, query),
            "query": query,
            "summary": summary,
            "pickings": [
                self._prepare_picking_values(picking)
                for picking in filtered_pickings
            ],
        }
        return request.render("tijari_putaway_mobile.putaway_today", values)

    @http.route(
        "/putaway/mobile/picking/<int:picking_id>",
        type="http",
        auth="public",
    )
    def putaway_detail(self, picking_id, **kwargs):
        if not self._ensure_logged_in():
            return self._redirect_to_login()

        picking = request.env["stock.picking"].browse(picking_id).exists()
        if not picking:
            return request.not_found()

        line_status = kwargs.get("line_status") or self.DEFAULT_LINE_STATUS_FILTER
        if line_status not in ("draft", "done", "all"):
            line_status = self.DEFAULT_LINE_STATUS_FILTER
        query = (kwargs.get("q") or "").strip()

        operation = self._operation_kind(picking)
        next_pickings = self._sort_pickings(
            request.env["stock.picking"].search(self._putaway_domain(operation))
        ).filtered(
            lambda candidate: candidate.id != picking.id
            and self._picking_status_key(candidate) in ("todo", "partial")
        )
        line_values = self._sort_line_values([
            self._prepare_move_line_values(line)
            for line in picking.move_line_ids
        ])
        searched_lines = [
            values
            for values in line_values
            if self._line_search_matches(values, query)
        ]
        line_summary = self._line_summary(searched_lines)

        values = {
            "picking": self._prepare_picking_values(picking),
            "next_picking": (
                self._prepare_picking_values(next_pickings[0])
                if next_pickings
                else False
            ),
            "line_status": line_status,
            "line_query": query,
            "line_status_filters": self._line_status_filters(
                picking.id,
                line_status,
                line_summary,
                query,
            ),
            "line_summary": line_summary,
            "move_lines": self._filter_line_values(line_values, line_status, query),
        }
        return request.render("tijari_putaway_mobile.putaway_detail", values)

    @http.route(
        "/putaway/mobile/scan",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def putaway_scan(self, **kwargs):
        payload = request.httprequest.get_json(silent=True) or {}
        line = request.env["stock.move.line"].browse(
            int(payload.get("move_line_id") or 0)
        ).exists()
        scan_target = payload.get("target")
        scanned_code = (payload.get("code") or "").strip()

        if not line:
            return request.make_json_response(
                {"ok": False, "message": "Move line tidak ditemukan."},
                status=404,
            )

        if scan_target not in ("location", "lot", "quantity") or not scanned_code:
            return request.make_json_response(
                {"ok": False, "message": "Target scan atau kode scan tidak valid."},
                status=400,
            )

        values = {}
        if scan_target == "location":
            expected_location = self._validation_location(line)
            values["confirmation_location_code"] = scanned_code
            matched = self._scan_matches(scanned_code, self._location_codes(expected_location))
            if matched:
                values["matching_loc_dest_id"] = expected_location.id
        elif scan_target == "lot":
            values["confirmation_lot_code"] = scanned_code
            matched = self._scan_matches(scanned_code, self._lot_codes(line))
            if matched and line.lot_id:
                values["matching_lot_id"] = line.lot_id.id
        else:
            try:
                confirmation_quantity = float(scanned_code)
            except ValueError:
                return request.make_json_response(
                    {"ok": False, "message": "Quantity harus berupa angka."},
                    status=400,
                )
            values["confirmation_quantity"] = confirmation_quantity
            matched = self._quantity_matches(
                confirmation_quantity,
                line.quantity,
                line.product_uom_id,
            )

        line.write(values)

        location_ok = self._scan_matches(
            line.confirmation_location_code,
            self._location_codes(self._validation_location(line)),
        )
        lot_ok = self._scan_matches(
            self._confirmation_lot_code(line),
            self._lot_codes(line),
        )
        quantity_ok = self._quantity_matches(
            line.confirmation_quantity,
            line.quantity,
            line.product_uom_id,
        )
        line.write({
            "matching": "match" if location_ok and lot_ok and quantity_ok else "not_match",
        })

        return request.make_json_response({
            "ok": True,
            "matched": matched,
            "location_ok": location_ok,
            "lot_ok": lot_ok,
            "quantity_ok": quantity_ok,
            "matching": line.matching,
            "message": "Validasi cocok." if matched else "Validasi belum cocok dengan data move line.",
        })
