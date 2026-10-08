{
    "name": "Approval Base",
    "version": "18.0.1.0.0",
    "depends": [
        "base",
        "mail",
        "hr",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir.sequence.xml",
        # "data/approval_model_data.xml",

        "views/approval_type_views.xml",
        "views/approval_request_views.xml",
        "views/approval_menu.xml",
    ],
    "application": True,
}
