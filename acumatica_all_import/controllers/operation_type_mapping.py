# -*- coding: utf-8 -*-


class OperationTypeMappingMixin:
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
        operation_category=False,
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

        if document_only or target_operation_type:
            return PickingType.browse()

        if not warehouse_code:
            return PickingType.browse()

        warehouse = self._search_warehouse(warehouse_code)
        if not warehouse:
            return PickingType.browse()

        if not operation_category:
            operation_category = {
                "incoming": "receive",
                "outgoing": "delivery",
            }.get(picking_code, "internal")

        return PickingType.resolve_picking_type(
            warehouse=warehouse,
            code=picking_code,
            operation_category=operation_category,
            api_acumatica=api_acumatica,
            transaction_key=api_acumatica,
            required=False,
        )

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

    def _search_outbound_pick_picking_type(self, warehouse_code, document_only=False, api_acumatica=False):
        PickingType = self._env()["stock.picking.type"].sudo()
        target_picking_type = PickingType.resolve_document_only_picking_type(
            api_acumatica=api_acumatica,
            document_only=document_only,
            warehouse_code=warehouse_code,
        )
        if target_picking_type:
            return target_picking_type

        if document_only:
            return PickingType.browse()

        if not warehouse_code:
            return PickingType.browse()

        warehouse = self._search_warehouse(warehouse_code)
        if not warehouse:
            return PickingType.browse()

        picking_type = PickingType.resolve_picking_type(
            warehouse=warehouse,
            code="internal",
            operation_category="pick",
            api_acumatica=api_acumatica,
            transaction_key=api_acumatica,
            required=False,
        )
        if picking_type:
            return picking_type

        # Backward-compat: gunakan Pick standar warehouse bila resolver kosong,
        # tetapi tetap validasi kategorinya agar tidak berubah menjadi Delivery.
        return (warehouse.pick_type_id if warehouse.pick_type_id.operation_category == "pick" else False) or PickingType.search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", "internal"),
            ("name", "ilike", "Pick"),
        ], limit=1)

    def _search_toko_pegang_do_picking_type(self, warehouse_code):
        """Resolve the first, native Pick operation for Toko Pegang DO."""
        PickingType = self._env()["stock.picking.type"].sudo()
        warehouse = self._search_warehouse(warehouse_code)
        if not warehouse:
            return PickingType.browse()

        picking_type = warehouse.pick_type_id
        if (
            picking_type
            and picking_type.active
            and picking_type.code == "internal"
            and picking_type.operation_category == "pick"
        ):
            return picking_type

        return PickingType.search([
            ("warehouse_id", "=", warehouse.id),
            ("active", "=", True),
            ("code", "=", "internal"),
            ("operation_category", "=", "pick"),
        ], limit=1) or PickingType.search([
            ("warehouse_id", "=", warehouse.id),
            ("active", "=", True),
            ("code", "=", "internal"),
            ("name", "ilike", "Pick"),
        ], limit=1)
