{
    "name": "Production Planning",
    "version": "19.0.2.0.0",
    "author": "Deep Elements",
    "license": "LGPL-3",
    "depends": ["mrp", "purchase_stock", "hr", "web", "mail"],
    "application": True,
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "security/rules.xml",
        "views/core.xml",
        "views/native.xml",
        "report/labels.xml",
        "views/configuration.xml",
    ],
    "installable": True,
}
