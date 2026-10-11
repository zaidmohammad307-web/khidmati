from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "scripts"))


def valid_environment():
    return {
        "ODOO_DB_HOST": "db",
        "ODOO_DB_PORT": "5432",
        "ODOO_DB_NAME": "deep_pilot",
        "ODOO_DB_USER": "odoo_app",
        "ODOO_DB_PASSWORD": "db-secret-should-stay-private",
        "ODOO_ADMIN_PASSWD": "manager-secret-should-stay-private",
        "ODOO_LOGIN": "admin",
        "ODOO_LOGIN_PASSWORD": "login-secret-should-stay-private",
        "ODOO_BOOTSTRAP_MODULES": "base,web,mrp,purchase_stock,hr",
    }
