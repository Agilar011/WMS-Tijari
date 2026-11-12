import logging
import traceback

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockInventoryOperationJob(models.Model):
    _name = "stock.inventory.operation.job"
    _description = "Inventory Adjustment Operation Job"
    _order = "id desc"

    inventory_id = fields.Many2one(
        "stock.inventory", required=True, readonly=True, ondelete="cascade", index=True
    )
    operation = fields.Selection(
        [("begin", "Begin Adjustment"), ("apply", "Update Stock")],
        required=True,
        readonly=True,
    )
    requested_by_id = fields.Many2one("res.users", required=True, readonly=True)
    state = fields.Selection(
        [("queued", "Queued"), ("running", "Running"), ("done", "Done"), ("failed", "Failed")],
        default="queued",
        required=True,
        readonly=True,
        index=True,
    )
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    attempt_count = fields.Integer(readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    error_message = fields.Text(readonly=True)
    user_error_message = fields.Text(readonly=True)

    def get_client_status(self):
        self.ensure_one()
        job = self.sudo()
        # The overlay polls this method as the logged-in user. Allow it to read
        # status only when that user can read the inventory document.
        job.inventory_id.with_user(self.env.user).check_access("read")
        retry_in_seconds = 0
        if job.next_attempt_at:
            retry_at = fields.Datetime.to_datetime(job.next_attempt_at)
            retry_in_seconds = max(
                (retry_at - fields.Datetime.now()).total_seconds(), 0
            )
        return {
            "state": job.state,
            "retrying": bool(
                job.state == "queued"
                and job.next_attempt_at
                and job.user_error_message
            ),
            "retry_in_seconds": retry_in_seconds,
            "error_message": job.user_error_message or False,
        }

    @api.model
    def _cron_process_next(self):
        # Inventory adjustments can target overlapping locations/products.
        # Serialize these long-running operations across cron workers so two
        # independent jobs cannot pass the conflict checks at the same time.
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)", [27182, 81828]
        )
        if not self.env.cr.fetchone()[0]:
            return

        self.env.cr.execute(
            """
            SELECT id
              FROM stock_inventory_operation_job
             WHERE state = 'queued'
               AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
             ORDER BY id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
            """
        )
        row = self.env.cr.fetchone()
        if not row:
            return

        job = self.sudo().browse(row[0])
        job.write({
            "state": "running",
            "started_at": fields.Datetime.now(),
            "finished_at": False,
            "error_message": False,
            "user_error_message": False,
            "attempt_count": job.attempt_count + 1,
        })
        try:
            with self.env.cr.savepoint():
                inventory = job.inventory_id.with_user(job.requested_by_id).with_context(
                    skip_inventory_operation_queue=True
                )
                if job.operation == "begin":
                    inventory.action_state_to_in_progress()
                else:
                    inventory.action_state_to_done()
                job.write({"state": "done", "finished_at": fields.Datetime.now()})
            _logger.info(
                "Inventory operation job %s completed: inventory=%s operation=%s",
                job.id,
                job.inventory_id.id,
                job.operation,
            )
        except Exception as exc:
            _logger.exception("Inventory operation job %s failed", job.id)
            retry = not isinstance(exc, UserError) and job.attempt_count < 3
            job.write({
                "state": "queued" if retry else "failed",
                "finished_at": fields.Datetime.now(),
                "error_message": "%s\n%s" % (exc, traceback.format_exc(limit=8)),
                "user_error_message": str(exc).strip() or _(
                    "Unexpected error while processing the inventory adjustment."
                ),
                "next_attempt_at": (
                    fields.Datetime.now() + relativedelta(minutes=2 * job.attempt_count)
                    if retry else False
                ),
            })

        if self.search_count([
            ("state", "=", "queued"),
            "|", ("next_attempt_at", "=", False),
            ("next_attempt_at", "<=", fields.Datetime.now()),
        ]):
            cron = self.env.ref(
                "stock_inventory.ir_cron_inventory_operation_jobs",
                raise_if_not_found=False,
            )
            if cron:
                cron._trigger()


class StockInventory(models.Model):
    _inherit = "stock.inventory"

    def _queue_inventory_operation(self, operation):
        self.ensure_one()
        expected_state = "draft" if operation == "begin" else "approved"
        if self.state != expected_state:
            raise UserError(_("This inventory adjustment is not ready for this operation."))
        if operation == "apply" and self.approval_state != "approved":
            raise UserError(_("The inventory adjustment must be approved before updating stock."))

        # Serialize submissions per adjustment so concurrent clicks cannot
        # create duplicate active jobs.
        self.env.cr.execute(
            "SELECT id FROM stock_inventory WHERE id = %s FOR UPDATE", [self.id]
        )
        Job = self.env["stock.inventory.operation.job"].sudo()
        job = Job.search([
            ("inventory_id", "=", self.id),
            ("state", "in", ("queued", "running")),
        ], limit=1)
        if not job:
            job = Job.create({
                "inventory_id": self.id,
                "operation": operation,
                "requested_by_id": self.env.user.id,
            })

        cron = self.env.ref(
            "stock_inventory.ir_cron_inventory_operation_jobs",
            raise_if_not_found=False,
        )
        if cron:
            cron._trigger()
        return {
            "type": "ir.actions.client",
            "tag": "stock_inventory.operation_loading",
            # Keep the current action stack intact. The loading screen is an
            # overlay dialog and will restore the existing controller on finish.
            "target": "new",
            "context": {"dialog_size": "extra-large"},
            "params": {
                "job_id": job.id,
                "job_model": "stock.inventory.operation.job",
                "status_method": "get_client_status",
                "poll_interval_ms": 2000,
                "operation_label": (
                    _("Begin Adjustment")
                    if operation == "begin"
                    else _("Update Stock")
                ),
                "return_action": {
                    "type": "ir.actions.act_window",
                    "name": self.display_name,
                    "res_model": self._name,
                    "res_id": self.id,
                    "view_mode": "form",
                    "views": [[False, "form"]],
                    "target": "current",
                },
            },
        }
