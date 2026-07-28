import base64
import re
import traceback
import os
from PIL import Image
import qrcode
import io
import logging 
import json
import requests
from collections import defaultdict
from odoo import models, api, fields, _
from odoo.exceptions import ValidationError, UserError
from odoo.addons.tijari_wms_18.controllers.controllers import WmsApiController

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Memberi label unik untuk menghindari warning 'Same label: Type (Acumatica)'
    adt_receipt_nbr = fields.Char(string='Receipt Nbr (Acumatica)')
    adt_vendor_code = fields.Char(string='VendorID (Acumatica)')
    adt_partner_ref = fields.Char(string='Vendor Ref (Acumatica)')
    adt_branch_warehouse = fields.Char(string='Branch (Acumatica)')
    adt_actual_qty = fields.Float(string='Control Qty (Acumatica)')
    adt_is_hold = fields.Boolean(string='Hold (Acumatica)')
    adt_inventory_ref = fields.Char(string='Inventory Ref Nbr (Acumatica)')
    adt_acumatica_write_date = fields.Datetime(string='Last Modified (Acumatica)')
    adt_header_location_code = fields.Char(string='Header Location (Acumatica)')
    adt_post_period = fields.Char(string='Post Period (Acumatica)')
    adt_status = fields.Char(string='Status (Acumatica)')
    adt_total_qty = fields.Float(string='Total Qty (Acumatica)')
    
    adt_type = fields.Char(string='Type (Acumatica)')
    
    adt_external_ref = fields.Char(string='External Ref (Acumatica)')
    adt_warehouse_code = fields.Char(string='Warehouse (Acumatica)')
    adt_external_id = fields.Char(string='UUID Header Acumatica')
    adt_to_warehouse_code = fields.Char(string='To Warehouse (Acumatica)')
    adt_from_warehouse_code = fields.Char(string='From Warehouse (Acumatica)')
    adt_description = fields.Char(string='Description (Acumatica)')
    adt_is_document_only = fields.Boolean(string='Is Document Only', index=True, copy=False)

    adt_actual_amount = fields.Float(string='Control Amount (Acumatica)')
    adt_total_amount = fields.Float(string='Total Amount (Acumatica)')

    adt_receipt_type = fields.Char(string='Receipt Type (Acumatica)')
    adt_trans_type = fields.Char(string='Trans Type (Acumatica)')
    sync_state = fields.Selection([
        ('ready', 'Ready'),
        ('not_ready', 'Not Ready'),
    ], string='Sync State', default='ready', readonly=True, help='Data acumatica yg tidak sesuai dengan master yg ada di wms akan masuk ke state Not Ready, dan record tidak bisa di proses sampai data master nya sudah sinkron.')

    sync_message = fields.Char(string='Sync Message', readonly=True, help='Keterangan jika ada data acumatica yang tidak sesuai dengan master yang ada di wms.')
    adt_shipment_status = fields.Char(string='Shipment Status (Acumatica)')
    destination_location = fields.Char(string='to delete field')
    created_by = fields.Char(string='Created by')
    approved_by = fields.Char(string='Approved by')
    created_by_id = fields.Many2one("res.users", string='Created by')
    approved_by_id = fields.Many2one("res.users", string='Approved by')
    all_moves_picked = fields.Boolean(
        compute='_compute_all_moves_picked',
    )
    allowed_putaway_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_allowed_putaway_product_ids',
    )
    scan_product_button = fields.Boolean(string='Scan Product')
    putaway_product_id = fields.Many2one(
        'product.product', string="Product Name")
    putaway_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="LOT Number",
        compute='_compute_putaway_values',
        readonly=True,
    )
    putaway_move_line_ids = fields.Many2many(
        comodel_name="stock.move.line",
        string="Stock Move Lines",
        compute='_compute_putaway_values',
        readonly=False,
    )

    def write(self, vals):
        result = super().write(vals)
        if 'adt_is_document_only' not in vals and ({'origin', 'adt_type'} & set(vals)):
            self._set_acumatica_document_only_flag()
        if not self.env.context.get('skip_document_only_picking_type_sync') and (
            {'adt_is_document_only', 'picking_type_id', 'origin', 'adt_type'} & set(vals)
        ):
            self._set_document_only_picking_type()
        return result

    @staticmethod
    def _document_only_value(value):
        if isinstance(value, bool):
            return value
        if value in (False, None, ''):
            return False
        return str(value).strip().lower() in ('true', '1', 'yes', 'y', 'document only')

    def _set_acumatica_document_only_flag(self):
        staging_specs = [
            ('acumatica.receipt.line', 'receipt_nbr', 'document_only'),
            ('acumatica.transfer.line', 'reference_nbr', 'document_only'),
            ('acumatica.receipt.change.item.line', 'reference_nbr', 'document_only'),
            ('acumatica.inventory.recieved.line', 'reference_nbr', 'document_only'),
            ('acumatica.shipment.line', 'shipment_nbr', 'document_only'),
            ('acumatica.shipment.gi.staging', 'adt_ShipmentNbr', 'adt_DocumentOnly'),
            ('acumatica.issue.line', 'reference_nbr', 'document_only'),
            ('acumatica.inventory.issue.line', 'reference_nbr', 'document_only'),
            ('acumatica.issue.po.return.line', 'reference_nbr', 'document_only'),
            ('acumatica.transfer.shipment.line', 'shipment_nbr', 'document_only'),
            ('acumatica.transfer.one.step.line', 'reference_nbr', 'document_only'),
            ('acumatica.transfer.two.step.line', 'reference_nbr', 'document_only'),
            ('acumatica.direct.transfer.staging', 'adt_ReferenceNbr', 'adt_DocumentOnly'),
            ('acumatica.vendor.return.direct.transfer.staging', 'adt_ReferenceNbr', 'adt_DocumentOnly'),
            ('acumatica.receipt.external.line', 'reference_nbr', 'document_only'),
            ('acumatica.toko.pegang.do.line', 'reference_nbr', 'document_only'),
        ]
        for picking in self:
            if picking.adt_is_document_only or not picking.origin:
                continue
            is_document_only = False
            for model_name, reference_field, document_field in staging_specs:
                if model_name not in self.env.registry.models:
                    continue
                Model = self.env[model_name].sudo()
                if reference_field not in Model._fields or document_field not in Model._fields:
                    continue
                staging = Model.search([(reference_field, '=', picking.origin)], limit=1)
                if staging and self._document_only_value(staging[document_field]):
                    is_document_only = True
                    break
            if is_document_only:
                picking.sudo().with_context(skip_document_only_sync=True).write({'adt_is_document_only': True})
        self._set_document_only_picking_type()

    def _get_document_only_operation(self):
        self.ensure_one()
        picking_type_code = self.picking_type_id.code
        if picking_type_code == 'incoming':
            return 'direct_receipt'
        if picking_type_code == 'outgoing':
            return 'direct_delivery_order'

        adt_type = (self.adt_type or '').strip().lower()
        if any(token in adt_type for token in ('receipt', 'transfer in', 'return')):
            return 'direct_receipt'
        if any(token in adt_type for token in ('issue', 'shipment', 'delivery', 'transfer out')):
            return 'direct_delivery_order'
        return False

    def _set_document_only_picking_type(self):
        PickingType = self.env['stock.picking.type'].sudo()
        for picking in self:
            if not picking.adt_is_document_only:
                continue
            if picking.picking_type_id.is_document_only_api:
                continue

            operation = picking._get_document_only_operation()
            if not operation:
                continue

            warehouse = picking.picking_type_id.warehouse_id or picking.location_dest_id.warehouse_id or picking.location_id.warehouse_id
            document_only_type = PickingType.resolve_document_only_picking_type(
                target_operation_type=operation,
                document_only=True,
                warehouse_code=warehouse.code if warehouse else False,
            )
            if document_only_type and document_only_type != picking.picking_type_id:
                picking.with_context(skip_document_only_picking_type_sync=True).sudo().write({
                    'picking_type_id': document_only_type.id,
                })

    def _adt_preserve_document_only_destination(self):
        for picking in self:
            if not picking.adt_dest_location_id:
                continue
            if picking.location_dest_id != picking.adt_dest_location_id:
                picking.with_context(skip_document_only_sync=True).sudo().write({
                    'location_dest_id': picking.adt_dest_location_id.id,
                })
            picking.move_ids.sudo().write({
                'location_dest_id': picking.adt_dest_location_id.id,
                'adt_dest_location_id': picking.adt_dest_location_id.id,
            })
            picking.move_line_ids.sudo().write({
                'location_dest_id': picking.adt_dest_location_id.id,
            })


    wms_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('waiting', 'Waiting Another Operation'),
            ('confirmed', 'Waiting'),
            ('assigned', 'Ready'),
            ('waiting_response', 'Waiting For Shipment'),
            ('return_shipment', 'Returned Shipment'),
            ('done', 'Done'),
            ('cancel', 'Cancelled'),
        ],
        string="WMS State",
        compute="_compute_wms_state",
        store=True,
        copy=False,
        tracking=True,
    )

    shipment_information = fields.Selection([
        ('partial', 'Partial Shipment'),
        ('full_shipment', 'Full Shipment'),
        ('full_return', 'Canceled'),
    ], string='Informasi TMS', help='Status shipment yang akan dikirimkan dari TMS.')

    status_ba = fields.Selection([
        ('conform', 'Conform'),
        ('discrepancy', 'Discrepancy'),],
    string='Status BA',
    )

    transaction_type = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
        ('internal', 'Internal'),
    ], string='Type transaksi', readonly=True)

    def _get_putaway_move_lines(self):
        self.ensure_one()

        move_lines = self.move_line_ids.filtered(
                lambda line: line.quantity > 0 and (line.lot_id or line.lot_name)
            )
        if self.putaway_product_id:
            move_lines = move_lines.filtered(
                lambda line: line.product_id == self.putaway_product_id and line.quantity > 0
            )

        return move_lines

    @api.depends("state")
    def _compute_wms_state(self):
        for picking in self:
            if picking.state != "done":
                picking.wms_state = picking.state
            

    @api.depends('move_ids.product_id')
    def _compute_allowed_putaway_product_ids(self):
        for picking in self:
            picking.allowed_putaway_product_ids = picking.move_ids.product_id

    @api.depends(
        'putaway_product_id',
        'move_line_ids',
        'move_line_ids.product_id',
        'move_line_ids.lot_id',
    )
    def _compute_putaway_values(self):
        for picking in self:
            move_lines = picking._get_putaway_move_lines()
            picking.putaway_move_line_ids = move_lines
            picking.putaway_lot_id = (
                move_lines.mapped('lot_id')[:1]
                if picking.putaway_product_id
                else False
            )

    @api.onchange('putaway_product_id')
    def _onchange_putaway_product_id(self):
        for picking in self:
            move_lines = picking._get_putaway_move_lines()
            picking.putaway_move_line_ids = move_lines
            picking.putaway_lot_id = (
                move_lines.mapped('lot_id')[:1]
                if picking.putaway_product_id
                else False
            )

    def _set_document_only_done_quantities(self):
        MoveLine = self.env['stock.move.line'].sudo()
        for picking in self:
            for move in picking.move_ids.filtered(lambda line: line.state not in ('done', 'cancel')):
                quantity = move.product_uom_qty
                if not quantity:
                    continue

                move_lines = move.move_line_ids
                quantity_field = 'quantity' if 'quantity' in MoveLine._fields else 'qty_done'
                move.write({
                    'quantity': quantity,
                })
                if move_lines:
                    if len(move_lines) > 1:
                        move_lines[:-1].write({
                            quantity_field: 0.0,
                            'picked': False,
                        })
                    line_vals = {
                        quantity_field: quantity,
                        'picked': True,
                    }
                    if (
                        move.product_id.tracking != 'none'
                        and not move_lines[-1].lot_id
                        and not move_lines[-1].lot_name
                    ):
                        line_vals['lot_name'] = picking.origin or picking.name or 'DOCUMENT ONLY'
                    move_lines[-1].write(line_vals)
                else:
                    move_line_vals = {
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        quantity_field: quantity,
                        'picked': True,
                    }
                    if move.product_id.tracking != 'none':
                        move_line_vals['lot_name'] = picking.origin or picking.name or 'DOCUMENT ONLY'
                    MoveLine.create(move_line_vals)

                move.move_line_ids.flush_recordset([quantity_field, 'picked'])
                move.flush_recordset(['quantity', 'picked'])
                self.env.cr.execute(
                    "UPDATE stock_move_line SET picked = TRUE WHERE move_id = %s",
                    [move.id],
                )
                self.env.cr.execute(
                    "UPDATE stock_move SET picked = TRUE WHERE id = %s",
                    [move.id],
                )
                move.move_line_ids.invalidate_recordset(['picked'])
                move.invalidate_recordset(['picked'])

    def _process_document_only_validation_action(self, action):
        if not isinstance(action, dict):
            return

        model_name = action.get('res_model')
        context = action.get('context') or {}
        if model_name == 'stock.immediate.transfer':
            wizard = self.env[model_name].with_context(context).create({})
            wizard.process()
        elif model_name == 'stock.backorder.confirmation':
            wizard = self.env[model_name].with_context(context).create({})
            wizard.process_cancel_backorder()

    def action_validate_document_only_import(self, force=False):
        for picking in self:
            if force and not picking.adt_is_document_only:
                picking.sudo().write({'adt_is_document_only': True})
            if not picking.adt_is_document_only or picking.state in ('done', 'cancel'):
                continue
            if not picking.move_ids:
                raise UserError(_("Document only picking %s has no lines to validate.") % picking.display_name)

            picking._adt_preserve_document_only_destination()
            picking.action_confirm()
            picking.action_assign()
            picking.button_validate()
            picking._adt_preserve_document_only_destination()
            # picking._set_document_only_done_quantities()
            # action = picking.with_context().button_validate()
            # picking._process_document_only_validation_action(action)
        return True


# Function to foward adt_type from parent picking
    @api.model_create_multi
    def create(self, vals_list):
        # print("=" * 100)
        # print("CREATE PICKING")
        # traceback.print_stack(limit=15)        
        print('=' * 100)
        print("@api.model_create_multi")

        print(f"Self: {self}")
        print(f"Vals List: {vals_list}")

        # Karena vals_list adalah sebuah LIST, kita harus melakukan looping
        # for vals in vals_list:
        #     # Ambil nilai 'origin' dengan aman dari dictionary
        #     origin = vals.get('origin')
            
        #     if origin:
        #         # Perbaikan pencarian: menggunakan titik 'stock.picking' dan format domain yang benar
        #         parent_picking = self.env['stock.picking'].search([('origin', '=', origin)], limit=1)
                
        #         # Jika parent_picking ditemukan, salin nilai adt_type ke data baru
        #         if parent_picking and parent_picking.adt_type:
        #             vals['adt_type'] = parent_picking.adt_type

        # # Panggil fungsi super() dengan melewatkan vals_list yang sudah diperbarui
        pickings = super(StockPicking, self).create(vals_list)
        pickings._set_acumatica_document_only_flag()
        pickings._set_document_only_picking_type()
        print(pickings)
        return pickings


    def action_put_in_pack(self, move_lines_to_pack=False):
        self.ensure_one()

        if self.env.context.get('sml_specific_default'):
            self = self.with_context(
                clean_context(self.env.context)
            )

        if self.state in ('done', 'cancel'):
            return super().action_put_in_pack(
                move_lines_to_pack=move_lines_to_pack
            )

        move_line_ids = self._package_move_lines(
            move_lines_to_pack=move_lines_to_pack
        )

        if not move_line_ids:
            raise UserError((
                "There is nothing eligible to put in a pack."
            ))

        # packages = self.env['stock.quant.package']
        # for move in move_line_ids.mapped('move_id'):

        #     lines = move_line_ids.filtered(
        #         lambda ml: ml.move_id == move
        #     )

        #     package = self._put_in_pack(lines)

        #     packages |= package

        # return True

        move_line_ids = move_line_ids.filtered(
            lambda line:
                line.quantity > 0
                and not line.result_package_id
        )

        if not move_line_ids:
            raise UserError(
                _("There is nothing eligible to put in a pack.")
            )

        # Group move line berdasarkan destination location.
        packages = self.env["stock.quant.package"]

        # Satu move line diproses satu per satu.
        for move_line in move_line_ids:
            package = self._put_in_pack(move_line)
            packages |= package

        return packages[-1] if packages else False
    
    def _put_in_pack(self, move_line_ids):
        """
        Create a package and package level for move lines that have
        the same destination location.

        Custom behavior:
        - Preserve the existing `location_dest_id`.
        - Do not recalculate putaway strategy during packing.
        """
        self.ensure_one()

        if not move_line_ids.location_dest_id:
            raise UserError(
                (
                    "Destination location is missing for product %s."
                ) % move_line_ids.product_id.display_name
            )

        package = self._get_put_in_pack_package()

        package_type = (
            move_line_ids.move_id
            .product_packaging_id
            .package_type_id
        )

        if package_type:
            package.package_type_id = package_type

        move_line_ids.write({
            "result_package_id": package.id,
        })
        # Buat package level untuk package tersebut.
        self.env["stock.package_level"].with_context(
            from_put_in_pack=True
        ).create({
            "package_id": package.id,
            "picking_id": self.id,
            "location_id": False,
            "location_dest_id": move_line_ids.location_dest_id.id,
            "move_line_ids": [
                (6, 0, move_line_ids.ids)
            ],
            "company_id": self.company_id.id,
        })

        return package

    def _get_put_in_pack_package(self):
        return self.env['stock.quant.package'].create({})

    def _check_sync_state(self):
        for picking in self:
            if picking.sync_state == 'not_ready':
                raise UserError(
                    f'Picking {picking.name} tidak bisa diproses karena data tidak lengkap: {picking.sync_message}'
                )

    # def action_confirm(self):
    #     self._check_sync_state()
    #     return super().action_confirm()
    
    def action_confirm(self):
        _logger.info(">>> action_confirm CALLED %s", self.ids)

        res = super().action_confirm()
        
        for picking in self:
                    for move in picking.move_ids:
                        for line in move.move_line_ids:
                            print(line)
                            if line.lot_id:
                                print(line.lot_id)
                                print(f"write source_location: {line.lot_id.location_id.id} product_lot_id: {line.lot_id.id,}")
                                line.write({
                                    'source_location_id': line.lot_id.location_id.id or line.location_id.id,
                                    'product_lot_id': line.lot_id.id,
                                })        

        return res

    adt_dest_location_id = fields.Many2one(
        "stock.location",
        domain="[('usage', '=', 'internal')]",
        string="Mapped Location",
    )
    note_ba = fields.Text(string="Notes For Official Report")
    picking_type_name = fields.Char(string="Picking Type Name", related="picking_type_id.name", store=True)

    def _allow_custom_push_destination(self):
        self.ensure_one()
        # Untuk picking type incomine, kalo dibutuhkan untuk internal, manufacturing, dan lain lain bisa ditambahkan "self.picking_type_id.code in ["incoming", "internal", "manufacturing"]" atau yang lain sesuai kebutuhan
        return self.picking_type_id.code == "incoming"

    def action_send_email_hasil_picking(self):
        self.ensure_one()

        # partner = self.partner_id
        # if not partner or not partner.email:
        #     raise ValidationError('Partner belum memiliki email.')

        # Generate PDF dari report Odoo, lebih baik daripada panggil controller langsung
        controller = WmsApiController()
        response = controller.PrintWarehouseReceipt(id=self.id)

        if response.status_code != 200:
            raise UserError(f"Gagal mendapatkan PDF. Kode status: {response.status_code}")

        pdf_content = response.data
        pdf_base64 = base64.b64encode(pdf_content)

        attachment_new = self.env['ir.attachment'].sudo().create({
            'name': f"Picking {self.name}.pdf",
            'datas': pdf_base64.decode('utf-8'),
            'res_model': 'stock.picking',
            'res_id': self.id,
            'type': 'binary',
            'mimetype': 'application/pdf',
        })

        template = self.env.ref(
            'tijari_wms_18.email_template_stock_picking_custom',
            raise_if_not_found=False
        )

        return {
            'name': 'Kirim Email Berita Acara',
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'stock.picking',
                'default_res_ids': [self.id],
                'default_use_template': bool(template),
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_attachment_ids': [(6, 0, [attachment_new.id])],
            },
        }

    def action_open_stock_move_scan_wizard(self):
        self.ensure_one()

        wizard = self.env['stock.move.scan.wizard'].create({
            'picking_id': self.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': ('Scan Product'),
            'res_model': 'stock.move.scan.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    @api.depends('move_ids.picked')
    def _compute_all_moves_picked(self):
        for picking in self:
            moves = picking.move_ids
            picking.all_moves_picked = (
                bool(moves) and all(move.picked for move in moves)
            )

    def action_prepare_scan_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'adt_scan_qr_to_picking_product',
            'params': {
                'picking_id': self.id,
                'title': 'Scan Product QR Code',
            },
        }

    def _find_product_by_scan_code(self, scan_code):
        Product = self.env['product.product']

        return Product.search([
            '|',
            ('barcode', '=', scan_code),
            ('default_code', '=', scan_code),
        ], limit=1)

    def action_apply_scanned_product(self, scanned_code):
        self.ensure_one()
        scanned_code = (scanned_code or '').strip()
        product = self._find_product_by_scan_code(scanned_code)

        if not product:
            raise ValidationError("Product tidak ditemukan untuk kode scan: %s" % scanned_code)

        self.write({'putaway_product_id': product.id})

        return {
            'product_id': product.id,
            'display_name': product.display_name,
        }
    
    def action_mark_as_done(self):
        self.ensure_one()
        if self.wms_state == 'return_shipment':
            self.wms_state = 'done'

        else: 
            raise UserError('Shipment return tidak bisa diselesaikan tanpa membuat dokumen return')

    @api.onchange("state")
    def _onchange_state_update_wms_state(self):
        for picking in self:
            if picking.state == 'done':
                continue
            picking.wms_state = picking.state        


    def _format_datetime(self, dt):
        if not dt:
            return None

        if isinstance(dt, str):
            dt = Datetime.from_string(dt)

        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # ==========================================================
    # Prepare Payload
    # ==========================================================

    def _prepare_loginext_payload(self):
        self.ensure_one()
        print(self)

        print(self.origin)

        header_to_send = self.env["loginext.staging.data"].search(
            [("odoo_shipment_number", "=", self.origin)],
            limit=1,
        )
        print(header_to_send)

        if not header_to_send:
            raise UserError("Data staging TMS tidak dapat ditemukan")
        
        return {
            "orderNo": header_to_send.loginext_order_no,
            "shipmentOrderDt": self._format_datetime(
                header_to_send.loginext_shipment_order_dt
            ),
            "shipmentOrderTypeCd": header_to_send.loginext_shipment_order_type_cd,
            "orderState": header_to_send.loginext_order_state,
            "distributionCenter": header_to_send.loginext_distribution_center,
            "returnBranch": header_to_send.loginext_return_branch,
            "packageWeight": str(header_to_send.loginext_package_weight or 0),
            "packageVolume": str(header_to_send.loginext_package_volume or 0),
            "preparationTime": 30,
            "paymentType": header_to_send.loginext_payment_type,
            "packageValue": str(header_to_send.loginext_package_value or 0),
            "numberOfItems": header_to_send.loginext_number_of_items or 0,
            "partialDeliveryAllowedFl": "Y" if header_to_send.loginext_partial_delivery_allowed_fl else "N",
            "returnAllowedFl": "Y" if header_to_send.loginext_return_allowed_fl else "N",
            "cancellationAllowedFl": "Y" if header_to_send.loginext_cancellation_allowed_fl else "N",
            "deliverServiceTime": '30',
            "deliverStartTimeWindow": self._format_datetime(header_to_send.loginext_deliver_start_time_window),
            "deliverEndTimeWindow": self._format_datetime(header_to_send.loginext_deliver_end_time_window),
            "deliveryType": header_to_send.loginext_delivery_type,
            "deliverBranch": header_to_send.loginext_deliver_branch,
            "deliverAccountCode": header_to_send.loginext_deliver_account_code,
            "deliverAccountName": header_to_send.loginext_deliver_account_name,
            "deliverApartment": header_to_send.loginext_deliver_apartment,
            "deliverStreetName": header_to_send.loginext_deliver_street_name,
            "deliverLocality": header_to_send.loginext_deliver_locality,
            "deliverCity": header_to_send.loginext_deliver_city,
            "deliverState": header_to_send.loginext_deliver_state,
            "deliverCountry": header_to_send.loginext_deliver_country,
            "deliverPinCode": header_to_send.loginext_deliver_pin_code,
            "deliverAddressTimezone": header_to_send.loginext_deliver_address_timezone,
            "deliverNotes": header_to_send.loginext_deliver_notes,
            "shipmentCrateMappings": [
                {
                    "crateCd": crate.loginext_crate_cd,
                    "crateName": crate.loginext_crate_name,
                    "crateType": crate.loginext_crate_type,
                    "crateWeight": crate.loginext_crate_weight,
                    "shipmentlineitems": [
                        {
                            "itemCd": item.loginext_item_cd,
                            "itemName": item.loginext_item_name,
                            "itemPrice": item.loginext_item_price,
                            "itemQuantity": item.loginext_item_quantity,
                            "itemType": item.loginext_item_type,
                            "itemWeight": item.loginext_item_weight,
                        }
                        for item in crate.item_ids
                    ],
                }
                for crate in header_to_send.crate_ids
            ],
        }

    # ==========================================================
    # POST API
    # ==========================================================

    def action_post_loginext(self):
        print("=" * 80)
        print("Sent LOGINEXT REQUEST")
        self.wms_state = 'waiting_response'

        LOGIN_URL = "https://api.loginextsolutions.com/LoginApp/login/authenticate"
        CREATE_URL = "https://api.loginextsolutions.com/ShipmentApp/mile/v2/create"

        USERNAME = "api.tms@aditya.co.id"
        PASSWORD = "9CE5Q8Jz_#xXR"

        body = [
            rec._prepare_loginext_payload()
            for rec in self
        ]

        print("=" * 80)
        print("LOGINEXT REQUEST")
        print("=" * 80)
        print(json.dumps(body, indent=4))

        session = requests.Session()

        try:
            # ======================================================
            # LOGIN
            # ======================================================

            login_payload = {
                "userName": USERNAME,
                "password": PASSWORD,
                "sessionExpiryTimeout": "1",
            }

            login_response = session.post(
                LOGIN_URL,
                json=login_payload,
                timeout=30,
            )

            print("=" * 80)
            print("LOGINEXT LOGIN RESPONSE")
            print("=" * 80)
            print(f"Status : {login_response.status_code}")
            print(login_response.text)


            login_response.raise_for_status()
            www_authenticate = login_response.headers.get("WWW-Authenticate")
            # ======================================================
            # CREATE SHIPMENT
            # ======================================================

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            if www_authenticate:
                headers["WWW-Authenticate"] = www_authenticate

            print("Sent Response to Loginext")
            response = session.post(
                CREATE_URL,
                headers=headers,
                json=body,
                timeout=1,
            )

            print("=" * 80)
            print("LOGINEXT CREATE RESPONSE")
            print("=" * 80)
            print(f"Status : {response.status_code}")
            print(response.text)

            response.raise_for_status()

            print("=" * 80)
            print("END LOGINEXT REQUEST")
            print("=" * 80)

            res = self.button_validate()

            return res


        except requests.exceptions.RequestException as e:
            _logger.exception(e)
            raise UserError(f"Loginext API Error\n\n{e}")

    def action_get_loginext(self):
        _logger.info("=" * 80)
        _logger.info("Get LOGINEXT REQUEST")
        # print(self)
        """
        Get Shipment dari Loginext berdasarkan tanggal dan Order No.
        """

        LOGIN_URL = "https://api.loginextsolutions.com/LoginApp/login/authenticate"
        SHIPMENT_URL = "https://api.loginextsolutions.com/ShipmentApp/mile/v1/shipment"

        USERNAME = "api.tms@aditya.co.id"
        PASSWORD = "9CE5Q8Jz_#xXR"

        session = requests.Session()

        try:
            # ==========================================================
            # LOGIN
            # ==========================================================
            login_payload = {
                "userName": USERNAME,
                "password": PASSWORD,
                "sessionExpiryTimeout": "1",
            }

            login_response = session.post(
                LOGIN_URL,
                json=login_payload,
                timeout=30,
            )

            _logger.info("=" * 80)
            _logger.info("LOGINEXT LOGIN")
            _logger.info(login_response.text)
            _logger.info("=" * 80)

            login_response.raise_for_status()
            www_authenticate = login_response.headers.get("WWW-Authenticate")
            # ==========================================================
            # GET SHIPMENT
            # ==========================================================
            params = {
                "start_date": "2026-04-20 00:00:00",
                "end_date": "2026-07-23 00:00:00",
                "order_no": f"testing-dev-{self.origin}",
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }


            if www_authenticate:
                headers["WWW-Authenticate"] = www_authenticate

            response = session.get(
                SHIPMENT_URL,
                params=params,
                headers=headers,
                timeout=120,
            )

            _logger.info("=" * 80)
            _logger.info("LOGINEXT GET SHIPMENT")
            _logger.info("Request URL : %s", response.request.url)
            _logger.info("Status Code : %s", response.status_code)
            _logger.info(response.text)
            _logger.info("=" * 80)

            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            _logger.exception(e)
            raise UserError(f"Loginext API Error\n\n{e}")

    def action_assign(self):
        _logger.info(">>> action_assign CALLED %s", self.ids)

        res = super().action_assign()

        for picking in self:
            for move in picking.move_ids:
                for line in move.move_line_ids:
                    print(line)
                    if line.lot_id:
                        print(line.lot_id)
                        # vals = {
                        #     'source_location_id': line.lot_id.location_id.id or line.location_id.id,
                        # }
                        # vals['product_lot_id'] = line.lot_id.id
                        # line.write(vals)
                        print(f"write source_location: {line.lot_id.location_id.id} product_lot_id: {line.lot_id.id,}")
                        line.write({
                            'source_location_id': line.lot_id.location_id.id or line.location_id.id,
                            'product_lot_id': line.lot_id.id,
                        })

        return res  

    def action_confirm_shipment(self):
        self.ensure_one()
        if not self.shipment_information:
            raise UserError('Informasi TMS tidak boleh kosong')

        if self.shipment_information == 'full_shipment':
            self.wms_state = 'done'

        if self.shipment_information != 'full_shipment':
            self.wms_state = 'return_shipment'     

    def button_validate(self):
        for picking in self:
            # Pick harus diblokir sebelum validasi standar Odoo memproses
            # perpindahan stok apabila masih ada line yang belum Match.
            if picking.picking_type_id.name in ('Pick', 'Pick Internal'):
                picking._check_validate_requirements()

            if picking.picking_type_id.name not in ('Pick', 'Receipt'):
                print(f"Run validate all except pick and receipt")
                # Lakukan perulangan untuk setiap stock.move yang ada di dalam picking
                for move in picking.move_ids:
                    # Jika move memiliki move_line_ids, lakukan update massal di level DB
                    for line in move.move_line_ids:
                        loc_code = str(line.location_id.unique_code or '').strip()
                        product_code = str(line.lot_id.name or '').strip()
                        vals = {
                            'confirmation_location_code': loc_code,
                            'confirmation_lot_code': product_code,
                            'matching': 'match',
                        }
                        print(f"Write vals = {vals}")

                        line.write(vals)

                        print(f"After write = {line.matching}")

                        print(f"After write line {line.id} = {line.matching} for picking: {picking.id}")

        res = super().button_validate()

        for rec in self:
            print(rec.picking_type_id.name)
            for line in rec.move_line_ids:
                print(f">>> Validating line {line.id} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id},Picking id: {line.picking_id.id}, Picking Type: {line.picking_id.picking_type_id.name}, Status product: {line.picking_id.picking_type_id.operation_category}, Matching Status: {line.matching}") # Cek di terminal Odoo
                line.lot_name = line.lot_id.name if line.lot_id else line.lot_name
                if not line.lot_name:
                    print(f"Missing lot: {line}")
                    raise UserError(_("Validation blocked.\n Lot not Found Please generate lot for all lines before validating the picking."))
                

            picking._check_validate_requirements()
            operation_category = picking.picking_type_id.operation_category
            print(f">>> Validating picking {picking.id} - Picking Type: {picking.picking_type_id.name}, Operation Category: {operation_category}") # Cek di terminal Odoo

            # Hanya enforce untuk PUT dan DELIVERY
            if operation_category in ['put', 'delivery']:
                for line in picking.move_line_ids:
                    # Jika belum dicek (invisible), tidak dianggap ok
                    print(f">>> Checking line {line.matching} - Product: {line.product_id.display_name}, Lot Name: {line.lot_id.name if line.lot_id else 'N/A'}") # Cek di terminal Odoo
                    # line.matching = 'match'
                    print(f">>> Matching status for line {line.id}: {line.matching}") # Cek di terminal Odoo
                    if line.matching != 'match':
                        raise UserError(_(
                            "Validation blocked.\n\n"
                            "Line:\n"
                            f"- Product: {line.product_id.display_name}\n"
                            f"- Qty: {line.quantity or line.product_uom_qty}\n\n"
                            "Status: ❌ NOT MATCH\n\n"
                            "Silakan pastikan scan location dan/atau lot sudah benar."
                        ))
                                        
            pickings = self.env["stock.picking"].search([])
            if picking.picking_type_id.code != "incoming":
                continue

            storage_pickings = self.env["stock.picking"].search([
                ("origin", "ilike", picking.origin or picking.name),
                ("picking_type_id.code", "=", "internal"),
            ], limit=1)
            total_qty = sum(picking.move_ids.move_line_ids.mapped("quantity"))
            picking.write({
                'adt_total_qty': total_qty
            })

            storage_pickings.write({
                "adt_dest_location_id": picking.adt_dest_location_id,
                "adt_type": picking.adt_type,
                "note" : picking.note,
            })

            for storage in storage_pickings:
                for storage_move in storage.move_ids:
                    receipt_move = picking.move_ids.filtered(
                        lambda m: m.product_id == storage_move.product_id
                    )[:1]

                    if receipt_move:
                        storage_move.write({
                            "product_note": receipt_move.product_note,
                        })

            for move in picking.move_ids:
                if move.quantity > move.product_uom_qty:
                    total_qty = sum(line.mapped("quantity"))
                    raise UserError(
                        _(
                            "Product: %s\n"
                            "Lot: %s\n"
                            "Total QTY: %s\n"
                            "Demand: %s\n\n"
                            "Quantity exceeds demand."
                        ) % (
                            move.product_id.display_name,
                            line.lot_id.name or "-",
                            move.quantity,
                            move.product_uom_qty,
                        )
                    )

        return res

    def _check_validate_requirements(self):
        self.ensure_one()
        _logger.info("Check Validate on = %s", self.id)

        active_moves = self.move_ids.filtered(
            lambda move: move.state != "cancel"
        )

        unpicked_moves = active_moves.filtered(
            lambda move: not move.picked
        )

        unmatched_move_lines = active_moves.move_line_ids.filtered(
            lambda line: line.matching != "match"
        )

        error_messages = []

        if unpicked_moves:
            products = "\n".join(
                f"- {move.product_id.display_name}"
                for move in unpicked_moves
            )

            error_messages.append(
                (
                    "Semua product harus dalam kondisi picked.\n"
                    "Produk yang belum Terambil:\n%s"
                )
                % products
            )

        if unmatched_move_lines:
            lines = "\n".join(
                "- %s | Lot/Serial: %s | Matching: %s"
                % (
                    line.product_id.display_name,
                    line.lot_id.name or line.lot_name or "-",
                    dict(line._fields["matching"].selection).get(
                        line.matching,
                        line.matching or "-"
                    ),
                )
                for line in unmatched_move_lines
            )

            error_messages.append(
                (
                    "Semua product harus memiliki status matching "
                    "'Match'.\n"
                    "Detail produk yang belum match:\n%s"
                )
                % lines
            )

        if error_messages:
            raise UserError("\n\n".join(error_messages))


# ================================================================================================
# Temp Storage function create move line qr code        
# ================================================================================================

    def action_print_lot_number_line(self):
        self.ensure_one()

        if not self.lot_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Lot Number belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        lot_names = list({
            lot.name for lot in self.lot_ids if lot.name
        })

        if not lot_names:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Peringatan',
                    'message': 'Lot Number belum tersedia.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        self.create_qrcode_name()

        return {
            'type': 'ir.actions.act_url',
            'url': '/print/lot_number_move_line?ids=%s' % self.id,
            'target': 'new',
        }

    def create_qrcode_name(self):
        for rec in self:
            lot_names = list(set(
                rec.lot_ids.mapped('name')
            ))

            text = ', '.join(filter(None, lot_names))

            if text:
                rec.qr_code_image = rec.create_qrcode(text)

    def create_qrcode(self, text):
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../static/src/img/logo-company.png')
        )

        logo = Image.open(logo_path)

        basewidth = 80
        wpercent = basewidth / float(logo.size[0])
        hsize = int(float(logo.size[1]) * wpercent)

        logo = logo.resize((basewidth, hsize))

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H
        )

        qr.add_data(text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        img = img.resize((300, 300))

        pos = (
            (img.size[0] - logo.size[0]) // 2,
            (img.size[1] - logo.size[1]) // 2
        )

        img.paste(logo, pos)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        return base64.b64encode(buffer.getvalue()).decode()

    
class StockRule(models.Model):
    _inherit = "stock.rule"

    # Override method _push_prepare_move_copy_values untuk mengubah lokasi tujuan push berdasarkan adt_dest_location_id di stock.picking jika picking type incoming dan adt_dest_location_id terisi, sehingga bisa push ke lokasi selain location_dest_id yang sudah ditentukan di stock.rule
    def _push_prepare_move_copy_values(self, move_to_copy, new_date,):
        vals = super(StockRule, self)._push_prepare_move_copy_values(move_to_copy, new_date)
        print('='*300)
        print("_push_prepare_move_copy_values")
        print(f"Vals to create new picking: {vals}")
        # print(f"Parent Picking: {move_to_copy}")

        picking = move_to_copy.picking_id

        print(picking)
        if picking:
            # print("=== DAFTAR FIELD DAN NILAI ===")
            # for field_name, field_object in picking._fields.items():
            #     # Mengambil nilai field
            #     val = picking[field_name]
            
            #     if field_object.type == 'many2one' and val:
            #         print(f"{field_name}: {val.display_name} (ID: {val.id})")
            #     else:
            #         print(f"{field_name}: {val}")

            adt_type = picking.adt_type


            if adt_type:
                vals.update({
                    "adt_type": picking.adt_type if picking.adt_type else picking.name,
                    "transaction_type": picking.transaction_type,
                    # "adt_type": picking.adt_type
                })

        if (picking and picking.adt_dest_location_id and picking._allow_custom_push_destination()):
            vals.update({
                "location_dest_id": picking.adt_dest_location_id.id,
                "adt_dest_location_id": picking.adt_dest_location_id.id,
                # "adt_dest_location_id": picking.move_ids.adt_dest_location_id.id,
                "origin": picking.origin if picking.origin else picking.name
            })

        print(f"vals to update: {vals}")

        return vals


class StockPickingAcumaticaError(models.Model):
    _name = 'stock.picking.acumatica.error'
    _description = 'Error log untuk data picking yang diimport dari Acumatica'

    partner = fields.Char(string='Contact')
    operation_type = fields.Selection([
        ('receipt', 'Receipt'),
        ('delivery', 'Delivery'),
        ('internal', 'Internal'),
    ], string='Operation Type')

    location = fields.Char(string='Source Location')
    location_dest = fields.Char(string='Destination Location')
    scheduled_date = fields.Datetime(string='Scheduled Date')
    origin = fields.Char(string='Source Document')
    adt_total_qty = fields.Float(string='Total Qty (Acumatica)')
    adt_actual_qty = fields.Float(string='Actual Qty (Acumatica)')
    state = fields.Selection([
        ('new', 'New'),
        ('resolved', 'Resolved')
    ], default='new')

    api_acumatica = fields.Selection([
        ('po_receipt', 'PO Receipt'),
        ('so_transfer', 'SOTR Receipt'),
        ('receipt_change_item', 'Receipt Type Change Item'),
        ('inventory_received', 'Inventory Receive'),
        ('shipment_so', 'Shipment SO Return'),
        ('so_shipment', 'Sales Order Shipment'),
        ('transfer_shipment', 'Transfer Shipment'),
        ('issue_change_item', 'Issue Type Change Item'),
        ('inventory_issue', 'Inventory Issue'),
        ('issue_po_return', 'Issue Type PO Return'),
        ('transfer_one_step', 'Transfer Pinjaman (1 Step)'),
        ('transfer_two_step', 'Transfer Pinjaman (2 Step)'),
    ], string='API Acumatica', required=True)

    error_message = fields.Text(string='Error Message')
    line_ids = fields.One2many('stock.picking.acumatica.error.line', 'error_id', string='Error Lines')
    payload = fields.Json()

class StockPickingAcumaticaErrorLine(models.Model):
    _name = "stock.picking.acumatica.error.line"

    error_id = fields.Many2one(
        "stock.picking.acumatica.error",
        ondelete="cascade"
    )
    inventory_id = fields.Char(string="Product")
    product_name = fields.Char()
    qty = fields.Float(string="Demand")
    uom = fields.Char()
    payload = fields.Json()
