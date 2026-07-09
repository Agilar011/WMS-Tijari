import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ImportTransferTwoStepWizard(models.TransientModel):
    _name = 'import.transfer.two.step.wizard'
    _description = 'Wizard Import Transfer Two Step dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help="Contoh: 2025-01-01T00:00:00+07:00")
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Transfer Order Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan diupdate)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

    def action_fetch_data(self):
        print(f"self: {self}")
        self.ensure_one()
        self.env['acumatica.transfer.two.step.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        line_raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data, batch_line = self.fetch_receipt_data(
                limit=self.batch_size,
                offset=offset,
                reference_nbr=self.reference_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)
            line_raw_list.extend(batch_line)

            # raise UserError('Checkpoint')
        
        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        existing_receipts = set()
        new_receipts = set()
        lines_to_create = []
        move_lines_to_create = []

        for item in raw_list:
            reference_nbr = item.get('reference_nbr')
            header_id = item.get('external_id')
            exists = bool(reference_nbr and Picking.search_count([('origin', '=', reference_nbr)]))
            if exists:
                existing_receipts.add(reference_nbr)
                msg = 'Sudah ada → akan diupdate'
            else:
                new_receipts.add(reference_nbr)
                msg = ''
            vals = dict(item)
            vals.update({
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': msg,
                'selected': True,
                'sync_date': fields.Datetime.now(),
            })
            # lines_to_create.append(vals)
            created_picking = self.env['acumatica.transfer.two.step.line'].create(vals)
            self.write({
                'state': 'fetched',
                'total_fetched': len(raw_list),
                'total_new': len([r for r in new_receipts if r]),
                'total_existing': len([r for r in existing_receipts if r]),
            })

            for line in raw_move_list:
                # Pastikan mencocokkan berdasarkan field referensi yang sama (misal: reference_nbr)
                if line.get('acumatica_header_id') == header_id:
                    move_vals = dict(line)
                    # Jika field relasi di tabel child Odoo bernama 'header_id', 
                    # kita belum bisa mengisinya di sini karena header belum di-create (.create())
                    move_vals.update({
                        'header_id': created_picking.id,
                    })
                    move_lines_to_create = self.env['acumatica.transfer.one.step.line.product'].create(move_vals)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.transfer.two.step.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def fetch_receipt_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
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
            if self.config_id.odata_filter:
                filters.append(f"({self.config_id.odata_filter})")
            else:
                filters.append("(TransferType eq '1-Step')")

            if filters:
                params['$filter'] = ' and '.join(filters)       

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Order (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            line_result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', {}),
                    'note': item.get('note', {}).get('value', '') or '',
                    'scheduled_date': self._val(item, 'Date'),
                    'is_hold': self._val(item, 'Hold'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'transfer_type': self._val(item, 'TransferType'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'to_warehouse_code': self._val(item, 'ToWarehouseID'),
                    'from_warehouse_code': self._val(item, 'FromWarehouseID'),
                    'description': self._val(item, 'Description'),
                    'trans_type': self._val(item, 'TransType'),
                }

                if header.get('from_warehouse_code'):
                    # Kirim data header ke fungsi pembantu
                    type_record = self._search_picking_type(header)

                    # print(f"")
                    # Ambil ID integer secara aman, gunakan False standar Odoo (bukan None)
                    header['picking_type_id'] = type_record.id if type_record else False

                result.append(header)
                print(f" Header result: {result}")

                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    result.append(dict(header, line_nbr='0'))
                    continue

                for detail in details:
                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    description = self._val(detail, 'Description') or self._val(detail, 'TransactionDescription')
                    warehouse_dest_code = self._val(detail, 'Warehouse') or header.get('warehouse_code')

                    line_result.append({
                        'acumatica_header_id' : item.get('id', {}),
                        'adt_rowNumber': str(line_nbr),
                        'adt_note' : detail.get('note', {}).get('value', '') or '',
                        'adt_Description': self._val(detail, 'Description'),
                        'adt_FromLocationID': self._val(detail, 'FromLocationID'),
                        'adt_InventoryID': self._val(detail, 'InventoryID'),
                        'adt_LineNumber' : str(line_nbr),
                        # 'adt_NoteID'
                        'adt_Quantity' : self._val(detail, 'Quantity'),
                        # 'adt_SOOrderNbr'
                        # 'adt_SOOrderType'
                        # 'adt_SOShipmentNbr'
                        'adt_ToLocationID' : self._val(detail, 'ToLocationID'),
                        'adt_UOM' : self._val(detail, 'UOM'),
                    })
                    print(f" Line result: {line_result}")

            _logger.info("Berhasil ambil %s rows Transfer Order dari Acumatica", len(result))
            return result, line_result
        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    def _val(self, item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

    def _normalize_rows(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        type = False

        print(f"Warehouse: {header['from_warehouse_code']}")

        location = Location.search([
            ('code', '=', header['from_warehouse_code'])
        ])

            
        if location:
            print(f"location : {location}")
            print(f"location : {location.odoo_building_id.id}")
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'internal'),
                ('is_default_api', '=', True)
            ])

            print(f"Type: {type}")

        return type if type else None


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Transfer Two Step dari Acumatica',
            'res_model': 'acumatica.transfer.two.step.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.transfer.two.step.line'].search([
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
            'name': 'Hasil Import Transfer Two Step dari Acumatica',
            'res_model': 'acumatica.transfer.two.step.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
