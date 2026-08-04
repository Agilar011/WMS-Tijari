import random

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AcumaticaTempReceiptGeneratorWizard(models.TransientModel):
    _name = 'acumatica.temp.receipt.generator.wizard'
    _description = 'Temporary WH33 Receipt Staging Generator'

    MARKER = 'TEMP GENERATED WH33 - safe to delete'
    INVENTORY_RECEIPT_TYPES = (
        ('TPDO', 'Toko Pegang DO'),
        ('TRIN', 'Transfer In'),
        ('CHGI', 'Change Item'),
        ('INVR', 'Inventory Receive'),
        ('CHGD', 'Change Item Discontinue'),
    )
    CUSTOMER_REQUIRED_TYPES = {'Toko Pegang DO', 'Change Item', 'Change Item Discontinue'}

    generate_type = fields.Selection([
        ('po_receipt', 'PO Receipt'),
        ('inventory_receipt', 'Inventory Receipt'),
        ('so_return', 'SO Return'),
        ('po_return', 'PO Return'),
    ], string='Generate Type', default='po_receipt', required=True)
    document_only = fields.Boolean(string='Document Only')
    random_data = fields.Boolean(string='Random Data', default=True)
    receipt_count = fields.Integer(string='Jumlah Receipt per Type', default=1, required=True)
    lines_per_receipt = fields.Integer(string='Jumlah Line per Receipt', default=1, required=True)
    receipt_prefix = fields.Char(string='Prefix Receipt', default='TMP-R26', required=True)
    receipt_date = fields.Date(string='Tanggal Receipt', default=fields.Date.context_today, required=True)
    line_qty = fields.Float(string='Qty per Line', default=1.0, required=True)
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        domain=[('is_company', '=', True)],
        help='Kosongkan untuk memakai vendor valid pertama dari master.',
    )
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        domain=[('is_company', '=', True)],
        help='Kosongkan untuk memakai customer valid pertama dari master.',
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Products',
        domain=[('default_code', '!=', False)],
        help='Kosongkan untuk memakai product valid pertama dari master.',
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='UOM',
        help='Kosongkan untuk memakai UOM product.',
    )
    location_code = fields.Char(string='Warehouse/Location Code', default='WH33-DCJKT', required=True)
    transfer_source_location_code = fields.Char(
        string='Transfer In Source Code',
        help='Kosongkan untuk memakai mapping Acumatica aktif selain lokasi tujuan.',
    )
    generated_receipt_ids = fields.Many2many(
        'acumatica.receipt.line',
        'acum_temp_receipt_generated_rel',
        'wizard_id',
        'receipt_id',
        string='Generated PO Receipts',
        readonly=True,
    )
    generated_inventory_receipt_ids = fields.Many2many(
        'acumatica.inventory.recieved.line',
        'acum_temp_inv_receipt_generated_rel',
        'wizard_id',
        'inventory_receipt_id',
        string='Generated Inventory Receipts',
        readonly=True,
    )
    generated_shipment_ids = fields.Many2many(
        'acumatica.shipment.line',
        'acum_temp_so_return_generated_rel',
        'wizard_id',
        'shipment_id',
        string='Generated SO Returns',
        readonly=True,
    )
    generated_po_return_ids = fields.Many2many(
        'acumatica.issue.po.return.line',
        'acum_temp_po_return_generated_rel',
        'wizard_id',
        'po_return_id',
        string='Generated PO Returns',
        readonly=True,
    )

    @api.constrains('receipt_count', 'lines_per_receipt', 'line_qty')
    def _check_positive_values(self):
        for wizard in self:
            if wizard.receipt_count < 1:
                raise UserError(_('Jumlah Receipt harus minimal 1.'))
            if wizard.lines_per_receipt < 1:
                raise UserError(_('Jumlah Line per Receipt harus minimal 1.'))
            if wizard.line_qty <= 0:
                raise UserError(_('Qty per Line harus lebih besar dari 0.'))

    def _get_vendor(self):
        self.ensure_one()
        if self.vendor_id:
            return self.vendor_id

        Partner = self.env['res.partner'].sudo()
        vendor = Partner.search([
            ('is_company', '=', True),
            ('company_registry', '!=', False),
        ], order='id', limit=1)
        if not vendor:
            vendor = Partner.search([('is_company', '=', True)], order='id', limit=1)
        return vendor

    def _get_vendor_pool(self):
        self.ensure_one()
        if self.vendor_id:
            return self.vendor_id

        Partner = self.env['res.partner'].sudo()
        vendors = Partner.search([
            ('is_company', '=', True),
            ('company_registry', '!=', False),
        ], order='id', limit=50)
        if not vendors:
            vendors = Partner.search([('is_company', '=', True)], order='id', limit=50)
        return vendors

    def _get_po_return_vendor_pool(self):
        self.ensure_one()
        if self.vendor_id:
            return self.vendor_id

        Partner = self.env['res.partner'].sudo()
        vendors = Partner.search([
            ('is_company', '=', True),
            ('ref', '!=', False),
        ], order='id', limit=50)
        if not vendors:
            vendors = Partner.search([('is_company', '=', True)], order='id', limit=50)
        return vendors

    def _get_customer(self):
        self.ensure_one()
        if self.customer_id:
            return self.customer_id

        Partner = self.env['res.partner'].sudo()
        customer = Partner.search([
            ('is_company', '=', True),
            ('company_registry', '!=', False),
        ], order='id', limit=1)
        if not customer:
            customer = Partner.search([('is_company', '=', True)], order='id', limit=1)
        return customer

    def _get_customer_pool(self):
        self.ensure_one()
        if self.customer_id:
            return self.customer_id

        Partner = self.env['res.partner'].sudo()
        customers = Partner.search([
            ('is_company', '=', True),
            ('company_registry', '!=', False),
        ], order='id', limit=50)
        if not customers:
            customers = Partner.search([('is_company', '=', True)], order='id', limit=50)
        return customers

    def _get_products(self):
        self.ensure_one()
        products = self.product_ids
        if not products:
            products = self.env['product.product'].sudo().search([
                ('default_code', '!=', False),
            ], order='id', limit=self.lines_per_receipt)
        if len(products) < self.lines_per_receipt:
            fallback = self.env['product.product'].sudo().search([
                ('default_code', '!=', False),
                ('id', 'not in', products.ids),
            ], order='id', limit=self.lines_per_receipt - len(products))
            products |= fallback
        return products

    def _get_product_pool(self):
        self.ensure_one()
        if self.product_ids:
            return self.product_ids

        return self.env['product.product'].sudo().search([
            ('default_code', '!=', False),
        ], order='id', limit=max(self.lines_per_receipt, 50))

    def _pick_record(self, records, sequence=1):
        if not records:
            return records
        if self.random_data:
            return random.choice(records)
        return records[(sequence - 1) % len(records)]

    def _pick_products(self, products, sequence=1):
        if len(products) <= self.lines_per_receipt:
            return products
        if self.random_data:
            product_ids = random.sample(products.ids, self.lines_per_receipt)
            return self.env['product.product'].sudo().browse(product_ids)
        start = (sequence - 1) % len(products)
        ordered_ids = products.ids[start:] + products.ids[:start]
        return self.env['product.product'].sudo().browse(ordered_ids[:self.lines_per_receipt])

    def _line_quantity(self, line_index, receipt_index=1):
        self.ensure_one()
        if not self.random_data:
            return self.line_qty

        max_qty = int(self.line_qty) if self.line_qty >= 1 else 1
        return float(random.randint(1, max_qty))

    def _get_wh33_warehouse(self):
        return self.env['stock.warehouse'].sudo().search([('code', '=', 'WH33')], limit=1)

    def _get_acumatica_location(self, code=False, wh33_fallback=True):
        Location = self.env['stock.location.acumatica'].sudo()
        location = Location.browse()
        if code:
            location = Location.search([('code', '=', code)], limit=1)
        if not location and wh33_fallback:
            location = Location.search([
                ('building', '=', 'WH33'),
                ('odoo_location_id', '!=', False),
            ], order='id', limit=1)
        return location

    def _get_transfer_source_location(self, destination_location):
        self.ensure_one()
        location = self._get_acumatica_location(self.transfer_source_location_code, wh33_fallback=False)
        if location and location.odoo_location_id:
            return location

        domain = [('odoo_location_id', '!=', False)]
        if destination_location:
            domain.append(('id', '!=', destination_location.id))
        source = self.env['stock.location.acumatica'].sudo().search(
            domain + [('building', '!=', 'WH33')],
            order='id',
            limit=1,
        )
        if not source:
            source = self.env['stock.location.acumatica'].sudo().search(domain, order='id', limit=1)
        return source

    def _get_po_picking_type(self, warehouse):
        PickingType = self.env['stock.picking.type'].sudo()
        if self.document_only:
            document_type = PickingType.resolve_document_only_picking_type(
                api_acumatica='po_receipt',
                document_only=True,
                warehouse_code='WH33',
                required=False,
            )
            if document_type:
                return document_type

        return PickingType.search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming'),
            ('is_default_api', '=', True),
        ], limit=1)

    def _get_incoming_picking_type(self, warehouse):
        PickingType = self.env['stock.picking.type'].sudo()
        if self.document_only:
            document_type = PickingType.resolve_document_only_picking_type(
                target_operation_type='direct_receipt',
                document_only=True,
                warehouse_code='WH33',
                required=False,
            )
            if document_type:
                return document_type

        return PickingType.search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming'),
            ('is_default_api', '=', True),
        ], limit=1)

    def _get_po_return_picking_type(self, warehouse, location_code):
        PickingType = self.env['stock.picking.type'].sudo()
        if self.document_only:
            document_type = PickingType.resolve_document_only_picking_type(
                api_acumatica='issue_po_return',
                document_only=True,
                warehouse_code=location_code,
                required=False,
            )
            if document_type:
                return document_type

        return PickingType.search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'internal'),
            ('is_default_api', '=', True),
        ], limit=1)

    def _get_inventory_config(self):
        Config = self.env['acumatica.config'].sudo()
        config = Config.search([
            ('active', '=', True),
            ('config_type', '=', 'inventory_received'),
            ('is_default', '=', True),
        ], limit=1)
        if not config:
            config = Config.search([
                ('active', '=', True),
                ('config_type', '=', 'inventory_received'),
            ], limit=1)
        return config

    @staticmethod
    def _normalize_transfer_type(value):
        return (value or '').strip().lower().replace('-', '_').replace(' ', '_')

    def _get_inventory_picking_type(self, transfer_type, warehouse, location_code, config=False):
        PickingType = self.env['stock.picking.type'].sudo()
        type_key = self._normalize_transfer_type(transfer_type)
        if self.document_only and type_key != 'transfer_in':
            document_type = PickingType.resolve_document_only_picking_type(
                api_acumatica='inventory_received',
                document_only=True,
                warehouse_code='WH33',
                required=False,
            )
            if document_type:
                return document_type

        if config:
            picking_type = config._resolve_inventory_receive_picking_type(
                transfer_type=transfer_type,
                warehouse_code=location_code,
                document_only=self.document_only,
            )
            if picking_type:
                return picking_type

        return PickingType.search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'internal' if type_key == 'transfer_in' else 'incoming'),
            ('is_default_api', '=', True),
        ], limit=1)

    def _validate_common_master_data(self):
        self.ensure_one()
        errors = []
        products = self._get_product_pool()
        warehouse = self._get_wh33_warehouse()
        destination_location = self._get_acumatica_location(self.location_code)

        if len(products) < self.lines_per_receipt:
            errors.append(_('Product dengan default_code tidak cukup untuk jumlah line yang diminta.'))
        else:
            missing_uom = products.filtered(lambda product: not (self.uom_id or product.uom_id))
            if missing_uom:
                errors.append(_('Ada product tanpa UOM: %s') % ', '.join(missing_uom.mapped('display_name')))

        if self.uom_id and not self.uom_id.exists():
            errors.append(_('UOM pilihan tidak valid.'))
        if not warehouse:
            errors.append(_('Warehouse WH33 tidak ditemukan.'))
        if not destination_location:
            errors.append(_('Location Acumatica %s tidak ditemukan, dan tidak ada fallback WH33 valid.') % self.location_code)
        elif not destination_location.odoo_location_id:
            errors.append(_('Location Acumatica %s belum punya Odoo Location.') % destination_location.code)

        if errors:
            raise UserError('\n'.join(errors))
        return products, warehouse, destination_location

    def _validate_po_master_data(self):
        errors = []
        products, warehouse, location = self._validate_common_master_data()
        vendor = self._get_vendor()
        picking_type = self._get_po_picking_type(warehouse) if warehouse else self.env['stock.picking.type'].browse()

        if not vendor:
            errors.append(_('Vendor master tidak ditemukan. Isi vendor atau buat vendor company terlebih dahulu.'))
        elif not (vendor.company_registry or vendor.name):
            errors.append(_('Vendor %s tidak punya company registry atau nama valid.') % vendor.display_name)
        if not picking_type:
            errors.append(_('Operation Type PO Receipt untuk WH33 tidak ditemukan.'))

        if errors:
            raise UserError('\n'.join(errors))
        vendors = self._get_vendor_pool()
        if not vendors:
            errors.append(_('Vendor master tidak ditemukan. Isi vendor atau buat vendor company terlebih dahulu.'))
        elif not all(vendor.company_registry or vendor.name for vendor in vendors):
            errors.append(_('Ada vendor tanpa company registry atau nama valid.'))

        if errors:
            raise UserError('\n'.join(errors))
        return vendors, products, warehouse, location, picking_type

    def _validate_inventory_master_data(self):
        errors = []
        products, warehouse, location = self._validate_common_master_data()
        customers = self._get_customer_pool()
        source_location = self._get_transfer_source_location(location)
        config = self._get_inventory_config()
        picking_types = {}

        if not customers:
            errors.append(_('Customer master tidak ditemukan untuk Toko Pegang DO / Change Item.'))
        elif not all(customer.company_registry or customer.name for customer in customers):
            errors.append(_('Ada customer tanpa company registry atau nama valid.'))

        if not source_location:
            errors.append(_('Source location untuk Transfer In tidak ditemukan.'))
        elif not source_location.odoo_location_id:
            errors.append(_('Source location %s belum punya Odoo Location.') % source_location.code)

        for _code, transfer_type in self.INVENTORY_RECEIPT_TYPES:
            picking_type = self._get_inventory_picking_type(
                transfer_type,
                warehouse,
                location.code if location else self.location_code,
                config=config,
            ) if warehouse else self.env['stock.picking.type'].browse()
            picking_types[transfer_type] = picking_type
            if not picking_type:
                errors.append(_('Operation Type untuk Inventory Receipt type %s tidak ditemukan.') % transfer_type)

        if errors:
            raise UserError('\n'.join(errors))
        return customers, products, warehouse, location, source_location, config, picking_types

    def _validate_so_return_master_data(self):
        errors = []
        products, warehouse, location = self._validate_common_master_data()
        customers = self._get_customer_pool()
        picking_type = self._get_incoming_picking_type(warehouse) if warehouse else self.env['stock.picking.type'].browse()

        if not customers:
            errors.append(_('Customer master tidak ditemukan untuk SO Return.'))
        elif not all(customer.name for customer in customers):
            errors.append(_('Ada customer tanpa nama valid.'))
        if not picking_type:
            errors.append(_('Operation Type SO Return untuk WH33 tidak ditemukan.'))

        if errors:
            raise UserError('\n'.join(errors))
        return customers, products, warehouse, location, picking_type

    def _validate_po_return_master_data(self):
        errors = []
        products, warehouse, location = self._validate_common_master_data()
        vendors = self._get_po_return_vendor_pool()
        picking_type = self._get_po_return_picking_type(
            warehouse,
            location.code if location else self.location_code,
        ) if warehouse else self.env['stock.picking.type'].browse()

        if not vendors:
            errors.append(_('Vendor master tidak ditemukan untuk PO Return.'))
        elif not all(vendor.ref or vendor.name for vendor in vendors):
            errors.append(_('Ada vendor tanpa ref atau nama valid.'))
        if not picking_type:
            errors.append(_('Operation Type PO Return untuk WH33 tidak ditemukan.'))

        if errors:
            raise UserError('\n'.join(errors))
        return vendors, products, warehouse, location, picking_type

    def _receipt_number(self, sequence):
        self.ensure_one()
        prefix = (self.receipt_prefix or 'TMP-R26').strip()
        return '%s-%04d' % (prefix, sequence)

    def _inventory_reference_number(self, type_code, sequence):
        self.ensure_one()
        prefix = (self.receipt_prefix or 'TMP-R26').strip()
        return '%s-%s-%04d' % (prefix, type_code, sequence)

    def _shipment_number(self, sequence):
        self.ensure_one()
        prefix = (self.receipt_prefix or 'TMP-R26').strip()
        return '%s-SOR-%04d' % (prefix, sequence)

    def _po_return_number(self, sequence):
        self.ensure_one()
        prefix = (self.receipt_prefix or 'TMP-R26').strip()
        return '%s-POR-%04d' % (prefix, sequence)

    def _external_id(self, receipt_nbr):
        return 'TEMP-%s' % receipt_nbr

    def _post_period(self):
        self.ensure_one()
        return self.receipt_date.strftime('%m%Y')

    def _scheduled_date(self):
        self.ensure_one()
        return fields.Date.to_string(self.receipt_date)

    def _line_total_qty(self):
        self.ensure_one()
        return self.line_qty * self.lines_per_receipt

    def action_generate_receipts(self):
        self.ensure_one()
        if self.generate_type == 'inventory_receipt':
            return self._generate_inventory_receipts()
        if self.generate_type == 'so_return':
            return self._generate_so_returns()
        if self.generate_type == 'po_return':
            return self._generate_po_returns()
        return self._generate_po_receipts()

    def _generate_po_receipts(self):
        self.ensure_one()
        vendors, products, warehouse, location, picking_type = self._validate_po_master_data()
        Receipt = self.env['acumatica.receipt.line'].sudo()
        ProductLine = self.env['acumatica.receipt.product.line'].sudo()
        Picking = self.env['stock.picking'].sudo()
        sync_date = fields.Datetime.now()
        generated = Receipt.browse()
        scheduled_date = self._scheduled_date()
        location_code = location.code or self.location_code

        for receipt_index in range(1, self.receipt_count + 1):
            receipt_nbr = self._receipt_number(receipt_index)
            vendor = self._pick_record(vendors, receipt_index)
            receipt_products = self._pick_products(products, receipt_index)
            line_quantities = [
                self._line_quantity(line_index, receipt_index)
                for line_index in range(1, len(receipt_products) + 1)
            ]
            line_total_qty = sum(line_quantities)
            existing_picking = Picking.search([('origin', '=', receipt_nbr)], limit=1)
            header_vals = {
                'external_id': self._external_id(receipt_nbr),
                'row_number': receipt_index,
                'note': self.MARKER,
                'branch_warehouse': 'MAIN',
                'building_code': warehouse.code,
                'actual_qty': str(line_total_qty),
                'scheduled_date': scheduled_date,
                'is_hold': 'True',
                'inventory_ref': False,
                'acumatica_write_date': fields.Datetime.to_string(sync_date),
                'header_location_code': 'MAIN',
                'post_period': self._post_period(),
                'receipt_nbr': receipt_nbr,
                'document_only': self.document_only,
                'status': 'On Hold',
                'total_qty': str(line_total_qty),
                'receipt_type': 'Receipt',
                'vendor_code': vendor.company_registry or vendor.name,
                'vendor_name': vendor.name,
                'partner_ref': 'TEMP',
                'warehouse_code': location_code,
                'picking_type_id': picking_type.id,
                'odoo_picking_id': existing_picking.id if existing_picking else False,
                'import_state': 'pending',
                'import_message': '%s: Sudah ada -> akan diupdate' % receipt_nbr if existing_picking else '',
                'selected': True,
                'sync_date': sync_date,
            }
            receipt = Receipt.search([('receipt_nbr', '=', receipt_nbr)], limit=1)
            if receipt:
                receipt.write(header_vals)
            else:
                receipt = Receipt.create(header_vals)

            ProductLine.search([('receipt_line_id', '=', receipt.id)]).unlink()
            ProductLine.create(self._po_product_line_values(receipt, receipt_products, location_code, line_quantities))
            generated |= receipt

        self.generated_receipt_ids = [(6, 0, generated.ids)]
        self.generated_inventory_receipt_ids = [(5, 0, 0)]
        self.generated_shipment_ids = [(5, 0, 0)]
        self.generated_po_return_ids = [(5, 0, 0)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated WH33 PO Receipt Staging'),
            'res_model': 'acumatica.receipt.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', generated.ids)],
            'context': {'create': False},
        }

    def _po_product_line_values(self, receipt, products, location_code, line_quantities):
        line_vals = []
        for line_index, product in enumerate(products, start=1):
            uom = self.uom_id or product.uom_id
            qty = line_quantities[line_index - 1]
            line_vals.append({
                'header_external_id': receipt.external_id,
                'receipt_line_id': receipt.id,
                'receipt_nbr': receipt.receipt_nbr,
                'line_external_id': '%s-LINE-%s' % (receipt.external_id, line_index),
                'line_nbr': str(line_index),
                'description': product.display_name,
                'transaction_description': product.display_name,
                'inventory_id': product.default_code,
                'line_type': 'Goods for IN',
                'location_dest_code': 'FG',
                'open_qty': '0',
                'order_qty': str(qty),
                'po_line_number': str(line_index),
                'po_number': receipt.receipt_nbr,
                'po_type': 'Normal',
                'po_receipt_line_number': str(line_index),
                'po_receipt_number': receipt.receipt_nbr,
                'product_uom_qty': str(qty),
                'uom_code': uom.name,
                'warehouse_dest_code': location_code,
                'line_note': self.MARKER,
            })
        return line_vals

    def _generate_inventory_receipts(self):
        self.ensure_one()
        customers, products, warehouse, location, source_location, config, picking_types = self._validate_inventory_master_data()
        Inventory = self.env['acumatica.inventory.recieved.line'].sudo()
        ProductLine = self.env['acumatica.inventory.recieved.product.line'].sudo()
        Picking = self.env['stock.picking'].sudo()
        InternalTransferOrder = self.env['internal.transfer.order'].sudo()
        sync_date = fields.Datetime.now()
        generated = Inventory.browse()
        scheduled_date = self._scheduled_date()
        destination_code = location.code or self.location_code
        source_code = source_location.code if source_location else destination_code

        row_number = 0
        for type_code, transfer_type in self.INVENTORY_RECEIPT_TYPES:
            for receipt_index in range(1, self.receipt_count + 1):
                row_number += 1
                reference_nbr = self._inventory_reference_number(type_code, receipt_index)
                customer = self._pick_record(customers, row_number)
                receipt_products = self._pick_products(products, row_number)
                line_quantities = [
                    self._line_quantity(line_index, row_number)
                    for line_index in range(1, len(receipt_products) + 1)
                ]
                line_total_qty = sum(line_quantities)
                existing_picking = Picking.search([('origin', '=', reference_nbr)], limit=1)
                existing_order = InternalTransferOrder.search([('external_ref', '=', reference_nbr)], limit=1)
                is_transfer_in = self._normalize_transfer_type(transfer_type) == 'transfer_in'
                needs_customer = transfer_type in self.CUSTOMER_REQUIRED_TYPES
                warehouse_code = source_code if is_transfer_in else destination_code
                warehouse_dest_code = destination_code
                header_vals = {
                    'row_number': row_number,
                    'external_id': self._external_id(reference_nbr),
                    'reference_nbr': reference_nbr,
                    'scheduled_date': scheduled_date,
                    'description': 'Temporary WH33 %s' % transfer_type,
                    'branch_warehouse': warehouse.code,
                    'actual_qty': str(line_total_qty),
                    'acumatica_write_date': fields.Datetime.to_string(sync_date),
                    'post_period': self._post_period(),
                    'status': 'Balanced',
                    'total_qty': str(line_total_qty),
                    'warehouse_code': warehouse_code,
                    'warehouse_dest_code': warehouse_dest_code,
                    'transfer_type': transfer_type,
                    'note': self.MARKER,
                    'external_ref': 'EXT-%s' % reference_nbr,
                    'document_only': self.document_only,
                    'customer_code': (customer.company_registry or customer.name) if needs_customer else False,
                    'shipment_nbr': 'SHP-%s' % reference_nbr if is_transfer_in else False,
                    'transfer_nbr': 'TO-%s' % reference_nbr if is_transfer_in else False,
                    'location_code': destination_code,
                    'change_item_ref_nbr': 'CI-%s' % reference_nbr if transfer_type in ('Change Item', 'Change Item Discontinue') else False,
                    'picking_type_id': picking_types[transfer_type].id,
                    'config_id': config.id if config else False,
                    'odoo_picking_id': existing_picking.id if existing_picking else False,
                    'odoo_internal_transfer_order_id': existing_order.id if existing_order else False,
                    'import_state': 'pending',
                    'import_message': '%s: Sudah ada -> akan diupdate' % reference_nbr if existing_picking or existing_order else '',
                    'selected': True,
                    'sync_date': sync_date,
                }
                receipt = Inventory.search([('reference_nbr', '=', reference_nbr)], limit=1)
                if receipt:
                    receipt.write(header_vals)
                else:
                    receipt = Inventory.create(header_vals)

                ProductLine.search([('inventory_line_id', '=', receipt.id)]).unlink()
                ProductLine.create(self._inventory_product_line_values(receipt, receipt_products, destination_code, line_quantities))
                generated |= receipt

        self.generated_inventory_receipt_ids = [(6, 0, generated.ids)]
        self.generated_receipt_ids = [(5, 0, 0)]
        self.generated_shipment_ids = [(5, 0, 0)]
        self.generated_po_return_ids = [(5, 0, 0)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated WH33 Inventory Receipt Staging'),
            'res_model': 'acumatica.inventory.recieved.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', generated.ids)],
            'context': {'create': False},
        }

    def _inventory_product_line_values(self, receipt, products, destination_code, line_quantities):
        line_vals = []
        for line_index, product in enumerate(products, start=1):
            uom = self.uom_id or product.uom_id
            qty = line_quantities[line_index - 1]
            line_vals.append({
                'header_external_id': receipt.external_id,
                'inventory_line_id': receipt.id,
                'line_external_id': '%s-LINE-%s' % (receipt.external_id, line_index),
                'line_note': self.MARKER,
                'branch_warehouse': 'WH33',
                'line_description': product.display_name,
                'inventory_id': product.default_code,
                'line_nbr': str(line_index),
                'location_code': destination_code,
                'product_uom_qty': str(qty),
                'uom_code': uom.name,
                'warehouse_dest_code': destination_code,
            })
        return line_vals

    def _generate_so_returns(self):
        self.ensure_one()
        customers, products, warehouse, location, picking_type = self._validate_so_return_master_data()
        Shipment = self.env['acumatica.shipment.line'].sudo()
        ProductLine = self.env['acumatica.shipment.product.line'].sudo()
        Picking = self.env['stock.picking'].sudo()
        sync_date = fields.Datetime.now()
        generated = Shipment.browse()
        scheduled_date = self._scheduled_date()
        location_code = location.code or self.location_code

        for shipment_index in range(1, self.receipt_count + 1):
            shipment_nbr = self._shipment_number(shipment_index)
            customer = self._pick_record(customers, shipment_index)
            shipment_products = self._pick_products(products, shipment_index)
            line_quantities = [
                self._line_quantity(line_index, shipment_index)
                for line_index in range(1, len(shipment_products) + 1)
            ]
            line_total_qty = sum(line_quantities)
            existing_picking = Picking.search([('origin', '=', shipment_nbr)], limit=1)
            header_vals = {
                'external_id': self._external_id(shipment_nbr),
                'row_number': shipment_index,
                'note': self.MARKER,
                'building_code': warehouse.code,
                'actual_qty': str(line_total_qty),
                'partner_code': getattr(customer, 'adt_b_account_id', False) or customer.name,
                'description': 'Temporary WH33 SO Return',
                'fob_point': 'TEMP',
                'fob_point_description': 'Temporary',
                'acumatica_write_date': fields.Datetime.to_string(sync_date),
                'header_location_code': location_code,
                'header_location_name': location.name,
                'operation': 'Receipt',
                'package_count': '1',
                'package_weight': '0',
                'scheduled_date': scheduled_date,
                'shipment_nbr': shipment_nbr,
                'shipped_qty': str(line_total_qty),
                'shipped_volume': '0',
                'shipped_weight': '0',
                'shipping_terms': 'TEMP',
                'shipping_zone': 'TEMP',
                'ship_via': 'TEMP',
                'status': 'Open',
                'warehouse_dest_code': location_code,
                'shipment_type': 'Shipment',
                'unlimited_packages': 'False',
                'warehouse_code': location_code,
                'warehouse_name': location.name,
                'document_only': self.document_only,
                'picking_type_id': picking_type.id,
                'odoo_picking_id': existing_picking.id if existing_picking else False,
                'import_state': 'pending',
                'import_message': '%s: Sudah ada -> akan diupdate' % shipment_nbr if existing_picking else '',
                'selected': True,
                'sync_date': sync_date,
            }
            shipment = Shipment.search([('shipment_nbr', '=', shipment_nbr)], limit=1)
            if shipment:
                shipment.write(header_vals)
            else:
                shipment = Shipment.create(header_vals)

            ProductLine.search([('shipment_line_id', '=', shipment.id)]).unlink()
            ProductLine.create(self._so_return_product_line_values(shipment, shipment_products, location_code, line_quantities))
            generated |= shipment

        self.generated_shipment_ids = [(6, 0, generated.ids)]
        self.generated_receipt_ids = [(5, 0, 0)]
        self.generated_inventory_receipt_ids = [(5, 0, 0)]
        self.generated_po_return_ids = [(5, 0, 0)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated WH33 SO Return Staging'),
            'res_model': 'acumatica.shipment.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', generated.ids)],
            'context': {'create': False},
        }

    def _so_return_product_line_values(self, shipment, products, location_code, line_quantities):
        line_vals = []
        for line_index, product in enumerate(products, start=1):
            uom = self.uom_id or product.uom_id
            qty = line_quantities[line_index - 1]
            line_vals.append({
                'header_external_id': shipment.external_id,
                'shipment_line_id': shipment.id,
                'shipment_nbr': shipment.shipment_nbr,
                'line_external_id': '%s-LINE-%s' % (shipment.external_id, line_index),
                'description': product.display_name,
                'note': self.MARKER,
                'is_free_item': 'False',
                'inventory_id': product.default_code,
                'line_nbr': str(line_index),
                'location_dest_code': 'FG',
                'open_qty': '0',
                'order_qty': str(qty),
                'order_line_number': str(line_index),
                'order_number': 'SO-%s' % shipment.shipment_nbr,
                'order_type': 'SO',
                'shipped_qty': str(qty),
                'uom_code': uom.name,
                'original_qty': str(qty),
                'warehouse_dest_code': location_code,
                'shipped_weight': '0',
            })
        return line_vals

    def _generate_po_returns(self):
        self.ensure_one()
        vendors, products, warehouse, location, picking_type = self._validate_po_return_master_data()
        PoReturn = self.env['acumatica.issue.po.return.line'].sudo()
        ProductLine = self.env['acumatica.issue.po.return.product'].sudo()
        Picking = self.env['stock.picking'].sudo()
        sync_date = fields.Datetime.now()
        generated = PoReturn.browse()
        scheduled_date = self._scheduled_date()
        location_code = location.code or self.location_code

        for receipt_index in range(1, self.receipt_count + 1):
            receipt_nbr = self._po_return_number(receipt_index)
            vendor = self._pick_record(vendors, receipt_index)
            receipt_products = self._pick_products(products, receipt_index)
            line_quantities = [
                self._line_quantity(line_index, receipt_index)
                for line_index in range(1, len(receipt_products) + 1)
            ]
            line_total_qty = sum(line_quantities)
            existing_picking = Picking.search([
                '|',
                ('origin', '=', receipt_nbr),
                ('adt_receipt_nbr', '=', receipt_nbr),
            ], limit=1)
            header_vals = {
                'external_id': self._external_id(receipt_nbr),
                'row_number': receipt_index,
                'note': self.MARKER,
                'branch_warehouse': 'MAIN',
                'actual_qty': str(line_total_qty),
                'total_qty': str(line_total_qty),
                'scheduled_date': scheduled_date,
                'warehouse_code': location_code,
                'header_location_code': 'MAIN',
                'document_only': self.document_only,
                'is_hold': 'False',
                'inventory_ref': False,
                'acumatica_write_date': fields.Datetime.to_string(sync_date),
                'post_period': self._post_period(),
                'receipt_nbr': receipt_nbr,
                'status': 'Balanced',
                'receipt_type': 'Issue',
                'vendor_code': vendor.ref or vendor.name,
                'partner_ref': 'TEMP',
                'line_nbr': '1',
                'description': 'Temporary WH33 PO Return',
                'transaction_description': 'Temporary WH33 PO Return',
                'inventory_id': receipt_products[:1].default_code if receipt_products else False,
                'line_type': 'Goods for IN',
                'location_dest_code': location_code,
                'open_qty': '0',
                'order_qty': str(line_total_qty),
                'po_line_number': '1',
                'po_number': receipt_nbr,
                'po_type': 'Normal',
                'po_receipt_line_number': '1',
                'po_receipt_number': receipt_nbr,
                'product_uom_qty': str(line_total_qty),
                'uom_code': (self.uom_id or receipt_products[:1].uom_id).name if receipt_products else False,
                'warehouse_dest_code': location_code,
                'picking_type_id': picking_type.id,
                'odoo_picking_id': existing_picking.id if existing_picking else False,
                'import_state': 'pending',
                'import_message': '%s: Sudah ada -> akan diupdate' % receipt_nbr if existing_picking else '',
                'selected': True,
                'sync_date': sync_date,
            }
            po_return = PoReturn.search([('receipt_nbr', '=', receipt_nbr)], limit=1)
            if po_return:
                po_return.write(header_vals)
            else:
                po_return = PoReturn.create(header_vals)

            ProductLine.search([('receipt_line_id', '=', po_return.id)]).unlink()
            ProductLine.create(self._po_return_product_line_values(po_return, receipt_products, location_code, line_quantities))
            generated |= po_return

        self.generated_po_return_ids = [(6, 0, generated.ids)]
        self.generated_receipt_ids = [(5, 0, 0)]
        self.generated_inventory_receipt_ids = [(5, 0, 0)]
        self.generated_shipment_ids = [(5, 0, 0)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated WH33 PO Return Staging'),
            'res_model': 'acumatica.issue.po.return.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', generated.ids)],
            'context': {'create': False},
        }

    def _po_return_product_line_values(self, po_return, products, location_code, line_quantities):
        line_vals = []
        for line_index, product in enumerate(products, start=1):
            uom = self.uom_id or product.uom_id
            qty = line_quantities[line_index - 1]
            line_vals.append({
                'receipt_line_id': po_return.id,
                'line_external_id': '%s-LINE-%s' % (po_return.external_id, line_index),
                'line_note': self.MARKER,
                'branch_warehouse': 'MAIN',
                'line_description': product.display_name,
                'inventory_id': product.default_code,
                'line_nbr': line_index,
                'location_code': location_code,
                'product_uom_qty': qty,
                'uom_code': uom.name,
                'warehouse_code': location_code,
            })
        return line_vals

    def action_cleanup_generated_receipts(self):
        self.ensure_one()
        prefix = (self.receipt_prefix or 'TMP-R26').strip() + '-%'
        if self.generate_type == 'po_return':
            receipts = self.env['acumatica.issue.po.return.line'].sudo().search([
                ('note', '=', self.MARKER),
                ('odoo_picking_id', '=', False),
                ('receipt_nbr', '=like', prefix),
            ])
        elif self.generate_type == 'so_return':
            receipts = self.env['acumatica.shipment.line'].sudo().search([
                ('note', '=', self.MARKER),
                ('odoo_picking_id', '=', False),
                ('shipment_nbr', '=like', prefix),
            ])
        elif self.generate_type == 'inventory_receipt':
            receipts = self.env['acumatica.inventory.recieved.line'].sudo().search([
                ('note', '=', self.MARKER),
                ('odoo_picking_id', '=', False),
                ('odoo_internal_transfer_order_id', '=', False),
                ('reference_nbr', '=like', prefix),
            ])
        else:
            receipts = self.env['acumatica.receipt.line'].sudo().search([
                ('note', '=', self.MARKER),
                ('odoo_picking_id', '=', False),
                ('receipt_nbr', '=like', prefix),
            ])
        count = len(receipts)
        receipts.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cleanup selesai'),
                'message': _('%s temporary receipt staging dihapus.') % count,
                'type': 'success',
                'sticky': False,
            },
        }
