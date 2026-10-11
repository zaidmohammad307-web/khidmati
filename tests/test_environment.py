from pathlib import Path
import tempfile
import unittest

from _support import ROOT
from lib.environment import SECRET_KEYS, read_environment, setup_environment, validate_environment


class EnvironmentTests(unittest.TestCase):
    def root(self, directory):
        path = Path(directory)
        (path / ".env.example").write_bytes((ROOT / ".env.example").read_bytes())
        return path

    def test_setup_creates_distinct_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            self.assertTrue(setup_environment(root))
            values = read_environment(root / ".env")
            self.assertEqual(len(set(values[key] for key in SECRET_KEYS)), len(SECRET_KEYS))
            validate_environment(values)

    def test_rerunning_setup_preserves_credentials_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            setup_environment(root)
            before = (root / ".env").read_bytes()
            self.assertFalse(setup_environment(root))
            self.assertEqual((root / ".env").read_bytes(), before)

    def test_generated_credentials_have_no_compose_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            setup_environment(root)
            for key in SECRET_KEYS:
                self.assertRegex(read_environment(root / ".env")[key], r"^[a-f0-9]{64}$")

    def test_template_contains_no_working_passwords(self):
        values = read_environment(ROOT / ".env.example")
        self.assertTrue(all(not values[key] for key in SECRET_KEYS))

    def test_duplicate_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("ODOO_DB_NAME=a\nODOO_DB_NAME=b\n")
            with self.assertRaises(ValueError):
                read_environment(path)

    def test_env_reader_does_not_execute_shell_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            marker = Path(directory) / "marker"
            path.write_text(f"ODOO_LOGIN=$(touch {marker})\n")
            self.assertIn("$(touch", read_environment(path)["ODOO_LOGIN"])
            self.assertFalse(marker.exists())

    def test_application_and_bootstrap_roles_must_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            setup_environment(root)
            values = read_environment(root / ".env")
            values["ODOO_DB_USER"] = values["POSTGRES_USER"]
            with self.assertRaises(ValueError):
                validate_environment(values)


if __name__ == "__main__":
    unittest.main()
