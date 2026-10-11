{
    "name": "Manufacturing Planning Cockpit",
    "version": "19.0.1.0.0",
    "author": "Deep Elements",
    "license": "LGPL-3",
    "depends": ["deep_shopfloor", "deep_data_import", "deep_material_risk"],
    "data": ["security/ir.model.access.csv", "security/rules.xml", "views/dashboard.xml"],
    "assets": {
        "web.assets_backend": [
            "deep_manufacturing_dashboard/static/src/*.js",
            "deep_manufacturing_dashboard/static/src/*.xml",
        ]
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
