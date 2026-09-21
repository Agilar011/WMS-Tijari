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

    def _get_group_partner_ids(self):
        self.ensure_one()
        return self.group_ids.mapped("users.partner_id").filtered("email")

    @api.onchange("group_ids")
    def _onchange_group_ids(self):
        for composer in self:
            composer.partner_ids = composer._get_group_partner_ids()

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
            picking = self.env[composer.model].browse(
                composer._evaluate_res_ids()[:1]
            )
            document_type = picking.adt_type or ""
            document_number = picking.origin or picking.name
            composer.subject = (
                f"Berita Acara Penerimaan Barang - {document_type} - {document_number}"
                if document_number
                else "Berita Acara Penerimaan Barang"
            )

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
        for composer in self:
            if composer.group_ids:
                composer.partner_ids = (
                    composer.partner_ids | composer._get_group_partner_ids()
                )
        if self.env.context.get("tijari_hasil_picking_email") and any(
            not composer.partner_ids for composer in self
        ):
            raise ValidationError(
                "Pilih minimal satu partner pada penerima email terlebih dahulu."
            )
        return super().action_send_mail()
