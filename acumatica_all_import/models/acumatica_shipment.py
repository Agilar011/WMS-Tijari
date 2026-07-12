import logging
from dateutil import parser as dateutil_parser
from docutils.nodes import note

from odoo import api, fields, models
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

import requests


class ShipmentImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaShipmentProductLine(models.Model):
    _name = 'acumatica.shipment.product.line'
    _description = 'Data Shipment Receipt dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica', readonly=True)
    shipment_line_id = fields.Many2one('acumatica.shipment.line', string='Receipt', ondelete='cascade')
    line_external_id = fields.Char(string='UUID Line Acumatica', readonly=True)

    shipment_nbr = fields.Char(string='Shipment Number', readonly=True, index=True)
    description = fields.Char(string='Description Line', readonly=True)
    note = fields.Text(string='Detail Note', readonly=True)
    is_free_item = fields.Char(string='Free Item', readonly=True)
    inventory_id = fields.Char(string='InventoryID', readonly=True)
    line_nbr = fields.Char(string='Line Nbr', readonly=True)
    location_dest_code = fields.Char(string='Location Detail', readonly=True)
    open_qty = fields.Char(string='Open Qty', readonly=True)
    order_qty = fields.Char(string='Ordered Qty', readonly=True)
    order_line_number = fields.Char(string='Order Line Nbr', readonly=True)
    order_number = fields.Char(string='Order Nbr', readonly=True)
    order_type = fields.Char(string='Order Type', readonly=True)
    shipped_qty = fields.Char(string='Shipped Qty Detail', readonly=True)
    uom_code = fields.Char(string='UOM', readonly=True)
    original_qty = fields.Char(string='Original Qty', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Detail', readonly=True)
    shipped_weight = fields.Char(string='Shipped Weight', readonly=True)


class AcumaticaShipmentLine(models.Model):
    _name = 'acumatica.shipment.line'
    _description = 'Data Shipment Receipt dari Acumatica'
    _order = 'shipment_nbr asc, id asc'

    row_number = fields.Integer(string='No', readonly=True)
    external_id = fields.Char(string='UUID Header', readonly=True)
    line_external_id = fields.Char(string='UUID Line', readonly=True)

    product_line_ids = fields.One2many('acumatica.shipment.product.line', 'shipment_line_id', string='Lines')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])
    building_code = fields.Char(string='Building Code', readonly=True)
    shipment_nbr = fields.Char(string='Shipment Number', readonly=True, index=True)
    partner_code = fields.Char(string='CustomerID', readonly=True)
    scheduled_date = fields.Char(string='Shipment Date', readonly=True)
    warehouse_code = fields.Char(string='Warehouse Asal', readonly=True)
    warehouse_name = fields.Char(string='Warehouse Name', readonly=True)
    warehouse_dest_code = fields.Char(string='Warehouse Tujuan', readonly=True)
    header_location_code = fields.Char(string='Location Header', readonly=True)
    header_location_name = fields.Char(string='Location Header Name', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    shipment_type = fields.Char(string='Type', readonly=True)
    operation = fields.Char(string='Operation', readonly=True)

    note = fields.Text(string='Header Note', readonly=True)
    actual_qty = fields.Char(string='Control Qty', readonly=True)
    description = fields.Char(string='Description Header', readonly=True)
    fob_point = fields.Char(string='FOB Point', readonly=True)
    fob_point_description = fields.Char(string='FOB Point Description', readonly=True)
    is_hold = fields.Char(string='Hold', readonly=True)
    is_insurance = fields.Char(string='Insurance', readonly=True)
    acumatica_write_date = fields.Char(string='Last Modified', readonly=True)
    package_count = fields.Char(string='Package Count', readonly=True)
    package_weight = fields.Char(string='Package Weight', readonly=True)
    is_picked = fields.Char(string='Picked', readonly=True)
    shipped_qty = fields.Char(string='Shipped Qty Header', readonly=True)
    shipped_volume = fields.Char(string='Shipped Volume', readonly=True)
    shipped_weight = fields.Char(string='Shipped Weight', readonly=True)
    shipping_terms = fields.Char(string='Shipping Terms', readonly=True)
    shipping_settings = fields.Char(string='Shipping Settings', readonly=True)
    shipping_zone = fields.Char(string='Shipping Zone', readonly=True)
    ship_via = fields.Char(string='Ship Via', readonly=True)
    unlimited_packages = fields.Char(string='Unlimited Packages', readonly=True)
    allocations = fields.Text(string='Allocations JSON')

    acumatica_id = fields.Char(string='Acumatica ID', readonly=True)
    acumatica_row_number = fields.Integer(string='Acumatica Row Number', readonly=True)
    acumatica_line_number = fields.Char(string='Acumatica Line Number', readonly=True)
    original_qty = fields.Char(string='Original Qty', readonly=True)

    import_state = fields.Selection([
        ('pending', 'Belum Diimport'),
        ('imported', 'Sudah Diimport'),
        ('updated', 'Diupdate'),
        ('error', 'Error'),
    ], default='pending', readonly=True)
    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('shipment_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        for rec in self:
            rec.exists_in_odoo = bool(rec.shipment_nbr and Picking.search_count([('origin', '=', rec.shipment_nbr)]))

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
        #     if not product:
        #         product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        # if not product and line.description:
        #     product = Product.search([('name', '=', line.description)], limit=1)
        # if not product:
        #     product = Product.create({
        #         'name': line.description or line.inventory_id or 'Unknown Product',
        #         'default_code': line.inventory_id or False,
        #         'type': 'consu',
        #     })
        return product

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line.partner_code:
            partner = Partner.search([('company_registry', '=', line.partner_code)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.partner_code)], limit=1)
        return partner

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if line.warehouse_code:
            warehouse = Warehouse.search([('code', '=', line.warehouse_code)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    
            else:
                warehouse = False
        return warehouse

    def _find_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        location = False
        if line.warehouse_code:
            location = Location.search([('code', '=', line.warehouse_code)], limit=1)
            if not location:
                location = Location.search([('name', '=', line.warehouse_code)], limit=1)
            else:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
        return location

    def _find_source_location(self, warehouse=False):
        Location = self.env['stock.location']
        supplier_loc = self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
        if supplier_loc:
            return supplier_loc
        return Location.search([('usage', '=', 'supplier')], limit=1) or (warehouse and warehouse.lot_stock_id)

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(
            lambda l: (
                l.import_state in ['pending', 'error'] 
                or (l.import_state in ['imported', 'updated'] and not l.odoo_picking_id)
            )
        )
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()

    def _persist_error_tracking(self, first, error_messages, line_payloads=None, payload=None):
        origin = first.shipment_nbr or False
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
                'partner': first.partner_code or False,
                'operation_type': 'receipt',
                'location': first.warehouse_code or False,
                'location_dest': first.warehouse_dest_code or False,
                'scheduled_date': first._parse_dt(first.scheduled_date),
                'origin': origin,
                'adt_total_qty': first._parse_float(first.shipped_qty),
                'adt_actual_qty': first._parse_float(first.actual_qty),
                'api_acumatica': 'shipment_so',
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
        origin = first.shipment_nbr or False
        if not origin:
            return

        error_data = self.env['stock.picking.acumatica.error'].search([('origin', '=', origin)], limit=1)
        if error_data:
            error_data.write({'state': 'resolved'})

    def _import_single_shipment(self, shipment):
        shipment.ensure_one()

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = shipment.shipment_nbr or False
        header_payload = shipment.read()[0] if shipment.exists() else {}
        error_messages = []
        all_line_payloads = []
        picking = shipment.odoo_picking_id.id
        action_state = 'pending'

        for shipment_line in shipment.product_line_ids:
            all_line_payloads.append({
                'inventory_id': shipment_line.inventory_id or False,
                'product_name': shipment_line.description or False,
                'qty': shipment._parse_float(shipment_line.shipped_qty),
                'uom': shipment_line.uom_code or False,
                'payload': shipment_line.read()[0] if shipment_line.exists() else {},
            })

        partner = self._find_partner(shipment)
        if not partner:
            error_messages.append(
                f'Customer with CustomerID {shipment.partner_code} was not found in the WMS | WMS Dependency : MASTER PARTNER.'
            )

        warehouse = shipment._find_warehouse(shipment)
        if not warehouse:
            error_messages.append(
                f'Warehouse with location code {shipment.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        dest_location = shipment._find_location_dest(shipment)
        if not dest_location:
            error_messages.append(
                f'Location with code {shipment.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        # picking_type = PickingType.search([
        #     ('warehouse_id', '=', warehouse.id if warehouse else False),
        #     ('code', '=', 'incoming'),
        # ], limit=1)
        picking_type = self.picking_type_id
        if not picking_type:
            warehouse_txt = f"Warehouse code {warehouse.code if warehouse else '-'}"
            location_txt = f'Location code {shipment.warehouse_code}'
            error_messages.append(
                f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
            )

        if error_messages:
            raise ShipmentImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
                line_payloads=all_line_payloads
            )

        picking_vals = {
            'partner_id': partner.id if partner else False,
            'picking_type_id': picking_type.id,
            'adt_dest_location_id': dest_location.id if dest_location else False,
            'scheduled_date': shipment._parse_dt(shipment.scheduled_date),
            'origin': origin,
            'note': shipment.note or False,
            'adt_acumatica_write_date': self._parse_dt(shipment.acumatica_write_date),
            'adt_total_qty': self._parse_float(shipment.actual_qty),
            'adt_actual_qty': self._parse_float(shipment.actual_qty),
            'adt_type': shipment.shipment_type or False

        }
        picking_vals = {key: value for key, value in picking_vals.items() if key in Picking._fields}

        if picking:
            if picking.state != 'draft':
                raise ShipmentImportError(
                    f'Shipment {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.',
                    payload={'header': header_payload, 'picking_vals': picking_vals},
                    line_payloads=all_line_payloads
                )
            picking.write(picking_vals)
            action_state = 'updated'
        else:
            picking = Picking.create(picking_vals)
            action_state = 'imported'

        for shipment_line in shipment.product_line_ids:
            move_vals = {}
            try:
                product = shipment._find_product(shipment_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {shipment_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    # error_line_payloads.append({
                    #     'inventory_id': shipment_line.inventory_id or False,
                    #     'product_name': shipment_line.description or False,
                    #     'qty': shipment._parse_float(shipment_line.shipped_qty),
                    #     'uom': shipment_line.uom_code or False,
                    #     'payload': shipment_line.read()[0] if shipment_line.exists() else {},
                    # })
                    continue

                uom = shipment._find_uom(shipment_line, product)
                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {shipment_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    # error_line_payloads.append({
                    #     'inventory_id': shipment_line.inventory_id or False,
                    #     'product_name': shipment_line.description or False,
                    #     'qty': shipment._parse_float(shipment_line.shipped_qty),
                    #     'uom': shipment_line.uom_code or False,
                    #     'payload': shipment_line.read()[0] if shipment_line.exists() else {},
                    # })
                    continue

                qty = shipment._parse_float(shipment_line.shipped_qty)
                existing = picking.move_ids.filtered(
                    lambda move: (
                        move.picking_id.id == picking.id
                        and move.product_id.id == product.id
                        and move.product_uom_qty == qty
                    )
                )
                if existing:
                    continue

                move_vals = {
                    'name': shipment_line.description or product.display_name,
                    'picking_id': picking.id if picking else False,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id if uom else product.uom_id.id,
                    'location_id': picking.location_id.id if picking else False,
                    'location_dest_id': picking.location_dest_id.id if picking else False,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'description_picking': shipment_line.description or False,
                    'product_note': shipment_line.note or False,
                    'adt_dest_location_id': picking.adt_dest_location_id.id if picking else False
                }

                # move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                Move.create(move_vals)

            except ShipmentImportError:
                raise

            except Exception as line_error:
                _logger.exception("Error import line %s", shipment.id)
                error_messages.append(str(line_error))
                all_line_payloads.append({
                    'inventory_id': shipment_line.inventory_id or False,
                    'product_name': shipment_line.description or False,
                    'qty': shipment._parse_float(shipment_line.shipped_qty),
                    'uom': shipment_line.uom_code or False,
                    'payload': move_vals if move_vals else (shipment_line.read()[0] if shipment_line.exists() else {}),
                })

        if error_messages:
            raise ShipmentImportError(
                '\n'.join(error_messages),
                payload={
                    'header': header_payload,
                    'picking_vals': picking_vals,
                    'picking_id': picking.id if picking else False,
                },
                line_payloads=all_line_payloads,
            )

        shipment.write({
            'import_state': action_state,
            'import_message': f'{action_state.title()}: {picking.name if picking else False}',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._resolve_error_tracking(shipment)
        # picking.action_confirm()
        return action_state

    def _do_import(self):
        imported = 0
        updated = 0
        error = 0

        grouped_shipments = []
        seen_shipment_numbers = set()
        for shipment in self.sorted(lambda record: (record.shipment_nbr or '', record.id)):
            shipment_key = shipment.shipment_nbr or shipment.id
            if shipment_key in seen_shipment_numbers:
                continue
            seen_shipment_numbers.add(shipment_key)
            grouped_shipments.append(shipment)

        for shipment in grouped_shipments:
            try:
                with self.env.cr.savepoint():
                    action_state = self._import_single_shipment(shipment)
                if action_state == 'imported':
                    imported += 1
                elif action_state == 'updated':
                    updated += 1
            except Exception as exc:
                _logger.exception("Error import shipment %s", shipment.shipment_nbr or shipment.id)
                if isinstance(exc, ShipmentImportError):
                    error_payload = exc.payload
                    all_line_payloads = exc.line_payloads
                    error_message = str(exc)
                else:
                    error_payload = {'header': shipment.read()[0] if shipment.exists() else {}}
                    all_line_payloads = []
                    error_message = str(exc)

                try:
                    self._persist_error_tracking(
                        shipment,
                        [error_message],
                        line_payloads=all_line_payloads,
                        payload=error_payload,
                    )
                except Exception:
                    _logger.exception(
                        "Failed to persist error tracking for shipment %s",
                        shipment.shipment_nbr or shipment.id,
                    )

                shipment.write({
                    'import_state': 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        # msg = f'Import done: {imported} shipment created, {updated} shipment updated, {error} shipment error.'
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Shipment SO Return',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'warning',
        #         'sticky': True,
        #     }
        # }

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
