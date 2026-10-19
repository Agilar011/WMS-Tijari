import json

from odoo import fields, models
from odoo.exceptions import UserError


class ImportInventoryAdjustmentWizard(models.TransientModel):
    _name = 'import.inventory.adjustment.wizard'
    _description = 'Tarik Inventory Adjustment dari Acumatica'

    config_id = fields.Many2one('acumatica.config', required=True, string='Konfigurasi API',
                                domain=[('config_type', '=', 'inventory_adjustment'), ('active', '=', True)])
    fetch_limit = fields.Integer(default=5000)
    fetch_skip = fields.Integer(default=0)
    batch_size = fields.Integer(default=50)
    total_fetched = fields.Integer(readonly=True)

    def action_fetch_data(self):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f'{self.config_id.api_url}/{self.config_id.endpoint_name}'
            params = {'$expand': self.config_id.odata_expand or 'InventoryAdjustmentGIDetails'}
            response = session.put(endpoint, params=params, json={}, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal mengambil Inventory Adjustment (HTTP {response.status_code}): {response.text}')
            payload = response.json()
        finally:
            self.config_id._do_logout(session)

        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get('value'), list):
            rows = payload['value']
        elif isinstance(payload, dict):
            rows = [payload]
        else:
            rows = []
        if self.fetch_skip:
            rows = rows[self.fetch_skip:]
        if self.fetch_limit > 0:
            rows = rows[:self.fetch_limit]
        Model = self.env['acumatica.inventory.adjustment.staging']
        created = updated = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            details = row.get('InventoryAdjustmentGIDetails') or []
            if isinstance(details, dict):
                details = details.get('value') or []
            parent_id = str(row.get('id') or row.get('RefNbr') or '')

            for detail_index, detail in enumerate(details, start=1):
                if not isinstance(detail, dict):
                    continue
                row_number = detail.get('rowNumber') or detail_index
                external_id = str(
                    detail.get('id') or f'{parent_id or "inventory-adjustment"}:{row_number}'
                )
                reference = detail.get('RefNbr')
                if isinstance(reference, dict):
                    reference = reference.get('value')
                vals = {
                    'acumatica_id': external_id,
                    'row_number': row_number,
                    'ref_nbr': reference or False,
                    'note': detail.get('note') or False,
                    'raw_data': json.dumps(detail, ensure_ascii=False),
                    'config_id': self.config_id.id,
                    'sync_date': fields.Datetime.now(),
                    'import_state': 'staged',
                    'import_message': False,
                }
                record = Model.search([
                    ('acumatica_id', '=', external_id),
                    ('config_id', '=', self.config_id.id),
                ], limit=1)
                # Reuse the old header record for the first detail on refetch.
                if not record and detail_index == 1 and parent_id:
                    record = Model.search([
                        ('acumatica_id', '=', parent_id),
                        ('config_id', '=', self.config_id.id),
                    ], limit=1)
                if record:
                    record.write(vals)
                    updated += 1
                else:
                    Model.create(vals)
                    created += 1
        self.config_id.last_sync = fields.Datetime.now()
        self.total_fetched = created + updated
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': 'Inventory Adjustment',
                       'message': f'Selesai. Baru: {created}, diperbarui: {updated}.',
                       'type': 'success', 'sticky': False},
        }
