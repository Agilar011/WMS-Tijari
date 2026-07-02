
from odoo import fields, models
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class ImportIssueWizard(models.TransientModel):
    _name = 'import.issue.wizard'
    _description = 'Wizard Import Issue Change Item dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Delivery Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    def fetch_issue_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand
            if self.config_id.odata_select:
                params['$select'] = self.config_id.odata_select
            if reference_nbr:
                filters.append(f"ReferenceNbr eq '{reference_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            if odata_filter:
                filters.append(f"({odata_filter})")
            # elif self.odata_filter:
            #     filters.append(f"({self.odata_filter})")

            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Issue Change Item (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            move_result = []
            print(f"Get Inventory Issue data from Acumatica: {len(raw_data)} records fetched with params: {params}")
            for row_number, item in enumerate(raw_data, start=1):

                print(f"Item: {item}")
         
                type = self._search_picking_type(item)
                if type:
                    type = type.id
                if not type:
                    type = None


                result.append( {
                    'external_id': item.get('id', '') or '',
                    'row_number': item.get('rowNumber', '') or '', 
                    'note': item.get('note', {}).get('', '') or '',
                    'branch_warehouse': self._val(item, 'LocationID'),
                    'actual_amount': self._val(item, 'ControlQty'),
                    'actual_qty': self._val(item, 'ControlQty'),
                    'scheduled_date': self._val(item, 'ShipmentDate'),
                    'description': self._val(item, 'Description'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'reference_nbr': self._val(item, 'ShipmentNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'ShippedQty'),
                    'trans_type': self._val(item, 'Type') or self._val(item, 'Type'),
                    'picking_type_id': type,
                    'warehouse_code': self._val(item, 'WarehouseID'),
                    'branch_warehouse': self._val(item, 'WarehouseName'),
                })
                print(f" Get data : {item['ShipmentNbr']}, Trans Type: {item['Type']}, Status: {item['Status']}")


                print(f"Result: {result[-1]}")
                details = item.get('Details') or item.get('details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []


                # if not details:
                #     result.append(dict(item, line_nbr='0'))
                #     continue

                for detail in details:
                    line_nbr = self._val(detail, 'LineNumber') or self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    move_result.append({
                        'external_id': item.get('id', '') or '',
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'branch_warehouse': self._val(detail, 'Branch'),
                        'line_description': self._val(detail, 'Description'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'location_code': self._val(detail, 'Location'),
                        'product_uom_qty': self._val(detail, 'Qty'),
                        'line_trans_type': self._val(detail, 'TranType'),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_code': self._val(detail, 'WarehouseID'),
                    })

            _logger.info('Berhasil ambil %s rows Issue Change Item dari Acumatica', len(result))
            self.config_id.last_sync = fields.Datetime.now()
            return result, move_result
        finally:
            self.config_id._do_logout(session)


    def action_fetch_data(self):
        self.ensure_one()
        self.env['acumatica.issue.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data, batch_move_data  = self.fetch_issue_data(
                limit=self.batch_size,
                offset=offset,
                reference_nbr=self.reference_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )

            print(f"Batch Data: {batch_data}")
            print(f"Batch Move Data: {batch_move_data}")

            if not batch_data:
                break

            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        existing_keys = set()
        new_keys = set()
        lines_to_create = []

        for item in raw_list:
            origin = item.get('reference_nbr')
            exists = bool(origin and Picking.search_count([('origin', '=', origin)]))
            if exists:
                existing_keys.add(origin)
                msg = 'Sudah ada → move akan ditambahkan jika belum ada'
            else:
                new_keys.add(origin)
                msg = ''

            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': msg,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })
            print(f"vals: {vals}")
            lines_to_create.append(vals)
            print(f"lines to create: {lines_to_create}")
            # raise UserError(f"Debug:")

        self.env['acumatica.issue.line'].create(lines_to_create)
        self.write({
            'state': 'fetched',
            'total_fetched': len(raw_list),
            'total_new': len([x for x in new_keys if x]),
            'total_existing': len([x for x in existing_keys if x]),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.issue.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Issue Change Item dari Acumatica',
            'res_model': 'acumatica.issue.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.issue.line'].search([
            ('config_id', '=', self.config_id.id),
            ('import_state', '=', 'pending'),
            ('selected', '=', True),
        ])
        if not lines:
            raise UserError('Tidak ada data pending yang dipilih untuk diimport.')
        lines._do_import()
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hasil Import Delivery Order',
            'res_model': 'acumatica.issue.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }

    def _normalize_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    def _val(self, item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        warehouse_code = header.get('WarehouseID')
        type = False

        print(f"Warehouse Code: {warehouse_code}")

        location = Location.search([
            ('code', '=', warehouse_code)
        ])

        print(f"Location: {location.id}")

        if location:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'outgoing'),                
                ('is_default_api', '=', True)
            ])

        return type
