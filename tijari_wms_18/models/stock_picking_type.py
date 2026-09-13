# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    operation_category = fields.Selection([
        ('pick', 'Pick'),
        ('put', 'Put'),
        ('pack', 'Pack'),
        ('internal', 'Internal Transfer'),
        ('receive', 'Receive'),
        ('delivery', 'Delivery'),
        ('others', 'Others')
    ], string='Operation Category', required=False, default='others')

    is_default_api = fields.Boolean(string="Default Picking Type For API")
    is_api_config = fields.Boolean(string="Picking Type API Config")
    is_document_only_api = fields.Boolean(string="Document Only API")

    @api.model
    def _normalize_document_only_operation(self, value):
        if not value:
            return False
        normalized = str(value).strip().lower().replace('-', '_').replace(' ', '_')
        aliases = {
            'direct_receipt': 'direct_receipt',
            'receipt': 'direct_receipt',
            'receive': 'direct_receipt',
            'incoming': 'direct_receipt',
            'direct_delivery_order': 'direct_delivery_order',
            'delivery': 'direct_delivery_order',
            'delivery_order': 'direct_delivery_order',
            'outgoing': 'direct_delivery_order',
        }
        return aliases.get(normalized)

    @api.model
    def _normalize_api_acumatica(self, value):
        if not value:
            return False
        return str(value).strip().lower().replace('-', '_').replace(' ', '_')

    @api.model
    def _get_document_only_operation_by_api(self):
        return {
            'po_receipt': 'direct_receipt',
            'receipt_change_item': 'direct_receipt',
            'inventory_received': 'direct_receipt',
            'inventory_receive': 'direct_receipt',
            'receipt_toko_pegang_do': 'direct_receipt',
            'transfer_in': 'direct_receipt',
            'so_transfer': 'direct_receipt',
            'sotr': 'direct_receipt',
            'vendor_return': 'direct_delivery_order',
            'so_shipment': 'direct_delivery_order',
            'so_shipment_toko_pegang_do': 'direct_delivery_order',
            'so_shipment_co': 'direct_delivery_order',
            'transfer_shipment': 'direct_delivery_order',
            'issue_change_item': 'direct_delivery_order',
            'inventory_issue': 'direct_delivery_order',
            'issue_change_item_discontinue': 'direct_delivery_order',
            'issue_po_return': 'direct_delivery_order',
            'po_return': 'direct_delivery_order',
            'transfer_one_step': 'direct_delivery_order',
            'transfer_two_step': 'direct_delivery_order',
            'credit_memo_consignment': 'direct_delivery_order',
            'invoice_consignment': 'direct_delivery_order',
        }

    @api.model
    def _get_document_only_picking_type(self, operation, building_id=False, warehouse_code=False, required=True):
        operation = self._normalize_document_only_operation(operation)
        operation_vals = {
            'direct_receipt': ('Direct Receipt', 'DRC'),
            'direct_delivery_order': ('Direct Delivery Order', 'DDO'),
        }
        if operation not in operation_vals:
            if required:
                raise UserError(_("Unsupported document only operation: %s") % operation)
            return self.browse()

        name, _sequence_code = operation_vals[operation]
        warehouse = self.env['stock.warehouse']
        building_id = building_id or warehouse_code
        if building_id:
            warehouse = self._adt_find_warehouse(building_id)
        warehouse_domain = [('warehouse_id', '=', warehouse.id)] if warehouse else []

        picking_type = self.sudo().search(
            [('name', '=', name), ('is_document_only_api', '=', True)] + warehouse_domain,
            limit=1,
        )
        if not picking_type:
            picking_type = self.sudo().search(
                [('name', '=', name)] + warehouse_domain,
                limit=1,
            )
        if picking_type and not picking_type.is_document_only_api:
            picking_type.write({
                'is_document_only_api': True,
                'is_api_config': True,
            })
        if not picking_type and warehouse:
            picking_type = self.sudo().search([
                ('name', '=', name),
            ], limit=1)
        if not picking_type and required:
            raise UserError(_("No document only picking type configured for %s") % name)
        return picking_type

    @api.model
    def resolve_document_only_picking_type(
        self,
        target_picking_type_id=False,
        target_operation_type=False,
        api_acumatica=False,
        document_only=False,
        building_id=False,
        warehouse_code=False,
        required=False,
    ):
        if target_picking_type_id:
            picking_type = self.sudo().browse(int(target_picking_type_id)).exists()
            if picking_type:
                return picking_type
            if required:
                raise UserError(_("Target picking type not found: %s") % target_picking_type_id)

        operation = self._normalize_document_only_operation(target_operation_type)
        if not operation and document_only:
            operation = self._get_document_only_operation_by_api().get(
                self._normalize_api_acumatica(api_acumatica)
            )
        if operation:
            return self._get_document_only_picking_type(
                operation,
                building_id=building_id or warehouse_code,
                required=required,
            )
        if required:
            raise UserError(_("Document only operation type is not provided"))
        return self.browse()

    @api.model
    def _adt_code_for_category(self, operation_category):
        return {
            'receive': 'incoming',
            'delivery': 'outgoing',
            'pick': 'internal',
            'pack': 'internal',
            'internal': 'internal',
        }.get(operation_category, 'internal')

    @api.model
    def _adt_category_for_code(self, code):
        return {
            'incoming': 'receive',
            'outgoing': 'delivery',
        }.get(code, 'internal')

    @api.model
    def _adt_preferred_warehouse_picking_type(self, warehouse, code, operation_category):
        """Return the warehouse-owned operation type for a code/category pair."""
        field_by_rule = {
            ('incoming', 'receive'): 'in_type_id',
            ('internal', 'pick'): 'pick_type_id',
            ('internal', 'pack'): 'pack_type_id',
            ('outgoing', 'delivery'): 'out_type_id',
            ('internal', 'internal'): 'adt_transfer_internal_type_id',
            ('internal', 'receive'): 'adt_receipt_internal_type_id',
        }
        field_name = field_by_rule.get((code, operation_category))
        picking_type = getattr(warehouse, field_name, False) if field_name else False
        if not picking_type or not picking_type.active:
            return self.browse()
        if picking_type.code != code or picking_type.operation_category != operation_category:
            return self.browse()
        return picking_type

    @api.model
    def _adt_find_warehouse(self, building_id):
        """Cari stock.warehouse berdasarkan BuildingID Acumatica.

        WarehouseID seperti ``WH33-PD`` adalah lokasi Acumatica, bukan
        warehouse pemilik picking type. Picking type harus di-resolve dari
        BuildingID, misalnya ``WH33``. Kalau yang datang kode lokasi,
        terjemahkan ke building-nya lewat mapping ``stock.location.acumatica``.
        """
        building_id = str(building_id or '').strip()
        Warehouse = self.env['stock.warehouse']
        if not building_id:
            return Warehouse.browse()
        warehouse = Warehouse.search([
            ('code', '=', building_id),
        ], limit=1)
        if warehouse:
            return warehouse
        mapping = self.env['stock.location.acumatica'].search([
            ('code', '=', building_id),
            ('is_active', '=', True),
            ('odoo_building_id', '!=', False),
        ], limit=1)
        return mapping.odoo_building_id

    @api.model
    def _adt_resolve_label(self, transaction_key, warehouse_label, code, operation_category):
        return (
            'transaction=%s warehouse=%s code=%s operation_category=%s'
            % (transaction_key or '-', warehouse_label or '-', code or '-', operation_category or '-')
        )

    @api.model
    def resolve_picking_type(
        self,
        building_id=False,
        warehouse_code=False,
        warehouse=False,
        code=False,
        operation_category=False,
        api_acumatica=False,
        transaction_key=False,
        document_only=False,
        target_picking_type_id=False,
        target_operation_type=False,
        required=True,
    ):
        """Resolver terpusat untuk stock.picking.type (WMS/Acumatica).

        Urutan pencarian:
          1. target_picking_type_id (divalidasi warehouse bila disediakan);
          2. document-only (is_document_only_api=True + nama exact per warehouse);
          3. pasangan code + operation_category dari pemetaan transaksi;
          4. search [building_id, code, operation_category];
          5. hasil > 1 -> raise error yang menyebut warehouse/code/category/
             transaction type (TIDAK memakai limit=1 secara diam-diam);
          6. tidak ditemukan -> raise error konfigurasi.

        Saat required=False resolver TIDAK melempar dan mengembalikan recordset
        kosong. Ini dipakai di flow import batch (fetch staging & webhook) supaya
        error picking type tidak menghentikan import; error akan dicatat sebagai
        import_message pada baris staging yang bersangkutan.
        """
        PickingType = self
        transaction_key = transaction_key or api_acumatica or ''

        # 1) Explicit target picking type
        if target_picking_type_id:
            picking_type = PickingType.browse(int(target_picking_type_id)).exists()
            if picking_type:
                if warehouse and picking_type.warehouse_id and picking_type.warehouse_id != warehouse:
                    if required:
                        raise UserError(_(
                            "Picking type %s bukan milik warehouse %s (transaction %s)."
                        ) % (picking_type.display_name, warehouse.display_name, transaction_key))
                    return PickingType.browse()
                return picking_type
            if required:
                raise UserError(_("Target picking type not found: %s") % target_picking_type_id)
            return PickingType.browse()

        building_id = building_id or warehouse_code
        if not warehouse and building_id:
            warehouse = self._adt_find_warehouse(building_id)

        # 2) Document-only operation type
        if document_only or target_operation_type:
            picking_type = self.resolve_document_only_picking_type(
                target_picking_type_id=target_picking_type_id,
                target_operation_type=target_operation_type,
                api_acumatica=api_acumatica,
                document_only=bool(document_only or target_operation_type),
                building_id=warehouse.code if warehouse else building_id,
                required=required,
            )
            if picking_type:
                return picking_type
            return picking_type

        # 3 & 4) Search dengan pasangan code + operation_category
        if not warehouse:
            label = self._adt_resolve_label(transaction_key, building_id, code, operation_category)
            if required:
                raise UserError(_("Warehouse tidak ditemukan untuk %s. Cek konfigurasi mapping warehouse.") % label)
            return PickingType.browse()

        if not code:
            code = self._adt_code_for_category(operation_category)
        if not operation_category:
            operation_category = self._adt_category_for_code(code)

        search_domain = [
            ('warehouse_id', '=', warehouse.id),
            ('active', '=', True),
        ]
        if code:
            search_domain.append(('code', '=', code))
        if operation_category:
            search_domain.append(('operation_category', '=', operation_category))

        candidates = PickingType.search(search_domain)

        # Prefer the explicit warehouse pointer when it matches the rule. This
        # prevents ambiguity between the warehouse's native Receipt/Pick/
        # Delivery type and other operation types with the same code/category.
        preferred = self._adt_preferred_warehouse_picking_type(
            warehouse, code, operation_category
        )
        if preferred and (document_only or not preferred.is_document_only_api):
            return preferred

        # Search is intentionally based only on building + code + category.
        # is_api_config is a UI/configuration marker, not a selector.
        if not candidates:
            candidates = PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('active', '=', True),
                ('code', '=', code),
                ('operation_category', '=', operation_category),
            ])
        if not candidates:
            # Data lama yang belum mengisi operation_category: hanya dipakai bila
            # kombinasi warehouse+code menghasilkan tepat satu operation type.
            candidates = PickingType.search([
                ('warehouse_id', '=', warehouse.id),
                ('active', '=', True),
                ('code', '=', code),
            ])

        # Kecualikan operation type document-only untuk transaksi normal.
        if not document_only:
            candidates = candidates.filtered(lambda pt: not pt.is_document_only_api)

        if len(candidates) > 1:
            label = self._adt_resolve_label(
                transaction_key, warehouse.display_name, code, operation_category
            )
            detail = ', '.join(
                '%s (id=%s)' % (candidate.display_name, candidate.id)
                for candidate in candidates
            )
            if required:
                raise UserError(_(
                    "Konfigurasi picking type ambigu untuk %s. "
                    "Ditemukan lebih dari satu operation type: %s. "
                    "Perbaiki konfigurasi agar hanya satu operation type aktif "
                "dengan (building_id, code, operation_category) yang sama."
                ) % (label, detail))
            return PickingType.browse()

        if not candidates:
            label = self._adt_resolve_label(
                transaction_key, warehouse.display_name, code, operation_category
            )
            if required:
                raise UserError(_(
                    "Operation type tidak ditemukan untuk %s. "
                    "Pastikan building, code, dan operation category pada "
                    "operation type sudah sesuai."
                ) % label)
            return PickingType.browse()

        return candidates

    @api.model
    def resolve_picking_type_from_operation(
        self,
        building_id=False,
        warehouse_code=False,
        warehouse=False,
        operation_category=False,
        api_acumatica=False,
        transaction_key=False,
        document_only=False,
        target_picking_type_id=False,
        target_operation_type=False,
        required=True,
    ):
        """Varian resolver yang menerima operation_category dan menurunkan code."""
        code = self._adt_code_for_category(operation_category)
        return self.resolve_picking_type(
            building_id=building_id,
            warehouse_code=warehouse_code,
            warehouse=warehouse,
            code=code,
            operation_category=operation_category,
            api_acumatica=api_acumatica,
            transaction_key=transaction_key,
            document_only=document_only,
            target_picking_type_id=target_picking_type_id,
            target_operation_type=target_operation_type,
            required=required,
        )

    # def get_action_picking_tree_draft(self):
    #     self.ensure_one()

    #     action = self._get_action("stock.stock_picking_action_picking_type")

    #     ctx = action.get("context", {})
    #     if isinstance(ctx, str):
    #         from odoo.tools.safe_eval import safe_eval
    #         ctx = safe_eval(ctx)

    #     ctx.update({
    #         "search_default_draft": 1,
    #     })

    #     action["context"] = ctx

    #     return action
