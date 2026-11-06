import logging
import traceback

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class AcumaticaInventoryStockGenerateJob(models.Model):
    _name = "acumatica.inventory.stock.generate.job"
    _description = "Inventory Stock Generate Job"
    _rec_name = "warehouse_code"
    _order = "id desc"

    config_id = fields.Many2one("acumatica.config", required=True, ondelete="cascade")
    location_mapping_id = fields.Many2one(
        "stock.location.acumatica", required=True, ondelete="cascade"
    )
    warehouse_code = fields.Char(related="location_mapping_id.code", store=True)
    requested_by_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    state = fields.Selection([
        ("queued", "Queued"),
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ], default="queued", required=True, index=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    total_fetched = fields.Integer(readonly=True)
    total_new = fields.Integer(readonly=True)
    total_updated = fields.Integer(readonly=True)
    error_message = fields.Text(readonly=True)
    attempt_count = fields.Integer(readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)

    @api.model
    def _cron_process_jobs(self):
        """Process one warehouse per transaction to keep work bounded/resumable."""
        self.env.cr.execute(
            """
            SELECT id
              FROM acumatica_inventory_stock_generate_job
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

        job = self.browse(row[0])
        job.write({
            "state": "running",
            "started_at": fields.Datetime.now(),
            "error_message": False,
            "attempt_count": job.attempt_count + 1,
        })
        try:
            with self.env.cr.savepoint():
                config = job.config_id
                wizard = self.env["import.inventory.stock.wizard"].sudo().create({
                    "config_id": config.id,
                    "warehouse_value": job.warehouse_code,
                    "inventory_id_value": (
                        config.request_inventory_id_value
                        if "request_inventory_id_value" in config._fields
                        else False
                    ),
                    "odata_expand": config.odata_expand or "InventorySiteInquiryDetails",
                    "odata_top": (
                        config.odata_top
                        if "odata_top" in config._fields and config.odata_top
                        else 0
                    ),
                    "batch_size": 1000,
                })
                wizard.action_fetch_data()
                job.write({
                    "state": "done",
                    "finished_at": fields.Datetime.now(),
                    "total_fetched": wizard.total_fetched,
                    "total_new": wizard.total_new,
                    "total_updated": wizard.total_existing,
                })
            _logger.info(
                "Inventory stock job %s (%s) completed: fetched=%s new=%s updated=%s",
                job.id, job.warehouse_code, wizard.total_fetched,
                wizard.total_new, wizard.total_existing,
            )
        except Exception as exc:
            _logger.exception("Inventory stock job %s failed", job.id)
            will_retry = job.attempt_count < 3
            job.write({
                "state": "queued" if will_retry else "failed",
                "finished_at": fields.Datetime.now(),
                "error_message": "%s\n%s" % (exc, traceback.format_exc(limit=8)),
                "next_attempt_at": (
                    fields.Datetime.now() + relativedelta(minutes=2 * job.attempt_count)
                    if will_retry else False
                ),
            })

        # Ask Odoo to run the next queued warehouse promptly. Each invocation
        # still commits independently, so a failure never loses completed work.
        if self.search_count([
            ("state", "=", "queued"),
            "|", ("next_attempt_at", "=", False),
            ("next_attempt_at", "<=", fields.Datetime.now()),
        ]):
            cron = self.env.ref(
                "acumatica_all_import.ir_cron_inventory_stock_generate_jobs",
                raise_if_not_found=False,
            )
            if cron:
                cron._trigger()

    def action_retry(self):
        self.sudo().filtered(lambda job: job.state == "failed").write({
            "state": "queued",
            "started_at": False,
            "finished_at": False,
            "error_message": False,
            "attempt_count": 0,
            "next_attempt_at": False,
        })
        cron = self.env.ref(
            "acumatica_all_import.ir_cron_inventory_stock_generate_jobs",
            raise_if_not_found=False,
        )
        if cron:
            cron._trigger()
        return True

