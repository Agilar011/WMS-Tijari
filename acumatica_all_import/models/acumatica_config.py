import requests
import json
import logging

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

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
        help='Dipakai untuk transaksi yang butuh endpoint Acumatica spesifik.',
    )
    is_default = fields.Boolean(
        string='Default',
        default=False,
        help='Dipakai sebagai config bawaan untuk tipe import yang sama.',
    )
    config_type = fields.Selection(
        selection=[
            ('po_receipt', 'PO Receipt'),
            ('so_transfer', 'SO Transfer'),
            ('receipt_change_item', 'Receipt Change Item'),
            ('inventory_received', 'Inventory Received'),
            ('shipment_so', 'Shipment SO Return'),
            ('so_shipment', 'SO Shipment'),
            ('transfer_shipment', 'Transfer Shipment'),
            ('issue_change_item', 'Issue Change Item'),
            ('inventory_issue', 'Inventory Issue'),
            ('issue_po_return', 'Issue PO Return'),
            ('transfer_one_step', 'Transfer One Step'),
            ('transfer_two_step', 'Transfer Two Step'),
            ('kit_assembly', 'Kit Assembly'),

            ('customer', 'Customer'),
            ('customer_location', 'Customer Location'),
            ('shipvia', 'Ship Via'),
            ('warehouse', 'Warehouse'),
            ('stock_item', 'Stock Item'),
            ('non_stock_item', 'Non Stock Item'),
            ('uom', 'Unit of Measure'),
            ('vendor', 'Vendor'),
            ('inventory_stock', 'Inventory Stock'),
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
            return default_config

        return self.search([
            ('config_type', '=', config_type),
            ('active', '=', True),
        ], limit=1)

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
    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass  # Logout gagal tidak masalah

    # ─── Fetch UoM dari API ──────────────────────────
    def fetch_uom_data(self, limit=500, offset=0):
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
