/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    Many2OneField,
    many2OneField,
} from "@web/views/fields/many2one/many2one_field";

export class PackageLevelAutoOpenField extends Many2OneField {
    setup() {
        super.setup();

        this.lastOpenedPackageLevelId = null;
    }

    async onWillUpdateProps(nextProps) {
        await super.onWillUpdateProps?.(nextProps);

        const packageLevel =
            nextProps.record.data.filtered_package_level_id;

        const packageLevelId =
            Array.isArray(packageLevel)
                ? packageLevel[0]
                : packageLevel;

        if (
            packageLevelId &&
            packageLevelId !== this.lastOpenedPackageLevelId
        ) {
            this.lastOpenedPackageLevelId = packageLevelId;

            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "stock.package_level",
                res_id: packageLevelId,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }
}

export const packageLevelAutoOpenField = {
    ...many2OneField,
    component: PackageLevelAutoOpenField,
};

registry
    .category("fields")
    .add(
        "package_level_auto_open",
        packageLevelAutoOpenField
    );