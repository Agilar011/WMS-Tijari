from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)


# toko.pegang.do
# toko_pegang_do
class ImportTokoPegangDOWizard(models.TransientModel):
    _name = 'import.toko.pegang.do.wizard'
    _description = 'Wizard Import Inventory Recieved dari Acumatica'

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
            params.append(f"Date ge date'{self.start_date}' and Date le date'{self.end_date}'")
        if self.odata_filter:
            params.append(self.odata_filter)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_toko_pegang_do_data(
                limit=self.batch_size,
                offset=offset,
                reference_nbr=self.reference_nbr,
                odata_filter=params if params else None,
            )

            if not batch_data:
                break

            raw_list += batch_data

        self.total_fetched = raw_list
        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

    @staticmethod
    def _val(item, key):
        value = item.get(key, {})
        if isinstance(value, dict):
            return value.get('value', '') or ''
        return value or ''

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

    def fetch_toko_pegang_do_data(self, limit=50, offset=0, reference_nbr=False, odata_filter=False):
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
            if odata_filter:
                filters.append(self.config_id.odata_filter)
                filters.extend(odata_filter)
            else:
                filters.append(f"({self.config_id.odata_filter})")
            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(f'Gagal fetch data (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            detail_result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': item.get('rowNumber', '') or '',
                    'note': item.get('note', {}).get('value', '') or '',
                    'branch_warehouse': self._val(item, 'Branch'),
                    'change_item_ref_nbr': self._val(item, 'ChangeItemRefNbr'),
                    'actual_qty': self._val(item, 'ControlQty'),
                    'customer_code': self._val(item, 'Customer'),
                    'scheduled_date': self._val(item, 'Date'),
                    'description': self._val(item, 'Description'),
                    # DocumentOnly
                    'external_ref': self._val(item, 'ExternalRef'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'location_code': str(self._val(item, 'Location')),
                    'post_period': str(self._val(item, 'PostPeriod')),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'shipment_nbr': self._val(item, 'ShipmentNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': str(self._val(item, 'TotalQty')),
                    'transfer_nbr': self._val(item, 'TransferNbr'),
                    'transfer_type': self._val(item, 'TransType'),
                    'warehouse_code': self._val(item, 'Warehouse')
                }
                
                details = item.get('Details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []


                # transfer_nbr = header['transfer_nbr']
                # if transfer_nbr:
                #     dest_warehouse_data = self.search_dest_warehouse(transfer_nbr, session)
                #     if dest_warehouse_data:
                #         header["warehouse_code"] = dest_warehouse_data.get('source_warehouse')
                        # header["warehouse_dest_code"] = dest_warehouse_data.get('dest_warehouse')

                if header['warehouse_code']:
                    type = self._search_picking_type(header)
                    header['picking_type_id'] = type.id if type else None

                result.append(header)


                for detail in details:
                    detail_result.append({        
                        'header_external_id': header['external_id'],
                        'line_external_id': detail.get('id', '') or '',
                        'line_nbr': str(self._val(detail, 'LineNbr')),
                        'line_note': self._val(detail, 'note'),
                        'branch_warehouse': self._val(detail, 'Branch'),
                        'line_description': self._val(detail, 'Description'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'location_code': self._val(detail, 'Location'),
                        'product_uom_qty': str(self._val(detail, 'Quantity')),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_dest_code': self._val(detail, 'Warehouse'),
                    })

            self.config_id.last_sync = fields.Datetime.now()
            _logger.info("Berhasil ambil %s rows PO inventory dari Acumatica", len(result))
            self._validate_staging_against_picking(result, detail_result)
            return len(result)

        finally:
            self.config_id._do_logout(session)

    # def search_dest_warehouse(self, transfer_nbr, session):
    #     self.ensure_one()
    #     if not transfer_nbr:
    #         return None
    #     try:
    #         endpoint = f"{self.config_id.api_url}/TransferOrder"
    #         params = {
    #             '$select': 'ToWarehouseID, FromWarehouseID, ReferenceNbr', 
    #             '$filter': f"ReferenceNbr eq '{transfer_nbr}'"
    #         }

    #         response = session.get(endpoint, params=params, timeout=90)
    #         if response.status_code != 200:
    #             raise UserError(f'Gagal ambil data Destination Warehouse (HTTP {response.status_code}): {response.text}')

    #         raw_data = self._normalize_rows(response.json())

    #         item = raw_data[0]  # misal ambil data pertama

    #         result = {
    #             'shipment_number': self._val(item, 'ShipmentNbr'),
    #             'dest_warehouse': self._val(item, 'ToWarehouseID'),
    #             'source_warehouse': self._val(item, 'FromWarehouseID'),
    #         }

    #         _logger.info('Berhasil ambil data Warehouse dari Transfer', len(result))
    #         return result
    #     except Exception as e:
    #         _logger.error('Gagal ambil data Warehouse dari Transfer: %s', str(e))
    #         return None

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
        existing_lines = self.env['acumatica.toko.pegang.do.line'].search([
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

        return self.env['acumatica.toko.pegang.do.line'].create(data)

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

        self.env['acumatica.toko.pegang.do.product.line'].create(data)

    def _update_inventory_lines_product(self, data, inventory):
        inventory_map = {
            rec['vals']['external_id']: rec['record']['id']
            for rec in inventory
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.toko.pegang.do.product.line']

        for vals in data:
            ext_id = vals.get('header_external_id')
            vals['inventory_line_id'] = inventory_map.get(ext_id)
            if vals['inventory_line_id']:
                product_line.browse(vals['inventory_line_id']).write(vals)


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Inventory Recieved dari Acumatica',
            'res_model': 'acumatica.toko.pegang.do.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.toko.pegang.do.line'].search([
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
            'name': 'Hasil Import Inventory Recieved',
            'res_model': 'acumatica.toko.pegang.do.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
