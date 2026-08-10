/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const ZXING_BROWSER_CDN_URLS = [
    "/tijari_wms_18/static/src/lib/zxing-browser.min.js",
    "https://cdn.jsdelivr.net/npm/@zxing/browser@0.1.5/umd/zxing-browser.min.js",
    "https://unpkg.com/@zxing/browser@0.1.5/umd/zxing-browser.min.js",
];
const SCANNER_FALLBACK_MESSAGE = "Scanner kamera tidak tersedia. Input manual diaktifkan.";

let zxingBrowserLoadPromise = null;

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function loadScript(src) {
    const existingScript = document.querySelector(`script[src="${src}"]`);
    if (existingScript) {
        return Promise.resolve();
    }

    return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.onload = resolve;
        script.onerror = () => reject(new Error("Library scanner gagal dimuat."));
        document.head.append(script);
    });
}

async function loadZxingBrowser() {
    if (window.ZXingBrowser) {
        return window.ZXingBrowser;
    }

    zxingBrowserLoadPromise = zxingBrowserLoadPromise || (async () => {
        let lastError = null;
        for (const src of ZXING_BROWSER_CDN_URLS) {
            try {
                await loadScript(src);
                if (window.ZXingBrowser) {
                    return;
                }
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError || new Error("Library scanner gagal dimuat.");
    })();
    await zxingBrowserLoadPromise;

    if (!window.ZXingBrowser) {
        throw new Error("Library scanner tidak tersedia.");
    }

    return window.ZXingBrowser;
}

function getScannerErrorMessage(error) {
    const name = error?.name || "";
    const message = error?.data?.message || error?.data?.arguments?.[0] || error?.message || "";

    if (!window.isSecureContext) {
        return "Akses kamera butuh HTTPS. Pastikan halaman dibuka lewat https://wms-aditya.duckdns.org.";
    }
    if (name === "NotAllowedError" || name === "SecurityError") {
        return "Akses kamera ditolak. Izinkan camera permission untuk situs WMS di browser dan OS.";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        return "Kamera tidak ditemukan di device ini.";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
        return "Kamera tidak bisa dibuka. Tutup aplikasi/tab lain yang sedang memakai kamera, lalu coba lagi.";
    }
    if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
        return "Kamera tersedia, tapi constraint kamera tidak cocok. Coba pilih/aktifkan kamera lain.";
    }

    return message || SCANNER_FALLBACK_MESSAGE;
}

function isCameraAccessError(error) {
    return [
        "NotAllowedError",
        "SecurityError",
        "NotFoundError",
        "DevicesNotFoundError",
        "NotReadableError",
        "TrackStartError",
        "OverconstrainedError",
        "ConstraintNotSatisfiedError",
    ].includes(error?.name || "");
}

function isCameraRetryableError(error) {
    return [
        "NotFoundError",
        "DevicesNotFoundError",
        "OverconstrainedError",
        "ConstraintNotSatisfiedError",
    ].includes(error?.name || "");
}

function notifyScannerError(envOrService, error) {
    const notification = envOrService?.services?.notification || envOrService;
    notification?.add?.(getScannerErrorMessage(error), {
        title: "Scan barcode gagal",
        type: "danger",
    });
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

function findActiveRow() {
    const row = document.querySelector(
        "tr.o_selected_row, tr.table-active, tr:focus-within"
    );

    if (row?.offsetParent !== null) {
        return row;
    }

    return null;
}

function findVisibleCell(row, fieldName) {
    const cells = Array.from(row?.querySelectorAll(`td[name="${fieldName}"]`) || []);
    return cells.find((cell) => cell.offsetParent !== null) || cells[0] || null;
}

function setCellText(row, fieldName, value) {
    const cell = findVisibleCell(row, fieldName);
    if (!cell) {
        return;
    }

    const input = cell.querySelector("input, textarea, .o_input");
    if (input && "value" in input) {
        input.value = value || "";
        return;
    }

    cell.textContent = value || "";
}

function setBadgeCell(row, fieldName, value, status) {
    const cell = findVisibleCell(row, fieldName);
    if (!cell) {
        return;
    }

    cell.replaceChildren();

    const badge = document.createElement("span");
    badge.className = "badge rounded-pill";
    if (status === "match") {
        badge.classList.add("text-bg-success");
    } else if (status === "not_match") {
        badge.classList.add("text-bg-danger");
    } else {
        badge.classList.add("text-bg-secondary");
    }
    badge.textContent = value || "";
    cell.append(badge);
}

function updateScanButtons(row, isMatched) {
    const buttons = row?.querySelectorAll(
        'button[name="action_prepare_scan_lot"], button[name="action_prepare_scan_location"]'
    );

    buttons?.forEach((button) => {
        button.classList.toggle("d-none", isMatched);
        button.style.display = isMatched ? "none" : "";
    });
}

function applyMoveLineScanResult(action, result) {
    const row = action.activeRow || findRowById(result?.id) || findActiveRow();
    if (!row || !result) {
        return;
    }

    for (const fieldName of ["confirmation_lot_code", "confirmation_location_code"]) {
        if (Object.prototype.hasOwnProperty.call(result, fieldName)) {
            setCellText(row, fieldName, result[fieldName]);
        }
    }

    if (Object.prototype.hasOwnProperty.call(result, "matching")) {
        setBadgeCell(row, "matching", result.matching_label || result.matching, result.matching);
        updateScanButtons(row, result.matching === "match");
    }

    if (Object.prototype.hasOwnProperty.call(result, "matching_lot_id")) {
        setCellText(row, "matching_lot_id", result.matching_lot_id?.[1] || "");
    }
    if (Object.prototype.hasOwnProperty.call(result, "matching_loc_dest_id")) {
        setCellText(row, "matching_loc_dest_id", result.matching_loc_dest_id?.[1] || "");
    }
    if (Object.prototype.hasOwnProperty.call(result, "location_dest_id")) {
        setCellText(row, "location_dest_id", result.location_dest_id?.[1] || "");
    }
    if (Object.prototype.hasOwnProperty.call(result, "location_putaway_id")) {
        setCellText(row, "location_putaway_id", result.location_putaway_id?.[1] || "");
    }
    if (Object.prototype.hasOwnProperty.call(result, "putaway_status")) {
        setBadgeCell(row, "putaway_status", result.putaway_status_label || result.putaway_status, result.putaway_status);
    }
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

    const activeRow = action.activeRow || findRowById(moveLineId) || findActiveRow();


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

async function setMoveLineFieldValue(action, value) {
    const params = action.params || {};
    const fieldName = params.field_name;
    const moveLineId = params.move_line_id;

    if (!fieldName || !moveLineId) {
        return false;
    }

    await focusMoveLineField(null, action);
    await delay(150);

    const activeRow = action.activeRow || findRowById(moveLineId) || findActiveRow();
    const targetCell = activeRow?.querySelector(`td[name="${fieldName}"]`);
    const input = targetCell?.querySelector("input, textarea, .o_input") || document.activeElement;

    if (!input || !("value" in input)) {
        return false;
    }

    input.focus?.();
    input.value = value;
    input.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        inputType: "insertText",
        data: value,
    }));
    input.dispatchEvent(new Event("change", { bubbles: true }));

    return true;
}

function createScannerDialog(title) {
    const overlay = document.createElement("div");
    overlay.className = "tjr-qr-scanner-overlay";
    overlay.style.cssText = [
        "position:fixed",
        "inset:0",
        "z-index:2147483647",
        "display:flex",
        "align-items:center",
        "justify-content:center",
        "background:rgba(0,0,0,.72)",
        "padding:16px",
    ].join(";");

    const dialog = document.createElement("div");
    dialog.style.cssText = [
        "width:min(480px,100%)",
        "background:#fff",
        "border-radius:8px",
        "box-shadow:0 18px 50px rgba(0,0,0,.35)",
        "overflow:hidden",
    ].join(";");

    const header = document.createElement("div");
    header.style.cssText = [
        "display:flex",
        "align-items:center",
        "justify-content:space-between",
        "gap:12px",
        "padding:12px 16px",
        "border-bottom:1px solid #ddd",
    ].join(";");

    const heading = document.createElement("strong");
    heading.textContent = title || "Scan QR Code";

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "btn btn-secondary btn-sm";
    closeButton.textContent = "Tutup";

    const body = document.createElement("div");
    body.style.cssText = "padding:16px;";

    const videoWrap = document.createElement("div");
    videoWrap.style.cssText = [
        "position:relative",
        "width:100%",
        "aspect-ratio:1/1",
        "background:#111",
        "border-radius:6px",
        "overflow:hidden",
    ].join(";");

    const video = document.createElement("video");
    video.setAttribute("playsinline", "playsinline");
    video.autoplay = true;
    video.muted = true;
    video.style.cssText = "width:100%;height:100%;object-fit:cover;";

    const guide = document.createElement("div");
    guide.style.cssText = [
        "position:absolute",
        "inset:18%",
        "border:2px solid rgba(255,255,255,.9)",
        "border-radius:8px",
        "box-shadow:0 0 0 999px rgba(0,0,0,.24)",
        "pointer-events:none",
    ].join(";");

    const status = document.createElement("div");
    status.style.cssText = "margin-top:10px;color:#444;font-size:13px;";
    status.textContent = "Arahkan kamera ke QR code.";

    videoWrap.append(video, guide);
    body.append(videoWrap, status);
    header.append(heading, closeButton);
    dialog.append(header, body);
    overlay.append(dialog);
    document.body.append(overlay);

    return { overlay, video, closeButton, status };
}

function stopStream(stream) {
    stream?.getTracks?.().forEach((track) => track.stop());
}

function getVideoConstraintCandidates() {
    return [
        {
            video: {
                facingMode: { ideal: "environment" },
            },
            audio: false,
        },
        {
            video: true,
            audio: false,
        },
    ];
}

async function getUserMediaWithFallback() {
    let lastError = null;

    for (const constraints of getVideoConstraintCandidates()) {
        try {
            return await navigator.mediaDevices.getUserMedia(constraints);
        } catch (error) {
            lastError = error;
            if (!isCameraRetryableError(error)) {
                throw error;
            }
        }
    }

    throw lastError || new Error(SCANNER_FALLBACK_MESSAGE);
}

async function scanQrFromCamera(title) {
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(SCANNER_FALLBACK_MESSAGE);
    }

    try {
        return await scanQrWithZxing(title);
    } catch (zxingError) {
        if (isCameraAccessError(zxingError)) {
            throw zxingError;
        }
        if (!window.BarcodeDetector) {
            throw zxingError;
        }
    }

    return scanQrWithBarcodeDetector(title);
}

async function scanQrWithBarcodeDetector(title) {
    if (!window.BarcodeDetector) {
        throw new Error(SCANNER_FALLBACK_MESSAGE);
    }

    const detector = new BarcodeDetector({
        formats: ["qr_code", "code_128", "ean_13", "ean_8", "code_39", "code_93", "upc_a", "upc_e"],
    });
    const dialog = createScannerDialog(title);
    let stream = null;
    let stopped = false;

    const close = () => {
        stopped = true;
        stopStream(stream);
        dialog.overlay.remove();
    };

    dialog.closeButton.addEventListener("click", close);

    try {
        stream = await getUserMediaWithFallback();
        dialog.video.srcObject = stream;
        await dialog.video.play();

        return await new Promise((resolve, reject) => {
            dialog.closeButton.addEventListener("click", () => reject(new Error("Scan dibatalkan.")), {
                once: true,
            });

            const detect = async () => {
                if (stopped) {
                    return;
                }

                try {
                    const codes = await detector.detect(dialog.video);
                    const value = codes?.[0]?.rawValue;
                    if (value) {
                        close();
                        resolve(value);
                        return;
                    }
                    window.requestAnimationFrame(detect);
                } catch (error) {
                    close();
                    reject(error);
                }
            };

            detect();
        });
    } catch (error) {
        close();
        throw error;
    }
}

async function scanQrWithZxing(title) {
    const ZXingBrowser = await loadZxingBrowser();
    const dialog = createScannerDialog(title);
    let controls = null;
    let stopped = false;

    const close = () => {
        if (stopped) {
            return;
        }
        stopped = true;
        controls?.stop?.();
        dialog.overlay.remove();
    };

    dialog.closeButton.addEventListener("click", close);
    dialog.status.textContent = "Membuka kamera...";

    try {
        const codeReader = new ZXingBrowser.BrowserMultiFormatReader();
        const constraintsCandidates = getVideoConstraintCandidates();

        return await new Promise((resolve, reject) => {
            dialog.closeButton.addEventListener("click", () => reject(new Error("Scan dibatalkan.")), {
                once: true,
            });

            const startScan = (index) => {
                const constraints = constraintsCandidates[index];
                codeReader.decodeFromConstraints(
                    constraints,
                    dialog.video,
                    (result) => {
                        const value = result?.getText?.() || result?.text;
                        if (!value) {
                            return;
                        }

                        close();
                        resolve(value);
                    }
                ).then(
                    (scanControls) => {
                        controls = scanControls;
                        dialog.status.textContent = "Arahkan kamera ke QR/barcode.";
                    },
                    (error) => {
                        if (isCameraRetryableError(error) && index < constraintsCandidates.length - 1) {
                            startScan(index + 1);
                            return;
                        }
                        close();
                        reject(error);
                    }
                );
            };

            startScan(0);
        });
    } catch (error) {
        close();
        throw error;
    }
}

async function scanQrToMoveLineField(env, action) {
    const params = action.params || {};
    const fieldName = params.field_name;
    const moveLineId = params.move_line_id;

    if (!fieldName || !moveLineId) {
        return;
    }

    try {
        action.activeRow = findRowById(moveLineId) || findActiveRow();
        const scannedCode = await scanQrFromCamera(params.title);
        if (env?.services?.orm) {
            const result = await env.services.orm.call(
                "stock.move.line",
                "action_apply_scanned_field",
                [[moveLineId], fieldName, scannedCode]
            );
            applyMoveLineScanResult(action, result);
        } else {
            await setMoveLineFieldValue(action, scannedCode);
        }
    } catch (error) {
        notifyScannerError(env, error);
        await focusMoveLineField(env, action);
    }
}

async function scanQrToPickingProduct(env, action) {
    const params = action.params || {};
    const resModel = params.res_model || "stock.picking";
    const resId = params.res_id || params.picking_id;

    if (!resId) {
        return;
    }

    try {
        const scannedCode = await scanQrFromCamera(params.title);
        await env.services.orm.call(
            resModel,
            "action_apply_scanned_product",
            [[resId], scannedCode]
        );
    } catch (error) {
        notifyScannerError(env, error);
        return;
    }
}

async function scanQrToPickingPackage(env, action) {
    const params = action.params || {};
    const resModel = params.res_model || "stock.picking";
    const resId = params.res_id || params.picking_id;

    if (!resId) {
        return;
    }

    try {
        const scannedCode = await scanQrFromCamera(params.title);
        await env.services.orm.call(
            resModel,
            "action_apply_scanned_package",
            [[resId], scannedCode]
        );
    } catch (error) {
        notifyScannerError(env, error);
        return;
    }
}

class MoveLineScanButton extends Component {
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get fieldName() {
        const pickingTypeName = this.props.record.data?.picking_type_name;
        const isPickFlow = ["Pick", "Pick Internal", "Pick Components"].includes(pickingTypeName);
        if (isPickFlow && this.constructor.scanFieldName === "confirmation_lot_code") {
            return "matching_lot_id";
        }
        if (isPickFlow && this.constructor.scanFieldName === "confirmation_location_code") {
            return "matching_loc_dest_id";
        }
        return this.constructor.scanFieldName;
    }

    get title() {
        return this.constructor.scanTitle;
    }

    get iconClass() {
        return this.constructor.iconClass;
    }

    async onClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const moveLineId = this.props.record.resId;
        if (!moveLineId) {
            return;
        }

        let scannedCode;
        try {
            scannedCode = await scanQrFromCamera(this.title);
        } catch (error) {
            notifyScannerError(this.notification, error);
            return;
        }

        const result = await this.orm.call(
            "stock.move.line",
            "action_apply_scanned_field",
            [[moveLineId], this.fieldName, scannedCode]
        );
        const updates = {};
        for (const fieldName of ["matching_lot_id", "matching_loc_dest_id"]) {
            if (Object.prototype.hasOwnProperty.call(result || {}, fieldName)) {
                updates[fieldName] = result[fieldName] || false;
            }
        }
        if (Object.keys(updates).length) {
            await this.props.record.update(updates);
        }
        await this.props.record.load();
    }
}

class MoveLineScanLotButton extends MoveLineScanButton {
    static template = "tijari.MoveLineScanButton";
    static scanFieldName = "confirmation_lot_code";
    static scanTitle = "Scan Lot QR Code";
    static iconClass = "fa fa-barcode";
}

class MoveLineScanLocationButton extends MoveLineScanButton {
    static template = "tijari.MoveLineScanButton";
    static scanFieldName = "confirmation_location_code";
    static scanTitle = "Scan Location QR Code";
    static iconClass = "fa fa-map-marker";
}

class ProductScanButton extends Component {
    static props = { ...standardFieldProps };
    static template = "tijari.ProductScanButton";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get applyMethodName() {
        return "action_apply_scanned_product";
    }

    async onClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const { resId, resModel } = this.props.record;
        if (!resId || !resModel) {
            return;
        }

        let scannedCode;
        try {
            scannedCode = await scanQrFromCamera("Scan Product QR Code");
        } catch (error) {
            notifyScannerError(this.notification, error);
            return;
        }

        await this.orm.call(
            resModel,
            this.applyMethodName,
            [[resId], scannedCode]
        );
        await this.props.record.load();
    }
}

class PickerProductScanButton extends ProductScanButton {
    get applyMethodName() {
        return "action_apply_scanned_picker_product";
    }
}

class PackageScanButton extends Component {
    static props = { ...standardFieldProps };
    static template = "tijari.PackageScanButton";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    async onClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const { resId, resModel } = this.props.record;
        if (!resId || !resModel) {
            return;
        }

        let scannedCode;
        try {
            scannedCode = await scanQrFromCamera("Scan Package QR Code");
        } catch (error) {
            notifyScannerError(this.notification, error);
            return;
        }

        await this.orm.call(
            resModel,
            "action_apply_scanned_package",
            [[resId], scannedCode]
        );
        await this.props.record.load();
    }
}

registry.category("actions").add("adt_focus_move_line_field", focusMoveLineField);
registry.category("actions").add("adt_scan_qr_to_move_line_field", scanQrToMoveLineField);
registry.category("actions").add("adt_scan_qr_to_picking_product", scanQrToPickingProduct);
registry.category("actions").add("adt_scan_qr_to_picking_package", scanQrToPickingPackage);
registry.category("fields").add("adt_scan_lot_button", {
    component: MoveLineScanLotButton,
});
registry.category("fields").add("adt_scan_location_button", {
    component: MoveLineScanLocationButton,
});
registry.category("fields").add("adt_scan_product_button", {
    component: ProductScanButton,
});
registry.category("fields").add("adt_scan_picker_product_button", {
    component: PickerProductScanButton,
});
registry.category("fields").add("adt_scan_package_button", {
    component: PackageScanButton,
});
// registry.category("actions").add("adt_scan_qr_to_move_line_field", focusMoveLineField);
