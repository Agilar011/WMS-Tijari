from dateutil import parser as dateutil_parser
import logging
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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


class AcumaticaTransferOneStepLine(models.Model):
    _name = 'acumatica.transfer.one.step.line'
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header Acumatica', readonly=True)
    line_external_id = fields.Char(string='UUID Line Acumatica', readonly=True)

    reference_nbr = fields.Char(string='Reference Number', readonly=True, index=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    to_warehouse_code = fields.Char(string='To Warehouse', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    from_warehouse_code = fields.Char(string='From Warehouse', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    transfer_type = fields.Char(string='Transfer Type', readonly=True)
    trans_type = fields.Char(string='Trans Type', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)

    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)
    line_description = fields.Char(string='Line Description', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    from_location_code = fields.Char(string='From Location', readonly=True)
    to_location_code = fields.Char(string='To Location', readonly=True)
    quantity = fields.Char(string='Quantity', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.transfer.one.step.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('reference_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.reference_nbr and Picking.search_count([('origin', '=', rec.reference_nbr)]))

    @staticmethod
    def _parse_dt(dt_str):
        if not dt_str:
            return False
        try:
            return dateutil_parser.parse(dt_str).replace(tzinfo=None)
        except Exception:
            return False

    @staticmethod
    def _parse_float(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _find_vendor(self, line):
        Partner = self.env['res.partner']
        vendor = False
        if line.vendor_code:
            vendor = Partner.search([('ref', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            if not vendor:
                vendor = Partner.search([('name', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
        return vendor

    # def _find_product(self, line):
    #     Product = self.env['product.product']
    #     product = False
    #     if line.inventory_id:
    #         product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
    #         if not product:
    #             product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
    #     if not product and line.transaction_description:
    #         product = Product.search([('name', '=', line.transaction_description)], limit=1)
    #     return product
    def _find_product(self, line):
        Product = self.env['product.product']

        product = False

        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)

        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)

        if not product:
            name = line.line_description or line.description or line.inventory_id or 'Unknown Product'
            existing = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if existing:
                return existing
            product = Product.create({
                'name': name,
                'default_code': line.inventory_id or False,
                'type': 'consu',  # stockable
            })

        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        warehouse = False
        if line.to_warehouse_code:
            warehouse_code = line.to_warehouse_code or line.from_warehouse_code
            warehouse = Warehouse.search([('code', '=', warehouse_code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', warehouse_code)], limit=1)
            else:
                warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location_dest(self, line, warehouse=False):
        Location = self.env['stock.location']
        location = False
        if line.to_location_code:
            location = Location.search([('complete_name', '=', line.to_location_code)], limit=1)
            if not location:
                location = Location.search([('name', '=', line.to_location_code)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()
    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        imported = 0
        updated = 0
        error = 0

        # proses per receipt number
        for reference_nbr in self.mapped('reference_nbr'):
            receipt_lines = self.filtered(
                lambda l: l.reference_nbr == reference_nbr and l.import_state == 'pending'
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]

            try:
                # vendor = self._find_vendor(first)
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(
                        f'Warehouse tidak ditemukan untuk code: {first.to_warehouse_code or first.from_warehouse_code or "-"}'
                    )

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'internal'), ('name', '=', 'Internal Transfers' )
                ], limit=1) or PickingType.search([
                    ('code', '=', 'internal'), ('name', '=', 'Internal Transfers' )
                ], limit=1)

                print(picking_type.mapped('name'))

                if not picking_type:
                    raise UserError('Picking type internal tidak ditemukan.')

                dest_location = self._find_location_dest(first, warehouse)
                if not dest_location:
                    raise UserError(
                        f'Location tujuan tidak ditemukan untuk code: '
                        f'{first.location_dest_code or first.header_location_code or "-"}'
                    )

                origin = first.reference_nbr or False

                vals = {
                    # 'partner_id': vendor.id if vendor else False,
                    'picking_type_id': picking_type.id,
                    'location_id': (
                        picking_type.default_location_src_id.id
                        if picking_type.default_location_src_id
                        else self.env.ref('stock.stock_location_suppliers').id
                    ),
                    # 'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'origin': origin,
                    'note': first.note or False,
                    # reference_nbr = 
                    # trans_type = 

                    # field custom, kalau ada di model
                    'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.transfer_type or False,
                    'adt_to_warehouse_code': first.to_warehouse_code or False,
                    'adt_from_warehouse_code': first.from_warehouse_code or False,
                    'adt_description': first.description or False,
                }

                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Picking._fields}

                # pakai origin buat dedup
                picking = Picking.search([('origin', '=', origin)], limit=1)

                if picking:
                    if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                        raise UserError(
                            f'Receipt {reference_nbr} sudah ada di Odoo dengan state '
                            f'{picking.state}, tidak bisa diupdate.'
                        )
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                else:
                    picking = Picking.create(vals)
                    action_state = 'imported'
                    imported += 1

                for line in receipt_lines:
                    try:
                        product = self._find_product(line)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.inventory_id or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        line_dest = self._find_location_dest(line, warehouse) or dest_location
                        qty = self._parse_float(line.quantity)

                        # dedup move
                        move_domain = [('picking_id', '=', picking.id)]
                        if 'adt_line_external_id' in Move._fields and line.line_external_id:
                            move_domain.append(('adt_line_external_id', '=', line.line_external_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('product_uom_qty', '=', qty),
                            ]

                        existing_move = Move.search(move_domain, limit=1)
                        if existing_move:
                            line.write({
                                'import_state': action_state,
                                'import_message': f'Skip duplicate: {picking.name}',
                                'odoo_picking_id': picking.id,
                            })
                            continue

                        move_vals = {
                            'name': line.description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': line_dest.id,
                            'description_picking': line.description or False,

                            'adt_line_nbr': line.line_nbr or False,
                            'adt_line_note': line.line_note or False,
                            'adt_inventory_id': line.inventory_id or False,
                            'adt_uom_code': line.uom_code or False,
                            'adt_line_description': line.line_description or False,
                            'adt_to_location_code': line.to_location_code or False,
                            'adt_from_location_code': line.from_location_code or False,
                            'adt_quantity': self._parse_float(line.quantity),

                        }

                        # filter field yang ada di stock.move
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}

                        Move.create(move_vals)

                        line.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name}',
                            'odoo_picking_id': picking.id,
                        })

                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        line.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_picking_id': picking.id if picking else False,
                        })
                        error += 1

            except Exception as e:
                _logger.exception("Error import receipt %s", reference_nbr)
                receipt_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                error += len(receipt_lines)

        msg = f'Import selesai: {imported} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Receipt',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

    def action_open_picking(self):
        self.ensure_one()
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada receipt di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }

    def action_select_all(self):
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})
