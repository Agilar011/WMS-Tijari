from odoo.exceptions import AccessDenied


class AccountNotRegistered(AccessDenied):
    """Raised when OAuth user is not registered in Odoo."""
    pass