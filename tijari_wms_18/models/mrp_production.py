from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import base64
from odoo.addons.tijari_wms_18.controllers.controllers import WmsApiController

import logging
_logger = logging.getLogger(__name__)

class WMSMRPProduction(models.Model):
    _inherit = "mrp.production"
    _description = "WMSMRPProduction"

    picking_type_name = fields.Char(
        related="picking_type_id.name",
        store=False,
    )
    catatan = fields.Text(string="Transaction Notes")
    desc_note = fields.Char('Description Note')

    def _prepare_stock_lot_values(self):
        self.ensure_one()
        product_code = self.product_id.default_code or f"PROD{self.product_id.id}"
        document_number = self.origin or self.name
        lot_name = "%s-%s-%s" % (
            product_code,
            fields.Date.today().strftime("%m%d%y"),
            document_number,
        )

        return {
            "product_id": self.product_id.id,
            "name": lot_name,
        }

    def _set_lot_producing(self):
        self.ensure_one()
        lot_values = self._prepare_stock_lot_values()
        lot = self.env["stock.lot"].search([
            ("product_id", "=", self.product_id.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
            ("name", "=", lot_values["name"]),
        ], limit=1)
        self.lot_producing_id = lot or self.env["stock.lot"].create(lot_values)

    def action_confirm(self):
        res = super().action_confirm()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })
        
        return res

    def action_confirm(self):
        res = super().action_confirm()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })

        return res

    def button_mark_done(self):
        for production in self:
            unfinished_moves = production.move_raw_ids.filtered(
                lambda move: move.status_mo_check != 'finished'
            )

            if unfinished_moves:
                details = "\n".join(
                    f"- {move.product_id.display_name}: {move.status_mo_check or 'Belum ada status'}"
                    for move in unfinished_moves
                )

                raise UserError(
                    "Tidak dapat menyelesaikan Manufacturing Order.\n\n"
                    "Raw Materials berikut belum memiliki status 'Finished':\n"
                    f"{details}"
                )

            if (
                production.product_id.tracking in ("lot", "serial")
                and not production.lot_producing_id
            ):
                production.action_generate_serial()

            for move in production.move_raw_ids:
                for line in move.move_line_ids:
                    confirmation_quantity = line.mo_confirmation_quantity

                    line.quantity_shadow = line.quantity
                    line.quantity = confirmation_quantity

        res = super().button_mark_done()

        for production in self:
            if production.origin:
                production.picking_ids.write({
                    "origin": production.origin,
                })
        
        return res

    def action_print_hasil_manufacturing(self):
        action = {}
        action['type'] = 'ir.actions.act_url'
        action['url'] = '/print/hasil_manufacturing?id=' + str(self.id)
        action['target'] = 'new'
        return action

    def action_send_email_hasil_manufacturing(self):
        self.ensure_one()

        response = WmsApiController().PrintHasilManufacturing(id=self.id)
        content_type = response.headers.get('Content-Type', '')
        if (
            response.status_code != 200
            or not response.data
            or 'application/pdf' not in content_type.lower()
        ):
            raise UserError(_('Gagal membuat PDF hasil manufacturing.'))

        attachment = self.env['ir.attachment'].sudo().create({
            'name': '%s_hasil_manufacturing.pdf' % (self.origin or self.name or 'manufacturing'),
            'datas': base64.b64encode(response.data).decode('utf-8'),
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
            'mimetype': 'application/pdf',
        })
        template = self.env.ref(
            'tijari_wms_18.email_template_hasil_manufacturing',
            raise_if_not_found=False,
        )

        return {
            'name': _('Kirim Email Hasil Manufacturing'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': self._name,
                'default_res_ids': [self.id],
                'default_use_template': bool(template),
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_attachment_ids': [(6, 0, [attachment.id])],
                'force_email': True,
                'tijari_hasil_manufacturing_email': True,
            },
        }
