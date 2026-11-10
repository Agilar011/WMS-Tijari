/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useRef } from "@odoo/owl";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { ListController } from "@web/views/list/list_controller";

async function openPickingByOrigin({ orm, action, notification, origin }) {
    try {
        const result = await orm.call(
            "stock.picking",
            "action_open_by_scanned_origin",
            [origin]
        );
        await action.doAction(result);
        return true;
    } catch (error) {
        const message =
            error.data?.message ||
            error.data?.arguments?.[0] ||
            error.message ||
            "Dokumen tidak ditemukan.";
        notification.add(message, {
            title: "Search Document",
            type: "danger",
        });
        return false;
    }
}

async function submitFromToolbar(controller, ev) {
    if (ev.key !== "Enter") {
        return;
    }
    ev.preventDefault();
    ev.stopPropagation();

    const input = ev.currentTarget;
    const origin = input.value.trim();
    if (!origin || controller.documentSearchBusy) {
        return;
    }

    controller.documentSearchBusy = true;
    input.disabled = true;
    const opened = await openPickingByOrigin({
        orm: controller.documentSearchOrm,
        action: controller.actionService,
        notification: controller.documentSearchNotification,
        origin,
    });
    if (opened) {
        input.value = "";
    }
    input.disabled = false;
    controller.documentSearchBusy = false;
    input.focus();
}

patch(KanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        this.documentSearchOrm = useService("orm");
        this.documentSearchNotification = useService("notification");
        this.documentSearchBusy = false;
    },

    onWorklistDocumentKeydown(ev) {
        return submitFromToolbar(this, ev);
    },
});

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        this.documentSearchOrm = useService("orm");
        this.documentSearchNotification = useService("notification");
        this.documentSearchBusy = false;
    },

    onWorklistDocumentKeydown(ev) {
        return submitFromToolbar(this, ev);
    },
});

export class DocumentSearchDialog extends Component {
    static template = "tijari.DocumentSearchDialog";
    static components = { Dialog };
    static props = { close: Function, title: { type: String, optional: true } };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.inputRef = useRef("documentInput");
        this.busy = false;
        onMounted(() => this.inputRef.el?.focus());
    }

    async onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const origin = ev.currentTarget.value.trim();
        if (!origin || this.busy) {
            return;
        }

        this.busy = true;
        ev.currentTarget.disabled = true;
        const opened = await openPickingByOrigin({
            orm: this.orm,
            action: this.action,
            notification: this.notification,
            origin,
        });
        if (opened) {
            this.props.close();
        } else {
            ev.currentTarget.disabled = false;
            ev.currentTarget.focus();
            this.busy = false;
        }
    }
}
