{
    "name": "WMS Push Notification",
    "version": "18.0.1.0.0",
    "category": "WMS",
    "summary": "Enable browser push notifications from the user menu",
    "depends": [
        "web",
        "mail",
    ],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "wms_push_notification/static/src/js/push_notification.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
