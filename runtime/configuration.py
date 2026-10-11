"""Validate environment values and render configuration without leaking secrets."""

import configparser
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MODULES = re.compile(r"^[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*$")


class ConfigurationError(ValueError):
    """An actionable configuration problem, with no secret values in its message."""


def required(environment: Mapping[str, str], key: str) -> str:
    value = environment.get(key, "")
    if not value or any(char in value for char in "\r\n\x00"):
        raise ConfigurationError(f"{key} must be set to a nonempty, single-line value.")
    return value


def identifier(value: str, key: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ConfigurationError(f"{key} must be a lowercase PostgreSQL identifier.")
    return value


def database_settings(environment: Mapping[str, str]) -> dict:
    try:
        port = int(environment.get("ODOO_DB_PORT", "5432"))
    except ValueError as exc:
        raise ConfigurationError("ODOO_DB_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("ODOO_DB_PORT must be between 1 and 65535.")
    user = identifier(required(environment, "ODOO_DB_USER"), "ODOO_DB_USER")
    if user == "postgres":
        raise ConfigurationError("ODOO_DB_USER must be a separate application role.")
    settings = {
        "host": required(environment, "ODOO_DB_HOST"),
        "port": port,
        "user": user,
        "password": required(environment, "ODOO_DB_PASSWORD"),
        "dbname": identifier(required(environment, "ODOO_DB_NAME"), "ODOO_DB_NAME"),
    }
    sslmode = environment.get("ODOO_DB_SSLMODE", "")
    if sslmode:
        if sslmode not in {"prefer", "require", "verify-ca", "verify-full"}:
            raise ConfigurationError("Invalid ODOO_DB_SSLMODE.")
        settings["sslmode"] = sslmode
    return settings


def module_names(environment: Mapping[str, str]) -> str:
    modules = environment.get(
        "ODOO_BOOTSTRAP_MODULES", "base,web,mrp,purchase_stock,hr,deep_sap_b1"
    )
    if not MODULES.fullmatch(modules):
        raise ConfigurationError("ODOO_BOOTSTRAP_MODULES must be comma-separated module names.")
    if not {"base", "web", "mrp", "purchase_stock"}.issubset(modules.split(",")):
        raise ConfigurationError("Bootstrap modules must include base, web, mrp, purchase_stock.")
    return modules


def render_config(environment: Mapping[str, str], template: Path) -> configparser.RawConfigParser:
    settings = database_settings(environment)
    parser = configparser.RawConfigParser()
    if not parser.read(template) or not parser.has_section("options"):
        raise ConfigurationError("The Odoo configuration template is missing its options section.")
    for option, value in {
        "db_host": settings["host"],
        "db_port": str(settings["port"]),
        "db_user": settings["user"],
        "db_password": settings["password"],
        "db_name": settings["dbname"],
        "dbfilter": "^" + re.escape(settings["dbname"]) + "$",
        "admin_passwd": required(environment, "ODOO_ADMIN_PASSWD"),
        "db_sslmode": settings.get("sslmode", "prefer"),
        "http_interface": environment.get("ODOO_HTTP_INTERFACE", "0.0.0.0"),
        "proxy_mode": "True" if environment.get("ODOO_PROXY_MODE") == "1" else "False",
    }.items():
        parser.set("options", option, value)
    return parser


def private_config(environment: Mapping[str, str], template: Path) -> Path:
    parser = render_config(environment, template)
    descriptor, filename = tempfile.mkstemp(prefix="drone-odoo-", suffix=".conf")
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        parser.write(stream)
    return Path(filename)
