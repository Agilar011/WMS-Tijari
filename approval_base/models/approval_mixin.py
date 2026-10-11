from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError


class ApprovalMixin(models.AbstractModel):
    _name = "approval.mixin"
    _description = "Approval Mixin"

    approval_type_id = fields.Many2one(
        "approval.type",
        string="Approval Type",
    )

    approval_request_id = fields.Many2one(
        "approval.request",
        string="Approval Request",
        copy=False,
    )

    approval_state = fields.Selection(
        related="approval_request_id.state",
        store=True,
        readonly=True,
    )

    current_approver_id = fields.Many2one(
        related="approval_request_id.current_user_id",
        store=True,
        readonly=True,
    )

    approval_line_ids = fields.One2many(
        comodel_name="approval.request.line",
        related="approval_request_id.line_ids",
        readonly=True,
    )  

    def write(self, vals):
        cancel_document = vals.get("state") in {"cancel", "cancelled"}
        approval_requests = self.env["approval.request"]
        if cancel_document:
            approval_requests = self.mapped("approval_request_id")

        result = super().write(vals)

        if cancel_document:
            approval_requests |= self.mapped("approval_request_id")
            approval_requests.filtered(
                lambda request: request.state != "cancelled"
            ).write({"state": "cancelled"})

        return result

    def action_submit_approval(self):
        self.ensure_one()

        if not self.approval_type_id:
            raise ValidationError(_("Approval Type is required."))


        return self._create_approval_request()

    def _create_approval_request(self):
        self.ensure_one()

        request = self.env["approval.request"].create_from_type(
            self.approval_type_id,
            self,
        )

        self.approval_request_id = request
        return request

    def action_approve(self):
        self.ensure_one()

        if not self.approval_request_id:
            raise UserError("This document has no approval request.")

        return self.approval_request_id.action_approve()


    def action_reject(self):
        self.ensure_one()

        if not self.approval_request_id:
            raise UserError("This document has no approval request.")

        return self.approval_request_id.action_reject()
    
    ### HELPER ###
    def _approval_approved(self):
        """Hook called when approval is fully approved."""
        return True

    def _approval_rejected(self):
        """Hook called when approval is rejected."""
        return True

    def _get_approval_amount(self):
        """
        Return amount used for amount-based approval.
        Override in business models.
        """
        self.ensure_one()
        return 0.0
    