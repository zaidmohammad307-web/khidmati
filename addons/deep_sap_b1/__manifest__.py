{
    "name": "SAP Business One VPN Integration",
    "version": "19.0.2.0.0",
    "author": "Deep Elements",
    "license": "LGPL-3",
    "depends": ["deep_control_tower", "auth_totp"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/crons.xml",
        "views/sap.xml",
        "views/native.xml",
    ],
    "installable": True,
}
