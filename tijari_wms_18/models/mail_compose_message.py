from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    group_ids = fields.Many2many(
        comodel_name="res.groups",
        relation="mail_compose_message_res_group_rel",
        column1="wizard_id",
        column2="group_id",
        string="Recipient Groups",
        help="Recipients are taken from the users belonging to these groups.",
    )
    @api.depends(
        "composition_mode", "model", "parent_id", "record_name",
        "res_domain", "res_ids", "template_id",
    )
    def _compute_subject(self):
        super()._compute_subject()
        if not self.env.context.get("tijari_hasil_picking_email"):
            return

        for composer in self:
            if composer.model != "stock.picking":
                continue
            res_ids = composer._evaluate_res_ids()
            picking = self.env[composer.model].browse(res_ids[:1])
            if picking:
                composer.subject = picking.origin or picking.name

    @api.depends(
        "composition_mode", "model", "parent_id", "res_domain",
        "res_ids", "template_id",
    )
    def _compute_partner_ids(self):
        super()._compute_partner_ids()
        if self.env.context.get("tijari_hasil_picking_email"):
            for composer in self:
                composer.partner_ids = False

    def action_send_mail(self):
        if self.env.context.get("tijari_hasil_picking_email") and any(
            not composer.partner_ids for composer in self
        ):
            raise ValidationError(
                "Pilih minimal satu partner pada penerima email terlebih dahulu."
            )
        return super().action_send_mail()
