
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
        staging_list = []
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
                
            if filters:
                params['$filter'] = ' and '.join(filters)
                
            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Issue Change Item (HTTP {response.status_code}): {response.text}')
                
            raw_data = self._normalize_rows(response.json())
            print(f"Get Inventory Issue data from Acumatica: {len(raw_data)} records fetched")
            
            issue_model = self.env['acumatica.issue.line']
            product_model = self.env['acumatica.issue.line.product']
            
            for item in raw_data:
                external_id = item.get('id', '') or ''
                ref_nbr = self._val(item, 'ShipmentNbr')
                
                # CHECKPOINT 1: Mulai transaksi tersendiri per Header menggunakan Try-Except
                try:
                    # 1. Cari tipe picking
                    picking_type = self._search_picking_type(item)
                    picking_type_id = picking_type.id if picking_type else None
                    
                    # 2. Siapkan data mapped untuk Header
                    header_vals = {
                        'external_id': external_id,
                        'row_number': item.get('rowNumber', '') or '',
                        'note': item.get('note', {}).get('', '') or '',
                        'actual_amount': self._val(item, 'ControlQty'),
                        'actual_qty': self._val(item, 'ControlQty'),
                        'scheduled_date': self._val(item, 'ShipmentDate'),
                        'description': self._val(item, 'Description'),
                        'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                        'reference_nbr': ref_nbr,
                        'status': self._val(item, 'Status'),
                        'total_qty': self._val(item, 'ShippedQty'),
                        'trans_type': self._val(item, 'Type'),
                        'picking_type_id': picking_type_id,
                        'warehouse_code': self._val(item, 'WarehouseID'),
                        'branch_warehouse': self._val(item, 'WarehouseName'),
                    }
                    
                    # 3. Create atau Update Header
                    issue_record = issue_model.search([('external_id', '=', external_id)], limit=1)
                    if issue_record:
                        issue_record.write(header_vals)
                    else:
                        issue_record = issue_model.create(header_vals)

                    record_id = issue_record.id
                    staging_list.append(record_id)
                    
                    # Commit Header terlebih dahulu agar Many2one ID terbentuk secara permanen di DB
                    self.env.cr.commit()
                    
                    # 4. Proses data Detail (Product Lines)
                    details = item.get('Details') or item.get('details') or []
                    if isinstance(details, dict):
                        details = details.get('value', []) or []
                    if not isinstance(details, list):
                        details = []

                    if not details:
                        print('Header tidak memiliki detail')
                        
                    for detail in details:
                        line_external_id = detail.get('id', '') or ''
                        # print(f"DEBUG DETAILS DATA untuk {ref_nbr}: {details}")

                        
                        # CHECKPOINT 2: Sub-transaksi untuk Detail
                        try:
                            line_nbr = self._val(detail, 'LineNumber') or self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
                            
                            detail_vals = {
                                'issue_shipment_id': issue_record.id,
                                'external_id': external_id,
                                'line_external_id': line_external_id,
                                'note': detail.get('note', {}).get('value', '') or '',
                                'branch': self._val(detail, 'Branch'),
                                'description': self._val(detail, 'Description'),
                                'inventory_id': self._val(detail, 'InventoryID'),
                                'line_number': str(line_nbr),
                                'location_code': self._val(detail, 'Location'),
                                'product_uom_qty': self._val(detail, 'Qty'),
                                'trans_type': self._val(detail, 'TranType'),
                                'uom_code': self._val(detail, 'UOM'),
                                'warehouse_code': self._val(detail, 'WarehouseID'),
                            }
                            
                            product_record = product_model.search([('line_external_id', '=', line_external_id)], limit=1) if line_external_id else False
                            if product_record:
                                product_record.write(detail_vals)
                            else:
                                product_model.create(detail_vals)
                            
                            # Commit setiap baris detail yang sukses
                            self.env.cr.commit()
                            
                        except Exception as e_detail:
                            self.env.cr.rollback()
                            issue_record.write({
                                'import_state' : 'error',
                                'import_message' : 'Proses generate product error'
                            })
                            # Jika detail error, rollback database khusus untuk baris detail ini saja
                            _logger.error("Gagal memproses baris detail (ID: %s) pada dokumen %s. Error: %s", line_external_id, ref_nbr, str(e_detail))
                            continue  # Lanjutkan ke baris detail berikutnya
                            
                except Exception as e_header:
                    self.env.cr.rollback()

                    if issue_record:
                        issue_record.write({
                            'import_state' : 'error',
                            'import_message' : 'Proses generate header error'
                        })


                    # Jika header error, rollback seluruh perubahan dokumen ini (termasuk jika ada detail yang sempat masuk)
                    _logger.error("Gagal sinkronisasi dokumen Acumatica (RefNbr: %s, ID: %s). Error: %s", ref_nbr, external_id, str(e_header))
                    continue  # Lanjutkan ke dokumen (item) berikutnya di raw_data
                        
            _logger.info('Selesai menjalankan sinkronisasi terjadwal Issue Change Item.')
            self.config_id.last_sync = fields.Datetime.now()
            self.env.cr.commit() # Commit final untuk waktu sync terakhir
            return staging_list
            
        finally:
            self.config_id._do_logout(session)

    def action_fetch_data(self):
        self.ensure_one()
        # self.env['acumatica.issue.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data  = self.fetch_issue_data(
                limit=self.batch_size,
                offset=offset,
                reference_nbr=self.reference_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )

            if not batch_data:
                break

            raw_list.extend(batch_data)

        if not raw_list:
            raise UserError('Tidak ada data yang diterima dari API Acumatica.')

        Picking = self.env['stock.picking']
        existing_keys = set()
        new_keys = set()
        lines_to_create = []

        # for item in raw_list:
        #     origin = item.get('reference_nbr')
        #     exists = bool(origin and Picking.search_count([('origin', '=', origin)]))
        #     if exists:
        #         existing_keys.add(origin)
        #         msg = 'Sudah ada → move akan ditambahkan jika belum ada'
        #     else:
        #         new_keys.add(origin)
        #         msg = ''

        #     vals = dict(item)
        #     vals.update({
        #         'config_id': self.config_id.id,
        #         'import_state': 'pending',
        #         'import_message': msg,
        #         'selected': True,
        #         'sync_date': fields.Datetime.now(),
        #     })
        #     print(f"vals: {vals}")
        #     lines_to_create.append(vals)
        #     # print(f"lines to create: {lines_to_create}")
        #     # raise UserError(f"Debug:")

        # self.env['acumatica.issue.line'].create(lines_to_create)
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
            ('code', '=', location)
        ])

        print(f"Location: {location.id}")

        if location:
            type = PickingType.search([
                ('warehouse_id', '=', location.odoo_building_id.id if location else False),
                ('code', '=', 'outgoing'),                
                ('is_default_api', '=', True)
            ])

        return type
