# -*- coding: utf-8 -*-
"""Durable queue for explicitly asynchronous WMS picking validation."""

import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StockPickingJob(models.Model):
    _name = "stock.picking.job"
    _description = "Stock Picking Transaction Job"
    _order = "priority, create_date, id"
    _check_company_auto = True

    _transitions = {
        "pending": {"processing", "cancelled"},
        "processing": {"pending", "completed", "failed", "cancelled"},
        "failed": {"pending", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }

    name = fields.Char(required=True, default="New", copy=False, index=True)
    picking_id = fields.Many2one(
        "stock.picking", required=True, ondelete="cascade", index=True,
        check_company=True,
    )
    attempt_ids = fields.One2many("stock.picking.job.attempt", "job_id", copy=False)
    current_attempt_id = fields.Many2one("stock.picking.job.attempt", copy=False, readonly=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
    )
    operation_type = fields.Selection(
        [("confirm_assign_validate", "Confirm, Reserve and Validate")],
        required=True, default="confirm_assign_validate", index=True,
    )
    priority = fields.Integer(default=10, required=True)
    state = fields.Selection(
        [("pending", "Pending"), ("processing", "Processing"),
         ("completed", "Completed"), ("failed", "Failed"),
         ("cancelled", "Cancelled")],
        default="pending", required=True, index=True, copy=False,
    )
    idempotency_key = fields.Char(required=True, copy=False, index=True)
    retry_count = fields.Integer(default=0, readonly=True, copy=False)
    max_retries = fields.Integer(default=5, required=True, copy=False)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now, index=True, copy=False)
    processing_at = fields.Datetime(readonly=True, copy=False)
    completed_at = fields.Datetime(readonly=True, copy=False)
    worker_id = fields.Char(readonly=True, copy=False, index=True)
    lease_token = fields.Char(readonly=True, copy=False)
    lease_expires_at = fields.Datetime(readonly=True, copy=False, index=True)
    error_message = fields.Text(readonly=True, copy=False)
    execution_duration = fields.Float(readonly=True, copy=False)

    _sql_constraints = [
        ("idempotency_key_unique", "unique(idempotency_key)",
         "This idempotency key has already been submitted."),
    ]

    def init(self):
        # Queue-only indexes; stock tables are intentionally never updated with SQL.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS stock_picking_job_ready_idx
            ON stock_picking_job (priority, next_attempt_at, create_date, id)
            WHERE state = 'pending'
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS stock_picking_job_active_picking_idx
            ON stock_picking_job (picking_id, operation_type)
            WHERE state IN ('pending', 'processing')
        """)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records.filtered(lambda item: item.name == "New"):
            record.name = "SPJ/%08d" % record.id
        return records

    def write(self, vals):
        target = vals.get("state")
        if target:
            for record in self:
                if target != record.state and target not in self._transitions[record.state]:
                    raise ValidationError(_("Invalid picking job state transition: %s to %s") % (record.state, target))
        return super().write(vals)

    def action_retry(self):
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError(_("Only stock managers can retry picking jobs."))
        for job in self:
            if job.state != "failed":
                raise UserError(_("Only failed jobs can be retried."))
            job.write({
                "state": "pending", "next_attempt_at": fields.Datetime.now(),
                "error_message": False, "worker_id": False,
                "lease_token": False, "lease_expires_at": False,
            })

    @api.model
    def lock_idempotency_key(self, key):
        key = (key or "").strip()
        if not key:
            raise ValidationError(_("An idempotency key is required for queued validation."))
        # Serialize duplicate API requests until the creating request commits.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [key])

    @api.model
    def enqueue_validation(self, picking, idempotency_key, priority=10, max_retries=5):
        picking.ensure_one()
        idempotency_key = (idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError(_("An idempotency key is required for queued validation."))
        if picking.state in ("done", "cancel"):
            raise UserError(_("Only an open picking can be queued for validation."))
        existing = self.sudo().search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            if existing.picking_id != picking or existing.operation_type != "confirm_assign_validate":
                raise ValidationError(_("The idempotency key is already used by another request."))
            return existing
        return self.sudo().create({
            "picking_id": picking.id,
            "company_id": picking.company_id.id,
            "operation_type": "confirm_assign_validate",
            "priority": int(priority),
            "idempotency_key": idempotency_key,
            "max_retries": max(0, int(max_retries)),
        })

    @api.model
    def claim_one(self, worker_id, lease_seconds=900):
        """Claim and commit one job before stock processing starts."""
        self.env.cr.execute("""
            SELECT id, current_attempt_id FROM stock_picking_job
             WHERE state = 'processing' AND lease_expires_at < timezone('UTC', NOW())
             ORDER BY lease_expires_at, id
             FOR UPDATE SKIP LOCKED LIMIT 1
        """)
        expired = self.env.cr.fetchone()
        if expired:
            job = self.sudo().browse(expired[0])
            if expired[1]:
                self.env["stock.picking.job.attempt"].sudo().browse(expired[1]).write({
                    "state": "abandoned", "completed_at": fields.Datetime.now(),
                    "error_message": "Worker lease expired before the attempt completed.",
                })
            job.write({
                "state": "pending", "worker_id": False, "lease_token": False,
                "lease_expires_at": False, "next_attempt_at": fields.Datetime.now(),
            })
        self.env.cr.execute("""
            SELECT id
              FROM stock_picking_job
             WHERE state = 'pending' AND next_attempt_at <= timezone('UTC', NOW())
             ORDER BY priority - FLOOR(EXTRACT(EPOCH FROM (timezone('UTC', NOW()) - create_date)) / 3600),
                      create_date, id
             FOR UPDATE SKIP LOCKED
             LIMIT 1
        """)
        row = self.env.cr.fetchone()
        if not row:
            return self.browse()
        job_id = row[0]
        token = str(uuid.uuid4())
        job = self.browse(job_id).sudo()
        job.write({
            "state": "processing",
            "worker_id": worker_id,
            "lease_token": token,
            "lease_expires_at": fields.Datetime.add(fields.Datetime.now(), seconds=lease_seconds),
            "processing_at": fields.Datetime.now(),
            "error_message": False,
        })
        attempt_number = len(job.attempt_ids) + 1
        attempt = self.env["stock.picking.job.attempt"].sudo().create({
            "job_id": job.id, "attempt_number": attempt_number,
            "worker_id": worker_id,
        })
        job.current_attempt_id = attempt
        self.env.cr.commit()
        return self.browse(job_id).sudo()

class StockPickingJobAttempt(models.Model):
    _name = "stock.picking.job.attempt"
    _description = "Stock Picking Job Attempt"
    _order = "job_id, attempt_number"
    _check_company_auto = True

    job_id = fields.Many2one("stock.picking.job", required=True, ondelete="cascade", index=True)
    attempt_number = fields.Integer(required=True)
    worker_id = fields.Char(required=True, index=True)
    state = fields.Selection(
        [("processing", "Processing"), ("completed", "Completed"),
         ("retry", "Retry Scheduled"), ("failed", "Failed"),
         ("abandoned", "Abandoned")],
        default="processing", required=True, index=True,
    )
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    completed_at = fields.Datetime()
    execution_duration = fields.Float()
    error_message = fields.Text()

    _sql_constraints = [
        ("job_attempt_number_unique", "unique(job_id, attempt_number)",
         "A job attempt number can only be used once."),
    ]

