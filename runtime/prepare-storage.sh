#!/bin/sh
set -eu
mkdir -p /var/lib/odoo
chown odoo:odoo /var/lib/odoo
# Leave existing files untouched; a restore produces files through the native Odoo account.
install -d -m 750 -o odoo -g odoo /var/lib/odoo/deep-secrets
if [ -f /run/source-secret/sap-password.txt ]; then
    install -m 600 -o odoo -g odoo /run/source-secret/sap-password.txt /var/lib/odoo/deep-secrets/sap-password.txt
fi
