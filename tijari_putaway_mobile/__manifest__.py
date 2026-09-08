{
    "name": "Tijari Putaway Mobile",
    "version": "18.0.0.1.0",
    "summary": "Mobile putaway screen with location and lot scan validation",
    "category": "Warehouse",
    "author": "Tijari",
    "license": "LGPL-3",
    "depends": [
        "stock",
        "tijari_wms_18",
    ],
    "data": [
        "views/templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "tijari_putaway_mobile/static/src/scss/putaway_mobile.scss",
            "tijari_putaway_mobile/static/src/js/putaway_mobile.js",
        ],
    },
    "installable": True,
    "application": True,
}
