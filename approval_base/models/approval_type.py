from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ApprovalType(models.Model):
    _name = "approval.type"
    _description = "Approval Type"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(
        required=True,
        tracking=True,
    )

    code = fields.Char(
        required=True,
    )

    approval_model_id = fields.Many2one(
        "approval.model",
        # required=True,
    )

    is_amount_based = fields.Boolean('Is Amount Based?')

    active = fields.Boolean(
        default=True,
    )

    line_ids = fields.One2many(
        "approval.type.line",
        "approval_type_id",
        string="Approval Lines",
        copy=True,
    )

    range_ids = fields.One2many(
        "approval.type.range",
        "approval_type_id",
        string="Approval Ranges",
    )

    def _get_approval_lines(self, amount=0):
        self.ensure_one()

        if not self.is_amount_based:
            return self.line_ids

        rule = self.range_ids.filtered(
            lambda r:
                r.min_amount <= amount
                and (
                    not r.max_amount
                    or amount <= r.max_amount
                )
        )[:1]

        if not rule:
            raise ValidationError(
                _("No approval range configured.")
            )

        return rule.line_ids
    
class ApprovalTypeLine(models.Model):
    _name = "approval.type.line"
    _description = "Approval Type Line"
    _order = "sequence,id"

    name = fields.Char(
        string="Role",
        # required=True,
    )

    approval_type_id = fields.Many2one(
        "approval.type",
        required=True,
        ondelete="cascade",
    )

    sequence = fields.Integer(
        default=1,
    )

    user_id = fields.Many2one(
        "res.users",
        required=True,
    )

class ApprovalTypeRange(models.Model):
    _name = "approval.type.range"
    _description = "Approval Type Range"
    _order = "min_amount"

    approval_type_id = fields.Many2one(
        "approval.type",
        required=True,
        ondelete="cascade",
    )

    name = fields.Char(required=True)

    min_amount = fields.Float(
        required=True,
    )

    max_amount = fields.Float(
        help="Leave empty for no upper limit."
    )

    line_ids = fields.One2many(
        "approval.type.range.line",
        "range_id",
    )

    approver_count = fields.Integer(
        compute="_compute_approver_count",
        string="Approvers",
    )

    @api.depends("line_ids")
    def _compute_approver_count(self):
        for rec in self:
            rec.approver_count = len(rec.line_ids)
    
    ### CONSTRAINTS ###
    @api.constrains("min_amount", "max_amount")
    def _check_amount(self):
        for rec in self:
            if rec.max_amount and rec.min_amount > rec.max_amount:
                raise ValidationError(
                    _("Minimum amount cannot be greater than maximum amount.")
                )

    @api.constrains("min_amount", "max_amount", "approval_type_id")
    def _check_overlap(self):
        for rec in self:
            others = rec.approval_type_id.range_ids - rec

            for other in others:
                rec_max = rec.max_amount or float("inf")
                other_max = other.max_amount or float("inf")

                if rec.min_amount <= other_max and other.min_amount <= rec_max:
                    raise ValidationError(
                        _("Approval ranges cannot overlap.")
                    )
                
class ApprovalTypeRangeLine(models.Model):
    _name = "approval.type.range.line"
    _description = "Approval Type Range Line"
    _order = "sequence"

    range_id = fields.Many2one(
        "approval.type.range",
        required=True,
        ondelete="cascade",
    )

    sequence = fields.Integer(default=10)

    name = fields.Char()

    user_id = fields.Many2one(
        "res.users",
        required=True,
    )