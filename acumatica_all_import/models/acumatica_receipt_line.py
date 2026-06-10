from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil import parser as dateutil_parser
import logging
import requests

_logger = logging.getLogger(__name__)


class AcumaticaReceiptLine(models.Model):
    _name = 'acumatica.receipt.line'
    _description = 'Data Inventory Receipt dari Acumatica'
    _order = 'receipt_nbr asc, line_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header Acumatica', readonly=True)
    line_external_id = fields.Char(string='UUID Line Acumatica', readonly=True)

    receipt_nbr = fields.Char(string='Receipt Number', readonly=True, index=True)
    vendor_code = fields.Char(string='VendorID', readonly=True)
    partner_ref = fields.Char(string='Vendor Ref', readonly=True)
    scheduled_date = fields.Char(string='Date', readonly=True)
    warehouse_code = fields.Char(string='Warehouse', readonly=True)
    header_location_code = fields.Char(string='Header Location', readonly=True)
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
    location_dest_code = fields.Char(string='Location', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    po_line_number = fields.Char(string='PO Line Nbr', readonly=True)
    po_number = fields.Char(string='PO Number', readonly=True)
    po_type = fields.Char(string='PO Type', readonly=True)
    po_receipt_line_number = fields.Char(string='PO Receipt Line Nbr', readonly=True)
    po_receipt_number = fields.Char(string='PO Receipt Nbr', readonly=True)
    product_uom_qty = fields.Char(string='Receipt Qty', readonly=True)
    transfer_order_line_number = fields.Char(string='Transfer Order Line Nbr', readonly=True)
    transfer_order_number = fields.Char(string='Transfer Order Nbr', readonly=True)
    transfer_order_type = fields.Char(string='Transfer Order Type', readonly=True)
    transfer_shipment_number = fields.Char(string='Transfer Shipment Nbr', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Dest', readonly=True)
    line_note = fields.Text(string='Line Note', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], string='Status', default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.receipt.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('receipt_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.receipt_nbr and Picking.search_count([('adt_receipt_nbr', '=', rec.receipt_nbr)]))

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
            # vendor = Partner.search([('ref', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            vendor = Partner.search([('company_registry', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
            if not vendor:
                vendor = Partner.search([('name', '=', line.vendor_code), ('is_company', '=', True)], limit=1)
        return vendor

    def _resolve_uom(self, uom_name):
        """
        Lookup uom.uom by name (case-insensitive).
        UOM sudah diimport sebelumnya ke uom.uom.
        Return: uom.uom record atau browse() jika tidak ditemukan.
        """
        if not uom_name:
            return self.env['uom.uom'].browse()
        uom = self.env['uom.uom'].search([('name', '=ilike', uom_name)], limit=1)
        return uom

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

    def _search_product_from_acumatica(self, line):
        session = self.config_id._do_login()
        try:
            endpoint = f"{self.config_id.base_url}/{self.config_id.endpoint_name}"
            params = {'$top': 1, '$filter': f"InventoryID eq '{line.inventory_id}'"}
            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Inventory Receipt (HTTP {response.status_code}): {response.text}')

            uom = self._resolve_uom(line.base_uom)
            if not uom and line.base_uom:
                _logger.warning(
                    "UOM '%s' tidak ditemukan di Odoo untuk item %s",
                    line.base_uom, line.inventory_id
                )

            odoo_type = self.ITEM_TYPE_MAP.get(
                    (line.item_type or '').lower(), 'consu'
                )

            valuation = self.VALUATION_MAP.get(line.valuation_method or '', False)

            item_status = self.STATUS_MAP.get(line.item_status or '', False)

            raw_data = self._normalize_rows(response.json())
            vals = {
                    # Field standar Odoo
                    'name':         raw_data.description,
                    'default_code': raw_data.inventory_id or False,
                    'type':         odoo_type,

                    # UOM
                    'uom_id':    uom.id if uom else False,
                    'uom_po_id': uom.id if uom else False,

                    # Field custom adt_
                    'adt_external_id':            raw_data.external_id or False,
                    'adt_item_class':             raw_data.item_class or False,
                    'adt_item_status':            item_status or False,
                    'adt_valuation_method':       valuation or False,
                    'adt_last_modified_datetime': self._parse_dt(raw_data.last_modified_datetime),
                }
            
        finally:
            self._do_logout(session)
            self.last_sync = fields.Datetime.now()

    def _find_product(self, line):
        Product = self.env['product.product']

        product = False

        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)

        if not product and line.transaction_description:
            product = Product.search([('name', '=', line.transaction_description)], limit=1)

        if not product:
            name = line.transaction_description or line.description or line.inventory_id or 'Unknown Product'
            existing = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if existing:
                return existing
            product = Product.create({
                'name': name,
                'default_code': line.inventory_id or False,
                'type': 'consu',  # stockable
            })
            session = self.config_id._do_login()
            endpoint = f"{self.config_id.base_url}/{self.config_id.endpoint_name}"
            params = {'$top': 1, '$filter': f"InventoryID eq '{line.inventory_id}'"}
            response = session.get(endpoint, params=params, timeout=90)
            if response.status_code != 200:
                raise UserError(f'Gagal ambil data Inventory Receipt (HTTP {response.status_code}): {response.text}')

            raw_data = self._normalize_rows(response.json())


        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if line.warehouse_dest_code:
            warehouse = Warehouse.search([('code', '=', line.warehouse_dest_code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', line.warehouse_dest_code)], limit=1)
            else:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    
            # else:
            #     warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse

    def _find_location_dest(self, line, warehouse=False):
        Location = self.env['stock.location']
        location = False
        if line.location_dest_code:
            location = Location.search([('complete_name', '=', line.location_dest_code)], limit=1)
            if not location:
                location = Location.search([('name', '=', line.location_dest_code)], limit=1)
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
        lines = self.filtered(lambda l: l.selected and l.import_state == 'pending')
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

        imported = 0
        updated = 0
        error = 0

        # proses per receipt number
        for receipt_nbr in self.mapped('receipt_nbr'):
            receipt_lines = self.filtered(
                lambda l: l.receipt_nbr == receipt_nbr and l.import_state == 'pending'
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]

            try:
                # Cari vendor, inventory, warehouse, uom. kalo salah satu tidak sync di wms, maka berikan flag Not Ready di stock.picking, dan keterangan di sync_message.
                vendor = self._find_vendor(first)
                if not vendor:
                    flag = {
                        'sync_state': 'not_ready',
                        'sync_message': f'Vendor dengan VendorID {first.vendor_code} tidak ditemukan di WMS.',
                    }
                else:
                    flag = {}

                warehouse = self._find_warehouse(first)
                if not warehouse:
                    flag = {
                        'sync_state': 'not_ready',
                        'sync_message': f'Warehouse dengan code {first.warehouse_dest_code} tidak ditemukan di WMS.',
                    }
                else:
                    flag = {}

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id if warehouse else False),
                    ('code', '=', 'incoming'),
                ], limit=1) or PickingType.search([
                    ('code', '=', 'incoming')
                ], limit=1)

                if not picking_type:
                    raise UserError('Picking type incoming tidak ditemukan.')

                # dest_location = self._find_location_dest(first, warehouse)
                # if not dest_location:
                #     raise UserError(
                #         f'Location tujuan tidak ditemukan untuk code: '
                #         f'{first.location_dest_code or first.header_location_code or "-"}'
                #     )

                origin = first.receipt_nbr or False

                vals = {
                    'partner_id': vendor.id if vendor else False,
                    'picking_type_id': picking_type.id,
                    # 'location_id': (
                    #     picking_type.default_location_src_id.id
                    #     if picking_type.default_location_src_id
                    #     else self.env.ref('stock.stock_location_suppliers').id
                    # ),
                    # 'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'origin': origin,
                    'note': first.note or False,

                    # field custom, kalau ada di model
                    'adt_receipt_nbr': first.receipt_nbr or False,
                    'adt_vendor_code': first.vendor_code or False,
                    'adt_partner_ref': first.partner_ref or False,
                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_actual_qty': self._parse_float(first.actual_qty),
                    'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
                    'adt_inventory_ref': first.inventory_ref or False,
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_header_location_code': first.header_location_code or False,
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.receipt_type or False,
                    'adt_warehouse_code': first.warehouse_code or False,
                    'adt_external_id': first.external_id or False,
                }

                # filter field yang bener-bener ada di stock.picking
                vals = {k: v for k, v in vals.items() if k in Picking._fields}

                # pakai origin buat dedup
                picking = Picking.search([('origin', '=', origin)], limit=1)
                final_vals = {**vals, **flag} if 'flag' in locals() else vals
                if flag:
                    error_data = Error.search([('origin', '=', origin)], limit=1)
                    if not error_data:
                        error_data = Error.create({
                            'partner': first.vendor_code or False,
                            'operation_type': 'receipt',
                            'location': first.warehouse_code or False,
                            'location_dest': first.warehouse_dest_code or False,
                            'scheduled_date': self._parse_dt(first.scheduled_date),
                            'origin': origin,
                            'api_acumatica': 'po_receipt',
                            'error_message': flag.get('sync_message', 'Data tidak sesuai dengan master di WMS.'),
                            'payload': str(vals)[:1000],
                        })
                else:
                    final_vals['state'] = 'assigned'
                    final_vals['sync_state'] = 'ready'
                    final_vals['sync_message'] = False
                    if picking:
                        if picking.state not in ('draft', 'waiting', 'confirmed', 'assigned'):
                            raise UserError(
                                f'Receipt {receipt_nbr} sudah ada di Odoo dengan state '
                                f'{picking.state}, tidak bisa diupdate.'
                            )
                        picking.write(final_vals)
                        action_state = 'updated'
                        updated += 1
                    else:
                        picking = Picking.create(final_vals)
                        action_state = 'imported'
                        imported += 1

                for line in receipt_lines:
                    try:
                        product = self._find_product(line)
                        if not product:
                            flag = {
                                'sync_state': 'not_ready',
                                'sync_message': f'Product dengan InventoryID {line.inventory_id} tidak ditemukan di WMS.',
                            }
                        else:
                            flag = {}

                        uom = self._find_uom(line, product)
                        # line_dest = self._find_location_dest(line, warehouse) or dest_location
                        qty = self._parse_float(line.product_uom_qty)

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
                            'name': line.transaction_description or line.description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': '9',
                            'description_picking': line.description or False,

                            'adt_line_external_id': line.line_external_id or False,
                            'adt_inventory_id': line.inventory_id or False,
                            'adt_line_nbr': line.line_nbr or False,
                            'adt_line_type': line.line_type or False,
                            'adt_open_qty': self._parse_float(line.open_qty),
                            'adt_order_qty': self._parse_float(line.order_qty),
                            'adt_po_line_number': line.po_line_number or False,
                            'adt_po_number': line.po_number or False,
                            'adt_po_type': line.po_type or False,
                            'adt_po_receipt_line_number': line.po_receipt_line_number or False,
                            'adt_po_receipt_number': line.po_receipt_number or False,
                            'adt_transfer_order_line_number': line.transfer_order_line_number or False,
                            'adt_transfer_order_number': line.transfer_order_number or False,
                            'adt_transfer_order_type': line.transfer_order_type or False,
                            'adt_transfer_shipment_number': line.transfer_shipment_number or False,
                            'adt_uom_code': line.uom_code or False,
                            'adt_warehouse_dest_code': line.warehouse_dest_code or False,
                            'adt_location_dest_code': line.location_dest_code or False,
                            'adt_line_note': line.line_note or False,
                        }

                        # filter field yang ada di stock.move
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}
                        if error_data:
                            ErrorLine.create({
                                'error_id': error_data.id,
                                'inventory_id': line.inventory_id or False,
                                'product_name': line.description or False,
                                'qty': line.product_uom_qty or False,
                                'uom': line.uom_code or False,
                            })
                            continue

                        if flag:
                            error_line_data = ErrorLine.search([('error_id', '=', error.id)], limit=1)
                            if not error_line_data:
                                error_line_data = ErrorLine.create({
                                    'error_id': error_data.id,
                                    'inventory_id': line.inventory_id or False,
                                    'product_name': line.description or False,
                                    'qty': line.product_uom_qty or False,
                                    'uom': line.uom_code or False,
                                    'payload': str(move_vals)[:1000],
                                })
                                error += 1
                        else:
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
                _logger.exception("Error import receipt %s", receipt_nbr)
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
