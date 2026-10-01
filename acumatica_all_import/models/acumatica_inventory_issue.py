import logging
from collections import defaultdict
from dateutil import parser as dateutil_parser
import requests

from odoo import _, fields, models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AcumaticaInventoryIssueLine(models.Model):
    _name = 'acumatica.inventory.issue.line'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'acumatica.picking.type.reresolve.mixin', 'acumatica.import.log.mixin']
    _description = 'Data Inventory Inventory Issue dari Acumatica'
    _order = 'reference_nbr asc, line_nbr asc, id asc'

    def _adt_picking_type_wizard_call(self):
        if self._is_disposal():
            # wizard juga tidak mencari picking type untuk disposal
            return False
        return (
            'import.inventory.issue.wizard',
            ({'DocumentOnly': self.document_only},),
            {'warehouse_code': self.warehouse_code},
        )

    row_number = fields.Integer(string='No')
    external_id = fields.Char(string='UUID Header')
    line_external_id = fields.Char(string='UUID Line')

    picking_type_id = fields.Many2one(comodel_name='stock.picking.type', string='Operation Types')

    product_line_ids = fields.One2many(
        'acumatica.inventory.issue.product',  # Model tujuan (detail)
        'receipt_line_id',             # Field Many2one yang ada di model detail
        string='Product Lines'
    )

    reference_nbr = fields.Char(string='Reference Number', index=True)
    scheduled_date = fields.Char(string='Date')
    building_code = fields.Char(string='Building Code')
    description = fields.Char(string='Header Description')
    doc_type = fields.Char(string='Doc Type')
    external_ref = fields.Char(string='External Ref')
    document_only = fields.Boolean(string='Document Only')
    status = fields.Char(string='Status')
    actual_qty = fields.Char(string='Control Qty')
    total_qty = fields.Char(string='Qty Total')
    actual_amount = fields.Char(string='Control Amount')
    total_amount = fields.Char(string='Total Amount')
    post_period = fields.Char(string='Post Period')
    acumatica_write_date = fields.Char(string='Last Modified')
    trans_type = fields.Char(string='Trans Type')
    note = fields.Text(string='Header Note')
    note_header_id = fields.Char(string='Note Header ID')
    change_item_ref_nbr = fields.Char(string='Change Item Ref Number')
    header_location_code = fields.Char(string='Header Location')
    customer_name = fields.Char(string='Customer Name')
    customer_location_id = fields.Char(string='Customer Location ID')
    customer_location_name = fields.Char(string='Customer Location Name')
    shipment_nbr = fields.Char(string='Shipment Nbr')
    transfer_nbr = fields.Char(string='Transfer Nbr')

    line_nbr = fields.Char(string='Line Nbr')
    line_description = fields.Char(string='Description')
    inventory_id = fields.Char(string='InventoryID')
    location_code = fields.Char(string='Location')
    product_uom_qty = fields.Char(string='Qty')
    line_trans_type = fields.Char(string='Line Trans Type')
    uom_code = fields.Char(string='UOM')
    warehouse_code = fields.Char(string='Warehouse')
    branch_warehouse = fields.Char(string='Branch')
    line_note = fields.Text(string='Line Note')

    import_state = fields.Selection([
        ('staged', 'Staged'),
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('rejected', 'Rejected'),
        ('error', 'Error'),
    ], default='staged', tracking=True)
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
    customer_id = fields.Char(string='Customer ID')
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer/Partner',
        compute='_compute_partner_id',
        help='Partner Odoo yang ditemukan dari Customer ID Acumatica.',
    )

    odoo_scrap_id = fields.Many2one(
            'stock.scrap',
            string='Stock Scrap di Odoo',
        )
    
    # ---------------------------------------------------------
    # BUTTONS
    # ---------------------------------------------------------

    @api.depends('customer_id')
    def _compute_partner_id(self):
        for record in self:
            record.partner_id = record._find_customer(record.customer_id)

    # ---------------------------------------------------------
    # MAIN PROCESS
    # ---------------------------------------------------------

    def _find_product(self, line):
        Product = self.env['product.product']
        product = False
        print(f"Product to search: {line.inventory_id}")
        if line.inventory_id:
            product = Product.search([('default_code', '=', line.inventory_id)], limit=1)
            if not product:
                product = Product.search([('barcode', '=', line.inventory_id)], limit=1)
        if not product and line.line_description:
            product = Product.search([('name', '=', line.line_description)], limit=1)

        print(f"Product to create: {product}")
        return product


    def _find_warehouse(self, line):
        # print(f"Line: {line}")
        Warehouse = self.env['stock.location.acumatica']
        warehouse = False

        code = line.warehouse_code 
        if code:
            warehouse = Warehouse.search([('code', '=', code)], limit=1)
            if not warehouse:
                warehouse = Warehouse.search([('name', '=', code)], limit=1)
            else:
                if not warehouse.odoo_building_id:
                    warehouse = False
                else:
                    warehouse = warehouse.odoo_building_id    
            # else:
            #     warehouse = Warehouse.search([('id', '=', 1)], limit=1)
        return warehouse or Warehouse.search([], limit=1)

    def _find_location(self, code):
        Location = self.env['stock.location.acumatica']
        location = False
        if code:
            location = Location.search([('code', '=', code)], limit=1)
        return location

    def _find_bad_stock_location(self, warehouse, location_code=None):
        """Return the internal Bad Stock location belonging to ``warehouse``."""
        loc = self._find_location(location_code)
        return self.env['stock.location'].search([
            ('id', '=', loc.odoo_location_id.id),
        ], limit=1)

    def _is_disposal(self):
        self.ensure_one()
        return (self.trans_type or '').strip().casefold() == 'disposal'

    def _prepare_disposal_internal_transfer(self, first, source_location, dest_location):
        TransferService = self.env['acumatica.internal.transfer.service']
        return TransferService.prepare_order(
            first.reference_nbr,
            source_location,
            dest_location,
            'intra_warehouse',
            schedule_date=self._parse_dt(first.scheduled_date),
            note=first.note or first.description or False,
            transfer_type='transfer_out',
        )

    def _find_customer(self, customer_code):
        print('def _find_customer')
        """Find the Odoo customer using the Acumatica CustomerID."""
        if not customer_code:
            return self.env['res.partner']

        if customer_code:
            print(f"Customer Code: {customer_code}")
            partner = self.env['res.partner'].search([('adt_b_account_id', '=', customer_code)], limit=1)
            if not partner:
                partner = self.env['res.partner'].search([('name', '=', customer_code)], limit=1)

            print(f"Partner from search_partner: {partner}")
        return partner
            
        # return self.env['res.partner'].search([
        #     ('company_registry', '=', customer_code),
        #     ('is_company', '=', True),
        # ], limit=1)

    def _find_uom(self, line, product=False):
        Uom = self.env['uom.uom']
        uom = False
        if line.uom_code:
            uom = Uom.search([('name', '=', line.uom_code)], limit=1)
        if not uom and product:
            uom = product.uom_id
        return uom
    
    def action_import_this(self):
        """Memicu proses impor khusus untuk 1 record aktif"""
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result

    def _do_import(self):
        print('Starting import for Inventory Issue with reference_nbr in:', self.mapped('reference_nbr'))
        Picking = self.env['stock.picking']
        Move = self.env['stock.move']
        
        created = updated = error = 0
        
        # Mengelompokkan lines berdasarkan reference_nbr untuk menghindari filtered() berulang
        lines_by_reference = defaultdict(lambda: self.env[self._name])
        for line in self:
            if line.reference_nbr and line.import_state == 'staged':
                lines_by_reference[line.reference_nbr] |= line

        for issue_key, issue_lines in lines_by_reference.items():
            print(f'Processing Inventory Issue with reference_nbr: {issue_key}')
            
            if not issue_lines:
                continue
                
            first = issue_lines[0]
            # print(f"value :{first}")
            
            try:
                # === PENTING: Buat Savepoint sebelum memproses satu issue_key ===
                # Jika terjadi error di dalam try ini, kita hanya me-rollback data untuk issue_key ini saja.
                self.env.cr.execute('SAVEPOINT import_issue_line')

                warehouse = self._find_warehouse(first)
                if not warehouse:
                    raise UserError(f'Warehouse tidak ditemukan untuk code: {first.warehouse_code or "-"}')
                    
                is_disposal = first._is_disposal()
                picking_type = first._adt_reresolve_picking_type()
                # Persist the resolved operation on staging as well.  Older
                # records may have been created before the resolver could
                # populate picking_type_id; reresolve otherwise only returns
                # the type for document generation and leaves the UI blank.
                if not first.picking_type_id and picking_type:
                    first.write({'picking_type_id': picking_type.id})
                if not picking_type and not is_disposal:
                    raise UserError('Picking type Delivery Order tidak ditemukan.')

                if is_disposal:
                    if warehouse._name != 'stock.warehouse':
                        raise UserError(
                            f'Warehouse mapping untuk code {first.warehouse_code or "-"} '
                            f'belum punya Building Grouping.'
                        )
                    source_location = warehouse.lot_stock_id
                    dest_location = self._find_bad_stock_location(warehouse, first.warehouse_code)
                    if not dest_location:
                        raise UserError(
                            f'Lokasi internal "Bad Stock" tidak ditemukan pada warehouse '
                            f'{warehouse.display_name}.'
                        )
                else:
                    source_location = picking_type.default_location_src_id
                    dest_location = picking_type.default_location_dest_id
                    
                
                if not source_location:
                    raise UserError('Source location warehouse tidak ditemukan.')
                if not dest_location:
                    raise UserError('Destination location tidak ditemukan.')
                # if dest_location.usage == 'customer':
                    # raise UserError('Destination location customer hanya boleh dipakai oleh SO Shipment.')

                customer = self._find_customer(first.customer_id)

                if is_disposal:
                    order, action_state = self._generate_disposal_scrap(first, dest_location)
                    # order, action_state = self._prepare_disposal_internal_transfer(
                    #     first,
                    #     source_location,
                    #     dest_location,
                    # )
                    # to_create_move = self.env['acumatica.inventory.issue.product'].search([('receipt_line_id', '=', first.id)])

                    # for line in to_create_move:
                    #     print("Processed Internal Transfer Move")

                    #     product = self._find_product(line)
                    #     if not product:
                    #         raise UserError(
                    #             f'Product tidak ditemukan untuk InventoryID: {line.inventory_id or "-"}'
                    #         )

                    #     uom = self._find_uom(line, product)
                    #     qty = self._parse_int(line.product_uom_qty)
                    #     move_vals = {
                    #         'name': line.line_description or product.display_name,
                    #         'product_id': product.id,
                    #         'product_uom_qty': qty,
                    #         'product_uom': uom.id if uom else product.uom_id.id,
                    #         'location_id': source_location.id,
                    #         'location_dest_id': dest_location.id,
                    #         'internal_transfer_order_id': order.id,
                    #         'description_picking': line.line_description or False,
                    #         'transaction_type': 'internal',
                    #         'adt_type': first.trans_type or False,
                    #     }
                    #     move_vals = {key: value for key, value in move_vals.items() if key in Move._fields}
                    #     Move.create(move_vals)

                    # self.env['acumatica.internal.transfer.service'].set_order_ready(order)
                    first.write({
                        'import_state': action_state,
                        'import_message': 'success',
                        'odoo_picking_id': False,
                        'odoo_internal_transfer_order_id': False,
                        'odoo_scrap_id': order.id
                    })

                    self.env.cr.execute('RELEASE SAVEPOINT import_issue_line')
                    self.env.cr.commit()
                    created += 1 if action_state == 'created' else 0
                    updated += 1 if action_state == 'updated' else 0
                    continue

                vals = {
                    'origin': first.reference_nbr,
                    'partner_id': customer.id if customer else False,
                    'picking_type_id': picking_type.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest_location.id,
                    'scheduled_date': self._parse_dt(first.scheduled_date),
                    'note': first.note or first.description or False,
                    'adt_receipt_nbr': first.reference_nbr or False,
                    'adt_branch_warehouse': first.branch_warehouse or False,
                    'adt_acumatica_write_date': self._parse_dt(first.acumatica_write_date),
                    'adt_post_period': first.post_period or False,
                    'adt_status': first.status or False,
                    'adt_total_qty': self._parse_int(first.total_qty),
                    'adt_warehouse_code': first.warehouse_code or False,
                    'adt_external_id': first.external_id or False,
                    'adt_type': first.trans_type or False,
                    'adt_change_item_ref_nbr': first.change_item_ref_nbr or False,
                    'transaction_type' : 'outbound',
                    'owner_id': first.partner_id.id if (first.trans_type or "").strip().casefold() == "toko pegang do" else False
                }
                
                picking = Picking.search([
                    ('origin', '=', first.reference_nbr),
                    ('picking_type_id', '=', picking_type.id),
                ], limit=1)
                
                if picking:
                    if picking.state != 'draft':
                        raise UserError(f'Delivery Order {first.reference_nbr} sudah ada di Odoo dengan state {picking.state}, tidak bisa diupdate.')
                    picking.write(vals)
                    action_state = 'updated'
                    updated += 1
                    self.env['acumatica.error.transaction']._handle_acumatica_update(first, origin=first.reference_nbr or False)
                    print(f"Update Picking: {picking}")
                else:
                    picking = Picking.create(vals)
                    action_state = 'created'
                    created += 1
                    print(f"Create Picking: {picking}")

                if action_state == 'updated':
                    picking.move_ids.unlink()

                to_create_move = self.env['acumatica.inventory.issue.product'].search([('receipt_line_id', '=', first.id)])
                    
                for line in to_create_move:
                    print("Processed Stock Move")

                    customer = False
                    if line.customer_id:
                        customer = self._find_customer(line.customer_id)

                    owner_id = False

                    if (first.trans_type or "").strip().casefold() == "toko pegang do":
                        if not customer:
                            raise UserError(
                                f"Customer dengan CustomerID {line.customer_id or '-'} "
                                f"tidak ditemukan untuk baris Disposal."
                            )
                        owner_id = customer.id
                    else:
                        owner_id = customer.id if customer else False

                    product = self._find_product(line)
                    if not product:
                        raise UserError(
                            f'Product tidak ditemukan untuk InventoryID: '
                            f'{line.inventory_id or "-"}'
                        )
                    uom = self._find_uom(line, product)
                    qty = self._parse_int(line.product_uom_qty)
                    print(f"Qty value before: {line.product_uom_qty} and after: {qty}")
                    
                    move_domain = [
                        ('picking_id', '=', picking.id),
                        ('product_id', '=', product.id),
                    ]
                    if owner_id:
                        move_domain.append(('owner_id', '=', owner_id))
                    existing_move = Move.search(move_domain, limit=1)
                    
                    if existing_move:
                        existing_move.write({
                            'product_uom_qty': qty,
                            'name': line.line_description or product.display_name,
                            'owner_id': owner_id,
                        })
                        first.write({
                            'import_state': action_state,
                            'import_message': 'success',
                            'odoo_picking_id': picking.id,
                            'odoo_internal_transfer_order_id': False,
                        })
                    else:
                        Move.create({
                            'name': line.line_description or product.display_name,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': uom.id if uom else product.uom_id.id,
                            'location_id': source_location.id,
                            'location_dest_id': dest_location.id,
                            'description_picking': line.line_description or False,
                            'transaction_type' : 'outbound',
                            'adt_type': first.trans_type or False,
                            'owner_id': owner_id,
                        })
                        first.write({
                            'import_state': action_state,
                            'import_message': 'success',
                            'odoo_picking_id': picking.id,
                            'odoo_internal_transfer_order_id': False,
                        })

                if first.document_only:
                    picking.action_validate_document_only_import(force=True)

                # === PENTING: Release Savepoint & Commit Data Sukses ===
                self.env.cr.execute('RELEASE SAVEPOINT import_issue_line')
                self.env.cr.commit()  # Mengunci data yang sukses ke database agar tidak hilang jika loop berikutnya error
                        
            except Exception as e:
                # === PENTING: Rollback hanya untuk baris yang error saja ===
                self.env.cr.execute('ROLLBACK TO SAVEPOINT import_issue_line')
                
                _logger.exception('Error import issue %s', issue_key)
                
                # Tulis pesan error ke object line (lalu commit status errornya agar tersimpan)
                product_lines = self.env['acumatica.inventory.issue.product'].search([
                    ('receipt_line_id', 'in', issue_lines.ids),
                ])
                line_payloads = [{
                    'inventory_id': line.inventory_id or False,
                    'product_name': line.line_description or False,
                    'qty': self._parse_int(line.product_uom_qty),
                    'uom': line.uom_code or False,
                    'payload': line.read()[0] if line.exists() else {},
                } for line in product_lines]
                self.env['acumatica.error.transaction']._handle_acumatica_error(
                    first,
                    [str(e)],
                    api_acumatica='inventory_issue',
                    operation_type='delivery',
                    origin=first.reference_nbr or issue_key,
                    partner=first.customer_id or False,
                    location=first.warehouse_code or False,
                    location_dest=dest_location.display_name if 'dest_location' in locals() and dest_location else False,
                    scheduled_date=first.scheduled_date,
                    total_qty=first.total_qty,
                    actual_qty=first.actual_qty,
                    payload={'header': first.read()[0] if first.exists() else {}},
                    line_payloads=line_payloads,
                )
                issue_lines.write({
                    'import_state': 'rejected' if any(term in (locals().get('error_message') or str(locals().get('e') or locals().get('line_e') or '')).lower() for term in ('tidak bisa diupdate', 'update digagalkan', 'sudah divalidasi', 'already processed', 'state ready', 'state done', 'state processed')) else 'error',
                    'import_message': str(e)[:200],
                    'odoo_picking_id': False,
                    'odoo_internal_transfer_order_id': False,
                    'odoo_scrap_id': False,
                })
                self.env.cr.commit() 
                
                error += len(issue_lines)
                
        msg = f'Import selesai: {created} dokumen dibuat, {updated} dokumen diupdate, {error} line error.'
        # Notifikasi dimatikan agar form staging tidak freeze/tidak realtime.
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Import Delivery Order',
        #         'message': msg,
        #         'type': 'success' if error == 0 else 'danger',
        #         'sticky': True,
        #     }
        # }

    def _generate_disposal_scrap(self, first, source_location):
        Scrap = self.env["stock.scrap"]
        ScrapLocation = self.env["stock.location"]

        warehouse = self._find_warehouse(first)
        
        if not source_location:
            raise UserError(
                f"Stock location tidak ditemukan untuk "
            )

        scrap_location = ScrapLocation.search([
            ("scrap_location", "=", True),
            ("company_id", "in", [False, warehouse.company_id.id]),
        ], limit=1)
        
        if not scrap_location:
            raise UserError(
                f"Scrap Location tidak ditemukan untuk "
                f"{warehouse.display_name}."
            )

        components = self.env[
                    "acumatica.inventory.issue.product"
        ].search([
            ("receipt_line_id", "=", first.id),
        ])

        if not components:
            raise UserError(
                f"Tidak ada product untuk disposal "
                f"{first.reference_nbr}."
            )

        # =========================================================
        # CHECK EXISTING SCRAP
        # =========================================================
        imported_status = ""
        scrap = Scrap.search([('origin', '=', first.reference_nbr)])

        scrap_lines = []
        for line in components:
            product = self._find_product(line)

            if not product:
                raise UserError(
                    f"Product tidak ditemukan untuk InventoryID: "
                    f"{line.inventory_id or '-'}"
                )

            uom = self._find_uom(line, product)
            qty = self._parse_int(line.product_uom_qty)

            scrap_lines.append({
                "product_id": product,
                "product_uom_id": uom or product.uom_id,
                "demand_qty": qty,
                "location_id": source_location,
                "name": (
                    line.line_description
                    or product.display_name
                ),
                "receipt_move_id": False,
            })
        if not scrap:
            scrap = Scrap.create({
                "origin": first.reference_nbr,
                "company_id": warehouse.company_id.id,
                "location_id": source_location.id,
                "scrap_location_id": scrap_location.id,
                "scheduled_date": self._parse_dt(first.scheduled_date),

                # Header / dummy
                "product_id": scrap_lines[0]["product_id"].id,
                "product_uom_id": scrap_lines[0]["product_uom_id"].id,
                "scrap_qty": scrap_lines[0]["demand_qty"],
            })  

            imported_status = "created"
        else:
            if scrap.state != "draft":
                raise UserError(
                    f"Scrap {scrap.name} for "
                    f"{first.reference_nbr} is already processed "
                    f"and the status is {scrap.state}."
                )
            
            # Scrap masih draft → rebuild
            scrap.scrap_line_ids.mapped("scrap_move_id").unlink()
            scrap.scrap_line_ids.unlink()

            imported_status = "updated"

        # =========================================================
        # PREPARE SCRAP LINES
        # =========================================================
        scrap.scrap_line_ids = [
            (
                0,
                0,
                {
                    "product_id": line["product_id"].id,
                    "product_uom_id": line["product_uom_id"].id,
                    "demand_qty": line["demand_qty"],
                    "location_id": line["location_id"].id,
                    "name": line["name"],
                    "receipt_move_id": False,
                },
            )
            for line in scrap_lines
        ]

        # =========================================================
        # CREATE WMS SCRAP MOVES
        # =========================================================
        scrap._create_scrap_moves()

        # =========================================================
        # SCRAP NAME
        # =========================================================
        if scrap.name == _("New"):
            scrap.name = (
                self.env["ir.sequence"].next_by_code("stock.scrap")
                or _("New")
            )

        return scrap, imported_status

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # DETAIL
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # API MAPPING
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # API
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------


    @api.depends('reference_nbr')
    def _compute_exists_in_odoo(self):
        Picking = self.env['stock.picking']
        InternalTransferOrder = self.env['internal.transfer.order']
        for rec in self:
            rec.exists_in_odoo = bool(
                rec.reference_nbr and (
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
    def _parse_int(value):
        try:
            return int(float(value or 0))
        except Exception:
            return 0.0


# Unknown

    def action_import_selected(self):
        lines = self.filtered(lambda l: l.selected and l.import_state in ['staged', 'error'])
        if not lines:
            raise UserError('Hanya bisa generate data dengan state Staged & Error')
        result = lines._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(lines)
        return result

    def action_import_this(self):
        print('Starting import for Inventory Issue with reference_nbr in:', self.mapped('reference_nbr'))
        self.ensure_one()
        result = self._do_import()
        self.env['acumatica.error.transaction']._handle_acumatica_created(self)
        return result


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
                'target': 'current',
            }
        if self.odoo_scrap_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.scrap',
                'res_id': self.odoo_scrap_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if not self.odoo_picking_id:
            raise UserError('Belum ada dokumen Odoo.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.odoo_picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class AcumaticaInventoryIssueProduct(models.Model):
    _name = 'acumatica.inventory.issue.product'
    _description = 'Data Inventory Inventory Issue dari Acumatica'
    _order = 'line_nbr asc, id asc'

    receipt_line_id = fields.Many2one(
        'acumatica.inventory.issue.line',
        string='Receipt Header',
        required=True,
        ondelete='cascade',
        index=True,
    )

    line_external_id = fields.Char(string='UUID Detail')
    line_note = fields.Char(string='Detail Note')
    branch_warehouse = fields.Char(string='Warehouse Branch')
    line_description = fields.Char(string='Product Description')
    inventory_id = fields.Char(string='UUID Product')
    line_nbr = fields.Char(string='Product line number')
    location_code = fields.Char(string='Product Location')
    line_location_name = fields.Char(string='Line Location Name')
    product_uom_qty = fields.Char(string='UOM Quantity')
    line_trans_type = fields.Char(string='Product Trans Type')
    uom_code = fields.Char(string='UOM')
    warehouse_code = fields.Char(string='Product Warehouse')
    line_warehouse_name = fields.Char(string='Line Warehouse Name')
    header_external_id = fields.Char(string='UUID Header')
    customer_id = fields.Char(string='Customer ID')
    line_note_id = fields.Char(string='Line Note ID')
