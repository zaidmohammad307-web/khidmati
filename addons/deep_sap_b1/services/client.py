"""SAP Service Layer transport. No business-document write API is exposed."""

import os
import re
import time
from urllib.parse import urljoin, urlsplit
import requests


class SAPError(Exception):
    def __init__(self, code, message, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(message)


def base_url(value):
    parsed = urlsplit(value or "")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in ("/b1s/v1", "/b1s/v2")
    ):
        raise SAPError(
            "CONFIG_URL",
            "Use an HTTPS Service Layer address ending in /b1s/v2 (or /b1s/v1). Do not put credentials in its URL.",
        )
    return value.rstrip("/") + "/"


class ServiceLayerClient:
    def __init__(
        self,
        url,
        company_db,
        username,
        password,
        ca_bundle=True,
        max_records=10000,
        deadline_seconds=90,
        session=None,
        sleeper=time.sleep,
    ):
        self.base = base_url(url)
        if not all((company_db, username, password)):
            raise SAPError(
                "CONFIG_CREDENTIALS",
                "Set the SAP company database, user and password in the server environment, then restart Odoo.",
            )
        self.credentials = {"CompanyDB": company_db, "UserName": username, "Password": password}
        self.session = session or requests.Session()
        self.session.trust_env = (
            False  # Keep VPN requests and credentials away from generic HTTP proxies.
        )
        if ca_bundle is False:
            raise SAPError("CONFIG_TLS", "TLS certificate verification cannot be disabled.")
        self.verify = ca_bundle
        self.max_records = max_records
        self.deadline = time.monotonic() + deadline_seconds
        self.sleeper = sleeper
        self.logged_in = False
        self.login_info = {}

    @classmethod
    def from_profile(cls, profile):
        prefix = profile.environment_prefix
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", prefix):
            raise SAPError(
                "CONFIG_PREFIX",
                "Environment prefix must contain uppercase letters, numbers and underscores.",
            )
        url = base_url(profile.base_url or os.environ.get(prefix + "_BASE_URL", ""))
        approved = os.environ.get(prefix + "_ALLOWED_ENDPOINTS", "") or os.environ.get(
            prefix + "_BASE_URL", ""
        )

        def identity(address):
            parsed = urlsplit(base_url(address.strip()))
            return (parsed.scheme, parsed.hostname, parsed.port or 443, parsed.path.rstrip("/"))

        if not approved or identity(url) not in {
            identity(address) for address in approved.split(",") if address.strip()
        }:
            raise SAPError(
                "CONFIG_APPROVED_ENDPOINT",
                "The profile endpoint must match a Service Layer endpoint approved in the server environment.",
            )
        ca = os.environ.get(prefix + "_CA_BUNDLE", "") or True
        if ca is not True and not os.path.isfile(ca):
            raise SAPError(
                "CONFIG_CA",
                "The configured SAP CA certificate file is not mounted on the Odoo server.",
            )
        password_file = os.environ.get(prefix + "_PASSWORD_FILE", "")
        password = os.environ.get(prefix + "_PASSWORD", "")
        if password_file:
            try:
                with open(password_file, encoding="utf-8") as stream:
                    password = stream.read(8193).rstrip("\r\n")
                if not password or len(password) > 8192:
                    raise ValueError()
            except (OSError, ValueError):
                raise SAPError(
                    "CONFIG_SECRET", "The SAP password file is missing or invalid."
                ) from None
        return cls(
            url,
            os.environ.get(prefix + "_COMPANY_DB", ""),
            os.environ.get(prefix + "_USERNAME", ""),
            password,
            ca_bundle=ca,
            max_records=profile.max_records,
        )

    def _url(self, path):
        candidate = urljoin(self.base, path)
        old, new = urlsplit(self.base), urlsplit(candidate)
        if (
            (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port)
            or not new.path.startswith(old.path)
            or new.username
            or new.password
            or new.fragment
        ):
            raise SAPError(
                "UNSAFE_NEXT_LINK",
                "SAP returned a pagination address outside the configured Service Layer.",
            )
        return candidate

    def _request(self, method, path, payload=None, params=None, refresh=True):
        url = self._url(path)
        for attempt in range(3):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise SAPError(
                    "TIME_BUDGET",
                    "SAP synchronization reached its time limit; reduce the selected datasets or record limit.",
                    True,
                )
            try:
                response = self.session.request(
                    method,
                    url,
                    json=payload,
                    params=params,
                    verify=self.verify,
                    timeout=(min(4, remaining), min(12, remaining)),
                    allow_redirects=False,
                    headers={"Accept": "application/json", "Prefer": "odata.maxpagesize=200"},
                )
            except requests.exceptions.SSLError:
                raise SAPError(
                    "TLS_CERTIFICATE",
                    "SAP TLS certificate verification failed. Mount the trusted SAP CA and use a hostname listed on its certificate.",
                ) from None
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < 2:
                    self.sleeper(min(2**attempt, 2))
                    continue
                raise SAPError(
                    "VPN_UNREACHABLE",
                    "SAP could not be reached. Check the VPN route, DNS, Service Layer port and host firewall from the Odoo host.",
                    True,
                ) from None
            if response.status_code == 401 and refresh and path != "Login":
                self.login()
                return self._request(method, path, payload, params, refresh=False)
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                self.sleeper(min(2**attempt, 2))
                continue
            if 300 <= response.status_code < 400:
                raise SAPError(
                    "HTTP_REDIRECT",
                    "Use the final Service Layer address directly; redirects are not followed.",
                )
            if response.status_code >= 400:
                if response.status_code == 401:
                    raise SAPError(
                        "SAP_LOGIN",
                        "SAP rejected the company database or integration user credentials.",
                    )
                if response.status_code == 403:
                    raise SAPError(
                        "SAP_PERMISSION",
                        "The SAP integration user lacks access to the requested dataset.",
                    )
                raise SAPError(
                    "SAP_HTTP_" + str(response.status_code),
                    "SAP rejected a request. Confirm that the selected entity and fields are supported by this Service Layer version.",
                    response.status_code in (429, 502, 503, 504),
                )
            if response.status_code == 204:
                return {}
            try:
                data = response.json()
            except ValueError:
                raise SAPError(
                    "SAP_RESPONSE", "Service Layer returned an invalid JSON response."
                ) from None
            if not isinstance(data, dict):
                raise SAPError("SAP_RESPONSE", "Expected a Service Layer object response.")
            return data
        raise SAPError("SAP_RETRY", "SAP temporary failure exhausted the retry limit.", True)

    def login(self):
        data = self._request("POST", "Login", self.credentials, refresh=False)
        session_id = data.get("SessionId")
        if not isinstance(session_id, str) or not session_id:
            raise SAPError("SAP_SESSION", "SAP login did not return a usable session.")
        # Session preserves B1SESSION and ROUTEID Set-Cookie; some gateways omit B1SESSION.
        cookies = [cookie for cookie in self.session.cookies if cookie.name == "B1SESSION"]
        if cookies:
            for cookie in cookies:
                cookie.value = session_id
        else:
            self.session.cookies.set(
                "B1SESSION",
                session_id,
                domain=urlsplit(self.base).hostname,
                path=urlsplit(self.base).path.rstrip("/"),
                secure=True,
            )
        self.logged_in = True
        self.login_info = {
            "version": str(data.get("Version", "")),
            "timeout_minutes": data.get("SessionTimeout"),
        }
        return self.login_info

    def collection(self, entity, params=None):
        if entity not in (
            "Items",
            "BusinessPartners",
            "PurchaseOrders",
            "Orders",
            "ProductTrees",
            "Warehouses",
        ):
            raise SAPError("ENTITY_NOT_ALLOWED", "This connector only reads approved SAP datasets.")
        if not self.logged_in:
            self.login()
        path, query, seen, result = entity, params or {}, set(), []
        while path:
            address = self._url(path)
            if address in seen:
                raise SAPError(
                    "PAGINATION_LOOP",
                    "SAP returned a repeated page; synchronization was rolled back.",
                )
            seen.add(address)
            data = self._request("GET", path, params=query)
            rows = data.get("value")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise SAPError("SAP_COLLECTION", "SAP returned a malformed collection.")
            result.extend(rows)
            if len(result) > self.max_records:
                raise SAPError(
                    "RECORD_LIMIT",
                    "SAP dataset exceeds the configured record limit. Increase the limit deliberately; a partial snapshot is never applied.",
                )
            path = data.get("@odata.nextLink") or data.get("odata.nextLink")
            if path is not None and not isinstance(path, str):
                raise SAPError("SAP_COLLECTION", "SAP returned an invalid next-page link.")
            query = None
        return result

    def close(self):
        if self.logged_in:
            try:
                self._request("POST", "Logout", refresh=False)
            except SAPError:
                pass
        self.session.close()

    def __enter__(self):
        try:
            self.login()
        except SAPError:
            self.close()
            raise
        return self

    def __exit__(self, *args):
        self.close()
