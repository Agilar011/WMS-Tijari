/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    Many2OneField,
    many2OneField,
} from "@web/views/fields/many2one/many2one_field";


export class LocationShortMany2OneField extends Many2OneField {
    static template = "tijari_wms_18.LocationShortMany2OneField";

    get displayName() {
        if (!this.value || !this.value[1]) {
            return "";
        }

        const fullName = this.value[1];

        if (!fullName.includes("/")) {
            return fullName;
        }

        const parts = fullName
            .split("/")
            .map(part => part.trim())
            .filter(Boolean);

        if (parts.length >= 2) {
            return `${parts[0]}/${parts[parts.length - 1]}`;
        }

        return fullName;
    }
}


export const locationShortMany2OneField = {
    ...many2OneField,
    component: LocationShortMany2OneField,
};


registry
    .category("fields")
    .add("location_short_many2one", locationShortMany2OneField);