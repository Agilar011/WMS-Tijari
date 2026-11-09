#!/usr/bin/env python3
"""Standalone Odoo 18 stock picking worker. Start via the configured Odoo venv."""

import logging
import multiprocessing
import os
from pathlib import Path
import random
import signal
import socket
import sys
import time
import uuid

# Odoo installations commonly run from a source checkout rather than an
# installed Python package. When this addon lives under that checkout, add the
# nearest source root so the standalone worker can import Odoo like odoo-bin.
for _candidate in Path(__file__).resolve().parents:
    if (_candidate / "odoo" / "__init__.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

import odoo
from odoo import api, fields
from odoo.exceptions import UserError
from odoo.modules.registry import Registry


_STOP = False
_LOGGER = logging.getLogger("tijari.stock_picking_worker")


def _stop(_signum, _frame):
    global _STOP
    _STOP = True


def _env_int(name, default, minimum=1):
    return max(minimum, int(os.environ.get(name, default)))


def _env_float(name, default, minimum=0.1):
    return max(minimum, float(os.environ.get(name, default)))


def _validate_action(env, picking, action):
    """Complete standard Odoo validation wizards returned by button_validate."""
    for _ in range(4):
        if not isinstance(action, dict) or action.get("type") != "ir.actions.act_window":
            return
        model = action.get("res_model")
        context = action.get("context") or {}
        if isinstance(context, str):
            raise UserError("Unexpected string context from stock validation wizard")
        wizard_model = env[model].with_context(**context)
        wizard = wizard_model.browse(action.get("res_id")).exists() if action.get("res_id") else wizard_model.create({})
        if model == "stock.immediate.transfer":
            action = wizard.process()
        elif model == "stock.backorder.confirmation":
            # Odoo's default lines preserve partial quantities and create backorders.
            action = wizard.process()
        else:
            raise UserError("Unsupported validation wizard: %s" % model)
    raise UserError("Stock validation returned too many consecutive wizard actions")


def _process_one(dbname, job_id, token, worker_id):
    registry = Registry(dbname)
    started = time.monotonic()
    with registry.cursor() as cr:
        env = api.Environment(cr, 1, {})
        job = env["stock.picking.job"].sudo().browse(job_id).exists()
        cr.execute(
            "SELECT state, lease_token, lease_expires_at, lease_expires_at > timezone('UTC', NOW()) FROM stock_picking_job WHERE id = %s",
            [job_id],
        )
        row = cr.fetchone()
        if not row or row[0] != "processing" or row[1] != token or not row[3]:
            cr.rollback()
            return
        picking = job.picking_id.sudo().with_company(job.company_id).with_context(
            allowed_company_ids=[job.company_id.id],
        )
        if picking.company_id != job.company_id:
            raise UserError("Picking company no longer matches the queued job")
        if picking.state == "done":
            # Handles a prior commit where stock completed but the worker died
            # before observing the result. Odoo commit atomicity normally prevents this.
            _complete_job(cr, job_id, token, worker_id, started)
            cr.commit()
            return
        if picking.state == "cancel":
            raise UserError("Cancelled pickings cannot be validated")
        if picking.state == "draft":
            picking.action_confirm()
        if picking.state in ("confirmed", "waiting", "partially_available"):
            picking.action_assign()
        if picking.state != "assigned":
            raise UserError("Picking is not ready for validation (state: %s)" % picking.state)
        result = picking.button_validate()
        _validate_action(env, picking, result)
        picking.invalidate_recordset(["state"])
        if picking.state != "done":
            raise UserError("Odoo validation did not complete the picking")
        _complete_job(cr, job_id, token, worker_id, started)
        cr.commit()


def _complete_job(cr, job_id, token, worker_id, started):
    # This conditional update shares the stock transaction. A lost lease makes
    # the update fail, rolling back all stock changes from this attempt.
    cr.execute("""
        UPDATE stock_picking_job
           SET state = 'completed', completed_at = timezone('UTC', NOW()),
               execution_duration = %s, worker_id = %s,
               lease_token = NULL, lease_expires_at = NULL,
               error_message = NULL
         WHERE id = %s AND state = 'processing' AND lease_token = %s
         RETURNING current_attempt_id
    """, [time.monotonic() - started, worker_id, job_id, token])
    if cr.rowcount != 1:
        raise UserError("The job lease expired before stock validation could commit")
    attempt_id = cr.fetchone()[0]
    if attempt_id:
        cr.execute("""
            UPDATE stock_picking_job_attempt
               SET state = 'completed', completed_at = timezone('UTC', NOW()),
                   execution_duration = EXTRACT(EPOCH FROM (timezone('UTC', NOW()) - started_at))
             WHERE id = %s AND state = 'processing'
        """, [attempt_id])


def _transient_error(exc):
    code = getattr(exc, "pgcode", None) or getattr(getattr(exc, "diag", None), "sqlstate", None)
    return code in {"40001", "40P01", "55P03", "57014"} or bool(code and code.startswith("08"))


def _record_failure(dbname, job_id, token, exc, retry_limit):
    registry = Registry(dbname)
    retry = _transient_error(exc)
    with registry.cursor() as cr:
        env = api.Environment(cr, 1, {})
        job = env["stock.picking.job"].sudo().browse(job_id).exists()
        cr.execute("SELECT state, lease_token, retry_count, max_retries, current_attempt_id FROM stock_picking_job WHERE id = %s FOR UPDATE", [job_id])
        row = cr.fetchone()
        if not row or row[0] != "processing" or row[1] != token:
            cr.rollback()
            return
        retries = row[2] + 1
        can_retry = retry and retries <= min(row[3], retry_limit)
        delay = min(3600, (2 ** min(retries, 10)) + random.uniform(0, 3))
        if row[4]:
            cr.execute("""
                UPDATE stock_picking_job_attempt
                   SET state = %s, completed_at = timezone('UTC', NOW()),
                       execution_duration = EXTRACT(EPOCH FROM (timezone('UTC', NOW()) - started_at)),
                       error_message = %s
                 WHERE id = %s AND state = 'processing'
            """, ["retry" if can_retry else "failed", ("%s: %s" % (type(exc).__name__, exc))[:4000], row[4]])
        values = {
            "state": "pending" if can_retry else "failed",
            "retry_count": retries,
            "next_attempt_at": fields.Datetime.add(fields.Datetime.now(), seconds=delay) if can_retry else False,
            "worker_id": False,
            "lease_token": False,
            "lease_expires_at": False,
            "error_message": ("%s: %s" % (type(exc).__name__, exc))[:4000],
        }
        job.write(values)
        cr.commit()


def _worker(dbname, worker_number):
    global _STOP
    _STOP = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = "%s-%s-%s" % (socket.gethostname(), worker_number, uuid.uuid4().hex[:8])
    poll = _env_float("STOCK_PICKING_POLL_SECONDS", 1.0)
    lease = _env_int("STOCK_PICKING_JOB_TIMEOUT_SECONDS", 900)
    retry_limit = _env_int("STOCK_PICKING_RETRY_LIMIT", 5, 0)
    batch_size = _env_int("STOCK_PICKING_BATCH_SIZE", 1)
    while not _STOP:
        completed_in_cycle = 0
        while not _STOP and completed_in_cycle < batch_size:
            try:
                with Registry(dbname).cursor() as cr:
                    env = api.Environment(cr, 1, {})
                    job = env["stock.picking.job"].claim_one(worker_id, lease)
                    job_id = job.id
                    token = job.lease_token
                    picking_id = job.picking_id.id
                    company_id = job.company_id.id
                if not job_id:
                    break
                _LOGGER.info("claimed job_id=%s picking_id=%s worker_id=%s company_id=%s", job_id, picking_id, worker_id, company_id)
                try:
                    _process_one(dbname, job_id, token, worker_id)
                    _LOGGER.info("finished job_id=%s worker_id=%s", job_id, worker_id)
                except Exception as exc:
                    _LOGGER.exception("failed job_id=%s worker_id=%s", job_id, worker_id)
                    _record_failure(dbname, job_id, token, exc, retry_limit)
                completed_in_cycle += 1
            except Exception:
                _LOGGER.exception("worker loop error worker_id=%s", worker_id)
                time.sleep(min(poll * 5, 30))
        if not _STOP:
            time.sleep(poll)
    _LOGGER.info("worker stopping worker_id=%s", worker_id)


def main():
    config_path = os.environ.get("ODOO_RC")
    if not config_path:
        raise SystemExit("Set ODOO_RC to the Odoo configuration file")
    odoo.tools.config.parse_config(["-c", config_path])
    dbname = os.environ.get("ODOO_DB") or odoo.tools.config["db_name"]
    if not dbname:
        raise SystemExit("Set ODOO_DB or db_name in the Odoo configuration")
    count = _env_int("STOCK_PICKING_WORKERS", 1)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    children = []
    for number in range(count):
        process = multiprocessing.Process(target=_worker, args=(dbname, number + 1), name="stock-picking-%s" % (number + 1))
        process.start()
        children.append(process)
    deadline = None
    while any(process.is_alive() for process in children):
        if _STOP and deadline is None:
            deadline = time.monotonic() + _env_int("STOCK_PICKING_SHUTDOWN_TIMEOUT_SECONDS", 60)
            for process in children:
                if process.is_alive():
                    process.terminate()
        if deadline and time.monotonic() >= deadline:
            for process in children:
                if process.is_alive():
                    process.terminate()
        for process in children:
            process.join(timeout=0.25)
    sys.exit(max((process.exitcode or 0) for process in children))


if __name__ == "__main__":
    main()
