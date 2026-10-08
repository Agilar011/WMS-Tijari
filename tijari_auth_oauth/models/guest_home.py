from odoo import models, fields


class GuestHome(models.Model):
    _name = "tijari.guest.home"
    _description = "Guest Home"

    name = fields.Char(
        default="Guest Home",
        readonly=True,
    )