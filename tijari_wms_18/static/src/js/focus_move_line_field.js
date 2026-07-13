/** @odoo-module **/

import { registry } from "@web/core/registry";

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function findRowById(recordId) {
    if (!recordId) {
        return null;
    }

    const rows = Array.from(
        document.querySelectorAll("tr.o_data_row")
    ).filter((row) => row.offsetParent !== null);

    return rows.find((row) => {
        const idCell = row.querySelector('td[name="id"]');

        if (!idCell) {
            return false;
        }

        const input = idCell.querySelector("input, .o_input");

        const value = input
            ? input.value
            : idCell.textContent.trim();

        return Number(value) === Number(recordId);
    });
}

async function focusMoveLineField(env, action) {
    const params = action.params || {};
    const fieldName = params.field_name;
    const moveLineId = params.move_line_id;

    if (!fieldName || !moveLineId) {
        return;
    }

    await delay(100);

    // let activeRow = document.querySelector(
    //     "tr.o_selected_row, tr.table-active, tr:focus-within"
    // );

    const activeRow = findRowById(moveLineId);


    let targetCell = null;

    if (activeRow) {
        targetCell = activeRow.querySelector(`td[name="${fieldName}"]`);
    }

    if (!targetCell) {
        const cells = Array.from(
            document.querySelectorAll(`td[name="${fieldName}"]`)
        );

        targetCell = cells.find((cell) => cell.offsetParent !== null);
    }

    if (!targetCell) {
        return;
    }

    targetCell.click();

    await delay(150);

    let input = targetCell.querySelector("input, textarea, .o_input");

    if (!input) {
        input = document.activeElement;
    }

    if (input && typeof input.focus === "function") {
        input.focus();
        input.select?.();
    }
}

registry.category("actions").add("adt_focus_move_line_field", focusMoveLineField);