from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
from datetime import datetime, time, timezone


import logging
_logger = logging.getLogger(__name__)


class ImportInventoryRecievedWizard(models.TransientModel):
    _name = 'import.inventory.recieved.wizard'
    _description = 'Wizard Import Inventory Receipt dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    reference_nbr = fields.Char(string='Filter Reference Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter' , help='Filter tambahan untuk query OData. Contoh: TransDate ge 2026-01-01T00:00:00Z')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Data Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    def action_fetch_data(self):
        self.ensure_one()

        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        params = []
        if self.start_date and self.end_date:
            start_date_datetime_str = datetime.combine(
                fields.Date.to_date(self.start_date),
                time.min,
                tzinfo=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
            end_date_datetime_str = datetime.combine(
                fields.Date.to_date(self.end_date),
                time.min,
                tzinfo=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
            params.append(f"Date ge datetimeoffset'{start_date_datetime_str}' and Date le datetimeoffset'{end_date_datetime_str}'")

            # params.append(f"Date ge date'{self.start_date}' and Date le date'{self.end_date}'")
        if self.odata_filter:
            params.append(self.odata_filter)

        # for i in range(loop_count):
        #     offset = self.fetch_skip + (i * self.batch_size)
        #     batch_data = self.fetch_inventory_recieved_data()

        #     if not batch_data:
        #         break

        #     raw_list += batch_data
        batch_data = self.fetch_inventory_recieved_data()
        self.total_fetched = batch_data
        if not batch_data:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

    @staticmethod
    def _val(item, key):
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

    @staticmethod
    def _normalize_rows(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if isinstance(payload.get('value'), list):
                return payload.get('value')
            if isinstance(payload.get('rows'), list):
                return payload.get('rows')
        return []

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']
        type = False

        mapped_type = self.config_id._resolve_inventory_receive_picking_type(
            transfer_type=header.get('transfer_type'),
            document_only=header.get('document_only'),
            warehouse_code=header.get('warehouse_code'),
        )
        if mapped_type:
            return mapped_type

        location = Location.search([
            ('code', '=', header['warehouse_code'])
        ])
        if location:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'incoming'),
                ('is_default_api', '=', True)
            ])

        return type if type else None

    def _coalesce_val(self, item, *keys):
        for key in keys:
            value = self._val(item, key)
            if value not in (False, None, ''):
                return value
        return ''

    def _extract_details(self, item, detail_key):
        details = item.get(detail_key) or item.get('Details') or []
        if isinstance(details, dict):
            details = details.get('value', []) or []
        return details if isinstance(details, list) else []

    def _is_transfer_in_type(self, value):
        return str(value or '').strip().lower().replace('-', '_').replace(' ', '_') in (
            'transfer_in',
            'transfer_receipt',
        )

    def _build_inventory_receipt_header(self, row_number, item, header_id, warehouse_code, warehouse_dest_code=False):
        transfer_type = self._val(item, 'TransType')
        header = {
            'external_id': header_id,
            'row_number': item.get('rowNumber') or row_number,
            'note': self._val(item, 'NoteHeader'),
            'branch_warehouse': self._val(item, 'Branch'),
            'change_item_ref_nbr': self._val(item, 'ChangeItemRefNbr'),
            'actual_qty': self._val(item, 'ControlQty'),
            'customer_code': self._val(item, 'CustomerID'),
            'scheduled_date': self._val(item, 'Date'),
            'description': self._val(item, 'Description'),
            'document_only': self._bool_val(item, 'DocumentOnly'),
            'external_ref': self._val(item, 'ExternalRef'),
            'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
            'location_code': str(self._val(item, 'Location')),
            'post_period': str(self._val(item, 'PostPeriod')),
            'reference_nbr': self._val(item, 'ReferenceNbr'),
            'shipment_nbr': self._val(item, 'ShipmentNbr'),
            'status': self._val(item, 'Status'),
            'total_qty': str(self._val(item, 'TotalQty')),
            'transfer_nbr': self._val(item, 'TransferNbr'),
            'transfer_type': transfer_type,
            'warehouse_code': warehouse_code,
            'warehouse_dest_code': warehouse_dest_code or warehouse_code,
        }
        picking_type = self._search_picking_type(header)
        header['picking_type_id'] = picking_type.id if picking_type else None
        return header

    def _build_inventory_receipt_detail(self, header_id, detail, warehouse_code):
        return {
            'header_external_id': header_id,
            'line_external_id': detail.get('id', '') or '',
            'line_nbr': str(self._val(detail, 'LineNbr')),
            'line_note': self._val(detail, 'LineNote'),
            'branch_warehouse': self._val(detail, 'LineBranch'),
            'line_description': self._val(detail, 'LineInventoryName'),
            'inventory_id': self._val(detail, 'LineInventoryID'),
            'location_code': self._val(detail, 'LineLocation'),
            'product_uom_qty': str(self._val(detail, 'LineQuantity')),
            'uom_code': self._val(detail, 'LineUOM'),
            'warehouse_dest_code': warehouse_code,
        }

    def fetch_inventory_recieved_data(self):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {}
            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand

            response = session.put(endpoint, params=params, json={"TransType": {"value": ""}}, timeout=300)
            if response.status_code != 200:
                raise UserError(f'Gagal fetch data Inventory Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = response.json()
            result = []
            detail_result = []
            headers_seen = set()

            data = raw_data.get("InventoryReceiptGIDetails", [])
            for row_number, item in enumerate(data, start=1):
                ref = self._val(item, 'ReferenceNbr')
                details = self._extract_details(item, self.config_id.odata_expand or 'InventoryReceiptGIDetails')
                if not details:
                    details = [item]

                transfer_type = self._val(item, 'TransType')
                line_warehouse = self._val(item, 'LineWarehouse') or self._val(item, 'LineWarehouseID')
                if self._is_transfer_in_type(transfer_type):
                    warehouse_code = (
                        self._val(item, 'FromWarehouseID')
                        or self._val(item, 'WarehouseID')
                        or line_warehouse
                    )
                    warehouse_dest_code = (
                        self._val(item, 'ToWarehouseID')
                        or self._val(item, 'Warehouse')
                        or self._val(item, 'LineWarehouseID')
                        or line_warehouse
                    )
                else:
                    warehouse_code = line_warehouse
                    warehouse_dest_code = warehouse_code
                header_id = ref or item.get('id', '')

                if header_id not in headers_seen:
                    result.append(self._build_inventory_receipt_header(row_number, item, header_id, warehouse_code, warehouse_dest_code))
                    headers_seen.add(header_id)

                for detail in details:
                    detail_result.append(self._build_inventory_receipt_detail(header_id, detail, warehouse_dest_code))

            self.config_id.last_sync = fields.Datetime.now()
            _logger.info("Berhasil ambil %s rows Inventory Receipt dari Acumatica", len(result))
            self._validate_staging_against_picking(result, detail_result)
            return len(result)

        finally:
            self.config_id._do_logout(session)

    def _validate_staging_against_picking(self, header_list, line_list):
        Picking = self.env['stock.picking']
        lines_to_create = []
        sync_data = fields.Datetime.now()
        for item in header_list:
            
            reference_nbr = item.get('reference_nbr')
            exists = Picking.search_read(
                domain=[('origin', '=', reference_nbr)],
                fields=['id', 'origin'],
                limit=1
            )
            lines_to_create.append({
                **item,
                'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': f'{reference_nbr}: Sudah ada → akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_inventory_lines(lines_to_create)
            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_inventory_lines(to_update)

            inventory = self._create_inventory_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                self._update_inventory_lines_product(line_update, to_update)

            if line_create:
                self._create_inventory_lines_product(line_create, inventory)

    def _search_inventory_lines(self, data):
        if not data:
            return [], [], []

        reference_nbrs = [
            d['reference_nbr']
            for d in data
            if d.get('reference_nbr')
        ]
        existing_lines = self.env['acumatica.inventory.recieved.line'].search([
            ('reference_nbr', 'in', reference_nbrs)
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


            if existing.acumatica_write_date == self._parse_dt(vals['acumatica_write_date']):
                unchanged.append(existing)
            else:
                to_update.append({
                    'record': existing,
                    'vals': vals,
                })

        return unchanged, to_update, to_create

    def _update_inventory_lines(self, data):
        if not data:
            return False

        for item in data:
            record = item['record']
            vals = item['vals']


            record.write(vals)

    def _create_inventory_lines(self, data):
        if not data:
            return False

        return self.env['acumatica.inventory.recieved.line'].create(data)

    def filter_product_line(self, data, update, create):
        # buat set dari semua external_id di update
        update_ids = {
            item.get('vals', {}).get('external_id')
            for item in update
            if item.get('vals', {}).get('external_id')
        }

        # filter data yang header_external_id ada di update_ids
        update_final = [
            line 
            for line in data 
            if line['header_external_id'] in update_ids
        ]

        # buat set dari semua external_id di create
        create_ids = {
            crt['external_id'] 
            for crt in create
        }

        # filter data yang header_external_id ada di create_ids
        create_final = [line for line in data if line['header_external_id'] in create_ids]

        return update_final, create_final
        
    def filter_by_inventory_lines(self, data, inventory):
        """
        Filter data berdasarkan header_external_id yang ada di inventory.
        
        :param data: list of dict (to_create atau to_update)
        :param inventory: recordset inventory
        :return: list of dict yang header_external_id-nya ada di inventory
        """
        inventory_ids = {rec['external_id'] for rec in inventory}

        filtered_data = [
            vals for vals in data
            if vals.get('header_external_id') in inventory_ids
        ]

        return filtered_data

    def _create_inventory_lines_product(self, data, inventory):
        inventory_map = {
            rec['external_id']: rec.id
            for rec in inventory
        }

        for vals in data:
            vals['inventory_line_id'] = inventory_map.get(
                vals['header_external_id']
            )

        self.env['acumatica.inventory.recieved.product.line'].create(data)

    def _update_inventory_lines_product(self, data, inventory):
        inventory_map = {
            rec['vals']['external_id']: rec['record']['id']
            for rec in inventory
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.inventory.recieved.product.line']

        for vals in data:
            ext_id = vals.get('header_external_id')
            vals['inventory_line_id'] = inventory_map.get(ext_id)
            if vals['inventory_line_id']:
                product_line.browse(vals['inventory_line_id']).write(vals)


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Inventory Receipt dari Acumatica',
            'res_model': 'acumatica.inventory.recieved.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.inventory.recieved.line'].search([
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
            'name': 'Hasil Import Inventory Receipt',
            'res_model': 'acumatica.inventory.recieved.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
