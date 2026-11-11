/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";

function getRpcErrorMessage(error) {
    const argumentsMessage = Array.isArray(error?.data?.arguments)
        ? error.data.arguments[0]
        : null;
    const candidates = [argumentsMessage, error?.data?.message, error?.message];
    const specificMessage = candidates.find(
        (message) =>
            typeof message === "string" &&
            message.trim() &&
            message.trim() !== "Odoo Server Error"
    );
    return (
        specificMessage?.trim() ||
        "Gagal membaca status proses. Periksa koneksi lalu coba lagi."
    );
}

/**
 * Reusable full-screen feedback for background operations.
 * Any queued operation can use this action by passing a job model, status
 * method, job id, operation label, and the action to reopen after completion.
 */
export class OperationLoadingAction extends Component {
    static template = "stock_inventory.OperationLoadingAction";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.params = this.props.action.params || {};
        this.pollInterval = this.params.poll_interval_ms || 2000;
        this.state = useState({
            phase: "loading",
            errorMessage: "",
            elapsedSeconds: 0,
        });
        this.pollTimer = null;
        this.elapsedTimer = null;
        this.startedAt = Date.now();

        onMounted(() => {
            this.elapsedTimer = setInterval(() => {
                this.state.elapsedSeconds = Math.floor(
                    (Date.now() - this.startedAt) / 1000
                );
            }, 1000);
            this.poll();
        });
        onWillUnmount(() => this.stopTimers());
    }

    get operationLabel() {
        return this.params.operation_label || "Operasi";
    }

    get elapsedLabel() {
        const minutes = Math.floor(this.state.elapsedSeconds / 60);
        const seconds = this.state.elapsedSeconds % 60;
        return minutes
            ? `${minutes} menit ${seconds} detik`
            : `${seconds} detik`;
    }

    stopTimers() {
        clearTimeout(this.pollTimer);
        clearInterval(this.elapsedTimer);
    }

    schedulePoll(delay = this.pollInterval) {
        clearTimeout(this.pollTimer);
        this.pollTimer = setTimeout(() => this.poll(), delay);
    }

    async poll() {
        const { job_id: jobId, job_model: jobModel, status_method: statusMethod } =
            this.params;
        if (!jobId || !jobModel || !statusMethod) {
            this.state.phase = "failed";
            this.state.errorMessage = "Informasi status proses tidak lengkap.";
            this.stopTimers();
            return;
        }

        try {
            const status = await this.orm.call(jobModel, statusMethod, [[jobId]]);
            if (status.state === "done") {
                this.stopTimers();
                await this.restorePreviousAction();
                return;
            }
            if (status.state === "failed") {
                this.state.phase = "failed";
                this.state.errorMessage =
                    status.error_message || "Proses gagal tanpa pesan error.";
                this.stopTimers();
                return;
            }

            if (status.retrying) {
                this.state.phase = "retrying";
                this.state.errorMessage = status.error_message || "";
                this.schedulePoll(
                    Math.max(this.pollInterval, status.retry_in_seconds * 1000 + 1000)
                );
                return;
            }

            this.state.phase = "loading";
            this.state.errorMessage = "";
            this.schedulePoll();
        } catch (error) {
            this.state.phase = "failed";
            this.state.errorMessage = getRpcErrorMessage(error);
            this.stopTimers();
        }
    }

    async returnToRecord() {
        await this.restorePreviousAction();
    }

    async restorePreviousAction() {
        const currentController = this.action.currentController;
        if (currentController?.jsId) {
            await this.action.restore(currentController.jsId);
        } else if (this.params.return_action) {
            await this.action.doAction(this.params.return_action);
        }
    }
}

registry.category("actions").add(
    "stock_inventory.operation_loading",
    OperationLoadingAction
);
