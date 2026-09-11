import requests
import json
import logging
from datetime import datetime
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaConfig(models.Model):
    _name = 'acumatica.config'
    _description = 'Konfigurasi Koneksi Acumatica WMS API'
    _rec_name = 'name'

    name = fields.Char(
        string='Nama Konfigurasi',
        required=True,
        default='Acumatica WMS',
    )
    base_url = fields.Char(
        string='Base URL',
        required=True,
        default='http://staging.aditya.group/acumportal/entity',
        help='Contoh: http://your-server/acumportal/entity',
    )
    api_version = fields.Char(
        string='API Version',
        required=True,
        default='25.200.002',
    )
    username = fields.Char(
        string='Username',
        required=True,
        default='wms',
    )
    password = fields.Char(
        string='Password',
        required=True,
    )
    company_code = fields.Char(
        string='Company Code',
        required=True,
        default='asgjkt',
    )
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(string='Terakhir Sync', readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)

    odata_expand = fields.Char(
        string='OData Expand',
        help='Contoh: Details atau Details,OtherChild'
    )
    odata_select = fields.Char(
        string='OData Select',
        help='Optional: pilih field tertentu'
    )
    odata_filter = fields.Char(
        string='OData Filter',
    )
    endpoint_name = fields.Char(
        string='Endpoint Name',
        required=True,
        help='Dipakai untuk transaksi yang butuh endpoint Acumatica spesifik.',
    )
    is_default = fields.Boolean(
        string='Default',
        default=False,
        help='Dipakai sebagai config bawaan untuk tipe import yang sama.',
    )
    picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'acumatica_config_stock_picking_type_rel',
        'config_id',
        'picking_type_id',
        string='Stock Picking Type',
        help='Operation type yang dipakai saat fetch data transaksi dengan konfigurasi ini.',
    )
    config_type = fields.Selection(
        selection=[
            ('po_receipt', 'PO Receipt'),
            ('so_transfer', 'Transfer (In/SOTR)'),
            ('inventory_received', 'Inventory Receipt'),
            ('shipment_so', 'SO Return'),
            ('so_shipment', 'SO Shipment'),
            ('shipment_completed', 'Shipment Completed'),
            ('transfer_shipment', 'Transfer (Out/Shipment)'),
            ('issue_change_item', 'Issue Change Item'),
            ('inventory_issue', 'Inventory Issue'),
            ('issue_po_return', 'PO Return'),
            ('transfer_one_step', 'Transfer 1 Step'),
            ('transfer_two_step', 'Transfer 2 Step'),
            ('kit_assembly', 'Kit Assembly'),

            ('customer', 'Customer'),
            ('warehouse', 'Warehouse'),
            ('stock_item', 'Stock Item'),
            ('non_stock_item', 'Non Stock Item'),
            ('uom', 'Unit of Measure'),
            ('vendor', 'Vendor'),
            ('inventory_stock', 'Inventory Stock'),
            ('invoice_consignment', 'Invoice Consignment'),
            ('vendor_return_direct_transfer', 'Return Consignment'),
            ('vendor_return_document_direct_transfer', 'Direct Transfer'),
            ('credit_memo_consignment', 'Credit Memo Consignment'),

        ], string='Config Type', required=True, default='uom',
    )

    @api.model
    def _get_default_config_for_type(self, config_type):
        if not config_type:
            return self.browse()

        default_config = self.search([
            ('config_type', '=', config_type),
            ('is_default', '=', True),
            ('active', '=', True),
        ], limit=1)
        if default_config:
            default_config._ensure_v2_api_defaults()
            return default_config

        fallback_config = self.search([
            ('config_type', '=', config_type),
            ('active', '=', True),
        ], limit=1)
        if fallback_config:
            fallback_config._ensure_v2_api_defaults()
            return fallback_config

        if config_type == 'kit_assembly':
            return self._create_default_kit_assembly_config()

        return self.browse()

    def _ensure_v2_api_defaults(self):
        v2_defaults = {
            'transfer_one_step': {
                'name': 'Acumatica Transfer One Step V2 - Default',
                'endpoint_name': 'TransferOrderGI',
                'odata_expand': 'TransferOrderGIDetails',
                'odata_filter': False,
                'old_endpoint_names': {'', 'TransferOrder'},
                'old_odata_expands': {'', 'Details'},
                'old_odata_filters': {
                    "TransferType eq '1-Step' and (Status eq 'On Hold' or Status eq 'Balanced')",
                    "TransferType eq '1-Step' and (Status eq 'On Hold' or Status eq 'Balanced') ",
                },
            },
            'transfer_two_step': {
                'name': 'Acumatica Transfer Two Step V2 - Default',
                'endpoint_name': 'TransferOrderGI',
                'odata_expand': 'TransferOrderGIDetails',
                'odata_filter': False,
                'old_endpoint_names': {'', 'TransferOrder'},
                'old_odata_expands': {'', 'Details'},
                'old_odata_filters': {
                    "TransferType eq '1-Step' and (Status eq 'On Hold' or Status eq 'Balanced')",
                    "TransferType eq '1-Step' and (Status eq 'On Hold' or Status eq 'Balanced') ",
                    "TransferType eq '2-Step' and (Status eq 'On Hold' or Status eq 'Balanced')",
                    "TransferType eq '2-Step' and (Status eq 'On Hold' or Status eq 'Balanced') ",
                },
            },
            'kit_assembly': {
                'name': 'Acumatica Kit Assembly V2 - Default',
                'endpoint_name': 'KitAssemblyGI',
                'odata_expand': 'KitAssemblyGIDetails',
                'old_endpoint_names': {'', 'KitAssembly'},
                'old_odata_expands': {'', 'StockComponents'},
            },
            'vendor_return_direct_transfer': {
                'name': 'Acumatica Return Consignment V2 - Default',
                'endpoint_name': 'VendorReturnGI',
                'odata_expand': 'VendorReturnGIDetails',
                'odata_filter': False,
                'old_endpoint_names': {'', 'TransferOrder', 'TransferOrderGI'},
                'old_odata_expands': {'', 'Details', 'TransferOrderGIDetails'},
                'old_odata_filters': {
                    "ReturnType eq 'Return Transfer' and (Status eq 'On Hold' or Status eq 'Balance')",
                },
            },
            'vendor_return_document_direct_transfer': {
                'name': 'Acumatica Vendor Return Document Direct Transfer V2 - Default',
                'endpoint_name': 'VendorReturnDocumentGI',
                'odata_expand': 'VendorReturnDocumentGIDetails',
                'odata_filter': False,
                'old_endpoint_names': {'', 'TransferOrder', 'TransferOrderGI'},
                'old_odata_expands': {'', 'Details', 'TransferOrderGIDetails'},
                'old_odata_filters': {
                    "ReturnType eq 'Return Transfer Document' and Status eq 'Released'",
                },
            },
            'credit_memo_consignment': {
                'name': 'Acumatica Credit Memo Consignment V2 - Default',
                'endpoint_name': 'CreditMemoConsignmentGI',
                'odata_expand': False,
                'odata_filter': False,
                'old_endpoint_names': {'', 'Invoice', 'InvoiceGI'},
                'old_odata_expands': {'', 'Details', 'InvoiceGIDetails', 'CreditMemoConsignmentGIDetails'},
                'old_odata_filters': {
                    "Type eq 'Credit Memo' and Status eq 'Open' and ConsignmentType eq 'Billing Notation'",
                    "Type eq 'Credit Memo' and ConsignmentType eq 'Billing Notation'",
                },
            },
        }
        for record in self:
            defaults = v2_defaults.get(record.config_type)
            if not defaults:
                continue
            vals = {}
            if record.config_type == 'credit_memo_consignment':
                vals['odata_expand'] = False
                vals['odata_filter'] = False
            if record.endpoint_name in defaults['old_endpoint_names']:
                vals['endpoint_name'] = defaults['endpoint_name']
            if record.odata_expand in defaults['old_odata_expands']:
                vals['odata_expand'] = defaults['odata_expand']
            if 'odata_filter' in defaults and record.odata_filter in defaults.get('old_odata_filters', set()):
                vals['odata_filter'] = defaults['odata_filter']
            if record.name and 'V2' not in record.name:
                vals['name'] = defaults['name']
            if vals:
                record.write(vals)
        return self

    @api.model
    def _normalize_inventory_receive_type(self, value):
        if not value:
            return 'inventory_receive'
        return str(value).strip().lower().replace('-', '_').replace(' ', '_')

    def _get_config_picking_type(self):
        self.ensure_one()
        return self.picking_type_ids[:1] if self.picking_type_ids else self.env['stock.picking.type'].browse()

    def _resolve_inventory_receive_picking_type(self, transfer_type=False, warehouse_code=False, document_only=False):
        self.ensure_one()
        PickingType = self.env['stock.picking.type']
        type_key = self._normalize_inventory_receive_type(transfer_type)
        domain_by_type = {
            'transfer_in': ('internal', 'receive'),
            'change_item': ('incoming', 'receive'),
            'inventory_receive': ('incoming', 'receive'),
            'inventory_received': ('incoming', 'receive'),
            'inventory_receipt': ('incoming', 'receive'),
        }
        code, operation_category = domain_by_type.get(type_key, (False, False))

        if document_only and type_key != 'transfer_in':
            return PickingType.resolve_document_only_picking_type(
                api_acumatica='inventory_received',
                document_only=document_only,
                warehouse_code=warehouse_code,
            )

        if not code:
            return PickingType.browse()

        return PickingType.resolve_picking_type(
            warehouse_code=warehouse_code,
            code=code,
            operation_category=operation_category,
            api_acumatica='inventory_received',
            transaction_key=type_key,
            required=False,
        )

    @api.model
    def _create_default_kit_assembly_config(self):
        source = self.search([('active', '=', True)], limit=1)
        vals = {
            'name': 'Acumatica Kit Assembly V2 - Default',
            'base_url': source.base_url or 'http://staging.aditya.group/acumportal/entity',
            'api_version': source.api_version or '25.200.002',
            'username': source.username or 'wms',
            'password': source.password or 'WMSAditya@2026',
            'company_code': source.company_code or 'asgjkt',
            'config_type': 'kit_assembly',
            'endpoint_name': 'KitAssemblyGI',
            'odata_expand': 'KitAssemblyGIDetails',
            'is_default': True,
            'active': True,
            'state': 'draft',
        }
        return self.create(vals)

    def _ensure_kit_assembly_defaults(self):
        for record in self.filtered(lambda config: config.config_type == 'kit_assembly'):
            vals = {}
            if not record.endpoint_name:
                vals['endpoint_name'] = 'KitAssemblyGI'
            if not record.odata_expand:
                vals['odata_expand'] = 'KitAssemblyGIDetails'
            if vals:
                record.write(vals)
        return self

    def _sync_default_flag(self):
        for record in self.filtered(lambda config: config.is_default and config.config_type):
            siblings = self.search([
                ('id', '!=', record.id),
                ('config_type', '=', record.config_type),
                ('is_default', '=', True),
            ])
            if siblings:
                siblings.write({'is_default': False})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_default_flag()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'is_default' in vals or 'config_type' in vals:
            self._sync_default_flag()
        return result

    # ─── Computed URLs ───────────────────────────────
    @property
    def api_url(self):
        return f"{self.base_url}/wms/{self.api_version}"

    @property
    def login_url(self):
        return f"{self.base_url}/auth/login"

    @property
    def logout_url(self):
        return f"{self.base_url}/auth/logout"

    # ─── Test Koneksi ────────────────────────────────
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

    # ─── Login helper ────────────────────────────────
    def _do_login(self):
        self.ensure_one()
        credentials = {
            "name": self.username,
            "password": self.password,
            "company": self.company_code,
        }
        try:
            # Acumatica dapat menyisakan session server dari proses sebelumnya.
            # Jalankan logout preflight sebelum membuat session baru. Logout
            # sengaja non-blocking karena session lama bisa saja sudah expired.
            self._do_logout()
            session = requests.Session()
            response = session.post(
                self.login_url,
                json=credentials,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code == 204:
                _logger.info("Acumatica login berhasil untuk user: %s", self.username)
                return session
            else:
                raise UserError(
                    f'Login gagal (HTTP {response.status_code}): {response.text}'
                )
        except requests.exceptions.ConnectionError:
            raise UserError(f'Tidak bisa terhubung ke server: {self.base_url}')
        except requests.exceptions.Timeout:
            raise UserError('Koneksi timeout. Periksa URL server.')

    # ─── Logout helper ───────────────────────────────
    def _do_logout(self, session=None):
        logout_session = session or requests.Session()
        try:
            logout_session.post(self.logout_url, timeout=10)
        except Exception:
            pass  # Logout gagal tidak masalah
        finally:
            if session is None:
                logout_session.close()

    # ─── Fetch UoM dari API ──────────────────────────
    def fetch_uom_data(self, limit=500, offset=0):
        print('get uom data')
        """
        Ambil data Units of Measure dari Acumatica API.
        Return: list of dict { unit_id, description, external_id }
        """
        self.ensure_one()
        session = self._do_login()

        try:
            endpoint = f"{self.api_url}/UnitsOfMeasure"
            params = {"$top": limit, "$skip": offset}

            response = session.get(endpoint, params=params, timeout=60)

            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil data UoM (HTTP {response.status_code}): {response.text}'
                )

            raw_data = response.json()
            _logger.info("Berhasil ambil %d records UoM dari Acumatica", len(raw_data))

            result = []
            for item in raw_data:
                result.append({
                    'unit_id':     item.get("UnitID", {}).get("value", "") or "",
                    'description': item.get("Description", {}).get("value", "") or "",
                    'external_id': item.get("id", "") or "",
                    'row_number':  item.get("rowNumber", 0),
                })

            return result

        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

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

    def _parse_datetime(self, value):
        if not value:
            return False

        if isinstance(value, datetime):
            return value

        try:
            # Support:
            # 2011-12-09T22:18:00+07:00
            # 2011-12-09T22:18:00Z
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return False        

    def _iter_transaction_type_payloads(self, payload):
        if isinstance(payload, list):
            for item in payload:
                yield from self._iter_transaction_type_payloads(item)
            return

        if not isinstance(payload, dict):
            return

        yield payload
        for value in payload.values():
            if isinstance(value, dict):
                nested = value.get('value')
                if isinstance(nested, (list, dict)):
                    yield from self._iter_transaction_type_payloads(nested)
            elif isinstance(value, list):
                yield from self._iter_transaction_type_payloads(value)

    def _extract_transaction_type_values(self, payload):
        source_keys = (
            'TransType',
            'TransactionType',
            'TransferType',
            'Type',
            'ReceiptType',
            'OrderType',
            'SOOrderType',
            'LineOrderType',
            'POOrderType',
            'LinePOOrderType',
            'TransferOrderType',
            'LineTransferOrderType',
            'ReturnType',
        )
        values = {}
        for item in self._iter_transaction_type_payloads(payload):
            for key in source_keys:
                value = self._val(item, key)
                if not value:
                    continue
                normalized = str(value).strip()
                if normalized:
                    values[(key, normalized)] = normalized
        return values

    def fetch_transaction_type_values(self, limit=50, offset=0):
        self.ensure_one()
        self._ensure_v2_api_defaults()
        if not self.endpoint_name:
            raise UserError('Endpoint Name wajib diisi sebelum sync transaction type.')

        session = self._do_login()
        try:
            endpoint = f"{self.api_url}/{self.endpoint_name}"
            params = {'$top': limit, '$skip': offset}
            if self.odata_expand:
                params['$expand'] = self.odata_expand
            if self.odata_select:
                params['$select'] = self.odata_select
            if self.odata_filter:
                params['$filter'] = self.odata_filter

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(
                    f'Gagal ambil transaction type {self.name} '
                    f'(HTTP {response.status_code}): {response.text}'
                )

            payload = response.json()
            return self._extract_transaction_type_values(payload)
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

    def action_sync_transaction_types(self):
        TransactionType = self.env['acumatica.transaction.type']
        synced = 0
        checked = 0
        messages = []

        for config in self:
            checked += 1
            try:
                with self.env.cr.savepoint():
                    values = config.fetch_transaction_type_values()
            except Exception as exc:
                messages.append(f'{config.name}: {str(exc)}')
                continue

            if not values:
                messages.append(f'{config.name}: tidak ada transaction type di sample response.')
                continue

            with self.env.cr.savepoint():
                for (source_field, trans_type), name in values.items():
                    record = TransactionType.search([
                        ('config_id', '=', config.id),
                        ('source_field', '=', source_field),
                        ('trans_type', '=', trans_type),
                    ], limit=1)
                    vals = {
                        'name': name,
                        'config_id': config.id,
                        'source_field': source_field,
                        'trans_type': trans_type,
                        'endpoint_name': config.endpoint_name,
                        'last_sync': fields.Datetime.now(),
                        'active': True,
                    }
                    if record:
                        record.write(vals)
                    else:
                        TransactionType.create(vals)
                    synced += 1

        message = f'Sync selesai. Config dicek: {checked}, transaction type tersimpan: {synced}.'
        if messages:
            message = f"{message}\n" + "\n".join(messages)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Transaction Type',
                'message': message,
                'type': 'success' if synced else 'warning',
                'sticky': bool(messages),
            }
        }
        

    # def fetch_kit_assembly_data(self, limit=100, offset=0):
    #     """Fetch 1 page Kit Assembly dari Acumatica (paging via $top/$skip)."""
    #     # print("==========================================================================================")
    #     # print("ACTION: Fetch data from Acumatica")
    #     # print("==========================================================================================")

    #     self.ensure_one()
    #     session = self._do_login()
    #     staging_header = self.env['acumatica.kit.assembly']
    #     staging_line = self.env['acumatica.kit.assembly.component']
    #     try:
    #         endpoint = f"{self.api_url}/KitAssembly"
    #         # print(f"Fetching Kit Assembly data from {endpoint} with limit={limit} and offset={offset}...")
    #         params = {'$top': limit, '$skip': offset, '$expand': 'StockComponents'}

    #         response = session.get(endpoint, params=params, timeout=60)
    #         if response.status_code != 200:
    #             raise UserError(
    #                 f'Gagal ambil data Kit Assembly '
    #                 f'(HTTP {response.status_code}): {response.text}'
    #             )

    #         raw_data = self._normalize_rows(response.json())
    #         result = []

    #         for item in raw_data:

    #             last_modified_datetime = self._parse_datetime(item.get('LastModifiedDateTime'))
    #             print(f"Last Modified Date Time: :{last_modified_datetime}")
    #             header = {
    #                 'name': self._val(item, 'ReferenceNbr'),
    #                 'external_id': item.get('id', '') or '',
    #                 'row_number': item.get('rowNumber', 0) or 0,
    #                 'description': self._val(item, 'Description'),
    #                 'inventory_id': self._val(item, 'InventoryID'),
    #                 'last_modified_datetime': last_modified_datetime,
    #                 'location': self._val(item, 'Location'),
    #                 'post_period': self._val(item, 'PostPeriod'),
    #                 'quantity': self._val(item, 'Qty'),
    #                 'reason_code': self._val(item, 'ReasonCode'),
    #                 'reference_nbr': self._val(item, 'ReferenceNbr'),
    #                 'requested_on': self._val(item, 'RequestedOn'),
    #                 'revision': self._val(item, 'Revision'),
    #                 'status': self._val(item, 'Status'),
    #                 'type': self._val(item, 'Type'),
    #                 'uom': self._val(item, 'UOM'),
    #                 'warehouse': self._val(item, 'Warehouse'),
    #             }

    #             # === PRINT DATA HEADER ===
    #             # print("==========================================================================================")
    #             # print("HEADER DATA:")
    #             # for h_key, h_val in header.items():
    #                 # print(f"{h_key:<25} : {h_val}")

    #             assembly = self.env['acumatica.kit.assembly'].create(header)  # Simpan header ke staging untuk referensi, bisa dihapus jika tidak perlu
    #             print(f"Created staging header record with ID {assembly.id} for ReferenceNbr {header['reference_nbr']}")

    #             stock_components = item.get('StockComponents') or []
    #             if isinstance(stock_components, dict):
    #                 stock_components = stock_components.get('value', []) or []
    #             if not isinstance(stock_components, list):
    #                 stock_components = []

    #             if not stock_components:
    #                 # print("-- (No Components Available)") # Info jika component kosong
    #                 result.append(dict(header, line_nbr='0'))
    #                 # print("==========================================================================================")
    #                 continue

    #             # === PRINT DATA COMPONENT ===
    #             # print("COMPONENTS:")
    #             for component in stock_components:
    #                 line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
                    
    #                 # Buat dictionary component data untuk mempermudah perulangan print
    #                 component_data = {
    #                     'line_external_id': component.get('id', '') or '',
    #                     'line_note': component.get('note', {}).get('value', '') or '',
    #                     'line_inventory_id': self._val(component, 'InventoryID'),
    #                     'line_component_qty': self._val(component, 'ComponentQty'),
    #                     'line_nbr': str(line_nbr),
    #                     'line_location_id': self._val(component, 'LocationID'),
    #                     'line_quantity': self._val(component, 'Qty'),
    #                     'line_reason_code': self._val(component, 'ReasonCode'),
    #                     'stock_inventory_id': self._val(component, 'StockInventoryID'),
    #                     'line_uom': self._val(component, 'UOM'),
    #                     'assembly_id': assembly.id,  # Simpan component dengan relasi ke header yang sudah dibuat, bisa dihapus jika tidak perlu
    #                 }
                    
    #                 # Print setiap field di dalam component ini dengan awalan '--'
    #                 # print("  ----------------------------------------")
    #                 # for c_key, c_val in component_data.items():
    #                     # print(f"  -- {c_key:<25} : {c_val}")

    #                 assembly_line = self.env['acumatica.kit.assembly.component'].create(component_data)  # Simpan component ke staging, bisa dihapus jika tidak perlu
    #                 # print(f"  Created staging component record with ID {assembly_line.id} for LineNbr {component_data['line_nbr']} under ReferenceNbr {header['reference_nbr']}")
                    
    #                 # Tetap masukkan ke hasil akhir Odoo wizard Anda
    #                 result.append({**header, **component_data})
                
    #             # print("==========================================================================================")


    #         # for item in raw_data:
    #         #     header = {
    #         #         'external_id': item.get('id', '') or '',
    #         #         'row_number': item.get('rowNumber', 0) or 0,
    #         #         'description': self._val(item, 'Description'),
    #         #         'inventory_id': self._val(item, 'InventoryID'),
    #         #         'last_modified_datetime': self._val(item, 'LastModifiedDateTime'),
    #         #         'location': self._val(item, 'Location'),
    #         #         'post_period': self._val(item, 'PostPeriod'),
    #         #         'quantity': self._val(item, 'Qty'),
    #         #         'reason_code': self._val(item, 'ReasonCode'),
    #         #         'reference_nbr': self._val(item, 'ReferenceNbr'),
    #         #         'requested_on': self._val(item, 'RequestedOn'),
    #         #         'revision': self._val(item, 'Revision'),
    #         #         'status': self._val(item, 'Status'),
    #         #         'type': self._val(item, 'Type'),
    #         #         'uom': self._val(item, 'UOM'),
    #         #         'warehouse': self._val(item, 'Warehouse'),


    #         #     }

    #         #     stock_components = item.get('StockComponents') or []
    #         #     if isinstance(stock_components, dict):
    #         #         stock_components = stock_components.get('value', []) or []
    #         #     if not isinstance(stock_components, list):
    #         #         stock_components = []

    #         #     if not stock_components:
    #         #         result.append(dict(header, line_nbr='0'))
    #         #         continue

    #         #     for component in stock_components:
    #         #         line_nbr = self._val(component, 'LineNbr') or component.get('rowNumber') or 0
    #         #         result.append({
    #         #             **header,
    #         #             'line_external_id': component.get('id', '') or '',
    #         #             'line_note': component.get('note', {}).get('value', '') or '',
    #         #             'line_inventory_id': self._val(component, 'InventoryID'),
    #         #             'line_component_qty': self._val(component, 'ComponentQty'),
    #         #             'line_nbr': str(line_nbr),
    #         #             'line_location_id': self._val(component, 'LocationID'),
    #         #             'line_quantity': self._val(component, 'Qty'),
    #         #             'line_reason_code': self._val(component, 'ReasonCode'),
    #         #             'stock_inventory_id': self._val(component, 'StockInventoryID'),
    #         #             'line_uom': self._val(component, 'UOM'),
    #         #         })

            
    #         _logger.info(
    #             'Berhasil ambil %s rows Kit Assembly dari Acumatica (skip=%s, top=%s)',
    #             len(result), offset, limit,
    #         )
    #         return result
    #     finally:
    #         self._do_logout(session)
    #         self.last_sync = fields.Datetime.now()
