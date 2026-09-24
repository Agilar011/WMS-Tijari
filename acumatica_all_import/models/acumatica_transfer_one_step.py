from dateutil import parser as dateutil_parser
import logging
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)



class AcumaticaTransferOneStepLine(models.Model):
    _name = 'acumatica.transfer.one.step.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    line_ids = fields.One2many(
        'acumatica.transfer.one.step.product', # Nama model child yang dituju
        'header_id',                  # Nama field Many2one di model child
        string='Transfer Lines'
    )

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header Acumatica')
    line_external_id = fields.Char(string='UUID Line Acumatica')

    reference_nbr = fields.Char(string='Reference Number', index=True)
    scheduled_date = fields.Char(string='Date')
    to_warehouse_code = fields.Char(string='To Warehouse')
    to_warehouse_name = fields.Char(string='To Warehouse Name')
    description = fields.Char(string='Description')
    external_ref = fields.Char(string='External Ref')
    from_warehouse_code = fields.Char(string='From Warehouse')
    from_warehouse_name = fields.Char(string='From Warehouse Name')
    status = fields.Char(string='Status')
    return_type = fields.Char(string='Return Type')
    transfer_type = fields.Char(string='Transfer Type')
    trans_type = fields.Char(string='Trans Type')
    total_qty = fields.Char(string='Qty Total')
    is_hold = fields.Char(string='Hold')
    post_period = fields.Char(string='Post Period')
    acumatica_write_date = fields.Char(string='Last Modified')
    note = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')
    document_only = fields.Boolean(string='Document Only')

    line_nbr = fields.Char(string='Line Nbr')
    line_note = fields.Text(string='Line Note')
    line_description = fields.Char(string='Line Description')
    inventory_id = fields.Char(string='InventoryID')
    from_location_code = fields.Char(string='From Location')
    to_location_code = fields.Char(string='To Location')
    quantity = fields.Char(string='Quantity')
    uom_code = fields.Char(string='UOM')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', tracking=True)

    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    import_message = fields.Char(string='Generation Message', tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order',
    )
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync')

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    can_rebuild_same_location_transfer = fields.Boolean(
        compute='_compute_can_rebuild_same_location_transfer',
    )
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")

    @api.depends('reference_nbr')
    def _compute_exists_in_odoo(self):
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            rec.exists_in_odoo = bool(
                rec.reference_nbr
                and InternalTransferOrder.search_count([('external_ref', '=', rec.reference_nbr)])
            )

    @api.depends(
        'import_state',
        'odoo_internal_transfer_order_id',
        'odoo_internal_transfer_order_id.state',
        'odoo_internal_transfer_order_id.transaction_type',
        'odoo_internal_transfer_order_id.location_id',
        'odoo_internal_transfer_order_id.location_dest_id',
        'odoo_internal_transfer_order_id.picking_ids',
        'odoo_internal_transfer_order_id.adt_transaction_type',
        'odoo_internal_transfer_order_id.move_ids.adt_type',
    )
    def _compute_can_rebuild_same_location_transfer(self):
        for line in self:
            order = line.odoo_internal_transfer_order_id
            api_type = (order.adt_transaction_type or '').strip().lower().replace('_', ' ') if order else ''
            is_one_step = (
                api_type in ('1-step', '1 step', 'transfer one step')
                or any(
                    'transfer one step' in (move.adt_type or '').strip().lower()
                    for move in order.move_ids
                )
            ) if order else False
            line.can_rebuild_same_location_transfer = bool(
                line.import_state in ('created', 'updated')
                and order
                and order.state == 'done'
                and not order.picking_ids
                and order.transaction_type == 'intra_warehouse'
                and order.location_id == order.location_dest_id
                and is_one_step
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
            name = line.line_description or line.line_description or line.inventory_id or 'Unknown Product'
            existing = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if existing:
                return existing
            product = Product.create({
                'name': name,
                'default_code': line.inventory_id or False,
                'type': 'consu',  # stockable
            })

        return product

    def _find_acumatica_location_mapping(self, code, label):
        LocationMapping = self.env['stock.location.acumatica']
        mapping = LocationMapping.search([
            ('code', '=', code),
            ('active', '=', True),
        ], limit=1)
        if not mapping:
            mapping = LocationMapping.search([
                ('name', '=', code),
                ('active', '=', True),
            ], limit=1)
        if not mapping:
            raise UserError(
                f'{label} mapping tidak ditemukan di stock.location.acumatica: {code or "-"}'
            )
        if not mapping.odoo_location_id:
            raise UserError(
                f'{label} mapping belum punya Odoo location: {code or "-"}'
            )
        return mapping

    def _find_transit_location(self):
        transit_location = self.env['stock.location'].search([
            ('usage', '=', 'transit'),
        ], limit=1)
        if not transit_location:
            transit_location = self.env['stock.location'].create({
                'name': 'Transit',
                'usage': 'transit',
            })
        return transit_location

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
                or l.can_rebuild_same_location_transfer
                or (
                    l.import_state in ['created', 'updated']
                    and not l.odoo_picking_id
                    and not l.odoo_internal_transfer_order_id
                )
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
    
    def _do_import(self):
        InternalTransferOrder = self.env['internal.transfer.order']
        Move = self.env['stock.move']

        created = 0
        skipped = 0
        updated = 0
        error = 0

        for reference_nbr in self.mapped('reference_nbr'):
            receipt_lines = self.filtered(
                lambda l: l.reference_nbr == reference_nbr
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]

            try:
                self.env.cr.execute('SAVEPOINT import_transfer_one_step_doc')
                origin = first.reference_nbr or False
                existing_order = InternalTransferOrder.search([
                    ('external_ref', '=', origin),
                ], limit=1)
                if existing_order:
                    existing_api_type = (
                        (existing_order.adt_transaction_type or '')
                        .strip().lower().replace('_', ' ')
                    )
                    legacy_same_location_done = (
                        existing_order.state == 'done'
                        and not existing_order.picking_ids
                        and existing_order.transaction_type == 'intra_warehouse'
                        and existing_order.location_id == existing_order.location_dest_id
                        and (
                            existing_api_type in ('1-step', '1 step', 'transfer one step')
                            or any(
                                'transfer one step' in (move.adt_type or '').strip().lower()
                                for move in existing_order.move_ids
                            )
                        )
                    )
                    if existing_order.state not in ('draft', 'cancel') and not legacy_same_location_done:
                        raise UserError(
                            f'Transfer {reference_nbr} sudah ada di Odoo dengan state '
                            f'{existing_order.state}, tidak bisa diupdate.'
                        )
                    if existing_order.picking_ids:
                        raise UserError(
                            f'Transfer {reference_nbr} sudah memiliki picking, tidak bisa diupdate.'
                        )
                    existing_order.move_ids.unlink()
                    if legacy_same_location_done:
                        existing_order.write({'state': 'draft'})
                    order = existing_order
                    action_state = 'updated'
                    updated += 1
                    self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=reference_nbr)
                else:
                    order = False
                    action_state = 'created'
                    created += 1

                transfer_service = self.env['acumatica.internal.transfer.service']
                transfer_info = transfer_service.classify_intra_by_location_mapping(
                    first.from_warehouse_code,
                    first.to_warehouse_code,
                    'WarehouseID',
                    'ToWarehouseID',
                    check_same_location_mapping=False,
                )
                source_location = transfer_info['source_location']
                destination_location = transfer_info['destination_location']
                same_odoo_location = source_location == destination_location

                if order:
                    order.write({
                        'transaction_type': transfer_info['transaction_type'],
                        'transfer_type': transfer_info['transfer_type'],
                        'adt_transaction_type': first.transfer_type or first.trans_type or False,
                        'document_only': bool(first.document_only),
                        'location_group_id': (
                            transfer_info['location_group'].id
                            if transfer_info.get('location_group') else False
                        ),
                        'location_id': source_location.id,
                        'location_dest_id': destination_location.id,
                        'transit_location_id': transfer_service.get_or_create_transit_location().id,
                        'schedule_date': self._parse_dt(first.scheduled_date),
                        'validation_policy': 'validate_all',
                        'note': first.note or False,
                        'description': first.description or False,
                        'state': 'draft',
                    })
                else:
                    order, action_state = transfer_service.prepare_order(
                        origin,
                        source_location,
                        destination_location,
                        transfer_info['transaction_type'],
                        self._parse_dt(first.scheduled_date),
                        first.note or False,
                        description=first.description or False,
                        transfer_type=transfer_info['transfer_type'],
                        location_group=transfer_info.get('location_group'),
                        adt_transaction_type=first.transfer_type or first.trans_type or False,
                        document_only=first.document_only,
                    )

                transfer_lines = self.env['acumatica.transfer.one.step.product'].search([
                    ('header_id', '=', first.id),
                ])

                for line in transfer_lines:
                    try:
                        product = self._find_product(line)
                        if not product:
                            raise UserError(
                                f'Product tidak ditemukan untuk InventoryID: '
                                f'{line.inventory_id or "-"}'
                            )

                        uom = self._find_uom(line, product)
                        qty = self._parse_float(line.quantity)

                        move_vals = {
                            'name': line.line_description or product.display_name,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': source_location.id,
                            'location_dest_id': destination_location.id,
                            'internal_transfer_order_id': order.id,
                            'description_picking': line.line_description or False,
                            'adt_line_nbr': line.line_nbr or False,
                            'adt_line_note': line.line_note or False,
                            'adt_inventory_id': line.inventory_id or False,
                            'adt_uom_code': line.uom_code or False,
                            'adt_line_description': line.line_description or False,
                            'adt_to_location_code': line.to_location_code or False,
                            'adt_from_location_code': line.from_location_code or False,
                            'adt_transfer_order_number': origin,
                            'adt_transfer_order_line_number': line.line_nbr or False,
                            'adt_transfer_order_type': first.transfer_type or False,
                            'adt_quantity': qty,
                            'adt_type': first.transfer_type or 'Transfer One Step',
                        }
                        move_vals = {k: v for k, v in move_vals.items() if k in Move._fields}
                        Move.create(move_vals)

                    except Exception as line_e:
                        _logger.exception('Error import transfer one step line %s', line.id)
                        raise UserError(str(line_e))

                if same_odoo_location:
                    # Keep both direct operation documents at the mapped location.
                    # This pair has no net stock effect and completes the ITO only
                    # after both pickings have been validated.
                    order.write({'document_only': False})
                    transfer_service.set_order_ready(order)
                    order._auto_validate_pickings_by_leg(('delivery', 'receipt'))
                else:
                    transfer_service.set_order_ready(order)
                receipt_lines.write({
                    'import_state': action_state,
                    'import_message': 'success',
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': order.id,
                })
                self.env['acumatica.error.transaction']._handle_acumatica_error(origin, 'transfer_one_step')
                self.env.cr.execute('RELEASE SAVEPOINT import_transfer_one_step_doc')

            except Exception as e:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT import_transfer_one_step_doc')
                _logger.exception('Error import transfer one step %s', reference_nbr)
                tracked_lines = self.env['acumatica.transfer.one.step.product'].search([
                    ('header_id', '=', first.id),
                ])
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='transfer_one_step',
                    operation_type='internal',
                    origin=reference_nbr,
                    location=first.from_warehouse_code or False,
                    location_dest=first.to_warehouse_code or False,
                    scheduled_date=first.scheduled_date,
                    total_qty=first.total_qty,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=[{
                        'inventory_id': line.inventory_id or False,
                        'product_name': line.line_description or False,
                        'qty': self._parse_float(line.quantity),
                        'uom': line.uom_code or False,
                        'payload': line.read()[0] if line.exists() else {},
                    } for line in tracked_lines],
                )
                receipt_lines.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': str(e)[:200],
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': False,
                })
                error += len(receipt_lines)

        msg = (
            f'Import selesai: {created} transfer dibuat, {updated} transfer diupdate, '
            f'{skipped} transfer diskip, {error} line error.'
        )
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Transfer One Step',
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
        if self.odoo_picking_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'res_id': self.odoo_picking_id.id,
                'view_mode': 'form',
            }
        raise UserError('Belum diimport, belum ada transfer di Odoo.')

    def action_select_all(self):
        self.search([('import_state', '=', 'staged')]).write({'selected': True})

    def action_deselect_all(self):
        self.search([]).write({'selected': False})


class AcumaticaTransferOneStepProduct(models.Model):
    _name = 'acumatica.transfer.one.step.product'
    _description = 'Transfer One Step Product'

    # Relasi ke Header / Parent
    header_id = fields.Many2one(
        'acumatica.transfer.one.step.line', 
        string='Header Reference', 
        ondelete='cascade', 
        required=True
    )
    
    # Nomor Baris & Identitas Produk
    acumatica_header_id = fields.Char(string="Header ID")
    reference_nbr = fields.Char(string="Reference Number", index=True)

    line_nbr = fields.Integer(string='Line Number')
    inventory_id = fields.Char(string='Product / Inventory')
    
    # Deskripsi & Catatan
    line_description = fields.Char(string='Description')
    line_note = fields.Text(string='Line Note')
    line_note_id = fields.Char(string='Line Note ID')
    
    # Lokasi Asal & Tujuan
    from_location_code = fields.Char(string='From Location')
    to_location_code = fields.Char(string='To Location')
    so_order_nbr = fields.Char(string='SO Order Number')
    so_order_type = fields.Char(string='SO Order Type')
    so_shipment_nbr = fields.Char(string='SO Shipment Number')
    
    # Kuantitas & Satuan
    quantity = fields.Float(string='Quantity')
    uom_code = fields.Char(string='Unit of Measure')
    
