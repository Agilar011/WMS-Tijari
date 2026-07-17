/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { onMounted, onPatched } from "@odoo/owl";

const AUTO_LAYOUT_CLASS = "o_list_table_auto_layout";

function hasAutoLayoutClass(className) {
    return (className || "").split(/\s+/).includes(AUTO_LAYOUT_CLASS);
}

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        const applyAutoTableLayout = () => {
            if (!hasAutoLayoutClass(this.props.archInfo.className)) {
                return;
            }

            const table = this.tableRef.el;

            if (!table) {
                return;
            }

            table.classList.add(AUTO_LAYOUT_CLASS);
            table.style.tableLayout = "auto";
            table.style.width = "";
            table.parentElement.style.width = "";
            table.querySelectorAll("thead th").forEach((header) => {
                header.style.width = "";
            });
        };

        onMounted(applyAutoTableLayout);
        onPatched(applyAutoTableLayout);
    },
});
