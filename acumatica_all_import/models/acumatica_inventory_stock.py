
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AcumaticaInventoryStockLine(models.Model):
    """
    Tabel staging: hasil tarikan data Inventory Stock dari Acumatica
    Mapping:
    """
    _name = 'acumatica.inventory.stock.line'
    _description = 'Data Inventory Stock dari Acumatica (Staging)'
    _order = 'row_number asc, unit_id asc'

    # ─── Data dari Acumatica ─────────────────────────
    row_number  = fields.Integer(string='No', readonly=True)
    unit_id     = fields.Char(string='UnitID (→ Kategori)', required=True, readonly=True)
    description = fields.Char(string='Description (→ Nama UoM)', readonly=True)
    external_id = fields.Char(string='UUID Acumatica', readonly=True)

    # ─── Status Import ───────────────────────────────
    import_state = fields.Selection([
        ('pending',  'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('skipped',  'Dilewati (Sudah Ada)'),
        ('error',    'Error'),
    ], string='Status', default='pending', readonly=True)

    import_message  = fields.Char(string='Keterangan', readonly=True)
    odoo_uom_id     = fields.Many2one('uom.uom', string='UoM di Odoo', readonly=True)
    odoo_categ_id   = fields.Many2one('uom.category', string='Kategori di Odoo', readonly=True)
    selected        = fields.Boolean(string='Pilih', default=True)

    # ─── Config reference ────────────────────────────
    config_id = fields.Many2one(
        'acumatica.config',
        string='Konfigurasi',
        readonly=True,
        ondelete='cascade',
    )
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # ─── Computed: sudah ada di Odoo? ────────────────
    exists_in_odoo = fields.Boolean(
        string='Sudah Ada di Odoo',
        compute='_compute_exists_in_odoo',
        store=False,
    )

    @api.depends('description')
    def _compute_exists_in_odoo(self):
        for rec in self:
            if rec.description:
                existing = self.env['uom.uom'].search([
                    ('name', '=ilike', rec.description)
                ], limit=1)
                rec.exists_in_odoo = bool(existing)
            else:
                rec.exists_in_odoo = False

    # ─── Action: Import baris yang dipilih ───────────
    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        """Import 1 baris saja (dari tombol di list)"""
        self.ensure_one()
        return self._do_import()

    def _do_import(self):
        """
        Logika import:
          - UnitID     → cari/buat uom.category
          - Description → cari/buat uom.uom di dalam kategori tersebut
        """
        imported = skipped = error = 0

        for line in self:
            try:
                if not line.description:
                    line.write({
                        'import_state':   'error',
                        'import_message': 'Description kosong, tidak bisa jadi nama UoM',
                    })
                    error += 1
                    continue

                # ── 1. Cari Kategori Unit ──
                uom_categ = self.env['uom.category'].search([
                    ('name', '=ilike', 'Unit')
                ], limit=1)
                if not uom_categ:
                    uom_categ = self.env['uom.category'].create({'name': 'Unit'})
                    _logger.info("Kategori UoM baru dibuat: %s", 'Unit')

                # ── 2. Cek apakah uom.uom (Description) sudah ada ──
                existing = self.env['uom.uom'].search([
                    ('name', '=ilike', line.description),
                    ('category_id', '=', uom_categ.id),
                ], limit=1)

                if existing:
                    existing.categ_id = uom_categ.id  # Pastikan kategorinya sesuai
                    line.write({
                        'import_state':   'skipped',
                        'import_message': f'Sudah ada: {existing.name} (kategori: {uom_categ.name})',
                        'odoo_uom_id':    existing.id,
                        'odoo_categ_id':  uom_categ.id,
                    })
                    skipped += 1
                else:
                    # Cek apakah kategori sudah punya reference unit
                    has_reference = self.env['uom.uom'].search([
                        ('category_id', '=', uom_categ.id),
                        ('uom_type', '=', 'reference'),
                    ], limit=1)

                    # ── 3. Buat uom.uom baru ──
                    new_uom = self.env['uom.uom'].create({
                        'name':        line.description,
                        'category_id': uom_categ.id,
                        'uom_type':    'smaller' if has_reference else 'reference',
                        'factor':      1.0,
                        'rounding':    0.01,
                        'active':      True,
                    })
                    line.write({
                        'import_state':   'imported',
                        'import_message': f'Dibuat: {new_uom.name} → kategori: {uom_categ.name}',
                        'odoo_uom_id':    new_uom.id,
                        'odoo_categ_id':  uom_categ.id,
                    })
                    imported += 1

            except Exception as e:
                _logger.error("Error import UoM line %s / %s: %s", line.unit_id, line.description, str(e))
                line.write({
                    'import_state':   'error',
                    'import_message': str(e)[:200],
                })
                error += 1

        # Notifikasi hasil
        msg = f'Import selesai: {imported} berhasil, {skipped} dilewati, {error} error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import UoM',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    # ─── Action: Reset status ─────────────────────────
    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state in ('skipped', 'error')).write({
            'import_state': 'pending',
            'import_message': False,
        })

    # ─── Select / Deselect all ───────────────────────
    def action_select_all(self):
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})

class AcumaticaInventoryStockConfig(models.Model):
    _name = 'acumatica.inventory.recieved.config'
    _description = 'Konfigurasi Koneksi Acumatica - Inventory Recieved'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Inventory Recieved')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.002')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
    endpoint_name = fields.Char(required=True, default='InventoryReceipt')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], default='draft', readonly=True)

    odata_expand = fields.Char(default='Details')
    odata_select = fields.Char()
    odata_filter = fields.Char(default="TransType eq 'Inventory Receive'")

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
            self._do_logout(session)
            self.state = 'connected'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Koneksi Berhasil',
                    'message': f'Berhasil terhubung ke {self.base_url}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            self.state = 'error'
            raise UserError(f'Koneksi gagal: {str(e)}')

    def _do_login(self):
        self.ensure_one()
        session = requests.Session()
        response = session.post(
            self.login_url,
            json={
                'name': self.username,
                'password': self.password,
                'company': self.company_code,
            },
            headers={'Content-Type': 'application/json'},
            timeout=30,
        )
        if response.status_code == 204:
            return session
        raise UserError(f'Login gagal (HTTP {response.status_code}): {response.text}')

    def _do_logout(self, session):
        try:
            session.post(self.logout_url, timeout=10)
        except Exception:
            pass

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

    def fetch_inventory_recieved_data(self, limit=50, offset=0, reference_nbr=False, last_modified_from=False, odata_filter=False):
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
            # if self.odata_filter:
            #     filters.append(f"({self.odata_filter})")
            if odata_filter:
                filters.append(f"({odata_filter})")
            if filters:
                params['$filter'] = ' and '.join(filters)

            response = session.get(endpoint, params=params, timeout=60)
            if response.status_code != 200:
                raise UserError(f'Gagal fetch data (HTTP {response.status_code}): {response.text}')

            rows = self._normalize_rows(response.json())
            result = []
            row_number = 1
            for header in rows:
                details = self._normalize_rows(header.get('Details') or header.get('details') or [])
                if not details:
                    details = [{}]
                for detail in details:
                    result.append({
                        'row_number': row_number,
                        'external_id': self._val(header, 'id') or header.get('id') or '',
                        'line_external_id': self._val(detail, 'id') or detail.get('id') or '',
                        'reference_nbr': self._val(header, 'ReferenceNbr'),
                        'scheduled_date': self._val(header, 'Date'),
                        'description': self._val(detail, 'Description') or self._val(header, 'Description'),
                        'header_description': self._val(header, 'Description'),
                        'actual_qty': str(self._val(header, 'ControlQty')),
                        'is_hold': str(self._val(header, 'Hold')),
                        'acumatica_write_date': self._val(header, 'LastModifiedDateTime'),
                        'post_period': str(self._val(header, 'PostPeriod')),
                        'status': self._val(header, 'Status'),
                        'total_qty': str(self._val(header, 'TotalQty')),
                        'warehouse_code': self._val(header, 'ToWarehouseID'),
                        'transfer_type': self._val(header, 'TransType'),
                        'note': self._val(header, 'note'),
                        'line_note': self._val(detail, 'note'),
                        'location_code': self._val(detail, 'Location'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(self._val(detail, 'LineNbr')),
                        'product_uom_qty': str(self._val(detail, 'Qty')),
                        'detail_warehouse_code': self._val(detail, 'WarehouseID'),
                        'uom_code': self._val(detail, 'UOM'),
                    })
                    row_number += 1
            self.last_sync = fields.Datetime.now()
            return result
        finally:
            self._do_logout(session)
