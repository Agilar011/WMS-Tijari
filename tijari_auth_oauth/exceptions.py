from odoo.exceptions import AccessDenied


class AccountNotRegistered(AccessDenied):
    """Raised when OAuth user is not registered in Odoo."""
    pass


class OAuthAccessDenied(AccessDenied):
    """Raised when an OAuth login is denied for a specific reason."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__()