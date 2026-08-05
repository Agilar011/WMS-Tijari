/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ViewButton } from "@web/views/view_button/view_button";

const AUTO_SAVE_CLASS = "o_wms_auto_save_before_action";

function hasAutoSaveClass(className) {
    return (className || "").split(/\s+/).includes(AUTO_SAVE_CLASS);
}

patch(ViewButton.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    },

    async onClick(ev) {
        if (!hasAutoSaveClass(this.props.className)) {
            return super.onClick(...arguments);
        }

        if (this.props.tag === "a") {
            ev.preventDefault();
        }

        const record = this.props.record;
        if (record && (record.isNew || await record.isDirty())) {
            const saved = await record.save();
            if (!saved) {
                return;
            }
        }

        await this.orm.call(record.resModel, this.clickParams.name, [[record.resId]], {
            context: record.context,
        });
        await record.load();
    },
});
