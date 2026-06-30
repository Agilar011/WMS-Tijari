import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError
import requests

_logger = logging.getLogger(__name__)


class ReceiptImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaTransferConfig(models.Model):
    _name = 'acumatica.transfer.config'
    _description = 'Konfigurasi Koneksi Acumatica - SOTR'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Acumatica Internal Transfer')
    base_url = fields.Char(required=True, help='Contoh: http://server/acumportal/entity')
    api_version = fields.Char(required=True, default='25.200.002')
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    company_code = fields.Char(required=True)
    endpoint_name = fields.Char(required=True, default='PurchaseReceipt')
    active = fields.Boolean(default=True)
    last_sync = fields.Datetime(readonly=True)
    state = fields.Selection([
        ('draft', 'Belum Ditest'),
        ('connected', 'Terhubung'),
        ('error', 'Error'),
    ], default='draft', readonly=True)

    odata_expand = fields.Char(default='Details')
    odata_select = fields.Char()
    odata_filter = fields.Char(default="Type eq 'Transfer Receipt'")

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

    # def fetch_transfer_data(self, limit=50, offset=0, receipt_nbr=False, last_modified_from=False, odata_filter=False):
    #     self.ensure_one()
    #     session = self._do_login()
    #     try:
    #         endpoint = f"{self.api_url}/{self.endpoint_name}"
    #         params = {'$top': limit, '$skip': offset}
    #         filters = []

    #         if self.odata_expand:
    #             params['$expand'] = self.odata_expand
    #         if self.odata_select:
    #             params['$select'] = self.odata_select
    #         if receipt_nbr:
    #             filters.append(f"ReceiptNbr eq '{receipt_nbr}'")
    #         if last_modified_from:
    #             filters.append(f"LastModifiedDateTime ge datetimeoffset'{last_modified_from}'")
    #         if odata_filter:
    #             filters.append(f"({odata_filter})")
    #         elif self.odata_filter:
    #             filters.append(f"({self.odata_filter})")

    #         if filters:
    #             params['$filter'] = ' and '.join(filters)

    #         response = session.get(endpoint, params=params, timeout=90)
    #         if response.status_code != 200:
    #             raise UserError(f'Gagal ambil data Transfer Receipt (HTTP {response.status_code}): {response.text}')

    #         raw_data = self._normalize_rows(response.json())
    #         result = []
    #         is_found_dest_warehouse = False

    #         for row_number, item in enumerate(raw_data, start=1):
    #             header = {
    #                 'external_id': item.get('id', '') or '',
    #                 'row_number': row_number,
    #                 'note': item.get('note', {}).get('value', '') or '',
    #                 'branch_warehouse': self._val(item, 'Branch'),
    #                 'actual_qty': self._val(item, 'ControlQty'),
    #                 'scheduled_date': self._val(item, 'Date'),
    #                 'is_hold': self._val(item, 'Hold'),
    #                 'inventory_ref': self._val(item, 'InventoryRefNbr'),
    #                 'acumatica_write_date': self._val(item, 'LastModifiedDateTime'),
    #                 'header_location_code': self._val(item, 'Location'),
    #                 'post_period': self._val(item, 'PostPeriod'),
    #                 'receipt_nbr': self._val(item, 'ReceiptNbr'),
    #                 'status': self._val(item, 'Status'),
    #                 'total_qty': self._val(item, 'TotalQty'),
    #                 'receipt_type': self._val(item, 'Type'),
    #                 'vendor_code': self._val(item, 'VendorID'),
    #                 'partner_ref': self._val(item, 'VendorRef'),
    #                 'warehouse_dest_code': self._val(item, 'Warehouse'),
    #             }

    #             details = item.get('Details') or []
    #             if isinstance(details, dict):
    #                 details = details.get('value', []) or []
    #             if not isinstance(details, list):
    #                 details = []

    #             if not details:
    #                 result.append(dict(header, line_nbr='0'))
    #                 continue

    #             for detail in details:
    #                 line_nbr = self._val(detail, 'LineNbr') or detail.get('rowNumber') or 0
    #                 description = self._val(detail, 'Description') or self._val(detail, 'TransactionDescription')
    #                 transfer_shipment_nbr = self._val(detail, 'TransferShipmentNbr')
    #                 if transfer_shipment_nbr and not is_found_dest_warehouse:
    #                     dest_warehouse_data = self.search_dest_warehouse(transfer_shipment_nbr, session)
    #                     is_found_dest_warehouse = True

    #                 result.append({
    #                     **header,
    #                     'line_external_id': detail.get('id', '') or '',
    #                     'line_note': detail.get('note', {}).get('value', '') or '',
    #                     'description': description,
    #                     'inventory_id': self._val(detail, 'InventoryID'),
    #                     'line_nbr': str(line_nbr),
    #                     'line_type': self._val(detail, 'LineType'),
    #                     'location_dest_code': self._val(detail, 'Location'),
    #                     'open_qty': self._val(detail, 'OpenQty'),
    #                     'order_qty': self._val(detail, 'OrderedQty'),
    #                     'po_line_number': self._val(detail, 'POLineNbr'),
    #                     'po_number': self._val(detail, 'POOrderNbr'),
    #                     'po_type': self._val(detail, 'POOrderType'),
    #                     'po_receipt_line_number': self._val(detail, 'POReceiptLineNbr'),
    #                     'po_receipt_number': self._val(detail, 'POReceiptNbr'),
    #                     'product_uom_qty': self._val(detail, 'ReceiptQty'),
    #                     'transaction_description': self._val(detail, 'TransactionDescription'),
    #                     'transfer_order_line_number': self._val(detail, 'TransferOrderLineNbr'),
    #                     'transfer_order_number': self._val(detail, 'TransferOrderNbr'),
    #                     'transfer_order_type': self._val(detail, 'TransferOrderType'),
    #                     'transfer_shipment_number': transfer_shipment_nbr,
    #                     'uom_code': self._val(detail, 'UOM'),
    #                     'warehouse_code': dest_warehouse_data.get('source_warehouse') if dest_warehouse_data else None,
    #                 })

    #         _logger.info('Berhasil ambil %s rows Transfer Receipt dari Acumatica', len(result))
    #         self.last_sync = fields.Datetime.now()
    #         return result
    #     finally:
    #         self._do_logout(session)

    # def search_dest_warehouse(self, transfer_nbr, session):
    #     self.ensure_one()
    #     # if not session:
    #     #     session = self._do_login()
    #     if not transfer_nbr:
    #         return None
    #     try:
    #         endpoint = f"{self.api_url}/Shipment"
    #         params = {
    #             '$select': 'ToWarehouseID, WarehouseID, ShipmentNbr', 
    #             '$filter': f"ShipmentNbr eq '{transfer_nbr}'"
    #         }

    #         response = session.get(endpoint, params=params, timeout=90)
    #         if response.status_code != 200:
    #             raise UserError(f'Gagal ambil data Destination Warehouse (HTTP {response.status_code}): {response.text}')

    #         raw_data = self._normalize_rows(response.json())

    #         item = raw_data[0]  # misal ambil data pertama

    #         result = {
    #             'shipment_number': self._val(item, 'ShipmentNbr'),
    #             'dest_warehouse': self._val(item, 'ToWarehouseID'),
    #             'source_warehouse': self._val(item, 'WarehouseID'),
    #         }

    #         _logger.info('Berhasil ambil data Warehouse dari Transfer Shipment', len(result))
    #         return result
    #     except Exception as e:
    #         _logger.error('Gagal ambil data Warehouse dari Transfer Shipment: %s', str(e))
    #         return None


class AcumaticaTransferProductLine(models.Model):
    _name = 'acumatica.transfer.product.line'
    _description = 'Data Product SOTR dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica', readonly=True)
    transfer_line_id = fields.Many2one('acumatica.transfer.line', string='Transfer', ondelete='cascade')
    line_external_id = fields.Char(string='UUID Line', readonly=True)
    
    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    transaction_description = fields.Char(string='Transaction Description', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    line_type = fields.Char(string='Line Type', readonly=True)
    location_dest_code = fields.Char(string='Location', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    po_line_number = fields.Char(string='PO Line Nbr', readonly=True)
    po_number = fields.Char(string='PO Number', readonly=True)
    po_type = fields.Char(string='PO Type', readonly=True)
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr', readonly=True)
    po_receipt_number = fields.Char(string='PO Receipt Nbr', readonly=True)
    product_uom_qty = fields.Char(string='Receipt Qty', readonly=True)
    transfer_order_number = fields.Char(string='Transfer Order Number', readonly=True, index=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Number', readonly=True)
    transfer_order_type = fields.Char(string='Transfer Order Type', readonly=True)
    transfer_shipment_number = fields.Char(string='Transfer Shipment Number', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)


class AcumaticaTransferLine(models.Model):
    _name = 'acumatica.transfer.line'
    _description = 'Data SOTR dari Acumatica'
    _order = 'transfer_order_number asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    product_line_ids = fields.One2many('acumatica.transfer.product.line', 'transfer_line_id', string='Lines')
    receipt_nbr = fields.Char(string='Receipt Number', readonly=True, index=True)
    transfer_order_number = fields.Char(string='Transfer Order Number', readonly=True, index=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Number', readonly=True)
    transfer_order_type = fields.Char(string='Transfer Order Type', readonly=True)
    transfer_shipment_number = fields.Char(string='Transfer Shipment Number', readonly=True)

    vendor_code = fields.Char(string='VendorID', readonly=True)
    partner_ref = fields.Char(string='Vendor Ref', readonly=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)
    header_location_code = fields.Char(string='Header Location', readonly=True)
    location_dest_code = fields.Char(string='Location', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    receipt_type = fields.Char(string='Type', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    total_qty = fields.Char(string='Total Qty', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    inventory_ref = fields.Char(string='Inventory Ref Nbr', readonly=True)
    post_period = fields.Char(string='Post Period', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    note = fields.Text(string='Header Note', readonly=True)
    branch_warehouse = fields.Char(string='Branch', readonly=True)

    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    description = fields.Char(string='Description', readonly=True)
    transaction_description = fields.Char(string='Transaction Description', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    line_type = fields.Char(string='Line Type', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    po_line_number = fields.Char(string='PO Line Nbr', readonly=True)
    po_number = fields.Char(string='PO Number', readonly=True)
    po_type = fields.Char(string='PO Type', readonly=True)
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr', readonly=True)
    po_receipt_number = fields.Char(string='PO Receipt Nbr', readonly=True)
    product_uom_qty = fields.Char(string='Receipt Qty', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Internal Transfer di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('receipt_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            origin = rec.receipt_nbr
            rec.exists_in_odoo = bool(origin and Picking.search_count([('origin', '=', origin)]))

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
        if not product and line.transaction_description:
            product = Product.search([('name', '=', line.transaction_description)], limit=1)
        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line.warehouse_code
        if code:
            warehouse = Warehouse.search([('code', '=', code), ('is_active', '=', True)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    

        return warehouse

    def _find_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        location = False
        if line.warehouse_dest_code:
            location = Location.search([('code', '=', line.warehouse_dest_code), ('is_active', '=', True)], limit=1)
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
        lines = self.filtered(lambda l: l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _persist_error_tracking(self, first, error_messages, line_payloads=None, payload=None):
        origin = first.receipt_nbr or False
        if not origin:
            return False

        line_payloads = line_payloads or []
        payload_text = payload if payload is not None else {}

        with self.env.registry.cursor() as cr:
            error_env = api.Environment(cr, self.env.uid, dict(self.env.context))
            Error = error_env['stock.picking.acumatica.error'].sudo()
            ErrorLine = error_env['stock.picking.acumatica.error.line'].sudo()

            error_data = Error.search([('origin', '=', origin)], limit=1)
            error_values = {
                'partner': first.vendor_code or False,
                'operation_type': 'receipt',
                'location': first.warehouse_code or False,
                'location_dest': first.warehouse_dest_code or False,
                'scheduled_date': first._parse_dt(first.scheduled_date),
                'origin': origin,
                'adt_total_qty': first._parse_float(first.total_qty),
                'adt_actual_qty': first._parse_float(first.actual_qty),
                'api_acumatica': 'po_receipt',
                'error_message': '\n'.join(error_messages),
                'payload': str(payload_text)[:1000],
                'state': 'new',
            }

            if error_data:
                error_data.write(error_values)
            else:
                error_data = Error.create(error_values)

            for line_payload in line_payloads:
                line_domain = [
                    ('error_id', '=', error_data.id),
                    ('inventory_id', '=', line_payload.get('inventory_id') or False),
                    ('qty', '=', line_payload.get('qty') or False),
                    ('uom', '=', line_payload.get('uom') or False),
                ]
                error_line = ErrorLine.search(line_domain, limit=1)
                line_values = {
                    'error_id': error_data.id,
                    'inventory_id': line_payload.get('inventory_id') or False,
                    'product_name': line_payload.get('product_name') or False,
                    'qty': line_payload.get('qty') or False,
                    'uom': line_payload.get('uom') or False,
                    'payload': str(line_payload.get('payload') or {})[:1000],
                }
                if error_line:
                    error_line.write(line_values)
                else:
                    ErrorLine.create(line_values)

            cr.commit()
            return error_data

    def _resolve_error_tracking(self, first):
        origin = first.receipt_nbr or False
        if not origin:
            return

        error_data = self.env['stock.picking.acumatica.error'].search([('origin', '=', origin)], limit=1)
        if error_data:
            error_data.write({'state': 'resolved'})

    def _import_single_receipt(self, receipt):
        receipt.ensure_one()

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = receipt.receipt_nbr or False
        header_payload = receipt.read()[0] if receipt.exists() else {}
        error_messages = []
        error_line_payloads = []
        picking = receipt.odoo_picking_id
        action_state = 'pending'

        # vendor = receipt._find_vendor(receipt)
        # if not vendor:
        #     error_messages.append(
        #         f'Vendor with VendorID {receipt.vendor_code} was not found in the WMS | WMS Dependency : MASTER VENDOR.'
        #     )

        warehouse = receipt._find_warehouse(receipt)
        if not warehouse:
            error_messages.append(
                f'Warehouse with location code {receipt.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        dest_location = receipt._find_location_dest(receipt)
        if not dest_location:
            error_messages.append(
                f'Location with code {receipt.warehouse_dest_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        picking_type = PickingType.search([
            ('warehouse_id', '=', warehouse.id if warehouse else False),
            ('operation_category', '=', 'internal'),
            ('code', '=', 'internal'),
        ], limit=1)
        if not picking_type:
            warehouse_txt = f"Warehouse code {warehouse.code if warehouse else '-'}"
            location_txt = f'Location code {receipt.warehouse_code}'
            error_messages.append(
                f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
            )

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
            )

        picking_vals = {
            # 'partner_id': vendor.id if vendor else False,
            'picking_type_id': picking_type.id,
            'location_dest_id': dest_location.id if dest_location else False,
            'adt_dest_location_id': dest_location.id if dest_location else False,
            'scheduled_date': receipt._parse_dt(receipt.scheduled_date),
            'origin': origin,
            'note': receipt.note or False,
            'adt_receipt_nbr': receipt.receipt_nbr or False,
            'adt_vendor_code': receipt.vendor_code or False,
            'adt_partner_ref': receipt.partner_ref or False,
            'adt_branch_warehouse': receipt.branch_warehouse or False,
            'adt_actual_qty': receipt._parse_float(receipt.actual_qty),
            'adt_is_hold': str(receipt.is_hold or '').lower() in ('true', '1', 'yes'),
            'adt_inventory_ref': receipt.inventory_ref or False,
            'adt_acumatica_write_date': receipt._parse_dt(receipt.acumatica_write_date),
            'adt_header_location_code': receipt.header_location_code or False,
            'adt_post_period': receipt.post_period or False,
            'adt_status': receipt.status or False,
            'adt_total_qty': receipt._parse_float(receipt.total_qty),
            'adt_type': receipt.receipt_type or False,
            'adt_warehouse_code': receipt.warehouse_code or False,
            'adt_external_id': receipt.external_id or False,
        }
        picking_vals = {key: value for key, value in picking_vals.items() if key in Picking._fields}

        if picking:
            if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                raise ReceiptImportError(
                    f'Receipt {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.',
                    payload={'header': header_payload, 'picking_vals': picking_vals},
                )
            picking.write(picking_vals)
            action_state = 'updated'
        else:
            picking = Picking.create(picking_vals)
            action_state = 'imported'

        for receipt_line in receipt.product_line_ids:
            move_vals = {}
            try:
                product = receipt._find_product(receipt_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receipt_line.inventory_id or False,
                        'product_name': receipt_line.description or False,
                        'qty': receipt._parse_float(receipt_line.product_uom_qty),
                        'uom': receipt_line.uom_code or False,
                        'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    })
                    continue

                uom = receipt._find_uom(receipt_line, product)
                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {receipt_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receipt_line.inventory_id or False,
                        'product_name': receipt_line.description or False,
                        'qty': receipt._parse_float(receipt_line.product_uom_qty),
                        'uom': receipt_line.uom_code or False,
                        'payload': receipt_line.read()[0] if receipt_line.exists() else {},
                    })
                    continue

                qty = receipt._parse_float(receipt_line.product_uom_qty)
                existing = picking.move_ids.filtered(
                    lambda move: (
                        move.picking_id == picking.id
                        and move.product_id.id == product.id
                        and move.product_uom_qty == qty
                    )
                )
                if existing:
                    continue

                move_vals = {
                    'name': receipt_line.transaction_description or receipt_line.description or product.display_name,
                    'picking_id': picking.id if picking else False,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id if uom else product.uom_id.id,
                    'location_id': picking.location_id.id if picking else False,
                    'location_dest_id': picking.location_dest_id.id if picking else False,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'description_picking': receipt_line.description or False,
                    'adt_line_external_id': receipt_line.line_external_id or False,
                    'adt_inventory_id': receipt_line.inventory_id or False,
                    'adt_line_nbr': receipt_line.line_nbr or False,
                    'adt_line_type': receipt_line.line_type or False,
                    'adt_open_qty': receipt._parse_float(receipt_line.open_qty),
                    'adt_order_qty': receipt._parse_float(receipt_line.order_qty),
                    'adt_po_line_number': receipt_line.po_line_number or False,
                    'adt_po_number': receipt_line.po_number or False,
                    'adt_po_type': receipt_line.po_type or False,
                    'adt_po_receipt_line_number': receipt_line.po_receipt_line_number or False,
                    'adt_po_receipt_number': receipt_line.po_receipt_number or False,
                    'adt_transfer_order_line_number': receipt_line.transfer_order_line_number or False,
                    'adt_transfer_order_number': receipt_line.transfer_order_number or False,
                    'adt_transfer_order_type': receipt_line.transfer_order_type or False,
                    'adt_transfer_shipment_number': receipt_line.transfer_shipment_number or False,
                    'adt_uom_code': receipt_line.uom_code or False,
                    'adt_warehouse_dest_code': receipt_line.warehouse_dest_code or False,
                    'adt_location_dest_code': receipt_line.location_dest_code or False,
                    'product_note': receipt_line.line_note or False,
                }

                move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                Move.create(move_vals)
                picking.action_confirm()

            except ReceiptImportError:
                raise

            except Exception as line_error:
                _logger.exception("Error import line %s", receipt.id)
                error_messages.append(str(line_error))
                error_line_payloads.append({
                    'inventory_id': receipt_line.inventory_id or False,
                    'product_name': receipt_line.description or False,
                    'qty': receipt._parse_float(receipt_line.product_uom_qty),
                    'uom': receipt_line.uom_code or False,
                    'payload': move_vals if move_vals else (receipt_line.read()[0] if receipt_line.exists() else {}),
                })

        if error_messages:
            raise ReceiptImportError(
                '\n'.join(error_messages),
                payload={
                    'header': header_payload,
                    'picking_vals': picking_vals,
                    'picking_id': picking.id if picking else False,
                },
                line_payloads=error_line_payloads,
            )

        receipt.write({
            'import_state': action_state,
            'import_message': f'{action_state.title()}: {picking.name if picking else False}',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._resolve_error_tracking(receipt)
        return action_state

    def _do_import(self):
        imported = 0
        updated = 0
        error = 0

        grouped_receipts = []
        seen_receipt_numbers = set()
        for receipt in self.sorted(lambda record: (record.receipt_nbr or '', record.id)):
            receipt_key = receipt.receipt_nbr or receipt.id
            if receipt_key in seen_receipt_numbers:
                continue
            seen_receipt_numbers.add(receipt_key)
            grouped_receipts.append(receipt)

        for receipt in grouped_receipts:
            try:
                with self.env.cr.savepoint():
                    action_state = self._import_single_receipt(receipt)
                if action_state == 'imported':
                    imported += 1
                elif action_state == 'updated':
                    updated += 1
            except Exception as exc:
                _logger.exception("Error import receipt %s", receipt.receipt_nbr or receipt.id)
                if isinstance(exc, ReceiptImportError):
                    error_payload = exc.payload
                    error_line_payloads = exc.line_payloads
                    error_message = str(exc)
                else:
                    error_payload = {'header': receipt.read()[0] if receipt.exists() else {}}
                    error_line_payloads = []
                    error_message = str(exc)

                try:
                    self._persist_error_tracking(
                        receipt,
                        [error_message],
                        line_payloads=error_line_payloads,
                        payload=error_payload,
                    )
                except Exception:
                    _logger.exception(
                        "Failed to persist error tracking for receipt %s",
                        receipt.receipt_nbr or receipt.id,
                    )

                receipt.write({
                    'import_state': 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        msg = f'Import done: {imported} receipt created, {updated} receipt updated, {error} receipt error.'
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
            raise UserError('Belum diimport, belum ada transfer di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }

