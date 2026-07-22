import requests
import logging

from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ImportTransferOneStepWizard(models.TransientModel):
    _name = 'import.transfer.one.step.wizard'
    _description = 'Wizard Import Transfer One Step dari Acumatica'

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
        self.env['acumatica.transfer.one.step.line'].search([('config_id', '=', self.config_id.id)]).unlink()

        import math

        raw_list = []
        raw_move_list = []
        loop_count = math.ceil(self.fetch_limit / self.batch_size)
        print(f"Loop Count: {loop_count}")

        for i in range(loop_count):
            offset = self.fetch_skip + (i * self.batch_size)
            batch_data, batch_data_line = self.fetch_receipt_data(
                limit=self.batch_size,
                offset=offset,
                reference_nbr=self.reference_nbr,
                last_modified_from=self.last_modified_from,
                odata_filter=self.odata_filter,
            )
            print(f"Batch Data: {batch_data}")

            if not batch_data:
                print(f"=== DEBUG: Batch data kosong pada offset {offset}. Loop dihentikan. ===")
                break

            raw_list.extend(batch_data)
            raw_move_list.extend(batch_data_line)

        # Perbaikan: Menggunakan print sebagai pengganti UserError jika data kosong
        if not raw_list:
            print("=================== DEBUG: API ACUMATICA EMPTY ===================")
            print("Tidak ada data Transfer Order yang diterima dari API Acumatica.")
            print(f"Parameter yang digunakan:")
            print(f"- Batch Size        : {self.batch_size}")
            print(f"- Reference Nbr     : {self.reference_nbr}")
            print(f"- Last Modified From: {self.last_modified_from}")
            print(f"- OData Filter      : {self.odata_filter}")
            print("==================================================================")

        InternalTransferOrder = self.env['internal.transfer.order']
        existing_receipts = set()
        new_receipts = set()
        lines_to_create = []
        move_lines_to_create = []

        for item in raw_list:
            reference_nbr = item.get('reference_nbr')
            header_id = item.get('external_id')
            exists = bool(
                reference_nbr
                and InternalTransferOrder.search_count([('external_ref', '=', reference_nbr)])
            )
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
            created_picking = self.env['acumatica.transfer.one.step.line'].create(vals)
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
                    move_lines_to_create = self.env['acumatica.transfer.one.step.product'].create(move_vals)

        # self.env['acumatica.transfer.one.step.line'].create(lines_to_create)
        # self.write({
        #     'state': 'fetched',
        #     'total_fetched': len(raw_list),
        #     'total_new': len([r for r in new_receipts if r]),
        #     'total_existing': len([r for r in existing_receipts if r]),
        # })

        

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'import.transfer.one.step.wizard',
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
            print("FINAL ENDPOINT URL:", response.url)  # <--- Tambahkan baris ini
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Order (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []
            result_line = []

            print(f"raw Data: {raw_data}")

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id'),
                    'note': item.get('note', {}).get('value', '') or '',
                    'scheduled_date': self._val(item, 'Date'),
                    'description': self._val(item, 'Description'),
                    'from_warehouse_code': self._val(item, 'FromWarehouseID'),
                    'is_hold': self._val(item, 'Hold'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'to_warehouse_code': self._val(item, 'ToWarehouseID'),
                    'transfer_type': self._val(item, 'TransferType'),
                    'trans_type': self._val(item, 'TransType'),
                }

                if header.get('from_warehouse_code'):
                    # Kirim data header ke fungsi pembantu
                    type_record = self._search_picking_type(header)

                    # print(f"")
                    # Ambil ID integer secara aman, gunakan False standar Odoo (bukan None)
                    header['picking_type_id'] = type_record.id if type_record else False

                result.append(header)

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

                    result_line.append({
                        'acumatica_header_id' : item.get('id', {}),
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'line_description': self._val(detail, 'Description'),
                        'from_location_code': self._val(detail, 'FromLocationID'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'to_location_code': self._val(detail, 'ToLocationID'),
                        'quantity': self._val(detail, 'Quantity'),
                        'uom_code': self._val(detail, 'UOM'),
                    })

            _logger.info("Berhasil ambil %s rows Transfer Order dari Acumatica", len(result))
            return result, result_line
        finally:
            self.config_id._do_logout(session)
            self.config_id.last_sync = fields.Datetime.now()


    @property
    def api_url(self):
        return f"{self.config_id.base_url}/wms/{self.config_id.api_version}"

    @property
    def login_url(self):
        return f"{self.config_id.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.config_id.base_url}/auth/logout"

    def action_test_connection(self):
        self.ensure_one()
        try:
            session = self._do_login()
            if session:
                self._do_logout(session)
                self.state = 'connected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Koneksi Berhasil!',
                        'message': f'Berhasil terhubung ke Acumatica ({self.base_url})',
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    def _do_login(self):
        self.ensure_one()

        last_error = None

        for attempt in range(1, 4):
            try:
                session = requests.Session()
                response = session.post(
                    self.login_url,
                    json={
                        "name": self.config_id.username,
                        "password": self.config_id.password,
                        "company": self.config_id.company_code
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 204:
                    return session

                raise UserError(
                    f'Login gagal (HTTP {response.status_code}): {response.text}'
                )

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_error = e

                if attempt < 3:
                    time.sleep(30)

        if isinstance(last_error, requests.exceptions.ConnectionError):
            raise UserError(
                f'Tidak bisa terhubung ke server: {self.base_url} (sudah dicoba 3 kali)'
            )

        if isinstance(last_error, requests.exceptions.Timeout):
            raise UserError(
                'Koneksi timeout setelah 3 kali percobaan. Periksa URL server.'
            )

        raise UserError('Login gagal setelah 3 kali percobaan.')


    def _do_logout(self, session):
        for attempt in range(1, 4):
            try:
                response = session.post(
                    self.logout_url,
                    timeout=10
                )

                # opsional: validasi status code
                if response.status_code in (200, 204):
                    return

                if attempt < 3:
                    time.sleep(30)

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout):
                if attempt < 3:
                    time.sleep(30)

            except Exception:
                # tetap diam seperti kode asli
                return
            
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
            'name': 'Data Transfer One Step dari Acumatica',
            'res_model': 'acumatica.transfer.one.step.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
            'context': {'default_config_id': self.config_id.id},
        }

    def action_import_all_pending(self):
        self.ensure_one()
        lines = self.env['acumatica.transfer.one.step.line'].search([
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
            'name': 'Hasil Import Transfer One Step dari Acumatica',
            'res_model': 'acumatica.transfer.one.step.line',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.config_id.id)],
        }

class AcumaticaTransferOneStepConfig(models.Model):
    _name = 'acumatica.transfer.one.step.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Receipt Import'
    _rec_name = 'name'

    name = fields.Char(string='Nama Konfigurasi', required=True, default='Acumatica WMS')
    base_url = fields.Char(string='Base URL', required=True, default='http://staging.aditya.group/acumportal/entity')
    api_version = fields.Char(string='API Version', required=True, default='25.200.002')
    username = fields.Char(string='Username', required=True, default='wms')
    password = fields.Char(string='Password', required=True)
    company_code = fields.Char(string='Company Code', required=True, default='asgjkt')
    endpoint_name = fields.Char(string='Endpoint Name', required=True, default='TransferOrder')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)
    odata_expand = fields.Char(
        string='OData Expand',
        default='Details',
        help='Contoh: Details atau Details,OtherChild'
    )
    odata_select = fields.Char(
        string='OData Select',
        help='Optional: pilih field tertentu'
    )
    odata_filter = fields.Char(
        string='OData Filter',
        default="TransferType eq '1-Step' and (Status eq 'On Hold' or Status eq 'Balanced')"
    )

    @property
    def api_url(self):
        return f"{self.base_url}/wms/{self.api_version}"

    @property
    def login_url(self):
        return f"{self.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.base_url}/auth/logout"

    def action_test_connection(self):
        self.ensure_one()
        try:
            session = self._do_login()
            if session:
                self._do_logout(session)
                self.state = 'connected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Koneksi Berhasil!',
                        'message': f'Berhasil terhubung ke Acumatica ({self.base_url})',
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    def _do_login(self):
        self.ensure_one()

        last_error = None

        for attempt in range(1, 4):
            try:
                session = requests.Session()
                response = session.post(
                    self.login_url,
                    json={
                        "name": self.username,
                        "password": self.password,
                        "company": self.company_code
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 204:
                    return session

                raise UserError(
                    f'Login gagal (HTTP {response.status_code}): {response.text}'
                )

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_error = e

                if attempt < 3:
                    time.sleep(30)

        if isinstance(last_error, requests.exceptions.ConnectionError):
            raise UserError(
                f'Tidak bisa terhubung ke server: {self.base_url} (sudah dicoba 3 kali)'
            )

        if isinstance(last_error, requests.exceptions.Timeout):
            raise UserError(
                'Koneksi timeout setelah 3 kali percobaan. Periksa URL server.'
            )

        raise UserError('Login gagal setelah 3 kali percobaan.')


    def _do_logout(self, session):
        for attempt in range(1, 4):
            try:
                response = session.post(
                    self.logout_url,
                    timeout=10
                )

                # opsional: validasi status code
                if response.status_code in (200, 204):
                    return

                if attempt < 3:
                    time.sleep(30)

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout):
                if attempt < 3:
                    time.sleep(30)

            except Exception:
                # tetap diam seperti kode asli
                return
            
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

    def fetch_receipt_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
        self.ensure_one()
        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/{self.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            filters = []

            if self.odata_expand:
                params['$expand'] = self.odata_expand

            if self.odata_select:
                params['$select'] = self.odata_select
            if reference_nbr:
                filters.append(f"ReferenceNbr eq '{reference_nbr}'")
            if last_modified_from:
                filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
            if self.odata_filter:
                filters.append(f"({self.odata_filter})")
            else:
                filters.append("(TransferType eq '1-Step')")

            if filters:
                params['$filter'] = ' and '.join(filters)       

            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Transfer Order (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())
            result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'note': item.get('note', {}).get('value', '') or '',
                    'scheduled_date': self._val(item, 'Date'),
                    'description': self._val(item, 'Description'),
                    'from_warehouse_code': self._val(item, 'FromWarehouseID'),
                    'is_hold': self._val(item, 'Hold'),
                    'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
                    'post_period': self._val(item, 'PostPeriod'),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    'status': self._val(item, 'Status'),
                    'total_qty': self._val(item, 'TotalQty'),
                    'to_warehouse_code': self._val(item, 'ToWarehouseID'),
                    'transfer_type': self._val(item, 'TransferType'),
                    'trans_type': self._val(item, 'TransType'),
                }

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

                    result.append({
                        **header,
                        'line_note': detail.get('note', {}).get('value', '') or '',
                        'line_description': self._val(detail, 'Description'),
                        'from_location_code': self._val(detail, 'FromLocationID'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(line_nbr),
                        'to_location_code': self._val(detail, 'ToLocationID'),
                        'quantity': self._val(detail, 'Quantity'),
                        'uom_code': self._val(detail, 'UOM'),
                    })

            _logger.info("Berhasil ambil %s rows Transfer Order dari Acumatica", len(result))
            return result
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

