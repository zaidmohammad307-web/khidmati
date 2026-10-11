import configparser
import os
import tempfile
import unittest
from pathlib import Path

from _support import ROOT, valid_environment
from configuration import (
    ConfigurationError,
    database_settings,
    module_names,
    private_config,
    render_config,
)


class ConfigurationTests(unittest.TestCase):
    def test_exact_database_filter_and_native_addon_paths(self):
        settings = render_config(valid_environment(), ROOT / "config/odoo.conf")
        self.assertEqual(settings.get("options", "dbfilter"), "^deep_pilot$")
        self.assertEqual(settings.get("options", "db_name"), "deep_pilot")
        self.assertFalse(settings.getboolean("options", "list_db"))
        self.assertIn("/mnt/extra-addons", settings.get("options", "addons_path"))

    def test_missing_secret_is_rejected_without_printing_other_secrets(self):
        values = valid_environment()
        values["ODOO_DB_PASSWORD"] = ""
        with self.assertRaises(ConfigurationError) as raised:
            render_config(values, ROOT / "config/odoo.conf")
        self.assertIn("ODOO_DB_PASSWORD", str(raised.exception))
        self.assertNotIn(values["ODOO_ADMIN_PASSWD"], str(raised.exception))

    def test_newline_configuration_injection_is_rejected(self):
        values = valid_environment()
        values["ODOO_ADMIN_PASSWD"] = "private\nlist_db = True"
        with self.assertRaises(ConfigurationError):
            render_config(values, ROOT / "config/odoo.conf")

    def test_privileged_database_role_is_rejected(self):
        values = valid_environment()
        values["ODOO_DB_USER"] = "postgres"
        with self.assertRaises(ConfigurationError):
            database_settings(values)

    def test_invalid_identifiers_and_ports_are_rejected(self):
        for key, value in (
            ("ODOO_DB_NAME", "deep.*"),
            ("ODOO_DB_USER", "u;DROP DATABASE x"),
            ("ODOO_DB_PORT", "0"),
            ("ODOO_DB_PORT", "65536"),
            ("ODOO_DB_PORT", "abc"),
        ):
            with self.subTest(key=key, value=value):
                values = {**valid_environment(), key: value}
                with self.assertRaises(ConfigurationError):
                    database_settings(values)

    def test_private_temp_file_round_trip(self):
        path = private_config(valid_environment(), ROOT / "config/odoo.conf")
        try:
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            parser = configparser.RawConfigParser()
            parser.read(path)
            self.assertEqual(
                parser.get("options", "db_password"), valid_environment()["ODOO_DB_PASSWORD"]
            )
        finally:
            path.unlink()

    def test_missing_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigurationError):
                render_config(valid_environment(), Path(directory) / "missing.conf")

    def test_required_native_modules_cannot_be_omitted(self):
        values = {**valid_environment(), "ODOO_BOOTSTRAP_MODULES": "base,web"}
        with self.assertRaises(ConfigurationError):
            module_names(values)

    def test_verified_database_tls_reaches_both_native_clients_and_config(self):
        values = {
            **valid_environment(),
            "ODOO_DB_SSLMODE": "verify-full",
            "ODOO_HTTP_INTERFACE": "127.0.0.1",
            "ODOO_PROXY_MODE": "1",
        }
        self.assertEqual(database_settings(values)["sslmode"], "verify-full")
        config = render_config(values, ROOT / "config/odoo.conf")
        self.assertEqual(config.get("options", "db_sslmode"), "verify-full")
        self.assertEqual(config.get("options", "http_interface"), "127.0.0.1")
        self.assertTrue(config.getboolean("options", "proxy_mode"))

    def test_invalid_database_tls_mode_is_refused(self):
        with self.assertRaises(ConfigurationError):
            database_settings({**valid_environment(), "ODOO_DB_SSLMODE": "verify-false"})


if __name__ == "__main__":
    unittest.main()
