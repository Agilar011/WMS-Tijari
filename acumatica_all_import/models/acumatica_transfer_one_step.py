from dateutil import parser as dateutil_parser
import logging
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)



class AcumaticaTransferOneStepLine(models.Model):
    _name = 'acumatica.transfer.one.step.line'
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    line_ids = fields.One2many(
        'acumatica.transfer.one.step.product', # Nama model child yang dituju
        'header_id',                  # Nama field Many2one di model child
        string='Transfer Lines'
    )

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
    document_only = fields.Boolean(string='Document Only', readonly=True)

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

    state = fields.Selection([
        ('draft', 'Siap'),
        ('fetched', 'Data Sudah Ditarik'),
        ('done', 'Selesai'),
    ], default='draft')

    import_message = fields.Char(string='Keterangan', readonly=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Receipt di Odoo', readonly=True)
    odoo_internal_transfer_order_id = fields.Many2one(
        'internal.transfer.order',
        string='Internal Transfer Order',
        readonly=True,
    )
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', readonly=True, ondelete='cascade')
    sync_date = fields.Datetime(string='Tanggal Sync', readonly=True)

    exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
    picking_type_id = fields.Many2one('stock.picking.type', string="Operation Type")

    @api.depends('reference_nbr')
    def _compute_exists_in_odoo(self):
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            rec.exists_in_odoo = bool(
                rec.reference_nbr
                and InternalTransferOrder.search_count([('external_ref', '=', rec.reference_nbr)])
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
                l.import_state in ['pending', 'error']
                or (
                    l.import_state in ['imported', 'updated']
                    and not l.odoo_picking_id
                    and not l.odoo_internal_transfer_order_id
                )
            )
        )
        if not lines:
            raise UserError('Tidak ada baris yang dipilih untuk diimport.')
        return lines._do_import()

    def action_import_this(self):
        self.ensure_one()
        return self._do_import()
    
    def _do_import(self):
        InternalTransferOrder = self.env['internal.transfer.order']
        Move = self.env['stock.move']

        imported = 0
        skipped = 0
        updated = 0
        error = 0

        for reference_nbr in self.mapped('reference_nbr'):
            receipt_lines = self.filtered(
                lambda l: l.reference_nbr == reference_nbr and l.import_state == 'pending'
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]

            try:
                origin = first.reference_nbr or False
                existing_order = InternalTransferOrder.search([
                    ('external_ref', '=', origin),
                ], limit=1)
                if existing_order:
                    if existing_order.state not in ('draft', 'cancel'):
                        raise UserError(
                            f'Transfer {reference_nbr} sudah ada di Odoo dengan state '
                            f'{existing_order.state}, tidak bisa diupdate.'
                        )
                    if existing_order.picking_ids:
                        raise UserError(
                            f'Transfer {reference_nbr} sudah memiliki picking, tidak bisa diupdate.'
                        )
                    existing_order.move_ids.unlink()
                    order = existing_order
                    action_state = 'updated'
                    updated += 1
                else:
                    order = False
                    action_state = 'imported'
                    imported += 1

                transfer_service = self.env['acumatica.internal.transfer.service']
                transfer_info = transfer_service.classify(
                    first.from_warehouse_code,
                    first.to_warehouse_code,
                    'FromWarehouseID',
                    'ToWarehouseID',
                )
                source_location = transfer_info['source_location']
                destination_location = transfer_info['destination_location']

                if transfer_info['status'] == 'skip':
                    receipt_lines.write({
                        'import_state': 'updated',
                        'import_message': transfer_info['message'],
                    })
                    skipped += len(receipt_lines)
                    continue

                if order:
                    order.write({
                        'transaction_type': transfer_info['transaction_type'],
                        'transfer_type': 'transfer_out',
                        'location_id': source_location.id,
                        'location_dest_id': destination_location.id,
                        'transit_location_id': transfer_service.get_or_create_transit_location().id,
                        'schedule_date': self._parse_dt(first.scheduled_date),
                        'validation_policy': 'validate_all',
                        'note': first.note or False,
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

                receipt_lines.write({
                    'import_state': action_state,
                    'import_message': f'{action_state.title()}: {order.name}',
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': order.id,
                })

            except Exception as e:
                _logger.exception('Error import transfer one step %s', reference_nbr)
                receipt_lines.write({
                    'import_state': 'error',
                    'import_message': str(e)[:200],
                })
                error += len(receipt_lines)

        msg = (
            f'Import selesai: {imported} transfer dibuat, {updated} transfer diupdate, '
            f'{skipped} transfer diskip, {error} line error.'
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Import Transfer One Step',
                'message': msg,
                'type': 'success' if error == 0 else 'warning',
                'sticky': True,
            }
        }

    def action_reset_pending(self):
        self.filtered(lambda l: l.import_state == 'error').write({'import_state': 'pending', 'import_message': False})

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
        self.search([('import_state', '=', 'pending')]).write({'selected': True})

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

    line_nbr = fields.Integer(string='Line Number')
    inventory_id = fields.Char(string='Product / Inventory')
    
    # Deskripsi & Catatan
    line_description = fields.Char(string='Description')
    line_note = fields.Text(string='Line Note')
    
    # Lokasi Asal & Tujuan
    from_location_code = fields.Char(string='From Location')
    to_location_code = fields.Char(string='To Location')
    
    # Kuantitas & Satuan
    quantity = fields.Float(string='Quantity')
    uom_code = fields.Char(string='Unit of Measure')
    
