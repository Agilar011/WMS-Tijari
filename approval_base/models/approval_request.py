from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ApprovalRequest(models.Model):
    _name = "approval.request"
    _description = "Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        default="New",
        copy=False,
        readonly=True,
    )

    approval_type_id = fields.Many2one(
        "approval.type",
        required=True,
        tracking=True,
    )

    state = fields.Selection([
        ("waiting", "Waiting"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ], default="waiting", tracking=True)

    line_ids = fields.One2many(
        "approval.request.line",
        "request_id",
        string="Approval Lines",
        copy=False,
    )

    current_line_id = fields.Many2one(
        "approval.request.line",
        compute="_compute_current_line",
        store=True,
    )

    current_user_id = fields.Many2one(
        "res.users",
        related="current_line_id.user_id",
        store=True,
    )

    reference = fields.Char()

    source_model = fields.Char(readonly=True)
    source_id = fields.Integer(readonly=True)

    def _check_current_approver(self):
        if self.state != "waiting":
            raise UserError(_("Approval request is already finished."))

        if self.current_user_id != self.env.user:
            raise UserError(_("You are not the current approver."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                model = vals.get("source_model")

                sequence = self.env["ir.sequence"].next_by_code(
                    f"approval.request.{model}"
                )

                if not sequence:
                    sequence = self.env["ir.sequence"].next_by_code(
                        "approval.request"
                    )

                vals["name"] = f"APR/{model.upper()}/{sequence}"

        return super().create(vals_list)

    @api.depends("line_ids.state")
    def _compute_current_line(self):
        for rec in self:
            waiting = rec.line_ids.filtered(
                lambda l: l.state == "waiting"
            ).sorted("sequence")

            rec.current_line_id = waiting[:1]

    def action_generate_lines(self):
        self.ensure_one()
        self.line_ids.unlink()

        approval_type = self.approval_type_id
        document = self._get_source_document()

        approval_lines = []
        amount = document._get_approval_amount()
        lines = approval_type._get_approval_lines(amount)

        for template in lines.sorted("sequence"):
            approval_lines.append((0, 0, {
                "sequence": template.sequence,
                "role": template.name,
                "user_id": template.user_id.id,
            }))

        self.write({
            "line_ids": approval_lines
        })
    
    @api.model
    def create_from_type(self, approval_type, document):
        request = self.create({
            "approval_type_id": approval_type.id,
            "source_model": document._name,
            "source_id": document.id,
            "reference": document.display_name,
        })

        request.action_generate_lines()

        return request

    def action_approve(self):
        self.ensure_one()

        self._check_current_approver()

        line = self.current_line_id

        line.write({
            "state": "approved",
            "action_date": fields.Datetime.now(),
        })

        waiting = self.line_ids.filtered(
            lambda l: l.state == "waiting"
        )

        if not waiting:
            self.state = "approved"
            document = self.env[self.source_model].browse(self.source_id)
            document._approval_approved()
    
    def action_reject(self):
        self.ensure_one()

        self._check_current_approver()

        line = self.current_line_id

        line.write({
            "state": "rejected",
            "action_date": fields.Datetime.now(),
        })

        self.state = "rejected"
        document = self.env[self.source_model].browse(self.source_id)
        document._approval_rejected()
    
    ### HELPER FUNCTION ###
    def _get_source_document(self):
        self.ensure_one()
        return self.env[self.source_model].browse(self.source_id)
    
class ApprovalRequestLine(models.Model):
    _name = "approval.request.line"
    _description = "Approval Request Line"
    _order = "sequence"

    request_id = fields.Many2one(
        "approval.request",
        required=True,
        ondelete="cascade",
    )

    sequence = fields.Integer()

    role = fields.Char()

    user_id = fields.Many2one(
        "res.users",
        required=True,
    )

    state = fields.Selection([
        ("waiting", "Waiting"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ], default="waiting")

    action_date = fields.Datetime()

    remark = fields.Text()     