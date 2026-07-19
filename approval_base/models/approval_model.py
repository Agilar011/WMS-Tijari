from odoo import _, api, fields, models

class ApprovalModel(models.Model):
    _name = "approval.model"
    _description = "Approval Supported Model"

    name = fields.Char(required=True)
    model_id = fields.Many2one(
        "ir.model",
        required=True,
        ondelete="cascade",
    )

    model = fields.Char(
        related="model_id.model",
        store=True,
    )

    active = fields.Boolean(default=True)