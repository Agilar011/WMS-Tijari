from odoo import models, fields, api
from odoo.exceptions import UserError

from dateutil import parser as dateutil_parser
import logging
import requests

_logger = logging.getLogger(__name__)

class AcumaticaInventoryReceiptTransferWhInConfig(models.Model):
    _name = 'acumatica.inventory.receipt.transfer.wh.in.config'
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
        default="TransferType eq '2-Step' and (Status eq 'On Hold' or Status eq 'Balanced')"
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



class AcumaticaInventoryReceiptTransferWhInStaging(models.Model):
    _name = 'acumatica.inventory.receipt.transfer.wh.in.staging'
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'adt_ReferenceNbr asc, id asc'

    line_ids = fields.One2many(
        'acumatica.inventory.receipt.transfer.wh.in.staging.line', 
        'header_id', 
        string="Detail Lines"
    )    

    adt_id = fields.Char(string="Acumatica id")
    adt_rowNumber = fields.Char(string="Acumatica rowNumber")
    adt_note = fields.Char(string="Acumatica note")
    adt_Branch = fields.Char(string="Acumatica Branch")
    adt_ChangeItemRefNbr = fields.Char(string="Acumatica ChangeItemRefNbr")
    adt_ControlQty = fields.Char(string="Acumatica ControlQty")
    adt_Customer = fields.Char(string="Acumatica Customer")
    adt_Date = fields.Char(string="Acumatica Date")
    adt_Description = fields.Char(string="Acumatica Description")
    adt_DocumentOnly = fields.Boolean(string="Acumatica DocumentOnly")
    adt_ExternalRef = fields.Char(string="Acumatica ExternalRef")
    adt_LastModifiedDateTime = fields.Char(string="Acumatica LastModifiedDateTime")
    adt_Location = fields.Char(string="Acumatica Location")
    adt_NoteID = fields.Char(string="Acumatica NoteID")
    adt_PostPeriod = fields.Char(string="Acumatica PostPeriod")
    adt_ReferenceNbr = fields.Char(string="Acumatica ReferenceNbr")
    adt_ShipmentNbr = fields.Char(string="Acumatica ShipmentNbr")
    adt_Status = fields.Char(string="Acumatica Status")
    adt_TotalQty = fields.Char(string="Acumatica TotalQty")
    adt_TransferNbr = fields.Char(string="Acumatica TransferNbr")
    adt_TransType = fields.Char(string="Acumatica TransType")
    adt_Warehouse = fields.Char(string="Acumatica Warehouse")

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")

    @api.depends('adt_ReferenceNbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.adt_ReferenceNbr and Picking.search_count([('origin', '=', rec.adt_ReferenceNbr)]))

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
    #     if line.adt_InventoryID:
    #         product = Product.search([('default_code', '=', line.adt_InventoryID)], limit=1)
    #         if not product:
    #             product = Product.search([('barcode', '=', line.adt_InventoryID)], limit=1)
    #     if not product and line.transaction_description:
    #         product = Product.search([('name', '=', line.transaction_description)], limit=1)
    #     return product
    def _find_product(self, line):
        Product = self.env['product.product']

        product = False

        if line.adt_InventoryID:
            product = Product.search([('default_code', '=', line.adt_InventoryID)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.adt_InventoryID)], limit=1)

        if not product and line.adt_Description:
            product = Product.search([('name', '=', line.adt_Description)], limit=1)

        if not product:
            name = line.adt_Description or line.description or line.adt_InventoryID or 'Unknown Product'
            existing = Product.search([('default_code', '=', line.adt_InventoryID)], limit=1)
            if existing:
                return existing
            product = Product.create({
                'name': name,
                'default_code': line.adt_InventoryID or False,
                'type': 'consu',  # stockable
            })

        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.warehouse']
        warehouse = False
        if line:
            print(f"Warehouse to search: {line}")
            warehouse_code = line 
            warehouse = Warehouse.search([('code', '=', warehouse_code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', warehouse_code)], limit=1)
            else:
                warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location_dest(self, line, warehouse=False):
        Location = self.env['stock.location']
        location = False
        if line:
            location = Location.search([('complete_name', '=', line)], limit=1)
            if not location:
                location = Location.search([('name', '=', line)], limit=1)
        if not location and warehouse:
            location = warehouse.lot_stock_id
        return location

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.adt_UOM:
            uom = Uom.search([('name', '=', line.adt_UOM)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['pending', 'error'])
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diacumatica.')
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
        # print(f"self mapped: {self.mapped('reference_nbr')}")

    
        for reference_nbr in self.mapped('adt_ReferenceNbr'):
            receipt_lines = self.filtered(
                lambda l: l.adt_ReferenceNbr == reference_nbr and l.import_state == 'pending'
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]
            print(f"first: {first}")
            try:
                self.env.cr.execute('SAVEPOINT import_inventory_receipt_transfer_wh_in_doc')
                # picking_type = False
                # vendor = self._find_vendor(first)
                warehouse_code = first.adt_Warehouse or False
                if first.adt_Warehouse:
                    warehouse = self._find_warehouse(first.adt_Warehouse)

                else:
                    line_record = self.env['acumatica.inventory.receipt.transfer.wh.in.staging.line'].search(
                        [('header_id', '=', first.id), ('adt_Warehouse', '!=', None)], # <-- Ubah Null menjadi None
                        limit=1
                    )

                    warehouse_code = line_record.adt_Warehouse if line_record else False
                    warehouse = self._find_warehouse(warehouse_code)

                if not warehouse:
                    raise UserError(
                        f'Warehouse tidak ditemukan untuk code: {first.to_warehouse_code or warehouse_code or "-"}'
                    )
                print(f"Warehouse : {warehouse}")
                picking_type = self.picking_type_id
                if not first.picking_type_id:
                    acumatica_mapped_location = self.env['stock.location.acumatica'].search(
                        [('code', '=', warehouse_code)], # <-- Ubah Null menjadi None
                        limit=1
                    )
                    warehouse_id = acumatica_mapped_location.odoo_building_id.id
                    print(f"Alternatif WH : {warehouse_id}")
                    if warehouse_id:
                        picking_type = PickingType.search([
                            ('warehouse_id', '=', warehouse_id),
                            ('code', '=', 'incoming'), ('sequence_code', '=', "TRI" )
                        ], limit=1) 

                        print(picking_type.mapped('name'))

                if not picking_type:
                    raise UserError('Picking type internal tidak ditemukan.')

                dest_location = self._find_location_dest(first.adt_Warehouse, warehouse)
                if not dest_location:
                    raise UserError(
                        f'Location tujuan tidak ditemukan untuk code: '
                        f'{first.location_dest_code or first.header_location_code or "-"}'
                    )

                origin = first.adt_ReferenceNbr or False

                vals = {
                    # 'partner_id': vendor.id if vendor else False,
                    'picking_type_id': picking_type.id,
                    'location_id': (
                        picking_type.default_location_src_id.id
                        if picking_type.default_location_src_id
                        else self.env.ref('stock.stock_location_suppliers').id
                    ),
                    # 'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.adt_Date),
                    'origin': origin,
                    'note': first.adt_note or False,
                    # reference_nbr = 
                    # trans_type = 

                    # field custom, kalau ada di model
                    # 'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
                    'adt_acumatica_write_date': self._parse_dt(first.adt_LastModifiedDateTime),
                    'adt_post_period': first.adt_PostPeriod or False,
                    'adt_status': first.adt_Status or False,
                    'adt_total_qty': self._parse_float(first.adt_TotalQty),
                    'adt_type': first.adt_TransType or False,
                    # 'adt_to_warehouse_code': first.to_warehouse_code or False,
                    # 'adt_from_warehouse_code': first.from_warehouse_code or False,
                    'adt_description': first.adt_Description or False,
                }

                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Picking._fields}

                # pakai origin buat dedup
                picking = Picking.search([('origin', '=', origin)], limit=1)

                if picking:
                    if picking.state != 'draft':
                        action_state = 'error'
                        error += 1
                        raise UserError(
                            f'Receipt {reference_nbr} sudah ada di Odoo dengan state '
                            f'{picking.state}, tidak bisa diupdate.'
                        )

                    if picking.state == 'draft':
                        print(f"Update Picking : {picking}")
                        action_state = 'updated'

                        first.write({
                            'import_state': action_state,
                            'import_message': f'Update picking : {picking.name}',
                            'odoo_picking_id': picking.id,
                        })

                        picking.write(vals)
                        imported += 1

                else:
                    picking = Picking.create(vals)
                    print(f"Picking : {picking} Created")
                    # raise UserError("Checkpoint")
                    action_state = 'imported'
                    imported += 1

                if action_state == 'error':
                    break

                to_create_move = self.env['acumatica.inventory.receipt.transfer.wh.in.staging.line'].search([
                        ('header_id', '=', first.id)
                    ])

                if action_state == 'updated' and picking:
                    moves_to_delete = self.env['stock.move'].search([('picking_id', '=', picking.id)])
                    if moves_to_delete:
                        moves_to_delete.unlink()

                for line in to_create_move:
                    for field_name in line._fields:
                        print(f"{field_name}: {line[field_name]}")
                    print("="*50 + "\n")
                    # raise UserError('Checkpoint')

                    try:
                        product = self._find_product(line)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.adt_InventoryID or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        line_dest = self._find_location_dest(line.adt_Warehouse, warehouse) or dest_location
                        qty = self._parse_float(line.adt_Quantity)

                        print(f"Convert : {line.adt_Quantity} to : {qty}")
                        # raise UserError('Checkpoint')

                        # dedup move
                        move_domain = [('picking_id', '=', picking.id)]
                        if 'adt_line_external_id' in Move._fields and line.adt_header_id:
                            move_domain.append(('adt_line_external_id', '=', line.adt_header_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('product_uom_qty', '=', qty),
                            ]

                        move_vals = {
                            'name': line.adt_Description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': line_dest.id,
                            'description_picking': line.adt_Description or False,

                            'adt_line_nbr': line.adt_LineNumber or False,
                            'adt_line_note': line.adt_note or False,
                            'adt_inventory_id': line.adt_InventoryID or False,
                            'adt_uom_code': line.adt_UOM or False,
                            'adt_line_description': line.adt_Description or False,
                            'adt_to_location_code': line.adt_Warehouse or False,
                            # 'adt_from_location_code': line.adt_FromLocationID or False,
                            'adt_quantity': self._parse_float(line.adt_Quantity),

                        }

                        # filter field yang ada di stock.move
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}

                        print(f"Move to create: {move_vals}")

                        created_move = Move.create(move_vals)

                        print("\n" + "="*50)
                        print(f"DEBUG STOCK MOVE ID: {created_move.id}")
                        print("="*50)
                        for field_name in created_move._fields:
                            print(f"{field_name}: {created_move[field_name]}")
                        print("="*50 + "\n")

                        first.write({
                            'import_state': action_state,
                            'import_message': f'{action_state.title()}: {picking.name}',
                            'odoo_picking_id': picking.id,
                        })

                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        raise UserError(str(line_e))
                        first.write({
                            'import_state': 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_picking_id': picking.id if picking else False,
                        })
                        error += 1

                if first.adt_DocumentOnly:
                    picking.action_validate_document_only_import(force=True)
                self.env['acumatica.error.tracking.mixin']._resolve_error_tracking(reference_nbr, 'inventory_receipt_transfer_wh_in')
                self.env.cr.execute('RELEASE SAVEPOINT import_inventory_receipt_transfer_wh_in_doc')

            except Exception as e:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT import_inventory_receipt_transfer_wh_in_doc')
                _logger.exception("Error import receipt %s", reference_nbr)
                tracked_lines = self.env['acumatica.inventory.receipt.transfer.wh.in.staging.line'].search([
                    ('header_id', '=', first.id),
                ])
                self.env['acumatica.error.tracking.mixin']._persist_error_tracking(
                    first,
                    [str(e)],
                    api_acumatica='inventory_receipt_transfer_wh_in',
                    operation_type='receipt',
                    origin=reference_nbr,
                    partner=first.adt_Customer or False,
                    location=first.adt_Warehouse or first.adt_Location or False,
                    location_dest=warehouse_code if 'warehouse_code' in locals() else False,
                    scheduled_date=first.adt_Date,
                    total_qty=first.adt_TotalQty,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.adt_InventoryID or False,
                        'product_name': line.adt_Description or False,
                        'qty': self._parse_float(line.adt_Quantity),
                        'uom': line.adt_UOM or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in tracked_lines],
                )
                receipt_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                    'odoo_picking_id': False,
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


class AcumaticaInventoryReceiptTransferWhInStagingLine(models.Model):
    _name = 'acumatica.inventory.receipt.transfer.wh.in.staging.line'
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'header_id asc, id asc'

    header_id = fields.Many2one(
        'acumatica.inventory.receipt.transfer.wh.in.staging',
        string="Header Reference", 
        ondelete='cascade', 
        index=True
    )
    
    adt_header_id = fields.Char(string='Acumatica header_id')
    adt_id = fields.Char(string='Acumatica id')
    adt_rowNumber = fields.Char(string='Acumatica rowNumber')
    adt_note = fields.Char(string='Acumatica note')
    adt_Branch = fields.Char(string='Acumatica Branch')
    adt_Description = fields.Char(string='Acumatica Description')
    adt_InventoryID = fields.Char(string='Acumatica InventoryID')
    adt_LineNumber = fields.Char(string='Acumatica LineNumber')
    adt_Location = fields.Char(string='Acumatica Location')
    adt_NoteID = fields.Char(string='Acumatica NoteID')
    adt_Quantity = fields.Char(string='Acumatica Quantity')
    adt_UOM = fields.Char(string='Acumatica UOM')
    adt_Warehouse = fields.Char(string='Acumatica Warehouse')

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    # exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
