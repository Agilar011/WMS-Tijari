/** @odoo-module **/

const observed = new WeakSet();

function hideZeroRemainingRows(container) {
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
}

function observe(container) {

    if (observed.has(container)) {
        return;
    }

    observed.add(container);

    hideZeroRemainingRows(container);

    new MutationObserver(() => {
        hideZeroRemainingRows(container);
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