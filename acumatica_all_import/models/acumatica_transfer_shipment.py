import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError
import requests

_logger = logging.getLogger(__name__)


class TransferShipmentImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaTransferShipmentLine(models.Model):
    _name = 'acumatica.transfer.shipment.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Transfer Shipment dari Acumatica'
    _order = 'shipment_nbr asc, id asc'

    shipment_line_ids = fields.One2many(
        'acumatica.transfer.shipment.line.product', 
        'shipment_id', 
        string='Shipment Lines'
    )

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header')
    line_row_number = fields.Char(string='Row Number Detail')

    building_code = fields.Char(string='BuildingID')
    shipment_nbr = fields.Char(string='Shipment Number', index=True)
    partner_code = fields.Char(string='CustomerID')
    customer_name = fields.Char(string='Customer Name')
    description = fields.Char(string='Description Header')
    document_only = fields.Boolean(string='Document Only')
    fob_point = fields.Char(string='FOB Point')
    is_hold = fields.Char(string='Hold')
    is_insurance = fields.Char(string='Insurance')
    acumatica_write_date = fields.Char(string='Last Modified')
    header_location_code = fields.Char(string='Location Header')
    location_name = fields.Char(string='Location Name')
    operation = fields.Char(string='Operation')
    package_count = fields.Char(string='Package Count')
    package_weight = fields.Char(string='Package Weight')
    is_picked = fields.Char(string='Picked')
    scheduled_date = fields.Char(string='Shipment Date')
    shipped_qty = fields.Char(string='Shipped Qty Header')
    shipped_volume = fields.Char(string='Shipped Volume')
    shipped_weight = fields.Char(string='Shipped Weight')
    shipping_terms = fields.Char(string='Shipping Terms')
    shipping_zone = fields.Char(string='Shipping Zone')
    ship_via = fields.Char(string='Ship Via')
    site_id_description = fields.Char(string='Site ID Description')
    status = fields.Char(string='Status')
    warehouse_dest_code = fields.Char(string='To Warehouse')
    shipment_type = fields.Char(string='Type')
    warehouse_code = fields.Char(string='Warehouse')
    is_unlimited_packages = fields.Char(string='Unlimited Packages')
    actual_qty = fields.Char(string='Control Qty')
    note = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')


    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged')
    import_message = fields.Char(string='Generation Message', tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order',
    )
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')

    @api.depends('shipment_nbr')
    def _compute_exists_in_odoo(self):
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            rec.exists_in_odoo = bool(
                rec.shipment_nbr
                and InternalTransferOrder.search_count([('external_ref', '=', rec.shipment_nbr)])
            )

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
        return product

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line.partner_code:
            partner = Partner.search([('ref', '=', line.partner_code)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.partner_code)], limit=1)
        return partner

    def _find_warehouse_by_code(self, code):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if code:
            warehouse = Warehouse.search([('code', '=', code), ('is_active', '=', True)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse

    def _find_location(self, code, warehouse=False, fallback_field='lot_stock_id'):
        Location = self.env['stock.location']
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse and hasattr(warehouse, fallback_field):
            location = getattr(warehouse, fallback_field)
        return location

    def _find_acumatica_location(self, code):
        Location = self.env['stock.location.acumatica']
        if not code:
            return False
        mapping = Location.search([('code', '=', code), ('is_active', '=', True)], limit=1)
        return mapping.odoo_location_id if mapping and mapping.odoo_location_id else False

    def _handle_acumatica_error(self, first, error_messages=False, line_payloads=None, payload=None):
        return self.env['acumatica.error.transaction']._handle_acumatica_error(
            first,
            error_messages,
            origin=first.shipment_nbr or False,
            payload=payload,
            line_payloads=line_payloads,
        )
    
    def _find_location2(self, code):
        print("search product location")
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        if code.location_dest_code:
            warehouse = Warehouse.search([('code', '=', code.location_dest_code), ('is_active', '=', True)], limit=1)
            if warehouse:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id

        return warehouse


        Location = self.env['stock.location']
        location = False
        if code:
            location = Location.search([('complete_name', '=', code)], limit=1)
            if not location:
                location = Location.search([('name', '=', code)], limit=1)
        if not location and warehouse and hasattr(warehouse, fallback_field):
            location = getattr(warehouse, fallback_field)
        return location

    def _find_uom(self, line, product):
        print("search product uom")
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
            if not uom and product:
                uom = product.uom_id
            
        return uom

    def action_import_selected(self):
        lines = self.filtered(
            lambda l: l.selected and (
                l.import_state in ['staged', 'error']
                or (
                    l.import_state in ['created', 'updated']
                    and not l.odoo_picking_id
                )
            )
        )
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_open_picking(self):
        self.ensure_one()
        if self.odoo_internal_transfer_order_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'internal.transfer.order',
                'res_id': self.odoo_internal_transfer_order_id.id,
                'view_mode': 'form',
            }
        if not self.odoo_picking_id:
            raise UserError('Belum diimport, belum ada receipt di Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
        }

    def action_import_this(self):
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _import_single_transfer_shipment(self, shipment):
        shipment.ensure_one()

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']

        origin = shipment.shipment_nbr or False
        header_payload = shipment.read()[0] if shipment.exists() else {}
        error_messages = []
        all_line_payloads = []
        picking = shipment.odoo_picking_id
        action_state = 'staged'

        for shipment_line in shipment.shipment_line_ids:
            all_line_payloads.append({
                'inventory_id': shipment_line.inventory_id or False,
                'product_name': shipment_line.line_description or False,
                'qty': shipment._parse_float(shipment_line.product_uom_qty),
                'uom': shipment_line.uom_code or False,
                'payload': shipment_line.read()[0] if shipment_line.exists() else {},
            })

        first_product_line = shipment.shipment_line_ids[:1]
        source_warehouse_code = (
            shipment.warehouse_code
            or (first_product_line.line_warehouse_code if first_product_line else False)
            or False
        )
        source_wh = shipment._find_warehouse_by_code(source_warehouse_code)
        dest_wh = False
        picking_type = shipment.picking_type_id
        if shipment.document_only:
            if not picking_type:
                picking_type = self.env['stock.picking.type'].resolve_document_only_picking_type(
                    api_acumatica='transfer_shipment',
                    document_only=shipment.document_only,
                    warehouse_code=source_warehouse_code,
                )
                if picking_type:
                    shipment.picking_type_id = picking_type

        if not source_wh:
            error_messages.append(
                f'Warehouse with location code {source_warehouse_code or "-"} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )
        if shipment.document_only and not picking_type:
            error_messages.append(
                f'Operation Type for Transfer Shipment with warehouse code {source_warehouse_code or "-"} was not found in the WMS | WMS Dependency : MASTER OPERATION TYPE.'
            )

        src_location = (
            shipment._find_acumatica_location(source_warehouse_code)
            or shipment._find_location(shipment.header_location_code, source_wh, 'lot_stock_id')
            or (picking_type.default_location_src_id if picking_type else False)
            or (source_wh.lot_stock_id if source_wh else False)
        )
        transfer_service = self.env['acumatica.internal.transfer.service']
        dest_location = False
        if shipment.document_only and not error_messages:
            transfer_info = transfer_service.classify_transfer_out_to_virtual(
                source_warehouse_code,
                shipment.warehouse_dest_code,
                'WarehouseID',
                'ToWarehouseID',
            )
            src_location = transfer_info['source_location']
            dest_location = transfer_info['destination_location']

        if not src_location:
            error_messages.append(
                f'Source location for code {source_warehouse_code or shipment.header_location_code or "-"} was not found in the WMS | WMS Dependency : MAPPING LOCATION.'
            )
        if shipment.document_only and dest_location and dest_location.usage == 'customer':
            error_messages.append(
                'Destination location customer hanya boleh dipakai oleh SO Shipment.'
            )

        if error_messages:
            raise TransferShipmentImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
                line_payloads=all_line_payloads,
            )

        if not shipment.document_only:
            transfer_info = transfer_service.classify_transfer_out_to_virtual(
                source_warehouse_code,
                shipment.warehouse_dest_code,
                'WarehouseID',
                'ToWarehouseID',
            )
            if transfer_info['status'] == 'skip':
                shipment.write({
                    'import_state': 'updated',
                    'import_message': 'success',
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': False,
                })
                self.env['acumatica.error.transaction']._handle_acumatica_update(shipment, origin=shipment.shipment_nbr or False)
                return 'updated'
            src_location = transfer_info['source_location']
            dest_location = transfer_info['destination_location']
            order, action_state = transfer_service.prepare_order(
                origin,
                src_location,
                dest_location,
                'inter_warehouse',
                shipment._parse_dt(shipment.scheduled_date),
                shipment.note or shipment.description or False,
                description=shipment.description or False,
                transfer_type='transfer_out',
                adt_transaction_type='Transfer Shipment',
                document_only=shipment.document_only,
            )

            for shipment_line in shipment.shipment_line_ids:
                move_vals = {}
                try:
                    product = shipment._find_product(shipment_line)
                    if not product:
                        error_messages.append(
                            f'Product with InventoryID {shipment_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                        )
                        continue

                    uom = shipment._find_uom(shipment_line, product)
                    if not uom:
                        error_messages.append(
                            f'UOM with InventoryID {shipment_line.inventory_id} was not found in the WMS | MASTER UOM.'
                        )
                        continue

                    qty = shipment._parse_float(shipment_line.product_uom_qty)
                    move_vals = {
                        'adt_dest_location_id': dest_location.id,
                        'adt_line_external_id': shipment_line.line_external_id or False,
                        'adt_inventory_id': shipment_line.inventory_id or False,
                        'adt_line_nbr': shipment_line.line_nbr or False,
                        'adt_order_qty': shipment._parse_float(shipment_line.order_qty),
                        'adt_open_qty': shipment._parse_float(shipment_line.open_qty),
                        'adt_transfer_order_line_number': shipment_line.order_line_number or False,
                        'adt_transfer_order_number': shipment_line.order_number or False,
                        'adt_transfer_order_type': shipment_line.order_type or False,
                        'adt_transfer_shipment_number': origin,
                        'adt_uom_code': shipment_line.uom_code or False,
                        'adt_warehouse_dest_code': shipment.warehouse_dest_code or False,
                        'adt_location_dest_code': shipment_line.location_dest_code or False,
                        'adt_type': 'Transfer Shipment',
                        'product_note': shipment_line.line_note or False,
                    }
                    transfer_service.create_order_move(
                        order,
                        product,
                        qty,
                        uom,
                        shipment_line.line_description or product.display_name,
                        shipment_line.line_description or False,
                        move_vals,
                    )
                except TransferShipmentImportError:
                    raise
                except Exception as line_error:
                    _logger.exception("Error import transfer shipment line %s", shipment_line.id)
                    error_messages.append(str(line_error))
                    all_line_payloads.append({
                        'inventory_id': shipment_line.inventory_id or False,
                        'product_name': shipment_line.line_description or False,
                        'qty': shipment._parse_float(shipment_line.product_uom_qty),
                        'uom': shipment_line.uom_code or False,
                        'payload': move_vals if move_vals else (shipment_line.read()[0] if shipment_line.exists() else {}),
                    })

            if error_messages:
                raise TransferShipmentImportError(
                    '\n'.join(error_messages),
                    payload={
                        'header': header_payload,
                        'order_id': order.id if order else False,
                    },
                    line_payloads=all_line_payloads,
                )

            transfer_service.set_order_ready(order)
            shipment.write({
                'import_state': action_state,
                'import_message': 'success',
                'odoo_picking_id': False,
                'odoo_internal_transfer_order_id': order.id if order else False,
            })
            self._handle_acumatica_error(shipment)
            return action_state

        picking_vals = {
            'origin': origin,
            'partner_id': dest_wh.partner_id.id if dest_wh and dest_wh.partner_id else False,
            'picking_type_id': picking_type.id,
            'location_id': src_location.id,
            'location_dest_id': dest_location.id,
            'adt_dest_location_id': dest_location.id,
            'scheduled_date': shipment._parse_dt(shipment.scheduled_date),
            'note': shipment.note or shipment.description or False,
            'adt_description': shipment.description or False,
            # 'adt_actual_qty': shipment._parse_float(shipment.actual_qty),
            'adt_total_qty': shipment._parse_float(shipment.shipped_qty),
            'adt_status': shipment.status or False,
            'adt_type': 'Transfer Shipment',
            'adt_warehouse_code': source_warehouse_code or False,
            'adt_to_warehouse_code': shipment.warehouse_dest_code or False,
            'adt_external_id': shipment.external_id or False,
            'adt_header_location_code': shipment.header_location_code or False,
            'adt_acumatica_write_date': shipment._parse_dt(shipment.acumatica_write_date),
            'adt_is_document_only': shipment.document_only,
        }
        picking_vals = {key: value for key, value in picking_vals.items() if key in Picking._fields}

        if picking:
            if picking.state != 'draft':
                raise TransferShipmentImportError(
                    f'Transfer Shipment {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.',
                    payload={'header': header_payload, 'picking_vals': picking_vals},
                    line_payloads=all_line_payloads,
            )
            picking.write(picking_vals)
            action_state = 'updated'
            self.env['acumatica.error.transaction']._handle_acumatica_update(shipment, origin=origin)
        else:
            existing_picking = Picking.search([
                ('origin', '=', origin),
                ('picking_type_id', '=', picking_type.id),
            ], limit=1)
            if existing_picking:
                if existing_picking.state != 'draft':
                    raise TransferShipmentImportError(
                        f'Transfer Shipment {origin} sudah ada di Odoo dengan state {existing_picking.state}, tidak bisa diupdate.',
                        payload={'header': header_payload, 'picking_vals': picking_vals},
                        line_payloads=all_line_payloads,
                )
                picking = existing_picking
                picking.write(picking_vals)
                action_state = 'updated'
                self.env['acumatica.error.transaction']._handle_acumatica_update(shipment, origin=origin)
            else:
                picking = Picking.create(picking_vals)
                action_state = 'created'

        if action_state == 'updated':
            picking.move_ids.unlink()

        for shipment_line in shipment.shipment_line_ids:
            move_vals = {}
            try:
                product = shipment._find_product(shipment_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {shipment_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    continue

                uom = shipment._find_uom(shipment_line, product)
                if not uom:
                    error_messages.append(
                        f'UOM with InventoryID {shipment_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    continue

                qty = shipment._parse_float(shipment_line.product_uom_qty)
                adt_dest_location = picking.location_dest_id.id if picking else False
                move_vals = {
                    'name': shipment_line.line_description or product.display_name,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'warehouse_id': source_wh.id if source_wh else False,
                    # 'description_picking': product.name or False,
                    'adt_dest_location_id': adt_dest_location,
                    'adt_line_external_id': shipment_line.line_external_id or False,
                    'adt_inventory_id': shipment_line.inventory_id or False,
                    'adt_line_nbr': shipment_line.line_nbr or False,
                    'adt_order_qty': shipment._parse_float(shipment_line.order_qty),
                    'adt_open_qty': shipment._parse_float(shipment_line.open_qty),
                    'adt_transfer_order_line_number': shipment_line.order_line_number or False,
                    'adt_transfer_order_number': shipment_line.order_number or False,
                    'adt_transfer_order_type': shipment_line.order_type or False,
                    'adt_transfer_shipment_number': origin,
                    'adt_uom_code': shipment_line.uom_code or False,
                    'adt_warehouse_dest_code': shipment.warehouse_dest_code or False,
                    'adt_location_dest_code': shipment_line.location_dest_code or False,
                    'adt_type': 'Transfer Shipment',
                    'product_note': shipment_line.line_note or False,
                }
                move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                Move.create(move_vals)
            except TransferShipmentImportError:
                raise
            except Exception as line_error:
                _logger.exception("Error import transfer shipment line %s", shipment_line.id)
                error_messages.append(str(line_error))
                all_line_payloads.append({
                    'inventory_id': shipment_line.inventory_id or False,
                    'product_name': shipment_line.line_description or False,
                    'qty': shipment._parse_float(shipment_line.product_uom_qty),
                    'uom': shipment_line.uom_code or False,
                    'payload': move_vals if move_vals else (shipment_line.read()[0] if shipment_line.exists() else {}),
                })

        if error_messages:
            raise TransferShipmentImportError(
                '\n'.join(error_messages),
                payload={
                    'header': header_payload,
                    'picking_vals': picking_vals,
                    'picking_id': picking.id if picking else False,
                },
                line_payloads=all_line_payloads,
            )

        if shipment.document_only:
            picking.action_validate_document_only_import(force=True)

        shipment.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_picking_id': picking.id if picking else False,
            'odoo_internal_transfer_order_id': False,
        })
        self._handle_acumatica_error(shipment)
        return action_state

    def _do_import(self):
        created = updated = error = 0
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
                    action_state = self._import_single_transfer_shipment(shipment)
                if action_state == 'created':
                    created += 1
                elif action_state == 'updated':
                    updated += 1
            except Exception as exc:
                _logger.exception('Error import transfer shipment %s', shipment.shipment_nbr or shipment.id)
                if isinstance(exc, TransferShipmentImportError):
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
                        'Failed to persist error tracking for transfer shipment %s',
                        shipment.shipment_nbr or shipment.id,
                    )

                shipment.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': error_message[:1000],
                })
                error += 1

        msg = f'Generate done: {created} transfer shipment created, {updated} transfer shipment updated, {error} transfer shipment error.'
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Generate Transfer Shipment',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

class AcumaticaTransferShipmentLineProduct(models.Model):
    _name = 'acumatica.transfer.shipment.line.product'
    _description = 'Data Product dari Transfer Shipment Acumatica'
    _order = 'shipment_id asc, line_nbr asc, id asc'

    
    shipment_id = fields.Many2one(
    'acumatica.transfer.shipment.line', 
    string='Parent Shipment', 
    ondelete='cascade', 
    required=True)

    shipment_nbr = fields.Char(string='Shipment Number', index=True)
    line_external_id = fields.Char(string='UUID Line')
    line_row_number = fields.Char(string='Line Nbr')
    line_nbr = fields.Char(string='Line Nbr')    
    line_description = fields.Char(string='Description Detail')
    is_free_item = fields.Char(string='Free Item')
    inventory_id = fields.Char(string='InventoryID')
    location_dest_code = fields.Char(string='LocationID')
    open_qty = fields.Char(string='Open Qty')
    order_qty = fields.Char(string='Ordered Qty')
    order_line_number = fields.Char(string='Order Line Nbr')
    order_number = fields.Char(string='Order Number', index=True)
    order_type = fields.Char(string='Order Type')
    original_qty = fields.Char(string='Original Qty')
    product_uom_qty = fields.Char(string='Shipped Qty Detail')
    uom_code = fields.Char(string='UOM')
    line_warehouse_code = fields.Char(string='Warehouse Detail')
    line_note = fields.Text(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')
    custom_json = fields.Text(string='Custom Payload')
