from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from lxml import etree
from odoo.tools.float_utils import float_compare, float_is_zero

class WMSStockScrap(models.Model):
    _inherit = 'stock.scrap'

    def _is_operator_only(self):
        if not self.env.user.has_group('tijari_wms_18.group_operator'):
            return False
        elevated = (
            'tijari_wms_18.group_it_staff',
            'stock.group_stock_manager',
            'base.group_system',
        )
        return not any(self.env.user.has_group(group) for group in elevated)

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id=view_id, view_type=view_type, **options)
        if self._is_operator_only() and view_type in ('form', 'list'):
            arch = etree.fromstring(result['arch'].encode())
            root_tag = 'form' if view_type == 'form' else 'list'
            root = arch if arch.tag == root_tag else arch.find('.//' + root_tag)
            if root is not None:
                root.set('create', 'false')
                root.set('delete', 'false')
                if view_type == 'list':
                    root.set('edit', 'false')
                else:
                    writable_pages = {'item_to_scrap', 'scrap_notes_page'}
                    for field_node in arch.xpath('.//field'):
                        page = field_node.getparent()
                        while page is not None and page.tag != 'page':
                            page = page.getparent()
                        if page is None or page.get('name') not in writable_pages:
                            field_node.set('readonly', '1')
                    for button in arch.xpath('.//header//button'):
                        button.set('invisible', '1')
            result['arch'] = etree.tostring(arch, encoding='unicode')
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and self._is_operator_only():
            raise AccessError(_('Warehouse Operator hanya memiliki akses baca pada Disposal Document.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and self._is_operator_only():
            writable_fields = {
                'note', 'scrap_line_ids', 'filtered_scrap_line_ids',
                'scrap_product_id', 'scrap_lot_id', 'filter_scan_code',
            }
            if set(vals) - writable_fields:
                raise AccessError(_('Warehouse Operator hanya dapat mengubah bagian Item to Scrap dan Notes.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self._is_operator_only():
            raise AccessError(_('Warehouse Operator tidak memiliki akses untuk menghapus Disposal Document.'))
        return super().unlink()

    product_id = fields.Many2one(
        'product.product', 'Product', domain="[('type', '=', 'consu')]",
        check_company=True)
    
    product_uom_id = fields.Many2one(
        'uom.uom', 'Unit of Measure',
        compute="_compute_product_uom_id", store=True, readonly=False, precompute=True,
        domain="[('category_id', '=', product_uom_category_id)]")

    scrap_qty = fields.Float(
        'Quantity', digits='Product Unit of Measure',
        compute='_compute_scrap_qty', default=1.0, readonly=False, store=True)

    scrap_line_ids = fields.One2many(
        "stock.scrap.line",
        "scrap_id",
        string="Scrap Lines",
        copy=False,
    )

    filtered_scrap_line_ids = fields.One2many(
        "stock.scrap.line",
        "scrap_id",
        string="Filtered Scrap Lines",
        compute="_compute_filtered_scrap_line_ids",
    )

    picking_id = fields.Many2one(
        "stock.picking",
        string="Receipt",
        readonly=True,
        copy=False,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("done", "Done"),
        ],
        default="draft",
        string="Status",
        copy=False,
        tracking=True
    )

    availability_state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("available", "Available"),
            ("insufficient", "Insufficient"),
        ],
        default="waiting",
        string="Stock Availability",
        copy=False,
        tracking=True
    )

    last_availability_check = fields.Datetime(
        string="Last Availability Check",
        readonly=True,
        copy=False,
    )        

    scheduled_date = fields.Datetime('Scheduled Date')

    filter_scan_code = fields.Char(
        string="Kode scan",
        help="Bisa diisi dari scanner handheld atau diketik manual.",
    )

    scrap_product_id = fields.Many2one(
        'product.product',
        string="Product Name",
    )

    allowed_scrap_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_scrap_product_ids',
    )

    allowed_scrap_lot_ids = fields.Many2many(
        'stock.lot',
        compute='_compute_allowed_scrap_lot_ids',
    )

    scrap_lot_id = fields.Many2one(
        'stock.lot',
        string="LOT Number",
        domain="[('id', 'in', allowed_scrap_lot_ids)]",
        readonly=False,
    )

    @api.depends('scrap_line_ids.product_id')
    def _compute_allowed_scrap_product_ids(self):
        for scrap in self:
            scrap.allowed_scrap_product_ids = scrap.scrap_line_ids.product_id

    @api.depends(
        'scrap_product_id',
        'scrap_lot_id',
        'scrap_line_ids',
        'scrap_line_ids.product_id',
        'scrap_line_ids.lot_ids',
    )
    def _compute_filtered_scrap_line_ids(self):
        for scrap in self:
            lines = scrap.scrap_line_ids
            if scrap.scrap_product_id:
                lines = lines.filtered(
                    lambda line: line.product_id == scrap.scrap_product_id
                )
            if scrap.scrap_lot_id:
                lines = lines.filtered(
                    lambda line: scrap.scrap_lot_id in line.lot_ids
                )
            scrap.filtered_scrap_line_ids = lines

    @api.onchange('scrap_product_id')
    def _onchange_scrap_product_id(self):
        for scrap in self:
            if scrap.scrap_lot_id and scrap.scrap_lot_id not in scrap.allowed_scrap_lot_ids:
                scrap.scrap_lot_id = False

    @api.onchange('scrap_lot_id')
    def _onchange_scrap_lot_id(self):
        for scrap in self:
            if scrap.scrap_lot_id:
                line = scrap.scrap_line_ids.filtered(
                    lambda item: scrap.scrap_lot_id in item.lot_ids
                )[:1]
                scrap.scrap_product_id = line.product_id

    @api.depends(
        "scrap_line_ids",
        "scrap_line_ids.product_id",
        "scrap_line_ids.lot_ids",
    )
    def _compute_allowed_scrap_lot_ids(self):
        for scrap in self:
            lines = scrap.scrap_line_ids

            if scrap.scrap_product_id:
                lines = lines.filtered(
                    lambda line: line.product_id == scrap.scrap_product_id
                )

            scrap.allowed_scrap_lot_ids = lines.mapped("lot_ids")

    @api.onchange('filter_scan_code')
    def _onchange_filter_scan_code(self):
        for scrap in self:
            if not scrap.filter_scan_code:
                continue
            values = scrap._get_picker_scan_values(scrap.filter_scan_code)
            scrap.update(values['values'])
            scrap.filter_scan_code = False
    
    def _get_picker_scan_values(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        if not scanned_code:
            raise ValidationError(_("Kode scan tidak boleh kosong."))

        scrap_moves = self.scrap_line_ids.filtered(
            lambda scrap_line: (
                scrap_line.product_id
            )
        )
        product, matched_by = self._find_product_scan_match(scanned_code)
        if product:
            matching_moves = scrap_moves.filtered(
                lambda move: move.product_id == product
            )
            if matching_moves:
                return {
                    'values': {
                        'scrap_product_id': product.id,
                        'scrap_lot_id': False,
                    },
                    'result': {
                        'product_id': product.id,
                        'display_name': product.display_name,
                        'lot_id': False,
                        'scrap_line_ids': matching_moves.ids,
                        'matched_by': 'product',
                    },
                }
            raise ValidationError(
                _(
                    "%s %s dikenali sebagai Product %s, tetapi product tersebut "
                    "tidak ada di dokumen ini."
                ) % (matched_by, scanned_code, product.display_name)
            )

        product, matching_lines, lot = self._find_scrap_product_by_lot_scan_code(scanned_code)
        return {
            'values': {
                'scrap_product_id': product.id,
                'scrap_lot_id': lot.id,
            },
            'result': {
                'product_id': product.id,
                'display_name': product.display_name,
                'lot_id': lot.id,
                'scrap_line_ids': matching_lines.ids,
                'matched_by': 'lot',
            },
        }

    def _find_product_scan_match(self, scan_code):
        Product = self.env['product.product']
        scan_code = (scan_code or '').strip()

        product = Product.search([('barcode', '=', scan_code)], limit=1)
        if product:
            return product, _('Barcode')

        product = Product.search([('default_code', '=', scan_code)], limit=1)
        if product:
            return product, _('SKU')

        return Product.browse(), False
    
    def _find_scrap_product_by_lot_scan_code(self, scan_code):
        self.ensure_one()
        lots = self.scrap_line_ids.mapped('lot_ids').filtered(
            lambda lot: lot.name == scan_code or lot.ref == scan_code
        )
        matching_lines = self.scrap_line_ids.filtered(
            lambda line: bool(line.lot_ids & lots)
        )

        if not matching_lines:
            if lots:
                raise ValidationError(
                    _("Lot %s ditemukan, tetapi tidak ada di dokumen ini.")
                    % scan_code
                )
            raise ValidationError(
                _("Kode %s tidak ditemukan sebagai Barcode, SKU, atau Lot.")
                % scan_code
            )

        products = matching_lines.product_id
        if len(products) > 1:
            raise ValidationError(_("Lot hasil scan mengarah ke lebih dari satu product."))

        return products[:1], matching_lines, lots[:1]

    def action_apply_scanned_picker_code(self, scanned_code):
        """Apply a generic scanner input that may identify a product or a lot."""
        self.ensure_one()
        values = self._get_picker_scan_values(scanned_code)
        self.write(values['values'])
        return values['result']

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("product_id") or not vals.get("scrap_line_ids"):
                continue

            for command in vals["scrap_line_ids"]:
                if command[0] == Command.CREATE:
                    line_vals = command[2]

                    vals["product_id"] = line_vals.get("product_id")
                    vals["product_uom_id"] = line_vals.get("product_uom_id")
                    break

        return super().create(vals_list)

    def action_validate(self):

        self.ensure_one()

        if self.state == "done":
            raise UserError(_("Scrap has already been validated."))

        if not self.scrap_line_ids:
            raise UserError(_("No scrap lines found."))

        # if self.availability_state != "available":
        #     raise UserError(_("Some products do not have sufficient stock."))

        self._check_all_lot_match()

        for line in self.scrap_line_ids:
        
            move = self.env["stock.move"].create(
                self._prepare_scrap_move_values(line)
            )

            scrap_move_line = line.scrap_move_id.move_line_ids

            if not scrap_move_line:
                raise UserError(
                    _(
                        "No stock allocation found for product %s."
                    ) % line.product_id.display_name
                )
                
            for move_line in scrap_move_line:

                available = self.env["stock.quant"]._get_available_quantity(
                    move_line.product_id,
                    move_line.location_id,
                    lot_id = move_line.lot_id,
                )
        
                if float_compare(
                    available,
                    move_line.scrapped_qty,
                    precision_rounding=move_line.product_uom_id.rounding,
                ) < 0:
                    raise UserError(_(
                        "%s no longer has enough stock for lot %s."
                    ) % (
                        move_line.product_id.display_name,
                        move_line.lot_id.name,
                    ))


                self.env["stock.move.line"].create({
                    "move_id": move.id,
                    "product_id": move_line.product_id.id,
                    "lot_id": move_line.lot_id.id,
                    "location_id": move_line.location_id.id,
                    "location_dest_id": self.scrap_location_id.id,
                    "product_uom_id": move_line.product_uom_id.id,
                    "quantity": move_line.scrapped_qty,
                    # "quantity": move_line.quantity,
                })

            move.with_context(
                is_scrap=True
            )._action_done()


            line.write({
                "move_id": move.id,
                # "availability_state": "available",
            })

        self.write({
            "state": "done",
            "date_done": fields.Datetime.now(),
        })

    def action_done(self):
        self.ensure_one()
        if self.name == _("New"):
            self.name = (
                self.env["ir.sequence"]
                .next_by_code("stock.scrap")
                or _("New")
            )
        for line in self.scrap_line_ids:
            move = line.move_id
            move.with_context(
                is_scrap=True
            )._action_done()

    def action_mark_as_to_do(self):
        self.state = "ready"

    def action_check_availability(self):
        self.ensure_one()

        if self.state == "done":
            raise UserError(_("Scrap already validated."))

        all_available = True

        for line in self.scrap_line_ids:
            self._check_line_availability(line)

            if line.availability_state != "available":
                all_available = False

        self.availability_state = (
            "available"
            if all_available
            else "insufficient"
        )

        self.last_availability_check = fields.Datetime.now()

        # if self.availability_state == "available":
        #     self.state = "ready"
        # else:
        #     self.state = "draft"

        return True

    def _prepare_base_move_values(self):
        self.ensure_one()

        return {
            "name": self.name,
            "origin": self.origin or self.picking_id.origin or self.name,
            "company_id": self.company_id.id,
            "state": "draft",
            "scrapped": True,
            "scrap_id": self.id,
            "picked": True,
            "picking_id": self.picking_id.id,
            "location_dest_id": self.scrap_location_id.id,
        }

    def _prepare_scrap_move_values(self, line):
        vals = self._prepare_base_move_values()

        vals.update({
            "product_id": line.product_id.id,
            "product_uom": line.product_uom_id.id,
            "product_uom_qty": line.demand_qty,
            "location_id": line.location_id.id,
        })

        return vals

    def _check_line_availability(self, line):
        locations = self._get_scrap_locations(line.location_id)

        available_qty = sum(
            self.env["stock.quant"]._get_available_quantity(
                line.product_id,
                location,
            )
            for location in locations
        )

        line.available_qty = available_qty

        if float_compare(
            available_qty,
            line.demand_qty,
            precision_rounding=line.product_uom_id.rounding,
        ) >= 0:
            line.availability_state = "available"
        else:
            line.availability_state = "insufficient"
        
        self._generate_wms_scrap_move_lines(line)

    def _create_scrap_moves(self):
        self.ensure_one()
        for line in self.scrap_line_ids:
            scrap_move = self.env["wms.scrap.move"].create({
                "scrap_id": self.id,
                "receipt_move_id": line.receipt_move_id.id if line.receipt_move_id else False,
                "product_id": line.product_id.id,
                "demand_qty": line.demand_qty,
                "product_uom": line.receipt_move_id.product_uom.id
            })

            line.scrap_move_id = scrap_move.id

            if line.receipt_move_id:
                for move_line in line.receipt_move_id.move_line_ids:
                    self.env["wms.scrap.move.line"].create({
                        "scrap_move_id": scrap_move.id,
                        "lot_id": move_line.lot_id.id,
                        "location_id": move_line.location_dest_id.id,
                        "product_uom_id": move_line.product_uom_id.id,
                        "quantity": move_line.quantity,
                    })
            # else:
            #     self.env["wms.scrap.move.line"].create({
            #         "move_id": scrap_move.id,
            #         "location_id": line.location_id.id,
            #         "quantity": line.demand_qty,
            #         "product_uom_id": line.product_uom_id.id,
            #     })

    def _generate_wms_scrap_move_lines(self, scrap_line):
        self.ensure_one()

        wms_move = scrap_line.scrap_move_id

        if not wms_move:
            return

        rounding = scrap_line.product_uom_id.rounding

        # =========================================================
        # 1. Ambil line yang sudah FINISHED
        # =========================================================
        finished_lines = wms_move.move_line_ids.filtered(
            lambda line: line.status == "finished"
        )

        # =========================================================
        # 2. Hapus hanya line yang belum FINISHED
        # =========================================================
        wms_move.move_line_ids.filtered(
            lambda line: line.status != "finished"
        ).unlink()

        # =========================================================
        # 3. Hitung quantity yang sudah dikonfirmasi/finished
        #    Gunakan scrapped_qty karena ini actual confirmed qty.
        # =========================================================
        finished_qty = sum(
            finished_lines.mapped("scrapped_qty")
        )

        # =========================================================
        # 4. Hitung sisa demand yang masih perlu dialokasikan
        # =========================================================
        remaining_qty = max(
            scrap_line.demand_qty - finished_qty,
            0.0,
        )

        if float_compare(
            remaining_qty,
            0.0,
            precision_rounding=rounding,
        ) <= 0:
            return

        # =========================================================
        # 5. Ambil seluruh location + child
        # =========================================================
        locations = self._get_scrap_locations(
            scrap_line.location_id
        )

        Quant = self.env["stock.quant"]

        # =========================================================
        # 6. Cari stock berdasarkan FIFO
        # =========================================================
        # Ambil quant yang:
        # - produknya sama
        # - lokasinya sama
        # - punya lot
        # - punya stock
        #
        # order ASC = FIFO berdasarkan lot/quant
        quants = Quant.search(
            [
                ("product_id", "=", scrap_line.product_id.id),
                ("location_id", "in", locations.ids),
                ("lot_id", "!=", False),
                ("quantity", ">", 0),
            ],
            order="in_date asc, id asc",
        )

        # remaining_qty = scrap_line.demand_qty

        # =========================================================
        # 7. Allocate sebanyak yang tersedia
        # =========================================================
        for quant in quants:

            # Demand sudah terpenuhi
            if float_compare(
                remaining_qty,
                0.0,
                precision_rounding=scrap_line.product_uom_id.rounding,
            ) <= 0:
                break

            available_qty = quant.quantity

            if float_compare(
                available_qty,
                0.0,
                precision_rounding=scrap_line.product_uom_id.rounding,
            ) <= 0:
                continue

            # Ambil sebanyak yang tersedia,
            # tetapi tidak boleh melebihi demand
            allocated_qty = min(
                available_qty,
                remaining_qty,
            )

            self.env["wms.scrap.move.line"].create({
                "scrap_move_id": wms_move.id,
                "product_id": scrap_line.product_id.id,
                "lot_id": quant.lot_id.id,
                "location_id": quant.location_id.id,
                "quantity": allocated_qty,
                "product_uom_id": scrap_line.product_uom_id.id,
            })

            remaining_qty -= allocated_qty

    def _check_all_lot_match(self):
        scrap_move_lines = self.scrap_line_ids.mapped('scrap_move_id').mapped('move_line_ids')
        unmatch_lots = scrap_move_lines.filtered(
            lambda m: m.match_status != 'match'
        )
        if unmatch_lots:
            text = "Product(s) that need Lot confirmation:\n"
            for lot in unmatch_lots:
                text += f"- {lot.product_id.name}\n"
            raise UserError(_(
                f"All scrap Lots must be matched before validation.\n\n{text}"
            ))
        
        unfinished_line = self.scrap_line_ids.filtered(
            lambda m: m.status != 'finished'
        )

        if unfinished_line:
            text = "Product(s) that not Finished:\n"
            for line in unfinished_line:
                text += f"- {line.product_id.name}\n"
            raise UserError(_(
                f"All products must be in Finished status.\n\n{text}"
        ))
    
    def _get_scrap_locations(self, location):
        return self.env["stock.location"].search([
            ("id", "child_of", location.id),
        ])

class StockScrapLine(models.Model):
    _name = "stock.scrap.line"
    _description = "Stock Scrap Line"
    _order = "id"

    scrap_id = fields.Many2one(
        "stock.scrap",
        required=True,
        ondelete="cascade",
    )

    name = fields.Char(string='Description')

    company_id = fields.Many2one(
        related="scrap_id.company_id",
        store=True,
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        required=True,
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        print(f"Scrap_id nya {self.scrap_id}")

    product_uom_id = fields.Many2one(
        "uom.uom",
        string="UoM",
        required=True,
    )

    demand_qty = fields.Float(
        string="Scrap Demand",
        digits="Product Unit of Measure",
    )

    available_qty = fields.Float(
        string="Available Qty",
        digits="Product Unit of Measure",
        copy=False,
        readonly=True,
    )

    scrapped_qty = fields.Float(
        string="Scrapped Qty",
        digits="Product Unit of Measure",
        copy=False,
        readonly=True,
        compute="_compute_scrapped_qty"
    )

    @api.depends(
        "scrap_move_id.move_line_ids.scrapped_qty",
    )
    def _compute_scrapped_qty(self):
        for move in self:
            total_scrapped_qty = sum(move.scrap_move_id.move_line_ids.mapped('scrapped_qty'))
            move.scrapped_qty = total_scrapped_qty if total_scrapped_qty > 0 else 0.0

    lot_ids = fields.Many2many(
        "stock.lot",
        string="Lots",
        compute="_compute_lot_ids",
        store=True,
    )

    @api.depends("scrap_move_id.move_line_ids.lot_id")
    def _compute_lot_ids(self):
        for line in self:
            line.lot_ids = line.scrap_move_id.move_line_ids.mapped("lot_id")


    availability_state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("available", "Available"),
            ("insufficient", "Insufficient"),
        ],
        default="waiting",
        string="Status",
        copy=False,
        tracking=True
    )      

    move_id = fields.Many2one(
        "stock.move",
        copy=False,
        readonly=True,
    )  

    # move_line_ids = fields.One2many(
    #     related="move_id.move_line_ids",
    #     readonly=True,
    # )

    move_state = fields.Selection(
        related="move_id.state",
        store=True,
        readonly=True,
    )

    location_id = fields.Many2one(
        "stock.location",
        readonly=True,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        readonly=True,
    )

    receipt_move_id = fields.Many2one(
        "stock.move",
        string="Receipt Move",
        readonly=True,
    )

    scrap_move_id = fields.Many2one(
        "wms.scrap.move",
        string="Srap Move",
        readonly=True,
    )

    status = fields.Selection([
        ('finished', 'Finished'),
        ('unfinished', 'Unfinished'),
    ], string='Status', default="unfinished", compute="_compute_status_check")

    @api.depends('scrap_move_id.move_line_ids.status')
    def _compute_status_check(self):
        for move in self:
            lines = move.scrap_move_id.move_line_ids
            move.status = (
                'finished' if lines and all(line.status == 'finished' for line in lines)
                else 'unfinished'
            )

    def action_show_details(self):
        return self.scrap_move_id.action_show_details()

class WMSScrapMove(models.Model):
    _name = "wms.scrap.move"
    _description = "WMS Scrap Move"

    scrap_id = fields.Many2one(
        "stock.scrap",
        required=True,
        ondelete="cascade",
    )

    state = fields.Selection(related="scrap_id.state")

    receipt_move_id = fields.Many2one(
        "stock.move",
        string="Receipt Move",
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        required=True,
        readonly=True,
    )

    demand_qty = fields.Float(
        string='Demand',
        required=True,
        readonly=True,
    )

    product_uom = fields.Many2one(
        'uom.uom', 
        string='product_uom',
        readonly=True,
    )

    move_line_ids = fields.One2many(
        "wms.scrap.move.line",
        "scrap_move_id",
        string="Details",
    )

    def action_show_details(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Detailed Operations"),
            "res_model": "wms.scrap.move",
            "view_mode": "form",
            "view_id": self.env.ref(
                "tijari_wms_18.wms_scrap_move_view_form"
            ).id,
            "res_id": self.id,
            "target": "new",
        }

class WMSScrapMoveLine(models.Model):
    _name = "wms.scrap.move.line"
    _description = "WMS Scrap Move Line"

    scrap_move_id = fields.Many2one(
        "wms.scrap.move",
        required=True,
        ondelete="cascade",
    )

    state = fields.Selection(related="scrap_move_id.state")

    product_id = fields.Many2one(
        related="scrap_move_id.product_id",
        store=True,
        readonly=True,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        string="Lot",
    )
    
    location_id = fields.Many2one(
        "stock.location",
        string="Pick From",
    )

    product_uom_id = fields.Many2one('uom.uom', string='UoM')

    quantity = fields.Float(
        required=True,
    )

    scrapped_qty = fields.Float('Scrapped Qty')

    confirmation_lot_code = fields.Char(
        string='Confirmation Lot Code',
        help='Scanned / input lot code for confirmation.',
        store=True
    )

    matching_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Confirm Lot",
        domain="[('id', 'in', allowed_matching_lot_ids)]",
        store=True
    )

    allowed_matching_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        string="Allowed Matching Lots",
        compute="_compute_allowed_matching_lot_ids",
    )

    def _compute_allowed_matching_lot_ids(self):
        for line in self:
            line.allowed_matching_lot_ids = line.scrap_move_id.move_line_ids.mapped("lot_id")

    status = fields.Selection([
        ('finished', 'Finished'),
        ('unfinished', 'Unfinished'),
    ], string='Status', default="unfinished")

    match_status = fields.Selection([
        ('match', 'Match'),
        ('not_match', 'Not Match'),
    ], string='Match Status', default='not_match', compute="_compute_match_status")

    @api.depends('matching_lot_id')
    def _compute_match_status(self):
        expected_lot = self.lot_id
        if self.matching_lot_id == expected_lot:
            self.match_status = 'match'
        else: 
            self.match_status = 'not_match'

    handheld_scan_code = fields.Char(
        string='Scan Handheld',
        help='Masukkan kode lot, lokasi, atau package dari scanner handheld atau ketik manual.',
        store=False,
    )

    @api.onchange('handheld_scan_code')
    def _onchange_handheld_scan_code(self):
        for line in self:
            values = line._get_handheld_scan_values(line.handheld_scan_code)
            if not values:
                continue
            line.update(values)
            line.handheld_scan_code = False

    def _get_handheld_scan_values(self, scanned_code):
        self.ensure_one()
        code = (scanned_code or '').strip()
        if not code:
            return {}

        lot = self._find_lot_by_scan_code(code)
        # Resolve an exact lot match before trying locations.  The allowed
        # lot relation can be temporarily stale while an editable move line
        # is being changed; treating a valid lot as a location then produces
        # the misleading "lot atau lokasi tidak terdaftar" error.
        values = {}
        if lot:
            values = {
                'confirmation_lot_code': code,
                'matching_lot_id': lot.id,
            }
        return values
    
    def _find_lot_by_scan_code(self, lot_code):
        Lot = self.env['stock.lot']
        lot_code = (lot_code or '').strip()
        if not lot_code:
            return Lot.browse()

        return Lot.search([('name', '=', lot_code)], limit=1)

    def action_mark_check_finished(self):
        self._validate_before_mark_finished()
        # match_status = self._get_matching_status_mo()   
        if self.match_status == 'not_match':
            raise ValidationError(f"Confirmation Lot {self.lot_id.name} belum match")

        self.write({
            'status': 'finished'
        })
        return {'type': 'ir.actions.act_window_close'}

    def action_mark_check_unfinished(self):
        self.write({'status': 'unfinished'})
        return self.scrap_move_id.action_show_details()

    def _validate_before_mark_finished(self):
        confirmation_quantity = self.scrapped_qty
        quantity = self.quantity

        rounding = self.product_uom_id.rounding if self.product_uom_id else 0.01
        comparison = float_compare(
            confirmation_quantity,
            quantity,
            precision_rounding=rounding,
        )

        if float_is_zero(
            confirmation_quantity,
            precision_rounding=rounding,
        ):
            raise UserError(f"Scrapped Qty Lot {self.lot_id.name} tidak boleh 0.")

        if comparison > 0:
            raise UserError("Scrapped Qty tidak boleh melebihi Quantity")

class ScrapStockPicking(models.Model):
    _inherit = 'stock.picking'

    scrap_ids = fields.One2many(
        "stock.scrap",
        "picking_id",
        string="Scraps",
    )

    show_generate_scrap = fields.Boolean(
        compute="_compute_show_generate_scrap"
    )

    @api.depends(
        "state",
        "adt_type",
        "scrap_ids",
        # "picking_type_id.operation_category",
    )
    def _compute_show_generate_scrap(self):
        for rec in self:
            rec.show_generate_scrap = (
                rec.state == "done"
                and rec.adt_type == "Disposal"
                # and rec.picking_type_id.operation_category == "receive"
                and not rec.scrap_ids
            )

    def action_generate_scrap(self):
        self.ensure_one()

        if not self.location_dest_id:
            raise UserError(_("Destination Location is required."))

        if self.state != "done":
            raise UserError(_("Only completed receipts can generate Scrap."))
        
        # if self.scrap_ids:
        #     raise UserError(_("Scrap has already been generated."))

        moves = self.move_ids.filtered(
            lambda m: m.state == "done"
            and m.quantity > 0
        )

        if not moves:
            raise UserError(_(
                "No available stock moves to generate Scrap."
            ))

        first_move = moves[0]

        scrap_location = self.env["stock.location"].search([
            ("scrap_location", "=", True),
            ("company_id", "in", [False, self.company_id.id]),
        ], limit=1)

        if not scrap_location:
            raise UserError(_("No Scrap Location configured."))

        scrap_lines = [
            (0,0, self._prepare_scrap_line_vals(move)) 
            for move in moves
        ]

        scrap = self.env["stock.scrap"].create({
            "origin": self.name,
            "company_id": self.company_id.id,
            "picking_id": self.id,
            "location_id": self.location_dest_id.id,
            "scrap_location_id": scrap_location.id,
            # dummy
            "product_id": first_move.product_id.id,
            "product_uom_id": first_move.product_uom.id,
            "scrap_qty": first_move.quantity,
            "scrap_line_ids": scrap_lines,
        })

        scrap._create_scrap_moves()

        if scrap.name == _("New"):
            scrap.name = (
                scrap.env["ir.sequence"]
                .next_by_code("stock.scrap")
                or _("New")
            )

        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.scrap",
            "view_mode": "form",
            "res_id": scrap.id,
        }

    def _prepare_scrap_line_vals(self, move):
            return {
                "receipt_move_id": move.id,
                "product_id": move.product_id.id,
                "product_uom_id": move.product_uom.id,
                "demand_qty": move.quantity,
                "location_id": move.location_dest_id.id,
                "name": move.description_picking 
                        or move.product_id.display_name,   
            }
