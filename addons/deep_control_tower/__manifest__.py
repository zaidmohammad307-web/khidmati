{
    "name": "Manufacturing Operations Control Tower",
    "version": "19.0.2.0.0",
    "author": "Deep Elements",
    "license": "LGPL-3",
    "depends": [
        "deep_operations",
        "deep_maintenance",
        "deep_planning_plus",
        "deep_quality_plus",
        "deep_contracts",
    ],
    "data": ["views/control_tower.xml"],
    "assets": {
        "web.assets_backend": [
            "deep_control_tower/static/src/*.js",
            "deep_control_tower/static/src/*.xml",
            "deep_control_tower/static/src/*.scss",
        ]
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
