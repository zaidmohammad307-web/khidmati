"""Use argument arrays and fixed cwd for cross-platform Docker Compose commands."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess


class Docker:
    def __init__(self, root: Path):
        self.root = root

    def check(self) -> None:
        if not shutil.which("docker"):
            raise RuntimeError(
                "Docker is not installed. Install and start Docker Desktop or Docker Engine."
            )
        subprocess.run(["docker", "compose", "version"], check=True, capture_output=True)
        subprocess.run(["docker", "info"], check=True, capture_output=True)

    def compose(self, *arguments, **kwargs):
        return subprocess.run(
            ["docker", "compose", *arguments],
            cwd=self.root,
            check=True,
            **kwargs,
        )

    @contextmanager
    def paused_application(self):
        """Freeze HTTP and cron writes while preserving the initial running state."""
        running = self.compose(
            "ps",
            "--status",
            "running",
            "--services",
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if "odoo-init" in running:
            raise RuntimeError(
                "Wait for database initialization to finish before backup or restore."
            )
        was_running = "odoo" in running
        if was_running:
            self.compose("stop", "odoo")
        try:
            yield
        finally:
            if was_running:
                self.compose("start", "odoo")
