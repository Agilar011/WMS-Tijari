/** @odoo-module **/

import { registry } from "@web/core/registry";

const SCANNER_FALLBACK_MESSAGE = "Scanner kamera tidak tersedia. Input manual diaktifkan.";

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

function findActiveRow() {
    const row = document.querySelector(
        "tr.o_selected_row, tr.table-active, tr:focus-within"
    );

    if (row?.offsetParent !== null) {
        return row;
    }

    return null;
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

    return { overlay, video, closeButton };
}

function stopStream(stream) {
    stream?.getTracks?.().forEach((track) => track.stop());
}

async function scanQrFromCamera(title) {
    if (!navigator.mediaDevices?.getUserMedia || !window.BarcodeDetector) {
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
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: { ideal: "environment" },
            },
            audio: false,
        });
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
        await setMoveLineFieldValue(action, scannedCode);
    } catch (error) {
        await focusMoveLineField(env, action);
    }
}

async function scanQrToPickingProduct(env, action) {
    const params = action.params || {};
    const pickingId = params.picking_id;

    if (!pickingId) {
        return;
    }

    try {
        const scannedCode = await scanQrFromCamera(params.title);
        await env.services.orm.call(
            "stock.picking",
            "action_apply_scanned_product",
            [[pickingId], scannedCode]
        );
        await env.services.action.doAction({
            type: "ir.actions.client",
            tag: "reload",
        });
    } catch (error) {
        return;
    }
}

registry.category("actions").add("adt_focus_move_line_field", focusMoveLineField);
registry.category("actions").add("adt_scan_qr_to_move_line_field", scanQrToMoveLineField);
registry.category("actions").add("adt_scan_qr_to_picking_product", scanQrToPickingProduct);
