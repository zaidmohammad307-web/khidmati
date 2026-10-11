{
    "name": "Manufacturing Shop Floor",
    "version": "19.0.2.0.0",
    "author": "Deep Elements",
    "license": "LGPL-3",
    "depends": ["deep_rework", "deep_capacity_planning"],
    "data": ["views/shopfloor.xml"],
    "assets": {
        "web.assets_backend": [
            "deep_shopfloor/static/src/components/*.js",
            "deep_shopfloor/static/src/components/*.xml",
            "deep_shopfloor/static/src/views/*.js",
            "deep_shopfloor/static/src/views/*.xml",
            "deep_shopfloor/static/src/scss/*.scss",
        ]
    },
    "installable": True,
}
