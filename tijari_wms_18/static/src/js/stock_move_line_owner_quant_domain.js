/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { SMLX2ManyField } from "@stock/fields/stock_move_line_x2_many_field";

patch(SMLX2ManyField.prototype, {

    async selectRecord(res_ids) {
        const pickingTypeName = this.props.record.data.picking_type_name || "";
        if (pickingTypeName !== "Pack") {
            return super.selectRecord(...arguments);
        }

        const move = this.props.record;
        const moveData = move.data;
        const fieldContext = this.props.context || {};
        const addContext = this.pendingLineContext || {};
        const getId = (value) => (Array.isArray(value) ? value[0] : value) || false;
        const demand =
            moveData.product_uom_qty -
            moveData.move_line_ids.records
                .map((line) => line.data.quantity)
                .reduce((sum, quantity) => sum + quantity, 0);
        const context = {
            ...fieldContext,
            ...addContext,
            default_quant_id: res_ids[0],
        };
        if (demand <= 0) {
            context.default_quantity = 0;
        } else if (this.dirtyQuantsData.has(res_ids[0])) {
            context.default_quantity = Math.min(
                this.dirtyQuantsData.get(res_ids[0]).available_quantity,
                demand
            );
        }
        const record = await this.list.addNewRecord({ context });
        const destinationId = this.pendingLineDestinationId;
        if (destinationId) {
            await record.update({ location_dest_id: this.pendingLineDestination });
        }
        record.dirty = true;

        // Persist the selected quant line before the user opens another line.
        // Otherwise a later Save & Confirm can reload the move from the server
        // and discard this still-virtual x2many record.
        await move.save();
    },
    
    async onAdd({ context, editable } = {}) {
        
        const pickingTypeName = this.props.record.data.picking_type_name || "";
        const isPickOperation = ["Pick", "Pick Internal", "Pick Components"].includes(
            pickingTypeName
        );
        const isPackOperation = ["Pack"].includes(
            pickingTypeName
        );
        const isManufacturing = !!this.props.context.active_mo_id;

        if (!this.props.record.data.show_quant &&
            !isPickOperation &&
            !isManufacturing &&
            !isPackOperation) {
            return super.onAdd(...arguments);
        }

        if (isPackOperation) {
            const move = this.props.record;
            const moveData = move.data;
            const getId = (value) => (Array.isArray(value) ? value[0] : value) || false;
            const moveId = move.resId || getId(moveData.id);
            const [parentMove] = moveId
                ? await this.orm.read(
                    "stock.move",
                    [moveId],
                    ["picking_id", "product_id", "location_id", "location_dest_id", "company_id"]
                )
                : [];
            const pickingId =
                getId(moveData.picking_id) ||
                getId(parentMove?.picking_id) ||
                getId(context?.default_picking_id);
            let destinationId =
                getId(moveData.location_dest_id) ||
                getId(parentMove?.location_dest_id) ||
                getId(context?.default_location_dest_id) ||
                getId(this.props.context?.default_location_dest_id);
            if (!destinationId && pickingId) {
                const [picking] = await this.orm.read("stock.picking", [pickingId], ["location_dest_id"]);
                destinationId = getId(picking?.location_dest_id);
            }
            let destination = false;
            if (destinationId) {
                const [location] = await this.orm.read(
                    "stock.location",
                    [destinationId],
                    ["display_name", "complete_name", "name"]
                );
                const displayName = location?.display_name || location?.complete_name || location?.name;
                destination = [destinationId, displayName];
            }
            context = {
                ...this.props.context,
                ...context,
                default_move_id: moveId || context?.default_move_id,
                default_picking_id: pickingId,
                default_product_id:
                    getId(moveData.product_id) || getId(parentMove?.product_id) || context?.default_product_id,
                default_location_id:
                    getId(moveData.location_id) || getId(parentMove?.location_id) || context?.default_location_id,
                default_location_dest_id: destinationId,
                default_company_id:
                    getId(moveData.company_id) || getId(parentMove?.company_id) || context?.default_company_id,
                active_picking_id: pickingId || context?.active_picking_id,
            };
            this.pendingLineContext = context;
            this.pendingLineDestinationId = destinationId || false;
            this.pendingLineDestination = destination;
        }

        await this.updateDirtyQuantsData();
        context = {
            ...context,
            single_product: true,
            list_view_ref: "stock.view_stock_quant_tree_simple",
            search_default_on_hand: true,
            search_default_in_stock: true,
        };

        const productName = this.props.record.data.product_id[1];
        const title = _t("Add line: %s", productName);
        let domain = [
            ["product_id", "=", this.props.record.data.product_id[0]],
            ["location_id", "child_of", this.props.context.default_location_id],
        ];

        const ownerId = this.props.record.data.owner_id?.[0];
        if (this.props.record.data.adt_type === "Toko Pegang DO" && ownerId) {
            context.search_default_owner_id = ownerId;
        }

        if (this.dirtyQuantsData.size) {
            const notFullyUsed = [];
            const fullyUsed = [];
            for (const [quantId, quantData] of this.dirtyQuantsData.entries()) {
                if (quantData.available_quantity > 0) {
                    notFullyUsed.push(quantId);
                } else {
                    fullyUsed.push(quantId);
                }
            }
            if (fullyUsed.length) {
                domain = Domain.and([domain, [["id", "not in", fullyUsed]]]).toList();
            }
            if (notFullyUsed.length) {
                domain = Domain.or([domain, [["id", "in", notFullyUsed]]]).toList();
            }
        }

        return this.selectCreate({ domain, context, title });
    },
    

});
