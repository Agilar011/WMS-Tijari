/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { SMLX2ManyField } from "@stock/fields/stock_move_line_x2_many_field";

patch(SMLX2ManyField.prototype, {
    
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
