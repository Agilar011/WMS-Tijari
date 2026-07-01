from odoo import fields, models
from odoo.exceptions import UserError


class ImportTransferShipmentWizard(models.TransientModel):
    _name = 'import.transfer.shipment.wizard'
    _description = 'Wizard Import Transfer Shipment dari Acumatica'

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi API', required=True, domain=[('active', '=', True)])
    fetch_limit = fields.Integer(string='Maks Data Ditarik', default=50)
    batch_size = fields.Integer(string='Batch Size untuk Import', default=20)
    shipment_nbr = fields.Char(string='Filter Shipment Number')
    last_modified_from = fields.Char(string='Filter Last Modified From', help='Contoh: 2026-02-12T00:00:00+07:00')

    wh33_filter = fields.Boolean(string='Filter WH33', help='Aktifkan untuk menambahkan filter WH33 pada query OData. Berfungsi untuk menfilter data receipt yang transaksi data ke WH33.')
    start_date = fields.Date(string='Filter Tanggal Mulai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-01')
    end_date = fields.Date(string='Filter Tanggal Selesai', help='Digunakan untuk filter data berdasarkan tanggal. Contoh: 2026-01-31')
    odata_filter = fields.Char(string='Custom OData Filter')

    odata_filter = fields.Char(string='Custom OData Filter')
    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')


    total_fetched = fields.Integer(string='Total Line Ditarik', readonly=True)
    total_new = fields.Integer(string='Transfer Baru', readonly=True)
    total_existing = fields.Integer(string='Sudah Ada (akan ditambah)', readonly=True)
    fetch_skip = fields.Integer(string='Skip Data Teratas', default=0, help='Jumlah data teratas yang akan dilewati saat fetch. Berguna untuk melewati data yang sudah pernah diimport sebelumnya.')

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

    def fetch_transfer_shipment_data(self, limit=50, offset=0, shipment_nbr=False, last_modified_from=False, odata_filter=False):
        self.ensure_one()
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.api_url}/{self.config_id.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.wh33_filter:
                params.append("startswith(Warehouse,'WH33')")
            if self.start_date and self.end_date:
                params.append(f"Date ge date'{self.start_date}' and Date le date'{self.end_date}'")

            if self.config_id.odata_expand:
                params['$expand'] = self.config_id.odata_expand
            if self.config_id.odata_select:
                params['$select'] = self.config_id.odata_select
            if shipment_nbr:
                filters.append(f"ShipmentNbr eq '{shipment_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            if odata_filter:
                filters.append(f"({odata_filter})")
            elif self.config_id.odata_filter:
                filters.append(f"({self.config_id.odata_filter})")

            if filters:
                params['$filter'] = ' and '.join(filters)

            print("Filter API:")
            print(endpoint)
            print(params)

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Shipment (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            result_line = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': row_number,
                    'note': item.get('note', {}).get('value', '') or '',
                    'actual_qty': self._val(item, 'ControlQty'),
                    'partner_code': self._val(item, 'CustomerID'),
                    'description': self._val(item, 'Description'),
                    'fob_point': self._val(item, 'FOBPoint'),
                    'is_hold': self._val(item, 'Hold'),
                    'is_insurance': self._val(item, 'Insurance'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'header_location_code': self._val(item, 'LocationID'),
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
                    'shipping_zone': self._val(item, 'ShippingZoneID'),
                    'ship_via': self._val(item, 'ShipVia'),
                    'status': self._val(item, 'Status'),
                    'warehouse_dest_code': self._val(item, 'ToWarehouseID'),
                    'shipment_type': self._val(item, 'Type'),
                    'warehouse_code': self._val(item, 'WarehouseID'),
                    'is_unlimited_packages': self._val(item, 'UnlimitedPackages'),
                }
                # print(header)
                # result.append(header)

                details = item.get('Details') or item.get('details') or []
                if isinstance(details, dict):
                    details = details.get('value', []) or []
                if not isinstance(details, list):
                    details = []

                if not details:
                    result.append(dict(header, line_nbr='0'))

                    continue
                if header['warehouse_code']:
                    type = self._search_picking_type(header)

                    print(type)
                    header['picking_type_id'] = type.id if type else None
                result.append(dict(header))


                for detail in details:
                    line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                    result_line.append({
                        'shipment_external_id' : item.get('id', ''),
                        'line_external_id': detail.get('id', '') or '',
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'line_row_number': detail.get('rowNumber') or '',
                        'line_description': self._val(detail, 'Description'),
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
                        'product_uom_qty': self._val(detail, 'ShippedQty'),
                        'uom_code': self._val(detail, 'UOM'),
                        'line_warehouse_code': self._val(detail, 'WarehouseID'),
                    })

            return result, result_line
        except Exception:
            raise
        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


    def action_fetch_data(self):
        self.ensure_one()
        self.env['acumatica.transfer.shipment.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        raw_line_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)

            result_dict, line_dict = self.fetch_transfer_shipment_data(
                limit=self.batch_size,
                offset=offset,
                shipment_nbr=self.shipment_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )

            # Ambil list data dari masing-masing dictionary dengan aman
            batch_data = result_dict if isinstance(result_dict, list) else []
            batch_data_line = line_dict if isinstance(line_dict, list) else []

            # Hentikan loop jika tidak ada data baru yang ditarik
            if not batch_data and not batch_data_line:
                break

            # Masukkan data ke dalam list utama
            raw_list.extend(batch_data)
            raw_line_list.extend(batch_data_line)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')
        
        if not raw_line_list:
            raise UserError('Tidak ada data product yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        existing_keys = set()
        new_keys = set()
        shipment_to_create = []
        lines_to_create = []

        for item in raw_list:
            origin = item.get('shipment_nbr')
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
            # shipment_to_create.append(vals)
            created_shipment = self.env['acumatica.transfer.shipment.line'].create(vals)
            self.write({
                'state': 'fetched',
                'total_fetched': len(raw_list),
                'total_new': len([x for x in new_keys if x]),
                'total_existing': len([x for x in existing_keys if x]),
            })

            for line in raw_line_list:
                print(line)
                if line.get('shipment_external_id') == item.get('external_id'):
                    vals_line = ({
                        'shipment_id' : created_shipment.id,
                        'line_external_id' : line.get('line_external_id'),
                        'line_note' : line.get('line_note'),
                        'line_row_number' : line.get('line_row_number'),
                        'line_description' : line.get('line_description'),
                        'is_free_item' : line.get('is_free_item'),
                        'inventory_id' : line.get('inventory_id'),
                        'line_nbr' : line.get('line_nbr'),
                        'location_dest_code' : line.get('location_dest_code'),
                        'open_qty' : line.get('open_qty'),
                        'order_qty' : line.get('order_qty'),
                        'order_line_number' : line.get('order_line_number'),
                        'order_number' : line.get('order_number'),
                        'order_type' : line.get('order_type'),
                        'original_qty' : line.get('original_qty'),
                        'product_uom_qty' : line.get('product_uom_qty'),
                        'uom_code' : line.get('uom_code'),
                        'line_warehouse_code' : line.get('line_warehouse_code'),
                    })

                    created_move = self.env['acumatica.transfer.shipment.line.product'].create(vals_line)

                    print(f"Created Move with ID: {created_move.id}")


        


        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.transfer.shipment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    def _search_picking_type(self, header):
        print(f" Self: {self}")
        print(f"Header : {header}")
        PickingType = self.env['stock.picking.type']
        Location = self.env['stock.location.acumatica']

        location = Location.search([
            ('code', '=', header['warehouse_code'])
        ])

        
        if location:
            print(f"Building id: {location.odoo_building_id.id}")
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'internal'),
                ('is_default_api', '=', True)
            ])

        return type if type else None


    def action_view_staging(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Data Transfer Shipment dari Acumatica',
            'res_model': 'acumatica.transfer.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.transfer.shipment.line'].search([
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
            'name': 'Hasil Import Transfer Shipment',
            'res_model': 'acumatica.transfer.shipment.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }
