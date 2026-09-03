(function () {
    "use strict";

    let activeLineId = null;
    let activeTarget = null;
    let stream = null;
    let detector = null;
    let scanTimer = null;

    function scannerEl() {
        return document.querySelector(".putaway-scanner");
    }

    function videoEl() {
        return document.querySelector(".putaway-video");
    }

    function messageEl() {
        return document.querySelector(".putaway-scanner-message");
    }

    function setMessage(text) {
        const message = messageEl();
        if (message) {
            message.textContent = text || "";
        }
    }

    async function stopScanner() {
        if (scanTimer) {
            window.clearTimeout(scanTimer);
            scanTimer = null;
        }
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        const scanner = scannerEl();
        if (scanner) {
            scanner.hidden = true;
        }
    }

    async function validateScan(code) {
        if (!activeLineId || !activeTarget || !code) {
            return;
        }

        setMessage("Validasi scan...");
        const response = await fetch("/putaway/mobile/scan", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                move_line_id: activeLineId,
                target: activeTarget,
                code: code,
            }),
        });
        const result = await response.json();
        setMessage(result.message || "Scan diproses.");

        if (result.ok) {
            window.setTimeout(() => window.location.reload(), 450);
        }
    }

    async function validateQuantity(lineId, quantity) {
        activeLineId = lineId;
        activeTarget = "quantity";
        await validateScan(quantity);
    }

    async function detectLoop() {
        if (!detector || !stream) {
            return;
        }
        try {
            const codes = await detector.detect(videoEl());
            if (codes && codes.length) {
                await validateScan(codes[0].rawValue);
                return;
            }
        } catch (error) {
            setMessage("Scanner otomatis belum bisa membaca. Pakai input manual.");
        }
        scanTimer = window.setTimeout(detectLoop, 300);
    }

    async function openScanner(lineId, target) {
        activeLineId = lineId;
        activeTarget = target;

        const scanner = scannerEl();
        const video = videoEl();
        if (!scanner || !video) {
            return;
        }

        scanner.hidden = false;
        setMessage("Arahkan kamera ke barcode atau QR.");

        if (!("mediaDevices" in navigator) || !navigator.mediaDevices.getUserMedia) {
            setMessage("Kamera tidak tersedia. Pakai input manual.");
            return;
        }

        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: {facingMode: "environment"},
                audio: false,
            });
            video.srcObject = stream;
            await video.play();

            if ("BarcodeDetector" in window) {
                detector = new window.BarcodeDetector({
                    formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8"],
                });
                detectLoop();
            } else {
                setMessage("Browser belum support scanner otomatis. Pakai input manual.");
            }
        } catch (error) {
            setMessage("Akses kamera gagal. Pakai input manual.");
        }
    }

    document.addEventListener("click", async (event) => {
        const scanButton = event.target.closest(".putaway-scan-button");
        if (scanButton) {
            openScanner(scanButton.dataset.lineId, scanButton.dataset.scanTarget);
            return;
        }

        if (event.target.closest(".putaway-close-scanner")) {
            stopScanner();
            return;
        }

        if (event.target.closest(".putaway-submit-scan")) {
            const input = document.querySelector(".putaway-manual-input");
            await validateScan(input ? input.value.trim() : "");
            return;
        }

        const quantityButton = event.target.closest(".putaway-quantity-button");
        if (quantityButton) {
            const lineId = quantityButton.dataset.lineId;
            const input = document.querySelector(
                `.putaway-quantity-input[data-line-id="${lineId}"]`
            );
            await validateQuantity(lineId, input ? input.value.trim() : "");
        }
    });
}());
