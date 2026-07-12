from odoo import models, api, fields
from odoo.exceptions import ValidationError, UserError
import base64


import os
from PIL import Image
import qrcode
import io


import logging
_logger = logging.getLogger(__name__)

from odoo.addons.tijari_wms_18.controllers.controllers import WmsApiController

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

        packages = self.env['stock.quant.package']

        for move in move_line_ids.mapped('move_id'):

            lines = move_line_ids.filtered(
                lambda ml: ml.move_id == move
            )

            package = self._put_in_pack(lines)

            packages |= package

        return True
    
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
            if picking.adt_dest_location_id:
                for move_line in picking.move_line_ids:
                    move_line.allocation_storage = move_line.adt_dest_location_id.id
            else:
                for move_line in picking.move_line_ids:
                    move_line.allocation_storage = picking.picking_type_id.warehouse_id.lot_stock_id.id

        return res

    adt_dest_location_id = fields.Many2one(
        "stock.location",
        domain="[('usage', '=', 'internal')]",
        string="Mapped Location",
    )
    note_ba = fields.Text(string="Notes For Official Report")

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
    def _push_prepare_move_copy_values(
        self,
        move_to_copy,
        new_date,
    ):
        vals = super()._push_prepare_move_copy_values(
            move_to_copy,
            new_date,
        )

        picking = move_to_copy.picking_id

        if (
            picking
            and picking.adt_dest_location_id
            and picking._allow_custom_push_destination()
        ):
            vals.update({
                "location_dest_id": picking.adt_dest_location_id.id,
                "adt_dest_location_id": picking.adt_dest_location_id.id,
                "adt_dest_location_id": picking.move_ids.adt_dest_location_id.id,
                "origin": picking.origin if picking.origin else picking.name
            })

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
