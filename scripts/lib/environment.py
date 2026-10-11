"""Manage the local .env file without executing it as shell code."""

import os
from pathlib import Path
import re
import secrets
import tempfile

SECRET_KEYS = (
    "POSTGRES_PASSWORD",
    "ODOO_DB_PASSWORD",
    "ODOO_ADMIN_PASSWD",
    "ODOO_LOGIN_PASSWORD",
)
NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def read_environment(path: Path) -> dict[str, str]:
    result = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"Invalid .env entry on line {number}.")
        if key in result:
            raise ValueError(f"Duplicate .env key {key}.")
        if any(char in value for char in "\r\n\x00"):
            raise ValueError(f"Invalid single-line value for {key}.")
        # This generated format deliberately has no shell quoting or interpolation.
        result[key] = value
    return result


def write_environment(path: Path, values: dict[str, str]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("# Generated local configuration. Keep this file private.\n")
            for key, value in values.items():
                if any(char in value for char in "\r\n\x00"):
                    raise ValueError(f"Invalid single-line value for {key}.")
                stream.write(f"{key}={value}\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def setup_environment(root: Path) -> bool:
    """Generate missing secrets once. Rerunning setup preserves existing credentials."""
    path = root / ".env"
    defaults = read_environment(root / ".env.example")
    existing = read_environment(path) if path.exists() else {}
    values = {**defaults, **existing}
    changed = not path.exists() or values != existing
    for key in SECRET_KEYS:
        if not values.get(key):
            values[key] = secrets.token_hex(32)
            changed = True
    from .encryption import create_key
    from .pki import setup_pki

    create_key(root / values.get("DEEP_BACKUP_KEY_FILE", "secrets/backup.key"))
    setup_pki(root, values.get("DEEP_HOSTNAME", "localhost"))
    secret_path = root / "secrets/sap-password.txt"
    if not secret_path.exists():
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    (root / "certificates").mkdir(exist_ok=True)
    validate_environment(values)
    if changed:
        write_environment(path, values)
    return changed


def validate_environment(values: dict[str, str]) -> None:
    for key in SECRET_KEYS:
        value = values.get(key, "")
        if not value or not re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
            raise ValueError(
                f"{key} must contain at least 20 letters, digits, underscores or hyphens."
            )
    for key in ("ODOO_DB_NAME", "ODOO_DB_USER", "POSTGRES_DB", "POSTGRES_USER"):
        if not NAME.fullmatch(values.get(key, "")):
            raise ValueError(f"{key} must be a lowercase PostgreSQL identifier.")
    if values["ODOO_DB_USER"] == values["POSTGRES_USER"] or values["ODOO_DB_USER"] == "postgres":
        raise ValueError(
            "The Odoo database user must be separate from the PostgreSQL administrator."
        )
    if values["POSTGRES_DB"] != "postgres":
        raise ValueError("POSTGRES_DB is the bootstrap database and must remain postgres.")
    if values.get("ODOO_DB_HOST") != "db" or values.get("ODOO_DB_PORT") != "5432":
        raise ValueError(
            "This local Compose environment uses ODOO_DB_HOST=db and ODOO_DB_PORT=5432."
        )
    try:
        port = int(values["ODOO_HTTP_PORT"])
    except (KeyError, ValueError) as exc:
        raise ValueError("ODOO_HTTP_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("ODOO_HTTP_PORT must be between 1 and 65535.")
