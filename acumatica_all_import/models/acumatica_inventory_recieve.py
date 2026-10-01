import logging
from dateutil import parser as dateutil_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
import requests


class InventoryImportError(Exception):
    def __init__(self, message, payload=None, line_payloads=None):
        super().__init__(message)
        self.payload = payload or {}
        self.line_payloads = line_payloads or []


class AcumaticaReceiptProductLine(models.Model):
    _name = 'acumatica.inventory.recieved.product.line'
    _description = 'Data Product Inventory Recieve dari Acumatica'

    header_external_id = fields.Char(string='UUID Header Acumatica')
    inventory_line_id = fields.Many2one('acumatica.inventory.recieved.line', string='Receipt', ondelete='cascade')

    line_external_id = fields.Char(string='UUID Line')
    line_note = fields.Text(string='Line Note')
    branch_warehouse = fields.Char(string='Branch')
    line_description = fields.Char(string='Description')
    inventory_id = fields.Char(string='InventoryID')
    line_nbr = fields.Char(string='Line Nbr')
    location_code = fields.Char(string='Location')
    line_location_name = fields.Char(string='Line Location Name')
    line_note_id = fields.Char(string='Line Note ID')
    product_uom_qty = fields.Char(string='Qty')
    uom_code = fields.Char(string='UOM')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    line_warehouse_name = fields.Char(string='Line Warehouse Name')


class AcumaticaInventoryRecievedLine(models.Model):
    _name = 'acumatica.inventory.recieved.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Inventory Recieved dari Acumatica'
    _order = 'reference_nbr asc, id asc'

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header')
    product_line_ids = fields.One2many('acumatica.inventory.recieved.product.line', 'inventory_line_id', string='Lines')
    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')

    reference_nbr = fields.Char(string='Reference Number', index=True)
    scheduled_date = fields.Char(string='Date')
    description = fields.Char(string='Description')
    branch_warehouse = fields.Char(string='Branch')
    building_code = fields.Char(string='Building Code')
    actual_qty = fields.Char(string='Control Qty')

    acumatica_write_date = fields.Char(string='Last Modified')
    post_period = fields.Char(string='Post Period')
    status = fields.Char(string='Status')
    total_qty = fields.Char(string='Qty Total')
    warehouse_code = fields.Char(string='Warehouse')
    warehouse_dest_code = fields.Char(string='Warehouse Dest')
    transfer_type = fields.Char(string='Transfer Type')
    doc_type = fields.Char(string='Doc Type')
    note = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')
    external_ref = fields.Char(string='External Ref')
    document_only = fields.Boolean(string='Document Only')
    customer_code = fields.Char(string='Customer Code')
    customer_location_id = fields.Char(string='Customer Location ID')
    customer_location_name = fields.Char(string='Customer Location Name')
    customer_name = fields.Char(string='Customer Name')
    vendor_code = fields.Char(string='VendorID')
    vendor_name = fields.Char(string='Vendor Name')
    shipment_nbr = fields.Char(string='Shipment Nbr')
    transfer_nbr = fields.Char(string='Transfer Nbr')
    location_code = fields.Char(string='Location Code')
    change_item_ref_nbr = fields.Char(string='Change Item Ref Number')


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
        string='Internal Transfer Order di Odoo',
    )
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')

    @api.depends('reference_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            rec.exists_in_odoo = bool(
                rec.reference_nbr
                and (
                    Picking.search_count([('origin', '=', rec.reference_nbr)])
                    or InternalTransferOrder.search_count([('external_ref', '=', rec.reference_nbr)])
                )
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

    @staticmethod
    def _normalize_transfer_type(value):
        return (value or '').strip().lower().replace('-', '_').replace(' ', '_')

    def _is_transfer_in(self):
        self.ensure_one()
        return self._normalize_transfer_type(self.transfer_type) in (
            'transfer_in',
            'transfer_receipt',
        )

    def _find_partner(self, line):
        Partner = self.env['res.partner']
        partner = False
        if line.customer_code:
            partner = Partner.search([('company_registry', '=', line.customer_code), ('is_company', '=', True)], limit=1)
            if not partner:
                partner = Partner.search([('name', '=', line.customer_code), ('is_company', '=', True)], limit=1)
        return partner

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        # if not product and line.line_description:
        #     product = Product.search([('name', '=', line.line_description)], limit=1)

        return product

    def _find_warehouse(self, line):
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False
        code = line.warehouse_dest_code
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
        if line.warehouse_dest_code:
            location = Location.search([('code', '=', line.warehouse_dest_code)], limit=1)
            if location:
                if not location.odoo_location_id:
                    location = False
                else:
                    location = location.odoo_location_id
        return location

    def _find_line_location_dest(self, line):
        Location = self.env['stock.location.acumatica']
        for code in (line.warehouse_dest_code, line.location_code):
            if not code:
                continue
            mapping = Location.search([('code', '=', code), ('active', '=', True)], limit=1)
            if not mapping:
                mapping = Location.search([('name', '=', code), ('active', '=', True)], limit=1)
            if mapping and mapping.odoo_location_id:
                return mapping.odoo_location_id
        return self.env['stock.location']

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
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
            origin=first.reference_nbr or False,
            payload=payload,
            line_payloads=line_payloads,
        )

    def _import_single_transfer_in(self, receive):
        receive.ensure_one()

        TransferService = self.env['acumatica.internal.transfer.service']
        Move = self.env['stock.move']

        origin = receive.reference_nbr or False
        header_payload = receive.read()[0] if receive.exists() else {}
        error_messages = []
        error_line_payloads = []

        source_code = receive.warehouse_code
        destination_code = receive.warehouse_dest_code or receive.warehouse_code
        try:
            transfer_info = TransferService.classify_transfer_in_from_virtual(
                source_code,
                destination_code,
                'FromWarehouseID',
                'ToWarehouseID',
            )
        except UserError as error:
            error_messages.append(str(error))
            transfer_info = False

        if transfer_info and transfer_info['status'] == 'skip':
            receive.write({
                'import_state': 'updated',
                'import_message': 'success',
                'odoo_internal_transfer_order_id': False,
                'odoo_picking_id': False,
            })
            self.env['acumatica.error.transaction']._handle_acumatica_update(receive, origin=receive.reference_nbr or False)
            self._handle_acumatica_error(receive)
            return 'updated'

        if error_messages:
            raise InventoryImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
            )

        source_location = transfer_info['source_location']
        destination_location = transfer_info['destination_location']
        if not source_location:
            raise InventoryImportError(
                f'Source location untuk warehouse {source_code or "-"} '
                'tidak ditemukan atau belum dimapping di WMS | '
                'WMS Dependency : MAPPING WAREHOUSE.'
            )
        if not destination_location:
            raise InventoryImportError(
                f'Destination location untuk warehouse {destination_code or "-"} '
                'tidak ditemukan atau belum dimapping di WMS | '
                'WMS Dependency : MAPPING WAREHOUSE.'
            )
        primary_external_ref = receive.reference_nbr or receive.transfer_nbr
        order, action_state = TransferService.prepare_order(
            primary_external_ref,
            source_location,
            destination_location,
            transfer_info['transaction_type'],
            schedule_date=receive._parse_dt(receive.scheduled_date),
            note=receive.note or False,
            description=receive.description or False,
            transfer_type='transfer_in',
            external_ref_in=receive.reference_nbr,
            external_ref_out=receive.transfer_nbr,
            adt_transaction_type=receive.transfer_type or receive.doc_type or False,
            document_only=receive.document_only,
        )

        order.write({'validation_policy': 'validate_all'})

        for receive_line in receive.product_line_ids:
            move_vals = {}
            line_payload = receive_line.read()[0] if receive_line.exists() else {}
            try:
                product = receive._find_product(receive_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receive_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receive_line.inventory_id or False,
                        'product_name': receive_line.line_description or False,
                        'qty': receive._parse_float(receive_line.product_uom_qty),
                        'uom': receive_line.uom_code or False,
                        'payload': receive_line.read()[0] if receive_line.exists() else {},
                    })
                    continue

                uom = receive._find_uom(receive_line, product)
                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {receive_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receive_line.inventory_id or False,
                        'product_name': receive_line.line_description or False,
                        'qty': receive._parse_float(receive_line.product_uom_qty),
                        'uom': receive_line.uom_code or False,
                        'payload': receive_line.read()[0] if receive_line.exists() else {},
                    })
                    continue

                qty = receive._parse_float(receive_line.product_uom_qty)
                line_destination = receive._find_line_location_dest(receive_line) or destination_location
                if not line_destination:
                    error_messages.append(
                        f'Destination location untuk line {receive_line.line_nbr or "-"} '
                        f'dengan warehouse {receive_line.warehouse_dest_code or destination_code or "-"} '
                        'tidak ditemukan atau belum dimapping di WMS | '
                        'WMS Dependency : MAPPING WAREHOUSE.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receive_line.inventory_id or False,
                        'product_name': receive_line.line_description or False,
                        'qty': qty,
                        'uom': receive_line.uom_code or False,
                        'payload': line_payload,
                    })
                    continue
                move_vals = {
                    'adt_inventory_id': receive_line.inventory_id or False,
                    'adt_line_nbr': receive_line.line_nbr or False,
                    'adt_uom_code': receive_line.uom_code or False,
                    'adt_warehouse_dest_code': receive_line.warehouse_dest_code or False,
                    'adt_location_dest_code': receive_line.location_code or False,
                    'adt_quantity': qty,
                    'adt_type': receive.transfer_type or 'Transfer In',
                    'product_note': receive_line.line_note or False,
                    'location_dest_id': line_destination.id,
                }
                move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                TransferService.create_order_move(
                    order,
                    product,
                    qty,
                    uom=uom,
                    name=receive_line.line_description or product.display_name,
                    description=receive_line.line_description or False,
                    extra_vals=move_vals,
                )

            except InventoryImportError:
                raise
            except Exception as line_error:
                _logger.exception("Error import transfer in line %s", receive_line.id)
                # A database error aborts the current PostgreSQL transaction.
                # Do not continue with the next line; let the outer savepoint
                # roll back the order and persist the original error cleanly.
                raise

        if error_messages:
            raise InventoryImportError(
                '\n'.join(error_messages),
                payload={
                    'header': header_payload,
                    'order_id': order.id if order else False,
                },
                line_payloads=error_line_payloads,
            )

        TransferService.set_order_ready(order)
        receive.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_internal_transfer_order_id': order.id if order else False,
            'odoo_picking_id': False,
        })
        self._handle_acumatica_error(receive)
        return action_state

    def _import_single_receive(self, receive):
        receive.ensure_one()

        if receive._is_transfer_in():
            return receive._import_single_transfer_in(receive)

        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        origin = receive.reference_nbr or False
        header_payload = receive.read()[0] if receive.exists() else {}
        error_messages = []
        error_line_payloads = []
        picking = receive.odoo_picking_id
        action_state = 'staged'

        warehouse = receive._find_warehouse(receive)
        if not warehouse:
            error_messages.append(
                f'Warehouse with location code {receive.warehouse_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        dest_location = receive._find_location_dest(receive)
        if not dest_location:
            error_messages.append(
                f'Location with code {receive.warehouse_dest_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
            )

        partner = False
        owner = False
        if receive.transfer_type in ['Change Item', 'Change Item Discontinue', 'Toko Pegang DO']:
            partner = receive._find_partner(receive)
            if receive.transfer_type == 'Toko Pegang DO':
                owner = partner
            if not partner:
                error_messages.append(
                    f'Partner with code {receive.customer_code} was not found in the WMS | WMS Dependency : MASTER CUSTOMER.'
                )

        # picking_type = PickingType.search([
        #     ('warehouse_id', '=', warehouse.id if warehouse else False),
        #     ('operation_category', '=', 'internal'),
        #     ('code', '=', 'internal'),
        # ], limit=1)
        if receive.picking_type_id:
            picking_type = receive.picking_type_id
        elif receive.config_id:
            picking_type = receive.config_id._resolve_inventory_receive_picking_type(
                transfer_type=receive.transfer_type,
                document_only=receive.document_only,
                warehouse_code=(
                    receive.warehouse_dest_code
                    or receive.warehouse_code
                ),
            )
        else:
            type_key = (receive.transfer_type or 'inventory_receive').strip().lower().replace('-', '_').replace(' ', '_')
            type_map = {
                'change_item': ('incoming', 'receive'),
                'change_item_discontinue': ('incoming', 'receive'),
                'toko_pegang_do': ('incoming', 'receive'),
                'inventory_receive': ('incoming', 'receive'),
                'inventory_received': ('incoming', 'receive'),
                'inventory_receipt': ('incoming', 'receive'),
            }
            code, operation_category = type_map.get(type_key, (False, False))
            if receive.document_only and type_key != 'transfer_in':
                picking_type = PickingType.resolve_document_only_picking_type(
                    api_acumatica='inventory_received',
                    document_only=True,
                    warehouse_code=receive.warehouse_dest_code,
                )
            elif code:
                picking_type = PickingType.resolve_picking_type(
                    warehouse_code=receive.warehouse_dest_code,
                    code=code,
                    operation_category=operation_category,
                    api_acumatica='inventory_received',
                    transaction_key=type_key,
                    required=False,
                )
            else:
                picking_type = PickingType.browse()
        if not receive.picking_type_id and picking_type:
            receive.write({'picking_type_id': picking_type.id})
        if not picking_type:
            warehouse_txt = f"Warehouse code {warehouse.code if warehouse else '-'}"
            location_txt = f'Location code {receive.warehouse_dest_code}'
            error_messages.append(
                f'Operation Type for code internal with {warehouse_txt if warehouse else location_txt} was not found in the WMS | WMS Depedency : MASTER OPERATION TYPE.'
            )

        if error_messages:
            raise InventoryImportError(
                '\n'.join(error_messages),
                payload={'header': header_payload},
            )

        picking_vals = {
            'partner_id': partner.id if partner else False,
            'origin': origin,
            'picking_type_id': picking_type.id,
            'adt_dest_location_id': dest_location.id if dest_location else False,
            'scheduled_date': receive._parse_dt(receive.scheduled_date),
            'note': receive.note or False,
            'owner_id': owner.id if owner else False,

            'adt_branch_warehouse': receive.branch_warehouse or False,
            'adt_actual_qty': self._parse_float(receive.actual_qty),
            'adt_acumatica_write_date': self._parse_dt(receive.acumatica_write_date),
            'adt_post_period': receive.post_period or False,
            'adt_total_qty': self._parse_float(receive.total_qty),
            'adt_type': receive.transfer_type or False,
            'adt_external_ref': receive.external_ref or False,
            'adt_change_item_ref_nbr': receive.change_item_ref_nbr or False,

            'desc_note': receive.description or False,
        }
        picking_vals = {key: value for key, value in picking_vals.items() if key in Picking._fields}

        if picking:
            if picking.state != 'draft':
                raise InventoryImportError(
                    f'receive {origin} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.',
                    payload={'header': header_payload, 'picking_vals': picking_vals},
            )
            picking.write(picking_vals)
            action_state = 'updated'
            self.env['acumatica.error.transaction']._handle_acumatica_update(receive, origin=origin)
        else:
            picking = Picking.create(picking_vals)
            action_state = 'created'

        if action_state == 'updated':
            picking.move_ids.unlink()

        for receive_line in receive.product_line_ids:
            move_vals = {}
            try:
                product = receive._find_product(receive_line)
                if not product:
                    error_messages.append(
                        f'Product with InventoryID {receive_line.inventory_id} was not found in the WMS | MASTER PRODUCT.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receive_line.inventory_id or False,
                        'product_name': receive_line.line_description or False,
                        'qty': receive._parse_float(receive_line.product_uom_qty),
                        'uom': receive_line.uom_code or False,
                        'payload': receive_line.read()[0] if receive_line.exists() else {},
                    })
                    continue

                uom = receive._find_uom(receive_line, product)
                dest_location = receive._find_location_dest(receive_line)
                if not dest_location:
                    error_messages.append(
                        f'Location with code {receive.warehouse_dest_code} was not found or inactive in the WMS | WMS Dependency : MAPPING WAREHOUSE.'
                    )

                if product and not uom:
                    error_messages.append(
                        f'UOM with InventoryID {receive_line.inventory_id} was not found in the WMS | MASTER UOM.'
                    )
                    error_line_payloads.append({
                        'inventory_id': receive_line.inventory_id or False,
                        'product_name': receive_line.line_description or False,
                        'qty': receive._parse_float(receive_line.product_uom_qty),
                        'uom': receive_line.uom_code or False,
                        'payload': receive_line.read()[0] if receive_line.exists() else {},
                    })
                    continue

                qty = receive._parse_float(receive_line.product_uom_qty)
                move_vals = {
                    'name': receive_line.line_description or product.display_name,
                    'picking_id': picking.id if picking else False,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': uom.id if uom else product.uom_id.id,
                    'location_id': picking.location_id.id if picking else False,
                    'location_dest_id': picking.location_dest_id.id if picking else False,
                    'warehouse_id': warehouse.id if warehouse else False,
                    'description_picking': receive_line.line_description or False,

                    'adt_inventory_id': receive_line.line_note or False,
                    'adt_line_nbr': receive_line.line_nbr or False,
                    'adt_uom_code': receive_line.uom_code or False,
                    'adt_warehouse_dest_code': receive_line.warehouse_dest_code or False,
                    'adt_dest_location_id': dest_location.id if dest_location else picking.adt_dest_location_id.id if picking else False,
                }

                move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                Move.create(move_vals)
                # picking.action_confirm()

            except InventoryImportError:
                raise

            except Exception as line_error:
                _logger.exception("Error import line %s", receive.id)
                error_messages.append(str(line_error))
                error_line_payloads.append({
                    'inventory_id': receive_line.inventory_id or False,
                    'product_name': receive_line.line_description or False,
                    'qty': receive._parse_float(receive_line.product_uom_qty),
                    'uom': receive_line.uom_code or False,
                    'payload': move_vals if move_vals else (receive_line.read()[0] if receive_line.exists() else {}),
                })

        if error_messages:
            raise InventoryImportError(
                '\n'.join(error_messages),
                payload={
                    'header': header_payload,
                    'picking_vals': picking_vals,
                    'picking_id': picking.id if picking else False,
                },
                line_payloads=error_line_payloads,
            )

        if receive.document_only:
            picking.action_validate_document_only_import(force=True)

        receive.write({
            'import_state': action_state,
            'import_message': 'success',
            'odoo_picking_id': picking.id if picking else False,
        })
        self._handle_acumatica_error(receive)
        return action_state

    def _do_import(self):
        created = 0
        updated = 0
        error = 0

        grouped_references = []
        seen_reference_numbers = set()
        for reference in self.sorted(lambda record: (record.reference_nbr or '', record.id)):
            reference_key = reference.reference_nbr or reference.id
            if reference_key in seen_reference_numbers:
                continue
            seen_reference_numbers.add(reference_key)
            grouped_references.append(reference)

        for receive in grouped_references:
            try:
                with self.env.cr.savepoint():
                    action_state = self._import_single_receive(receive)
                if action_state == 'created':
                    created += 1
                elif action_state == 'updated':
                    updated += 1
            except Exception as exc:
                _logger.exception("Error import Inventory Receive %s", receive.reference_nbr or receive.id)
                if isinstance(exc, InventoryImportError):
                    error_payload = exc.payload
                    error_line_payloads = exc.line_payloads
                    error_message = str(exc)
                else:
                    error_payload = {'header': receive.read()[0] if receive.exists() else {}}
                    error_line_payloads = []
                    error_message = str(exc)

                try:
                    self._handle_acumatica_error(
                        receive,
                        [error_message],
                        line_payloads=error_line_payloads,
                        payload=error_payload,
                    )
                except Exception:
                    _logger.exception(
                        "Failed to persist error tracking for receive %s",
                        receive.reference_nbr or receive.id,
                    )

                receive.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': error_message[:1000],
                })
                error += 1
                continue

        msg = f'Import done: {created} receive created, {updated} receive updated, {error} receive error.'
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Inventory Receive',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'staged', 'import_message': False})

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
            raise UserError('Belum diimport, belum ada delivery order di Odoo.')
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
