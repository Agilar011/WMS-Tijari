from odoo import _, fields, models
from odoo.exceptions import ValidationError


class GeneratePackageWizard(models.TransientModel):
    _name = 'generate.package.wizard'
    _description = 'Generate Package'

    package_cat = fields.Selection(
        selection=[
            ('box', 'Box'),
            ('palet', 'Palet'),
        ],
        string='Package Category',
        required=True,
        default='box',
    )

    quantity = fields.Integer(
        string='Quantity',
        required=True,
        default=1,
    )

    def action_generate(self):
        self.ensure_one()

        if self.quantity <= 0:
            raise ValidationError(
                _('Quantity harus lebih dari 0.')
            )

        vals_list = [
            {
                'package_cat': self.package_cat,
            }
            for _ in range(self.quantity)
        ]

        self.env['stock.quant.package'].create(vals_list)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _(
                    '%s package %s berhasil dibuat.'
                ) % (
                    self.quantity,
                    dict(self._fields['package_cat'].selection)[
                        self.package_cat
                    ],
                ),
                'type': 'success',
                'sticky': True,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            },
        }