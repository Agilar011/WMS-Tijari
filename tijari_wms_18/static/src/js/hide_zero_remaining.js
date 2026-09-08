/** @odoo-module **/

const observed = new WeakSet();

function hideZeroRemainingRecords(container) {
    container.querySelectorAll("tbody tr.o_data_row").forEach((row) => {

        const qtyCell = row.querySelector(
            'td[name="remaining_package_qty"]'
        );

        if (!qtyCell) {
            return;
        }

        const qty = parseFloat(qtyCell.textContent.trim());

        row.style.display =
            !isNaN(qty) && qty <= 0
                ? "none"
                : "";
    });

    container.querySelectorAll(".o_kanban_record").forEach((card) => {
        const qtyElement = card.querySelector(".tijari-qty-unpack");

        if (!qtyElement) {
            return;
        }

        const qty = parseFloat(qtyElement.textContent.trim());

        if (!isNaN(qty) && qty <= 0) {
            card.style.setProperty("display", "none", "important");
        } else {
            card.style.removeProperty("display");
        }
    });

}


function observe(container) {

    if (observed.has(container)) {
        return;
    }

    observed.add(container);

    hideZeroRemainingRecords(container);


    new MutationObserver(() => {
        hideZeroRemainingRecords(container);
    }).observe(container, {
        childList: true,
        subtree: true,
    });
}

function boot() {

    document
        .querySelectorAll('div[name="move_ids_without_package"]')
        .forEach(observe);

    requestAnimationFrame(boot);
}

boot();