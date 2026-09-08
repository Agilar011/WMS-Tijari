from odoo import fields, models


class TijariPackageLevelDetailWizard(models.TransientModel):
    _name = "package.level.detail.wizard"
    _description = "Package Level Detail"
 
    package_level_id = fields.Many2one('stock.package_level', string='package level')

    status = fields.Selection(
        [
            ("finished", "Finished"),
            ("unfinished", "Unfinished"),
        ],
        string="Status",
        default="unfinished",
        readonly=True,
    )

    package_id = fields.Many2one(
        "stock.quant.package",
        string="Package",
        readonly=True,
    )

    package_cat = fields.Selection(
        [
            ("box", "Box"),
            ("palet", "Palet"),
        ],
        string="Package Category",
        related="package_id.package_cat",
        readonly=True,
    )

    move_line_ids = fields.Many2many(
        "stock.move.line",
        string="Move Lines",
        readonly=True,
    )

    def action_mark_finished(self):
        self.package_level_id.write({'status': 'finished'})
        return True
    
    def action_mark_unfinished(self):
        self.package_level_id.write({'status': 'unfinished'})
        return True
