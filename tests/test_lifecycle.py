import subprocess
import unittest
from unittest.mock import Mock

from _support import ROOT
from lib.docker import Docker


class LifecycleTests(unittest.TestCase):
    def test_failed_backup_restores_running_state(self):
        docker = Docker(ROOT)
        docker.compose = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="db\nodoo\n"))
        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            with docker.paused_application():
                raise RuntimeError("simulated failure")
        docker.compose.assert_any_call("stop", "odoo")
        docker.compose.assert_any_call("start", "odoo")

    def test_initially_stopped_application_is_not_started(self):
        docker = Docker(ROOT)
        docker.compose = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="db\n"))
        with docker.paused_application():
            pass
        self.assertEqual(docker.compose.call_count, 1)

    def test_initialization_must_finish_before_backup(self):
        docker = Docker(ROOT)
        docker.compose = Mock(
            return_value=subprocess.CompletedProcess([], 0, stdout="db\nodoo-init\n")
        )
        with self.assertRaisesRegex(RuntimeError, "initialization"):
            with docker.paused_application():
                self.fail("must not enter backup section during initialization")


if __name__ == "__main__":
    unittest.main()
