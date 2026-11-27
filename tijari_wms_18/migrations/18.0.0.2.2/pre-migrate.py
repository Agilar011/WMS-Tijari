# -*- coding: utf-8 -*-
"""Drop stale Transfer Shipment discrepancy references from stored view archs.

``stock.picking.transfer_shipment_discrepancy``, ``attachment_ids`` and the
``waiting_approval`` wms_state were removed. Views in
``views/stock_picking_views.xml`` still hold the old arch in the database until
that file is reloaded, but earlier data files (e.g. ``stock_move_views.xml``)
validate the combined stock.picking views first and would fail on the removed
fields. Strip those references here; the XML reload then writes the new arch.
"""

import json
import re

_REPLACEMENTS = [
    (re.compile(r"\(not stock_lebih and not transfer_shipment_discrepancy\)"), "not stock_lebih"),
    (re.compile(r"<button\b[^>]*transfer_shipment_discrepancy[^>]*/>\s*"), ""),
    (re.compile(r"<field\b[^>]*transfer_shipment_discrepancy[^>]*/>\s*"), ""),
    (re.compile(r" or transfer_shipment_discrepancy\b"), ""),
    (re.compile(r", 'waiting_approval'\)"), ")"),
]


def migrate(cr, version):
    cr.execute(
        """
        SELECT id, arch_db
          FROM ir_ui_view
         WHERE arch_db::text LIKE '%%transfer_shipment_discrepancy%%'
            OR arch_db::text LIKE '%%waiting_approval%%'
        """
    )
    for view_id, arch in cr.fetchall():
        if not arch:
            continue
        cleaned = {}
        for lang, value in arch.items():
            for pattern, replacement in _REPLACEMENTS:
                value = pattern.sub(replacement, value or "")
            cleaned[lang] = value
        if cleaned != arch:
            cr.execute(
                "UPDATE ir_ui_view SET arch_db = %s::jsonb WHERE id = %s",
                (json.dumps(cleaned), view_id),
            )
