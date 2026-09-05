/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { SpreadsheetDashboardAction } from "@spreadsheet_dashboard/bundle/dashboard_action/dashboard_action";

patch(SpreadsheetDashboardAction.prototype, {
    getDashboardGroups() {
        const groups = super.getDashboardGroups(...arguments);
        const params = this.props.action.params || this.props.action.context?.params || {};
        if (!params.api_data_hub_only) {
            if (!params.inventory_dashboard_only) {
                return groups;
            }
            return groups.filter((group) => group.name === "Inventory Operations");
        }
        return groups.filter((group) => group.name === "API Data Hub");
    },
});
