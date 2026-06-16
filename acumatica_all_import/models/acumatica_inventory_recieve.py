import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
import requests


class AcumaticaInventoryRecievedConfig(models.Model):
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

            raw_data = self._normalize_rows(response.json())
            result = []

            for row_number, item in enumerate(raw_data, start=1):
                header = {
                    'external_id': item.get('id', '') or '',
                    'row_number': item.get('rowNumber', '') or '',
                    'note': item.get('note', {}).get('value', '') or '',
                    'branch_warehouse': self._val(item, 'Branch'),
                    # ChangeItemRefNbr
                    'actual_qty': self._val(item, 'ControlQty'),
                    # Customer
                    'scheduled_date': self._val(item, 'Date'),
                    'header_description': self._val(header, 'Description'),
                    # DocumentOnly
                    # ExternalRef
                    'acumatica_write_date': self._val(header, 'LastModifiedDateTime'),
                    # Location
                    'post_period': str(self._val(header, 'PostPeriod')),
                    'reference_nbr': self._val(item, 'ReferenceNbr'),
                    # ShipmentNbr
                    'status': self._val(item, 'Status'),
                    'total_qty': str(self._val(item, 'TotalQty')),
                    # TransferNbr
                    'transfer_type': self._val(item, 'TransType'),
                }
                
                details = self._normalize_rows(header.get('Details') or header.get('details') or [])
                if not details:
                    details = [{}]

                for detail in details:
                    result.append({        
                        'line_external_id': item.get('id', '') or '',
                        'line_note': self._val(detail, 'note'),
                        'branch_warehouse': self._val(item, 'Branch'),
                        'line_description': self._val(detail, 'Description'),
                        'inventory_id': self._val(detail, 'InventoryID'),
                        'line_nbr': str(self._val(detail, 'LineNbr')),
                        'location_code': self._val(detail, 'Location'),
                        'product_uom_qty': str(self._val(detail, 'Qty')),
                        'uom_code': self._val(detail, 'UOM'),
                        'warehouse_dest_code': self._val(detail, 'Warehouse'),
                    })
                    row_number += 1
            self.last_sync = fields.Datetime.now()
            return result
        finally:
            self._do_logout(session)


class AcumaticaReceiptProductLine(models.Model):
    _name = 'acumatica.inventory.recieved.product.line'
    _description = 'Data Product Inventory Recieve dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica', readonly=True)
    inventory_line_id = fields.Many2one('acumatica.inventory.recieved.line', string='Receipt', ondelete='cascade')

    line_external_id = fields.Char(string='UUID Line', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)
    line_description = fields.Char(string='Description', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    location_code = fields.Char(string='Location', readonly=True)
    product_uom_qty = fields.Char(string='Qty', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)


class AcumaticaInventoryRecievedLine(models.Model):
    _name = 'acumatica.inventory.recieved.line'
    _description = 'Data Inventory Recieved dari Acumatica'
    _order = 'reference_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    product_line_ids = fields.One2many('acumatica.inventory.recieved.product.line', 'inventory_line_id', string='Lines')

    reference_nbr = fields.Char(string='Reference Number', readonly=True, index=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)

    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    warehouse_code = fields.Char(string='Warehouse')
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)
    transfer_type = fields.Char(string='Transfer Type', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)
    external_ref = fields.Char(string='External Ref', readonly=True)
    customer_code = fields.Char(string='Branch Warehouse', readonly=True)
    shipment_nbr = fields.Char(string='Shipment Nbr', readonly=True)
    transfer_nbr = fields.Char(string='Transfer Nbr', readonly=True)
    location_code = fields.Char(string='Location Code', readonly=True)
    change_item_ref_nbr = fields.Char(string='Change Item Ref Number', readonly=True)


    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Delivery Order di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.inventory.recieved.config', string='Konfigurasi', readonly=True, ondelete='cascade')
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

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)

        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line.warehouse_code
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse

    def _find_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        location = False
        if line.warehouse_code:
            location = Location.search([('code', '=', line.warehouse_code)], limit=1)
            if location:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
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
        Error = self.env['stock.picking.acumatica.error']
        ErrorLine = self.env['stock.picking.acumatica.error.line']

        imported = updated = error = 0
        for line in self:
            first = line
            origin = first.reference_nbr or False
            error_list = []
            try:
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    error_list.append(f'Warehouse with location code {first.warehouse_code} was not found in the WMS | MAPPING WAREHOUSE.')

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id if warehouse else False),
                    ('operation_category', '=', 'internal'),
                    ('code', '=', 'internal'),
                ], limit=1)
                if not picking_type:
                    warehouse_txt = f'Warehouse code {warehouse.name}'
                    location_txt = f'Location code {first.warehouse_code}'
                    error_list.append(f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | MASTER OPERATION TYPE.')

                dest_location = self._find_location_dest(first)
                if not dest_location:
                    error_list.append(f'Location with code {first.warehouse_dest_code} was not found in the WMS | MAPPING WAREHOUSE.')

                vals = {
                    'origin': origin,
                    'picking_type_id': picking_type.id,
                    'location_dest_id': dest_location.id if dest_location else False,
                    'adt_dest_location_id': dest_location.id if dest_location else False,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,

                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.transfer_type or False,
                    'adt_external_ref': first.external_ref or False,
                }
                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Picking._fields}


                picking = self.odoo_picking_id
                error_data = False
                if error_list:
                    error_data = Error.search([('origin', '=', origin)], limit=1)
                    if not error_data:
                        error_data = Error.create({
                            'operation_type': 'receipt',
                            'location': first.warehouse_code or False,
                            'location_dest': first.warehouse_dest_code or False,
                            'scheduled_date': self._parse_dt(first.scheduled_date),
                            'origin': origin,
                            'adt_total_qty': self._parse_float(first.total_qty),
                            'adt_actual_qty': self._parse_float(first.actual_qty),
                            'api_acumatica': 'inventory_received',
                            'error_message': '\n'.join(error_list),
                            'payload': str(vals)[:1000],
                        })
                else:
                    if picking:
                        if picking.state in ('done', 'cancel'):
                            raise UserError(f'Receive {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                        picking.write(vals)
                        action_state = 'updated'
                        updated += 1
                    else:
                        picking = Picking.create(vals)
                        picking.action_confirm()
                        action_state = 'imported'
                        imported += 1

                for line in self.product_line_ids:
                    try:
                        product = self._find_product(line)
                        if not product:
                            error_list.append(f'Product with InventoryID {line.inventory_id} was not found in the WMS | MASTER PRODUCT.')

                        uom = self._find_uom(line, product)
                        if not uom:
                            error_list.append(f'UOM with InventoryID {line.inventory_id} was not found in the WMS | MASTER UOM.')

                        qty = self._parse_float(line.product_uom_qty)
                        move_name = line.line_description or product.display_name
                        # move_dest = self._find_location(line, warehouse) or dest_location or picking.location_dest_id

                        # existing = Move.search([
                        #     ('picking_id', '=', picking.id),
                        #     ('product_id', '=', product.id),
                        #     ('name', '=', move_name),
                        #     ('product_uom_qty', '=', qty),
                        # ], limit=1)
                        existing = picking.move_ids.filtered(lambda m:
                            m.picking_id == picking.id and
                            m.product_id.id == product.id and
                            m.product_uom_qty == qty
                        )
                        if existing:
                            first.write({
                                'import_state': action_state,
                                'import_message': f'{action_state.title()}: {picking.name} (move sudah ada)',
                                'odoo_picking_id': picking.id,
                            })
                            continue

                        move_vals = {
                            'name': move_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            # 'location_dest_id': move_dest.id,
                            'description_picking': line.line_description or False,

                            'adt_inventory_id': line.line_note or False,
                            'adt_line_nbr': line.line_nbr or False,
                            'adt_uom_code': line.uom_code or False,
                            'adt_warehouse_dest_code': line.warehouse_dest_code or False,
                            'adt_type': first.transfer_type or False,
                        }
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}
                        if error_data:
                            existing_error = error_data.line_ids.filtered(lambda m:
                                m.error_id.id == error_data.id and
                                m.inventory_id == line.inventory_id and
                                m.qty == line.product_uom_qty
                            )
                            if existing_error:
                                ErrorLine.create({
                                    'error_id': error_data.id,
                                    'inventory_id': line.inventory_id or False,
                                    'product_name': line.line_description or False,
                                    'qty': line.product_uom_qty or False,
                                    'uom': line.uom_code or False,
                                })
                            else:
                                ErrorLine.create({
                                    'error_id': error_data.id,
                                    'inventory_id': line.inventory_id or False,
                                    'product_name': line.line_description or False,
                                    'qty': line.product_uom_qty or False,
                                    'uom': line.uom_code or False,
                                })
                            continue

                        if error_list:                                
                            error_line_data = ErrorLine.search([('error_id', '=', error.id)], limit=1)
                            if not error_line_data:
                                error_line_data = ErrorLine.create({
                                    'error_id': error_data.id,
                                    'inventory_id': line.inventory_id or False,
                                    'product_name': line.line_description or False,
                                    'qty': line.product_uom_qty or False,
                                    'uom': line.uom_code or False,
                                    'payload': str(move_vals)[:1000],
                                })
                                error += 1
                                first.write({
                                    'import_state': action_state,
                                    'import_message': f'{action_state.title()}: {picking.name}',
                                })
                        else:
                            Move.create(move_vals)

                        first.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name}',
                            'odoo_picking_id': picking.id,
                        })
                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        first.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_picking_id': picking.id if picking else False,
                        })

                if error_list:
                    _logger.exception("Error import receipt %s", origin)
                    self.write({
                        'import_state': 'error',
                        'import_message': '\n'.join(error_list),
                    })
                    error += 1

            except Exception as e:
                _logger.exception('Error import inventory recieved %s', first.id)
                first.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200]
                })

        msg = f'Import selesai: {imported} delivery dibuat, {updated} delivery diupdate, {error} line error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Inventory Recieved to Delivery Order',
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
            raise UserError('Belum diimport, belum ada delivery order di Odoo.')
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
