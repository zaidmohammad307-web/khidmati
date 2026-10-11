"""Launch the upstream Odoo CLI. No manufacturing business logic lives here."""

import logging
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
import time

from configuration import (
    ConfigurationError,
    database_settings,
    module_names,
    private_config,
    required,
)

LOGGER = logging.getLogger("drone.foundation")
TEMPLATE = Path(__file__).with_name("odoo.conf")

BOOTSTRAP_ADMIN = """
import os
admin = env.ref('base.user_admin')
admin.write({'login': os.environ['ODOO_LOGIN'],
             'password': os.environ['ODOO_LOGIN_PASSWORD']})
env['ir.config_parameter'].sudo().set_param('deep.foundation.version', '19.0.1.0.0')
env.cr.commit()
"""


def connection(settings: dict, database: str):
    # psycopg2 ships in the official Odoo image; standalone tests need no database.
    import psycopg2

    return psycopg2.connect(**{**settings, "dbname": database}, connect_timeout=5)


def wait_for_database(settings: dict, timeout: int = 120) -> None:
    import psycopg2

    deadline = time.monotonic() + timeout
    while True:
        try:
            with closing(connection(settings, "postgres")) as database:
                with database.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return
        except psycopg2.OperationalError:
            if time.monotonic() >= deadline:
                raise ConfigurationError(
                    "PostgreSQL is unavailable. Check the database service and application password."
                ) from None
            time.sleep(1)


def installed_modules(settings: dict) -> set[str]:
    """Read installation metadata only; application transactions use native Odoo."""
    with closing(connection(settings, "postgres")) as database:
        with database.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (settings["dbname"],))
            if not cursor.fetchone():
                return set()
    with closing(connection(settings, settings["dbname"])) as database:
        with database.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.ir_module_module')")
            if not cursor.fetchone()[0]:
                return set()
            cursor.execute("SELECT name FROM ir_module_module WHERE state = 'installed'")
            return {row[0] for row in cursor.fetchall()}


def initialize(config: Path, settings: dict) -> None:
    modules = module_names(os.environ)
    existing = installed_modules(settings)
    if set(modules.split(",")).issubset(existing):
        LOGGER.info("Database is initialized; existing users and passwords were preserved.")
        return
    required(os.environ, "ODOO_LOGIN")
    required(os.environ, "ODOO_LOGIN_PASSWORD")
    LOGGER.info("Installing native Community modules through the Odoo CLI.")
    subprocess.run(
        [
            "odoo",
            f"--config={config}",
            "--init=" + modules,
            "--without-demo=True",
            "--stop-after-init",
            "--no-http",
        ],
        check=True,
    )
    if "base" not in existing:
        subprocess.run(
            [
                "odoo",
                "shell",
                f"--config={config}",
                "--no-http",
            ],
            input=BOOTSTRAP_ADMIN,
            text=True,
            check=True,
        )
        LOGGER.info("Initial administrator configured. Read the login credentials in .env.")
    else:
        LOGGER.info("Existing base installation detected; administrator password was preserved.")


def main(arguments: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = None
    try:
        settings = database_settings(os.environ)
        config = private_config(os.environ, TEMPLATE)
        wait_for_database(settings)
        mode = arguments[0] if arguments else "serve"
        if mode == "init":
            initialize(config, settings)
            config.unlink(missing_ok=True)
            return 0
        if mode == "serve":
            if not set(module_names(os.environ).split(",")).issubset(installed_modules(settings)):
                raise ConfigurationError(
                    "Native modules are not initialized. Run the odoo-init service."
                )
            command = ["odoo", f"--config={config}", *arguments[1:]]
        else:
            # Native subcommands precede server options (e.g. `odoo shell -c ...`).
            args = arguments[1:] if mode == "odoo" else arguments
            if args and not args[0].startswith("-"):
                command = ["odoo", args[0], f"--config={config}", *args[1:]]
            else:
                command = ["odoo", f"--config={config}", *args]
        os.execvp(command[0], command)
    except ConfigurationError as exc:
        LOGGER.error("%s", exc)
    except subprocess.CalledProcessError as exc:
        LOGGER.error(
            "Native Odoo command failed with exit code %s. Review the Odoo logs.", exc.returncode
        )
    if config:
        config.unlink(missing_ok=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
