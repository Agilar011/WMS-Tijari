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
            "tag": "display_notification",
            "params": {
                "title": _("Inventory Adjustment"),
                "message": (
                    _("Begin Adjustment has been queued.")
                    if operation == "begin"
                    else _("Update Stock has been queued.")
                ),
                "type": "info",
                "sticky": False,
            },
        }
