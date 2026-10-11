#!/usr/bin/env python3
"""Real HTTP session smoke test against the running Odoo application."""

import http.cookiejar
import json
from pathlib import Path
import sys
import ssl
from urllib.error import URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from lib.environment import read_environment

ROOT = Path(__file__).resolve().parents[1]


class VerificationError(RuntimeError):
    pass


def call(opener, origin: str, path: str, parameters: dict):
    payload = {"jsonrpc": "2.0", "method": "call", "params": parameters, "id": 1}
    request = Request(
        origin + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=120) as response:
        result = json.load(response)
    if "error" in result:
        raise VerificationError(
            "Odoo rejected the verification request. Check credentials and logs."
        )
    return result.get("result")


def verify(values: dict[str, str]) -> None:
    secure = "docker-compose.secure.yml" in values.get("COMPOSE_FILE", "")
    origin = (
        (
            "https://"
            + values.get("DEEP_HOSTNAME", "localhost")
            + ":"
            + values.get("DEEP_HTTPS_PORT", "8443")
        )
        if secure
        else "http://127.0.0.1:" + values["ODOO_HTTP_PORT"]
    )
    handlers = [HTTPCookieProcessor(http.cookiejar.CookieJar())]
    if secure:
        handlers.append(
            HTTPSHandler(context=ssl.create_default_context(cafile=str(ROOT / "secrets/ca.crt")))
        )
    opener = build_opener(*handlers)
    with opener.open(origin + "/web/login", timeout=30) as response:
        if response.status != 200 or b'name="login"' not in response.read(512_000):
            raise VerificationError("Odoo did not serve the login form.")
    session = call(
        opener,
        origin,
        "/web/session/authenticate",
        {
            "db": values["ODOO_DB_NAME"],
            "login": values["ODOO_LOGIN"],
            "password": values["ODOO_LOGIN_PASSWORD"],
        },
    )
    if not session or not session.get("uid"):
        raise VerificationError("Administrator login failed.")
    names = sorted(
        set(values["ODOO_BOOTSTRAP_MODULES"].split(","))
        | {
            "deep_core",
            "deep_mps",
            "deep_capacity_planning",
            "deep_quality",
            "deep_rework",
            "deep_data_import",
            "deep_material_risk",
            "deep_shopfloor",
            "deep_manufacturing_dashboard",
            "deep_operations",
            "deep_maintenance",
            "deep_planning_plus",
            "deep_quality_plus",
            "deep_contracts",
            "deep_control_tower",
            "deep_sap_b1",
            "auth_totp",
        }
    )
    modules = call(
        opener,
        origin,
        "/web/dataset/call_kw/ir.module.module/search_read",
        {
            "model": "ir.module.module",
            "method": "search_read",
            "args": [[["name", "in", names]]],
            "kwargs": {"fields": ["name", "state"], "limit": len(names)},
        },
    )
    installed = {module["name"] for module in modules if module["state"] == "installed"}
    missing = set(names) - installed
    if missing:
        raise VerificationError(
            "Required native modules are not installed: " + ", ".join(sorted(missing))
        )
    metrics = call(
        opener,
        origin,
        "/web/dataset/call_kw/deep.manufacturing.dashboard/metrics",
        {
            "model": "deep.manufacturing.dashboard",
            "method": "metrics",
            "args": [],
            "kwargs": {},
        },
    )
    if not isinstance(metrics, dict) or "capacity" not in metrics:
        raise VerificationError("The manufacturing dashboard did not return metrics.")
    tower = call(
        opener,
        origin,
        "/web/dataset/call_kw/deep.control.tower/metrics",
        {"model": "deep.control.tower", "method": "metrics", "args": [], "kwargs": {}},
    )
    if not isinstance(tower, dict) or "alerts" not in tower or "contracts" not in tower:
        raise VerificationError("The operations control tower did not return its queues.")
    print(
        "PASS: login, administrator authentication, all 16 addons, planning cockpit and control tower metrics."
    )
    print("Installed: " + ", ".join(sorted(installed)))


if __name__ == "__main__":
    try:
        verify(read_environment(ROOT / ".env"))
    except (VerificationError, URLError, OSError, ValueError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
