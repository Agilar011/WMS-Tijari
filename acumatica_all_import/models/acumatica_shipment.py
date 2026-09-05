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

    header_external_id = fields.Char(string='UUID Header Acumatica')
    shipment_line_id = fields.Many2one('acumatica.shipment.line', string='Receipt', ondelete='cascade')
    line_external_id = fields.Char(string='UUID Line Acumatica')

    shipment_nbr = fields.Char(string='Shipment Number', index=True)
    description = fields.Char(string='Description Line')
    note = fields.Text(string='Detail Note')
    line_note_id = fields.Char(string='Line Note ID')
    is_free_item = fields.Char(string='Free Item')
    inventory_id = fields.Char(string='InventoryID')
    line_nbr = fields.Char(string='Line Nbr')
    location_dest_code = fields.Char(string='Location Detail')
    open_qty = fields.Char(string='Open Qty')
    order_qty = fields.Char(string='Ordered Qty')
    order_line_number = fields.Char(string='Order Line Nbr')
    order_number = fields.Char(string='Order Nbr')
    order_type = fields.Char(string='Order Type')
    shipped_qty = fields.Char(string='Shipped Qty Detail')
    uom_code = fields.Char(string='UOM')
    original_qty = fields.Char(string='Original Qty')
    warehouse_dest_code = fields.Char(string='Warehouse Detail')
    warehouse_dest_name = fields.Char(string='Warehouse Detail Name')
    shipped_weight = fields.Char(string='Shipped Weight')


class AcumaticaShipmentLine(models.Model):
    _name = 'acumatica.shipment.line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Data Shipment Receipt dari Acumatica'
    _order = 'shipment_nbr asc, id asc'

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header')
    line_external_id = fields.Char(string='UUID Line')

    product_line_ids = fields.One2many('acumatica.shipment.product.line', 'shipment_line_id', string='Lines')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types', domain=[('is_default_api', '=', True)])
    building_code = fields.Char(string='Building Code')
    shipment_nbr = fields.Char(string='Shipment Number', index=True)
    partner_code = fields.Char(string='CustomerID')
    partner_name = fields.Char(string='Customer Name')
    scheduled_date = fields.Char(string='Shipment Date')
    warehouse_code = fields.Char(string='Warehouse Asal')
    warehouse_name = fields.Char(string='Warehouse Name')
    warehouse_dest_code = fields.Char(string='Warehouse Tujuan')
    header_location_code = fields.Char(string='Location Header')
    header_location_name = fields.Char(string='Location Header Name')
    header_location_code_2 = fields.Char(string='Location Header 2')
    header_location_name_2 = fields.Char(string='Location Header Name 2')
    status = fields.Char(string='Status')
    document_only = fields.Boolean(string='Document Only', readonly=True)
    shipment_type = fields.Char(string='Type')
    operation = fields.Char(string='Operation')

    note = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')
    actual_qty = fields.Char(string='Control Qty')
    description = fields.Char(string='Description Header')
    fob_point = fields.Char(string='FOB Point')
    fob_point_description = fields.Char(string='FOB Point Description')
    is_hold = fields.Char(string='Hold')
    is_insurance = fields.Char(string='Insurance')
    acumatica_write_date = fields.Char(string='Last Modified')
    package_count = fields.Char(string='Package Count')
    package_weight = fields.Char(string='Package Weight')
    is_picked = fields.Char(string='Picked')
    shipped_qty = fields.Char(string='Shipped Qty Header')
    shipped_volume = fields.Char(string='Shipped Volume')
    shipped_weight = fields.Char(string='Shipped Weight')
    shipping_terms = fields.Char(string='Shipping Terms')
    shipping_settings = fields.Char(string='Shipping Settings')
    shipping_zone = fields.Char(string='Shipping Zone')
    ship_via = fields.Char(string='Ship Via')
    unlimited_packages = fields.Char(string='Unlimited Packages')
    allocations = fields.Text(string='Allocations JSON')

    acumatica_id = fields.Char(string='Acumatica ID')
    acumatica_row_number = fields.Integer(string='Acumatica Row Number')
    acumatica_line_number = fields.Char(string='Acumatica Line Number')
    original_qty = fields.Char(string='Original Qty')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged', readonly=True)
    import_message = fields.Char(string='Generation Message', readonly=True, tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference', readonly=True)
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
            partner = Partner.search([('adt_b_account_id', '=', line.partner_code)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.partner_code)], limit=1)

            if partner:
                print(f"Partner found: {partner}")
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
                l.import_state in ['staged', 'error']
                or (l.import_state in ['created', 'updated'] and not l.odoo_picking_id)
            )
        )
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _handle_acumatica_error(self, first, error_messages=False, line_payloads=None, payload=None):
        return self.env['acumatica.error.transaction']._handle_acumatica_error(
            first,
            error_messages,
            origin=first.shipment_nbr or False,
            payload=payload,
            line_payloads=line_payloads,
        )

    def _import_single_shipment(self, shipment):
        shipment.ensure_one()

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = shipment.shipment_nbr or False
        header_payload = shipment.read()[0] if shipment.exists() else {}
        error_messages = []
        all_line_payloads = []
        picking = shipment.odoo_picking_id
        action_state = 'staged'

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
            'adt_type': 'SO Return' if shipment.shipment_type == 'Shipment' else shipment.shipment_type,
            # 'adt_type': shipment.shipment_type or False

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
            self.env['acumatica.error.transaction']._handle_acumatica_update(shipment, origin=origin)
        else:
            picking = Picking.create(picking_vals)
            action_state = 'created'

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
            'import_message': 'success',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._handle_acumatica_error(shipment)
        # picking.action_confirm()
        return action_state

    def _do_import(self):
        created = 0
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
                if action_state == 'created':
                    created += 1
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
                    self._handle_acumatica_error(
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
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        msg = f'Generate done: {created} shipment created, {updated} shipment updated, {error} shipment error.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Generate Shipment SO Return',
                'message': msg,
                'type': 'success' if error == 0 else 'danger',
                'sticky': True,
            }
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

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
        self.search([('import_state', '=', 'staged')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})
