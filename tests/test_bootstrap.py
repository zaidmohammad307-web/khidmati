from pathlib import Path
import unittest
from unittest.mock import patch

from _support import valid_environment
import entrypoint


class BootstrapTests(unittest.TestCase):
    def test_existing_database_never_resets_password(self):
        with (
            patch.dict(entrypoint.os.environ, valid_environment(), clear=True),
            patch.object(
                entrypoint,
                "installed_modules",
                return_value={"base", "web", "mrp", "purchase_stock", "hr"},
            ),
            patch.object(entrypoint.subprocess, "run") as command,
        ):
            entrypoint.initialize(Path("private.conf"), valid_environment())
            command.assert_not_called()

    def test_new_install_sets_admin_only_after_native_install_succeeds(self):
        with (
            patch.dict(entrypoint.os.environ, valid_environment(), clear=True),
            patch.object(entrypoint, "installed_modules", return_value=set()),
            patch.object(entrypoint.subprocess, "run") as command,
        ):
            entrypoint.initialize(Path("private.conf"), valid_environment())
            self.assertEqual(command.call_count, 2)
            first, second = command.call_args_list
            self.assertIn("--init=base,web,mrp,purchase_stock,hr", first.args[0])
            self.assertEqual(second.args[0][1], "shell")
            for call in command.call_args_list:
                self.assertNotIn(valid_environment()["ODOO_LOGIN_PASSWORD"], " ".join(call.args[0]))

    def test_failed_native_install_does_not_configure_admin(self):
        import subprocess

        with (
            patch.dict(entrypoint.os.environ, valid_environment(), clear=True),
            patch.object(entrypoint, "installed_modules", return_value=set()),
            patch.object(
                entrypoint.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["odoo"])
            ) as command,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                entrypoint.initialize(Path("private.conf"), valid_environment())
            self.assertEqual(command.call_count, 1)

    def test_partial_existing_install_preserves_existing_user(self):
        with (
            patch.dict(entrypoint.os.environ, valid_environment(), clear=True),
            patch.object(entrypoint, "installed_modules", return_value={"base", "web"}),
            patch.object(entrypoint.subprocess, "run") as command,
        ):
            entrypoint.initialize(Path("private.conf"), valid_environment())
            self.assertEqual(command.call_count, 1)


if __name__ == "__main__":
    unittest.main()
