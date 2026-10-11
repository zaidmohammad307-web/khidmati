#!/usr/bin/env python3
"""Cross-platform setup and lifecycle CLI for the isolated Odoo Community pilot."""

import argparse
from pathlib import Path
import re
import subprocess
import sys

from lib.backups import create_backup, restore_backup
from lib.docker import Docker
from lib.environment import read_environment, setup_environment, validate_environment

ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    modes = command.add_subparsers(dest="action", required=True)
    modes.add_parser(
        "setup", help="Generate .env credentials once; never reset an existing password"
    )
    modes.add_parser("start", help="Build, initialize, start and wait for a healthy login page")
    modes.add_parser("init", help="Run only the native database/module initialization")
    modes.add_parser("check", help="Check Docker, credentials and Compose without printing secrets")
    modes.add_parser("stop", help="Stop containers while preserving database and filestore")
    modes.add_parser("status", help="Show container status")
    modes.add_parser("logs", help="Follow application and initializer logs")
    modes.add_parser("verify", help="Authenticate and check the installed native applications")
    modes.add_parser("test", help="Run foundation and calculation tests without Docker")
    modes.add_parser("acceptance", help="Run native Odoo end-to-end transactional tests")
    backup = modes.add_parser("backup", help="Back up PostgreSQL and the filestore as one archive")
    backup.add_argument("--output", type=Path)
    restore = modes.add_parser(
        "restore", help="Restore to a NEW database, preserving the current one"
    )
    restore.add_argument("archive", type=Path)
    restore.add_argument("--target", required=True)
    restore.add_argument("--activate", action="store_true")
    restore.add_argument(
        "--allow-plain-backup",
        action="store_true",
        help="Explicit migration of an older trusted plaintext backup",
    )
    update = modes.add_parser(
        "update", help="Stop application writes and run a native module update"
    )
    update.add_argument("modules", help="Comma-separated installed addon names")
    return command


def execute(options) -> None:
    if options.action == "test":
        subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ROOT,
            check=True,
        )
        return
    if options.action == "setup":
        changed = setup_environment(ROOT)
        print("Created or completed .env." if changed else "Existing .env preserved.")
        print("Login name and password are in ODOO_LOGIN and ODOO_LOGIN_PASSWORD in .env.")
        return
    if not (ROOT / ".env").exists():
        raise ValueError("Run python scripts/manage.py setup first.")
    values = read_environment(ROOT / ".env")
    validate_environment(values)
    docker = Docker(ROOT)
    docker.check()
    if options.action == "check":
        docker.compose("config", "--quiet")
        print("Docker, environment and Compose configuration passed.")
    elif options.action == "start":
        docker.compose("config", "--quiet")
        docker.compose("up", "-d", "--build", "--wait", "--wait-timeout", "600")
        subprocess.run([sys.executable, "scripts/verify.py"], cwd=ROOT, check=True)
        secure = "docker-compose.secure.yml" in values.get("COMPOSE_FILE", "")
        origin = (
            f"https://{values.get('DEEP_HOSTNAME', 'localhost')}:{values.get('DEEP_HTTPS_PORT', '8443')}"
            if secure
            else f"http://localhost:{values['ODOO_HTTP_PORT']}"
        )
        print(f"Open {origin}/web/login")
    elif options.action == "init":
        docker.compose("up", "-d", "--wait", "db")
        docker.compose("run", "--build", "--rm", "-T", "--no-deps", "odoo-init")
    elif options.action == "stop":
        docker.compose("stop")
    elif options.action == "status":
        docker.compose("ps", "-a")
    elif options.action == "logs":
        docker.compose("logs", "-f", "odoo", "odoo-init")
    elif options.action == "verify":
        subprocess.run([sys.executable, "scripts/verify.py"], cwd=ROOT, check=True)
    elif options.action == "backup":
        print(create_backup(docker, ROOT, options.output))
    elif options.action == "restore":
        restore_backup(
            docker,
            ROOT,
            options.archive.resolve(),
            options.target,
            options.activate,
            options.allow_plain_backup,
        )
        print(f"Restored into {options.target}. The original database was preserved.")
        if not options.activate:
            print("This restore was not activated. Set ODOO_DB_NAME to the target when ready.")
    elif options.action == "acceptance":
        with docker.paused_application():
            docker.compose(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "odoo",
                "--update=deep_sap_b1,deep_control_tower,deep_manufacturing_dashboard",
                "--test-enable",
                "--test-tags=/deep_sap_b1,/deep_control_tower,/deep_manufacturing_dashboard",
                "--stop-after-init",
                "--no-http",
            )
        print("Native manufacturing workflow tests passed; application running state restored.")
    elif options.action == "update":
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*", options.modules):
            raise ValueError("Module names must be comma-separated lowercase identifiers.")
        with docker.paused_application():
            docker.compose(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "odoo",
                "--update=" + options.modules,
                "--stop-after-init",
                "--no-http",
            )
        print("Module update completed; application running state was restored.")


def main() -> int:
    try:
        execute(parser().parse_args())
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
    except subprocess.CalledProcessError as exc:
        print(
            f"Command failed with exit code {exc.returncode}. Review service logs.", file=sys.stderr
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
