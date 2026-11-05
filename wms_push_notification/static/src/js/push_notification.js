/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("user_menuitems").add("wms_push_notification", (env) => {
    const permission = env.services["mail.notification.permission"];

    return {
        type: "item",
        id: "wms_push_notification",
        description: "Aktifkan Notifikasi WMS",
        callback: async () => {
            await permission.requestPermission();
        },
        show: () => true,
        sequence: 64,
    };
});
