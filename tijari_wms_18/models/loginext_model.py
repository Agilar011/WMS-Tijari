from odoo import fields, models

class LoginextMasterCountry(models.Model):
    _name = "loginext.master.country"
    _description = "Loginext Master Country"

    country = fields.Char(string="Country")
    code = fields.Char(string="Code")


class LoginextMasterState(models.Model):
    _name = "loginext.master.state"
    _description = "Loginext Master State"
    _rec_name = "state"

    state = fields.Char(string="State")
    code = fields.Char(string="Code")