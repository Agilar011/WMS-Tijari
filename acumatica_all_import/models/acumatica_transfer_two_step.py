from odoo import models, fields, api
from odoo.exceptions import UserError

from dateutil import parser as dateutil_parser
import logging
import requests

_logger = logging.getLogger(__name__)

class AcumaticaTransferTwoStepLine(models.Model):
    _name = 'acumatica.transfer.two.step.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    line_ids = fields.One2many(
        'acumatica.transfer.two.step.line.product', 
        'header_id', 
        string="Detail Lines"
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
        if line.to_warehouse_code:
            warehouse_code = line.to_warehouse_code or line.from_warehouse_code
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
    
    def _do_import(self):
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        PickingType = self.env['stock.picking.type']

        created = 0
        updated = 0
        error = 0

        # proses per receipt number
        # print(f"self mapped: {self.mapped('reference_nbr')}")

    
        for reference_nbr in self.mapped('reference_nbr'):
            receipt_lines = self.filtered(
                lambda l: l.reference_nbr == reference_nbr
            )
            if not receipt_lines:
                continue

            first = receipt_lines[0]
            update_messages = []
            print(f"first: {first}")

            try:
                self.env.cr.execute('SAVEPOINT import_transfer_two_step_doc')
                transfer_service = self.env['acumatica.internal.transfer.service']
                try:
                    transfer_info = transfer_service.classify_transfer_out_to_virtual(
                        first.from_warehouse_code,
                        first.to_warehouse_code,
                        'FromWarehouseID',
                        'ToWarehouseID',
                    )
                except UserError as mapping_error:
                    error_text = str(mapping_error).lower()
                    user_message = (
                        f"Warehouse tujuan {first.to_warehouse_code or '-'} belum memiliki mapping lokasi aktif di WMS. Periksa mapping warehouse tujuan."
                        if 'towarehouseid' in error_text else
                        f"Warehouse sumber {first.from_warehouse_code or '-'} belum memiliki mapping lokasi aktif di WMS. Periksa mapping warehouse sumber."
                    )
                    raise UserError(f"{mapping_error}\nUSER_MESSAGE:{user_message}")
                if transfer_info['status'] == 'skip':
                    receipt_lines.write({
                        'import_state': 'updated',
                        'import_message': 'success',
                        'odoo_picking_id': False,
                        'odoo_internal_transfer_order_id': False,
                    })
                    self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=first.reference_nbr or False)
                    updated += len(receipt_lines)
                    self.env.cr.execute('RELEASE SAVEPOINT import_transfer_two_step_doc')
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type='import', webhook_name='Transfer Two Step',
                        transaction_name=first.reference_nbr or str(first.id),
                        event_type='update',
                        message='Transfer tidak memerlukan pembuatan dokumen baru karena lokasi sumber dan tujuan sudah sesuai.',
                    )
                    continue

                existing_order = self.env['internal.transfer.order'].search([('external_ref', '=', first.reference_nbr)], limit=1)
                previous_moves = {}
                if existing_order:
                    update_messages.extend(self.env['acumatica.webhook.error.service']._get_user_facing_field_changes(
                        existing_order,
                        {'location_id': transfer_info['source_location'].id,
                         'location_dest_id': transfer_info['destination_location'].id,
                         'schedule_date': self._parse_dt(first.scheduled_date) or fields.Datetime.now(),
                         'note': first.note or False, 'description': first.description or False,
                         'adt_transaction_type': 'Transfer 2 Step', 'document_only': bool(first.document_only)},
                        field_names={'location_id', 'location_dest_id', 'schedule_date', 'note', 'description', 'adt_transaction_type', 'document_only'},
                        prefix='Header',
                    ))
                    for old_move in existing_order.move_ids:
                        key = str(old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.id)
                        previous_moves[key] = {'label': old_move.adt_line_nbr or old_move.adt_inventory_id or old_move.name, 'product': old_move.product_id.display_name or '—', 'qty': old_move.product_uom_qty, 'uom': old_move.product_uom.display_name or '—', 'destination': old_move.location_dest_id.display_name or '—', 'name': old_move.name or '—'}

                order, action_state = transfer_service.prepare_order(
                    first.reference_nbr,
                    transfer_info['source_location'],
                    transfer_info['destination_location'],
                    transfer_info['transaction_type'],
                    self._parse_dt(first.scheduled_date),
                    first.note or False,
                    description=first.description or False,
                    transfer_type='transfer_out',
                    adt_transaction_type='Transfer 2 Step',
                    document_only=first.document_only,
                )

                to_create_move = self.env['acumatica.transfer.two.step.line.product'].search([('header_id', '=', first.id)])
                for line in to_create_move:
                    product = self._find_product(line)
                    if not product:
                        raise UserError(f'Product tidak ditemukan untuk InventoryID: {line.adt_InventoryID or "-"}')
                    uom = self._find_uom(line, product)
                    qty = self._parse_float(line.adt_Quantity)
                    created_move = transfer_service.create_order_move(order, product, qty, uom, line.adt_Description or product.display_name, line.adt_Description or False, {
                        'adt_line_nbr': line.adt_LineNumber or False,
                        'adt_line_note': line.adt_note or False,
                        'adt_inventory_id': line.adt_InventoryID or False,
                        'adt_uom_code': line.adt_UOM or False,
                        'adt_line_description': line.adt_Description or False,
                        'adt_to_location_code': line.adt_ToLocationID or False,
                        'adt_from_location_code': line.adt_FromLocationID or False,
                        'adt_transfer_order_number': first.reference_nbr,
                        'adt_transfer_order_line_number': line.adt_LineNumber or False,
                        'adt_transfer_order_type': first.transfer_type or False,
                        'adt_quantity': qty,
                        'adt_type': 'Transfer 2 Step',
                    })
                    if action_state == 'updated':
                        line_key = str(line.adt_LineNumber or line.adt_InventoryID or created_move.id)
                        old = previous_moves.pop(line_key, None)
                        label = line.adt_LineNumber or line.adt_InventoryID or '?'
                        current = {'Produk': product.display_name or '—', 'Jumlah': f'{qty:g}', 'Satuan': uom.display_name if uom else '—', 'Lokasi tujuan': created_move.location_dest_id.display_name or '—', 'Deskripsi': created_move.name or '—'}
                        if old:
                            previous = {'Produk': old['product'], 'Jumlah': f"{old['qty']:g}", 'Satuan': old['uom'], 'Lokasi tujuan': old['destination'], 'Deskripsi': old['name']}
                            changes = [f'{name}: {previous[name]} → {value}' for name, value in current.items() if previous[name] != value]
                            if changes:
                                update_messages.append(f"• Baris {label}: " + '; '.join(changes))
                        else:
                            update_messages.append(f"• Baris {label}: {product.display_name}, jumlah {qty:g} {uom.display_name if uom else ''} ditambahkan")

                if action_state == 'updated':
                    update_messages.extend(f"• Baris {old['label']}: {old['product']} dihapus" for old in previous_moves.values())

                transfer_service.set_order_ready(order)
                receipt_lines.write({
                    'import_state': action_state,
                    'import_message': 'success',
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': order.id,
                })
                self.env['acumatica.error.transaction']._handle_acumatica_error(first.reference_nbr, 'transfer_two_step')
                if action_state == 'created':
                    created += 1
                else:
                    updated += 1
                self.env.cr.execute('RELEASE SAVEPOINT import_transfer_two_step_doc')
                if action_state == 'updated':
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type='import', webhook_name='Transfer Two Step',
                        transaction_name=first.reference_nbr or str(first.id),
                        event_type='update',
                        message='\n'.join(update_messages) or 'Transfer berhasil disinkronkan; tidak ada field yang berubah.',
                    )
                continue

                # vendor = self._find_vendor(first)
                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(
                        f'Warehouse tidak ditemukan untuk code: {first.to_warehouse_code or first.from_warehouse_code or "-"}'
                    )

                picking_type = PickingType.search([
                    ('warehouse_id', '=', warehouse.id),
                    ('code', '=', 'internal'), ('name', '=', 'Internal Transfers' )
                ], limit=1) or PickingType.search([
                    ('code', '=', 'internal'), ('name', '=', 'Internal Transfers' )
                ], limit=1)

                print(picking_type.mapped('name'))

                if not picking_type:
                    raise UserError('Picking type internal tidak ditemukan.')

                dest_location = self._find_location_dest(first.to_warehouse_code, warehouse)
                if not dest_location:
                    raise UserError(
                        f'Location tujuan tidak ditemukan untuk code: '
                        f'{first.location_dest_code or first.header_location_code or "-"}'
                    )

                origin = first.reference_nbr or False

                vals = {
                    # 'partner_id': vendor.id if vendor else False,
                    'picking_type_id': picking_type.id,
                    'location_id': (
                        picking_type.default_location_src_id.id
                        if picking_type.default_location_src_id
                        else self.env.ref('stock.stock_location_suppliers').id
                    ),
                    # 'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'origin': origin,
                    'note': first.note or False,
                    # reference_nbr = 
                    # trans_type = 

                    # field custom, kalau ada di model
                    'adt_is_hold': str(first.is_hold or '').lower() in ('true', '1', 'yes'),
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_float(first.total_qty),
                    'adt_type': first.transfer_type or False,
                    'adt_to_warehouse_code': first.to_warehouse_code or False,
                    'adt_from_warehouse_code': first.from_warehouse_code or False,
                    'adt_description': first.description or False,
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
                        self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=first.reference_nbr or False)
                        created += 1

                else:
                    picking = Picking.sudo().create(vals)
                    print(f"Picking : {picking} Created")
                    # raise UserError("Checkpoint")
                    action_state = 'created'
                    created += 1

                if action_state == 'error':
                    break

                to_create_move = self.env['acumatica.transfer.two.step.line.product'].search([
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
                        line_dest = self._find_location_dest(line.adt_ToLocationID, warehouse) or dest_location
                        qty = self._parse_float(line.adt_Quantity)

                        print(f"Convert : {line.adt_Quantity} to : {qty}")
                        # raise UserError('Checkpoint')

                        # dedup move
                        move_domain = [('picking_id', '=', picking.id)]
                        if 'adt_line_external_id' in Move._fields and line.acumatica_header_id:
                            move_domain.append(('adt_line_external_id', '=', line.acumatica_header_id))
                        else:
                            move_domain += [
                                ('product_id', '=', product.id),
                                ('product_uom_qty', '=', qty),
                            ]

                        # existing_move = Move.search(move_domain, limit=1)
                        # if existing_move:
                        #     first.write({
                        #         'import_state': action_state,
                        #         'import_message': f'Skip duplicate: {picking.name}',
                        #         'odoo_picking_id': picking.id,
                        #     })
                        #     continue

                        move_vals = {
                            'name': line.adt_Description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': line_dest.id,
                            # 'description_picking': product.name or False,

                            'adt_line_nbr': line.adt_LineNumber or False,
                            'adt_line_note': line.adt_note or False,
                            'adt_inventory_id': line.adt_InventoryID or False,
                            'adt_uom_code': line.adt_UOM or False,
                            'adt_line_description': line.adt_Description or False,
                            'adt_to_location_code': line.adt_ToLocationID or False,
                            'adt_from_location_code': line.adt_FromLocationID or False,
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
                            'import_message': 'success',
                            'odoo_picking_id': picking.id,
                        })

                    except Exception as line_e:
                        _logger.exception("Error import line %s", line.id)
                        raise UserError(str(line_e))
                        first.write({
                            'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                            'import_message': str(line_e)[:200],
                            'odoo_picking_id': picking.id if picking else False,
                        })
                        error += 1

                if first.document_only:
                    picking.action_validate_document_only_import(force=True)

            except Exception as e:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT import_transfer_two_step_doc')
                _logger.exception("Error import receipt %s", reference_nbr)
                raw_error = str(e)
                error_text = raw_error.lower()
                user_message = False
                if 'user_message:' in error_text:
                    user_message = raw_error.split('USER_MESSAGE:', 1)[-1].strip()
                elif 'operation type' in error_text or 'picking type' in error_text:
                    user_message = f"Operation Type untuk Transfer Two Step {reference_nbr or '-'} belum tersedia. Minta admin memeriksa pengaturan tipe transfer di WMS."
                elif 'tidak bisa diupdate' in error_text or 'sudah di state' in error_text or 'already processed' in error_text:
                    user_message = f"Transfer Two Step {reference_nbr or '-'} tidak dapat diperbarui karena proses sebelumnya sudah berjalan. Periksa status transfer terkait di WMS."
                elif 'product tidak ditemukan' in error_text or 'product with inventoryid' in error_text:
                    user_message = f"Produk pada Transfer Two Step {reference_nbr or '-'} belum terdaftar. Periksa master produk di WMS."
                elif 'operation line belum diisi' in error_text or 'no lines to validate' in error_text:
                    user_message = f"Transfer Two Step {reference_nbr or '-'} belum bisa diproses karena belum memiliki baris produk. Lengkapi detail transaksi."
                error_message = raw_error.split('\nUSER_MESSAGE:', 1)[0]
                tracked_lines = self.env['acumatica.transfer.two.step.line.product'].search([
                    ('header_id', '=', first.id),
                ])
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='transfer_two_step',
                    operation_type='internal',
                    origin=reference_nbr,
                    location=first.from_warehouse_code or False,
                    location_dest=first.to_warehouse_code or False,
                    scheduled_date=first.scheduled_date,
                    total_qty=first.total_qty,
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
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': str(e)[:200],
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': False,
                })
                error += len(receipt_lines)
                if user_message:
                    self.env['acumatica.webhook.error.service'].send_user_error(
                        webhook_type='import', webhook_name='Transfer Two Step',
                        transaction_name=reference_nbr or str(first.id),
                        event_type='error', message=user_message,
                    )
                else:
                    self.env['acumatica.webhook.error.service'].send_error(
                        webhook_type='import', webhook_name='Transfer Two Step',
                        error=raw_error, error_type='unexpected',
                    )

        msg = f'Import selesai: {created} receipt dibuat, {updated} receipt diupdate, {error} line error.'
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Inventory Receipt',
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


class AcumaticaTransferTwoStepLineProduct(models.Model):
    _name = 'acumatica.transfer.two.step.line.product'
    _description = 'Data Transfer Order dari Acumatica'
    _order = 'header_id asc, id asc'

    header_id = fields.Many2one(
        'acumatica.transfer.two.step.line', 
        string="Header Reference", 
        ondelete='cascade', 
        index=True
    )

    acumatica_header_id = fields.Char(string="Acumatica Header ID")
    reference_nbr = fields.Char(string="Reference Number", index=True)
    adt_rowNumber = fields.Char(string="Acumatica rowNumber")
    adt_note = fields.Char(string="Acumatica note")
    adt_Description = fields.Char(string="Acumatica Description")
    adt_FromLocationID = fields.Char(string="Acumatica FromLocationID")
    adt_InventoryID = fields.Char(string="Acumatica InventoryID")
    adt_LineNumber = fields.Char(string="Acumatica LineNumber")
    adt_NoteID = fields.Char(string="Acumatica NoteID")
    adt_LineNoteID = fields.Char(string="Acumatica LineNoteID")
    adt_Quantity = fields.Char(string="Acumatica Quantity")
    adt_SOOrderNbr = fields.Char(string="Acumatica SOOrderNbr")
    adt_SOOrderType = fields.Char(string="Acumatica SOOrderType")
    adt_SOShipmentNbr = fields.Char(string="Acumatica SOShipmentNbr")
    adt_ToLocationID = fields.Char(string="Acumatica ToLocationID")
    adt_UOM = fields.Char(string="Acumatica UOM")

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], string='Status', default='staged', tracking=True)
    import_message = fields.Char(string='Generation Message', tracking=True)
    odoo_picking_id = fields.Many2one('stock.picking', string='Document Reference')
    selected = fields.Boolean(string='Pilih', default=True)

    config_id = fields.Many2one('acumatica.config', string='Konfigurasi', ondelete='set null')
    sync_date = fields.Datetime(string='Tanggal Sync')

    # exists_in_odoo = fields.Boolean(string='Sudah Ada di Odoo', compute='_compute_exists_in_odoo')
