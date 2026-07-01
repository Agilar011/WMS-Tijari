from odoo import fields, models
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser

import logging
_logger = logging.getLogger(__name__)

from datetime import datetime, time, timezone

class ImportShipmentWizard(models.TransientModel):
    _name = 'import.shipment.wizard'
    _description = 'Wizard Import Shipment Receipt dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    shipment_nbr = fields.Char(string='Filter Shipment Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')
    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Receipt Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')
    wh33_filter = fields.Boolean(string='Filter WH33', default=True, help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')

    def action_fetch_data(self):
        self.ensure_one()
        # self.env['acumatica.shipment.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = 0
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        params = []
        if self.wh33_filter:
            params.append("startswith(WarehouseID,'WH33')")
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
            params.append(f"ShipmentDate ge datetimeoffset'{start_date_datetime_str}' and ShipmentDate le datetimeoffset'{end_date_datetime_str}'")
        if self.odata_filter:
            params.append(self.odata_filter)


        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data = self.fetch_shipment_data(
                limit=self.batch_size,
                offset=offset,
                shipment_nbr=self.shipment_nbr,
                odata_filter=params if params else None,
            )

            if not batch_data:
                break

            raw_list += batch_data

        self.total_fetched = raw_list
        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.shipment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Shipment Receipt dari Acumatica',
            'res_model': 'acumatica.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.shipment.line'].search([
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
            'name': 'Hasil Import Shipment Receipt',
            'res_model': 'acumatica.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
    
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

    def _search_picking_type(self, header):
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']

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

    def fetch_shipment_data(self, limit=50, offset=0, shipment_nbr=False, last_modified_from=False, odata_filter=False):
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
            if shipment_nbr:
                filters.append(f"ShipmentNbr eq '{shipment_nbr}'")
            if odata_filter:
                filters.extend(odata_filter)
            if self.config_id.odata_filter:
                filters.append(self.config_id.odata_filter)
            else:
                filters.append("(Type eq 'Shipment' and Operation eq 'Receipt')")

            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Shipment Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            detail_result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'actual_qty': self._val(item, 'ControlQty'),
                    'partner_code': self._val(item, 'CustomerID'),
                    'description': self._val(item, 'Description'),
                    'fob_point': self._val(item, 'FOBPoint'),
                    'fob_point_description': self._val(item, 'FOBPointDescription'),
                    'is_hold': self._val(item, 'Hold'),
                    'is_insurance': self._val(item, 'Insurance'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'LocationID'),
                    'header_location_name': self._val(item, 'LocationName'),
                    'operation': self._val(item, 'Operation'),
                    'package_count': self._val(item, 'PackageCount'),
                    'package_weight': self._val(item, 'PackageWeight'),
                    'is_picked': self._val(item, 'Picked'),
                    'scheduled_date': self._val(item, 'ShipmentDate'),
                    'shipment_nbr': self._val(item, 'ShipmentNbr'),
                    'shipped_qty': self._val(item, 'ShippedQty'),
                    'shipped_volume': self._val(item, 'ShippedVolume'),
                    'shipped_weight': self._val(item, 'ShippedWeight'),
                    'shipping_terms': self._val(item, 'ShippingTerms'),
                    'shipping_settings': self._val(item, 'ShippingSettings'),
                    'shipping_zone': self._val(item, 'ShippingZoneID'),
                    'ship_via': self._val(item, 'ShipVia'),
                    'status': self._val(item, 'Status'),
                    'warehouse_dest_code': self._val(item, 'ToWarehouseID'),
                    'shipment_type': self._val(item, 'Type'),
                    'unlimited_packages': self._val(item, 'UnlimitedPackages'),
                    'warehouse_code': self._val(item, 'WarehouseID'),
                    'warehouse_name': self._val(item, 'WarehouseName'),
                }

                shipment_to_address = item.get('ShipToAddress') or item.get('shipToAddress') or {}
                if shipment_to_address:
                    shipment_to_address = {
                        'shipment_to_address_line_1': self._val(shipment_to_address, 'AddressLine1'),
                        'shipment_to_address_line_2': self._val(shipment_to_address, 'AddressLine2'),
                        'shipment_to_address_city': self._val(shipment_to_address, 'City'),
                        'shipment_to_address_country': self._val(shipment_to_address, 'Country'),
                        'shipment_to_address_country': self._val(shipment_to_address, 'CountryName'),
                        'shipment_to_address_postal_code': self._val(shipment_to_address, 'PostalCode'),
                        'shipment_to_address_state': self._val(shipment_to_address, 'State'),
                    }

                details = item.get('Details') or item.get('details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []
                if header['warehouse_code']:
                    type = self._search_picking_type(header)
                    header['picking_type_id'] = type.id if type else None

                result.append(**header, **shipment_to_address) if shipment_to_address else result.append(header)

                for detail in details:
                    allocations = detail.get('Allocations') or detail.get('allocations') or []
                    allocations_container = []
                    if isinstance(allocations, dict):
                        allocations = allocations.get('value', []) or []
                    if not isinstance(allocations, list):
                        allocations = []
                    if allocations:
                        for allocation in allocations:
                            allocations_container.append({
                                'allocation_line_external_id': allocation.get('id', '') or '',
                                'allocation_acumatica_id': allocation.get('id', '') or '',
                                'allocation_acumatica_row_number': allocation.get('rowNumber') or 0,
                                'allocation_detail_note': self._val(allocation, 'note'),
                                'allocation_line_description': self._val(allocation, 'Description'),
                                'allocation_inventory_id': self._val(allocation, 'InventoryID'),
                                'allocation_location_dest_code': self._val(allocation, 'LocationID'),
                                'allocation_qty': self._val(allocation, 'Quantity'),
                                'allocation_split_line_nbr': self._val(allocation, 'SplitLineNbr'),
                                'allocation_uom_code': self._val(allocation, 'UOM'),
                            })

                    line_nbr = self._val(detail, 'LineNbr')
                    detail_result.append({
                        # 'allocations': allocations_container,
                        'header_external_id': header['external_id'],
                        'line_external_id': detail.get('id', '') or '',
                        'note': detail.get('note', {}).get('value', '') or '',
                        'description': self._val(detail, 'Description'),
                        'is_free_item': self._val(detail, 'FreeItem'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'location_dest_code': self._val(detail, 'LocationID'),
                        'open_qty': self._val(detail, 'OpenQty'),
                        'order_qty': self._val(detail, 'OrderedQty'),
                        'order_line_number': self._val(detail, 'OrderLineNbr'),
                        'order_number': self._val(detail, 'OrderNbr'),
                        'order_type': self._val(detail, 'OrderType'),
                        'original_qty': self._val(detail, 'OriginalQty'),
                        'shipped_qty': self._val(detail, 'ShippedQty'),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_dest_code': self._val(detail, 'WarehouseID'),
                    })
                    # result.append({
                    #     **header,
                    #     **shipment_to_address,
                    # })
                    

            _logger.info('Berhasil ambil %s rows Shipment Receipt dari Acumatica', len(result))
            self._validate_staging_against_picking(result, detail_result)
            return len(result)
            # return result
        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    def _validate_staging_against_picking(self, header_list, line_list):
        Picking = self.env['stock.picking']
        lines_to_create = []
        sync_data = fields.Datetime.now()
        for item in header_list:
            
            shipment_nbr = item.get('shipment_nbr')
            exists = Picking.search_read(
                domain=[('origin', '=', shipment_nbr)],
                fields=['id', 'origin'],
                limit=1
            )
            lines_to_create.append({
                **item,
                'odoo_picking_id' : exists[0]['id'] if exists else False,
                'config_id': self.config_id.id,
                'import_state': 'pending',
                'import_message': f'{shipment_nbr}: Sudah ada → akan diupdate' if exists else '',
                'selected': True,
                'sync_date': sync_data,
            })

        if lines_to_create:
            # Lakukan pengecekan terlebih dahulu untuk filter data yg diperlukan
            unchanged, to_update, to_create = self._search_shipment_lines(lines_to_create)

            # Lanjut untuk mengolah data dari masing masing variabel yg telah di filter sebelumnya
            self._update_shipment_lines(to_update)

            shipments = self._create_shipment_lines(to_create)
            line_update, line_create = self.filter_product_line(line_list, to_update, to_create)
            if line_update:
                self._update_shipment_lines_product(line_update, to_update)

            if line_create:
                self._create_shipment_lines_product(line_create, shipments)

    def _search_shipment_lines(self, data):
        if not data:
            return [], [], []

        shipment_nbrs = [
            d['shipment_nbr']
            for d in data
            if d.get('shipment_nbr')
        ]
        existing_lines = self.env['acumatica.shipment.line'].search([
            ('shipment_nbr', 'in', shipment_nbrs)
        ])

        existing_map = {
            line.shipment_nbr: line
            for line in existing_lines
        }

        unchanged = []
        to_update = []
        to_create = []
        
        for vals in data:
            existing = existing_map.get(vals['shipment_nbr'])

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

    def _update_shipment_lines(self, data):
        if not data:
            return False

        for item in data:
            record = item['record']
            vals = item['vals']


            record.write(vals)

    def _create_shipment_lines(self, data):
        if not data:
            return False

        return self.env['acumatica.shipment.line'].create(data)

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
        
    def filter_by_shipment_lines(self, data, shipments):
        """
        Filter data berdasarkan header_external_id yang ada di shipments.
        
        :param data: list of dict (to_create atau to_update)
        :param shipments: recordset receipt
        :return: list of dict yang header_external_id-nya ada di shipments
        """
        shipment_ids = {rec['external_id'] for rec in shipments}

        filtered_data = [
            vals for vals in data
            if vals.get('header_external_id') in shipment_ids
        ]

        return filtered_data

    def _create_shipment_lines_product(self, data, shipments):
        shipment_map = {
            rec['external_id']: rec.id
            for rec in shipments
        }

        for vals in data:
            vals['shipment_line_id'] = shipment_map.get(
                vals['header_external_id']
            )

        self.env['acumatica.shipment.product.line'].create(data)

    def _update_shipment_lines_product(self, data, shipments):
        shipment_map = {
            rec['vals']['external_id']: rec['record']['id']
            for rec in shipments
            if rec.get('vals')
            and rec.get('record')
        }

        product_line = self.env['acumatica.shipment.product.line']

        for vals in data:
            ext_id = vals.get('header_external_id')
            vals['shipment_line_id'] = shipment_map.get(ext_id)
            if vals['shipment_line_id']:
                product_line.browse(vals['shipment_line_id']).write(vals)

