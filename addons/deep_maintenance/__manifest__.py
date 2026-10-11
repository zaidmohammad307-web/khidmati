{
    "name": "Equipment Downtime / Preventive Maintenance",
    "version": "19.0.2.0.0",
    "author": "Deep Elements",
    "license": "LGPL-3",
    "depends": ["deep_operations", "maintenance"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/crons.xml",
        "views/maintenance.xml",
        "views/native.xml",
    ],
    "installable": True,
}
