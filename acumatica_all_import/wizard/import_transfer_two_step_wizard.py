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
        self.ensure_one()

        raw_list, line_raw_list = self.fetch_transfer_two_step_data()

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        self._validate_staging_against_transfer(raw_list, line_raw_list)

        self.total_fetched = len(raw_list)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.transfer.two.step.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _validate_staging_against_transfer(self, header_list, line_list):
        InternalTransferOrder = self.env['internal.transfer.order']
        sync_data = fields.Datetime.now()
        lines_to_create = []

        for item in header_list:
            reference_nbr = item.get('reference_nbr')
            existing_transfer = InternalTransferOrder.search_read(
                domain=[('external_ref', '=', reference_nbr)],
                fields=['id', 'external_ref'],
                limit=1,
            )

            lines_to_create.append({
                **item,
                'odoo_internal_transfer_order_id': existing_transfer[0]['id'] if existing_transfer else False,
                'config_id': self.config_id.id,
                'import_state': 'staged',
                'import_message': f'{reference_nbr}: Sudah ada → akan diupdate' if existing_transfer else '',
                'selected': True,
                'sync_date': sync_data,
            })

        if not lines_to_create:
            return {'created': 0, 'updated': 0, 'unchanged': 0}

        unchanged, to_update, to_create = self._search_transfer_two_step_lines(lines_to_create)
        self._update_transfer_two_step_lines(to_update)
        created_headers = self._create_transfer_two_step_lines(to_create)

        line_update, line_create = self._filter_transfer_two_step_product_lines(
            line_list,
            to_update,
            to_create,
        )
        if line_update:
            self._update_transfer_two_step_product_lines(line_update, to_update)
        if line_create:
            self._create_transfer_two_step_product_lines(line_create, created_headers)

        return {
            'created': len(to_create),
            'updated': len(to_update),
            'unchanged': len(unchanged),
        }

    def _search_transfer_two_step_lines(self, data):
        if not data:
            return [], [], []

        reference_nbrs = [
            vals['reference_nbr']
            for vals in data
            if vals.get('reference_nbr')
        ]
        existing_lines = self.env['acumatica.transfer.two.step.line'].search([
            ('reference_nbr', 'in', reference_nbrs),
            ('config_id', '=', self.config_id.id),
        ])
        existing_map = {
            line.reference_nbr: line
            for line in existing_lines
        }

        unchanged = []
        to_update = []
        to_create = []

        for vals in data:
            existing = existing_map.get(vals['reference_nbr'])
            if not existing:
                to_create.append(vals)
                continue

            if existing.acumatica_write_date == vals['acumatica_write_date']:
                unchanged.append(existing)
            else:
                to_update.append({
                    'record': existing,
                    'vals': vals,
                })

        return unchanged, to_update, to_create

    def _update_transfer_two_step_lines(self, data):
        for item in data:
            item['record'].write(item['vals'])

    def _create_transfer_two_step_lines(self, data):
        if not data:
            return self.env['acumatica.transfer.two.step.line']
        return self.env['acumatica.transfer.two.step.line'].create(data)

    def _filter_transfer_two_step_product_lines(self, data, update, create):
        update_ids = {
            item.get('vals', {}).get('reference_nbr')
            for item in update
            if item.get('vals', {}).get('reference_nbr')
        }
        create_ids = {
            vals.get('reference_nbr')
            for vals in create
            if vals.get('reference_nbr')
        }

        update_final = [
            vals for vals in data
            if vals.get('reference_nbr') in update_ids
        ]
        create_final = [
            vals for vals in data
            if vals.get('reference_nbr') in create_ids
        ]

        return update_final, create_final

    def _create_transfer_two_step_product_lines(self, data, headers):
        header_map = {
            header.reference_nbr: header.id
            for header in headers
        }
        vals_list = []
        for vals in data:
            header_id = header_map.get(vals.get('reference_nbr'))
            if header_id:
                vals_list.append({
                    **vals,
                    'header_id': header_id,
                })
        if vals_list:
            self.env['acumatica.transfer.two.step.line.product'].create(vals_list)

    def _update_transfer_two_step_product_lines(self, data, headers):
        header_map = {
            item['vals']['reference_nbr']: item['record']
            for item in headers
            if item.get('vals') and item.get('record')
        }
        ProductLine = self.env['acumatica.transfer.two.step.line.product']
        vals_list = []
        refreshed_headers = self.env['acumatica.transfer.two.step.line']

        for vals in data:
            header = header_map.get(vals.get('reference_nbr'))
            if not header:
                continue
            if header not in refreshed_headers:
                refreshed_headers |= header
            vals_list.append({
                **vals,
                'header_id': header.id,
            })

        refreshed_headers.mapped('line_ids').unlink()
        if vals_list:
            ProductLine.create(vals_list)

    def fetch_transfer_two_step_data(self):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {}

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand

            response = session.put(endpoint, params=params, json={"TransferType": {"value": "2 Step"}}, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Order (HTTP {response.status_code}): {response.text}')

            raw_data = response.json()
            result = []
            line_result = []

            detail_rows = (
                raw_data.get("TransferOrderGIDetails")
                or raw_data.get("TransferPinjamanGIDetails")
                or []
            )
            if isinstance(detail_rows, dict):
                detail_rows = detail_rows.get("value", []) or []
            if not isinstance(detail_rows, list):
                detail_rows = []

            if self.reference_nbr:
                detail_rows = [
                    item for item in detail_rows
                    if self._val(item, 'ReferenceNbr') == self.reference_nbr
                ]
            if self.last_modified_from:
                detail_rows = [
                    item for item in detail_rows
                    if self._val(item, 'LastModifiedDateTime') >= self.last_modified_from
                ]
            if self.fetch_skip:
                detail_rows = detail_rows[self.fetch_skip:]
            if self.fetch_limit:
                detail_rows = detail_rows[:self.fetch_limit]

            headers_by_ref = {}
            header_order = []

            for row_number, item in enumerate(detail_rows, start=1):
                reference_nbr = self._val(item, 'ReferenceNbr')
                header_id = (
                    self._val(item, 'NoteHeaderID')
                    or raw_data.get('id')
                    or reference_nbr
                    or item.get('id')
                )

                if reference_nbr not in headers_by_ref:
                    header_order.append(reference_nbr)
                    headers_by_ref[reference_nbr] = {
                        'external_id': header_id,
                        'row_number': row_number,
                        'note': self._val(item, 'NoteHeader') or item.get('note', '') or '',
                        'scheduled_date': self._val(item, 'Date'),
                        'external_ref': self._val(item, 'ExternalRef'),
                        'is_hold': self._val(item, 'Hold'),
                        'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                        'note_header_id': self._val(item, 'NoteHeaderID'),
                        'post_period': self._val(item, 'PostPeriod'),
                        'status': self._val(item, 'Status'),
                        'total_qty': self._val(item, 'TotalQty'),
                        'transfer_type': self._val(item, 'TransferType'),
                        'return_type': self._val(item, 'ReturnType'),
                        'reference_nbr': reference_nbr,
                        'to_warehouse_code': self._val(item, 'ToWarehouseID'),
                        'to_warehouse_name': self._val(item, 'ToWarehouseName'),
                        'from_warehouse_code': self._val(item, 'FromWarehouseID'),
                        'from_warehouse_name': self._val(item, 'FromWarehouseName'),
                        'description': self._val(item, 'Description'),
                        'document_only': self._bool_val(item, 'DocumentOnly'),
                        'trans_type': self._val(item, 'TransType'),
                    }

                    if headers_by_ref[reference_nbr].get('from_warehouse_code'):
                        type_record = self._search_picking_type(headers_by_ref[reference_nbr])
                        headers_by_ref[reference_nbr]['picking_type_id'] = type_record.id if type_record else False

                line_number = (
                    self._val(item, 'LineNumber')
                    or self._val(item, 'LineNbr')
                    or item.get('rowNumber')
                    or 0
                )
                line_result.append({
                    'acumatica_header_id': reference_nbr,
                    'reference_nbr': reference_nbr,
                    'adt_rowNumber': str(line_number),
                    'adt_note': self._val(item, 'LineNote') or item.get('note', '') or '',
                    'adt_Description': self._val(item, 'LineDescription') or self._val(item, 'Description'),
                    'adt_FromLocationID': self._val(item, 'LineFromLocationID') or self._val(item, 'FromLocationID'),
                    'adt_InventoryID': self._val(item, 'LineInventoryID') or self._val(item, 'InventoryID'),
                    'adt_LineNumber': str(line_number),
                    'adt_NoteID': self._val(item, 'LineNoteID'),
                    'adt_LineNoteID': self._val(item, 'LineNoteID'),
                    'adt_Quantity': self._val(item, 'LineQuantity') or self._val(item, 'Quantity'),
                    'adt_SOOrderNbr': self._val(item, 'LineSOOrderNbr'),
                    'adt_SOOrderType': self._val(item, 'LineSOOrderType'),
                    'adt_SOShipmentNbr': self._val(item, 'LineSOShipmentNbr'),
                    'adt_ToLocationID': self._val(item, 'LineToLocationID') or self._val(item, 'ToLocationID'),
                    'adt_UOM': self._val(item, 'LineUOM') or self._val(item, 'UOM'),
                })

            result = [headers_by_ref[reference_nbr] for reference_nbr in header_order]

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

    @staticmethod
    def _bool_value(value):
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, bool):
            return value
        if value in (False, None, ''):
            return False
        return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'document only')

    def _bool_val(self, item, key):
        return self._bool_value(item.get(key, {}))

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
        config_picking_type = self.config_id._get_config_picking_type() if self.config_id else False
        if config_picking_type:
            return config_picking_type

        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        type = False

        document_only_type = PickingType.resolve_document_only_picking_type(
            api_acumatica='transfer_two_step',
            document_only=header.get('document_only'),
            warehouse_code=header.get('from_warehouse_code'),
        )
        if document_only_type:
            return document_only_type

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
            ('import_state', '=', 'staged'),
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
