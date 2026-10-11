import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from _support import ROOT

spec = importlib.util.spec_from_file_location(
    "sap_transport", ROOT / "addons/deep_sap_b1/services/client.py"
)
sap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sap)


def response(code=200, **data):
    value = Mock(status_code=code)
    value.json.return_value = data
    return value


class SAPTransportTests(unittest.TestCase):
    def client(self, responses):
        session = requests.Session()
        session.request = Mock(side_effect=responses)
        return sap.ServiceLayerClient(
            "https://sap.example.invalid:50000/b1s/v2",
            "company",
            "integration",
            "secret-must-not-be-logged",
            session=session,
            sleeper=lambda _: None,
        )

    def test_login_pagination_cookies_and_tls_verification(self):
        client = self.client(
            [
                response(SessionId="session", Version="10"),
                response(value=[{"ItemCode": "A"}], **{"@odata.nextLink": "Items?$skip=1"}),
                response(value=[{"ItemCode": "B"}]),
                response(204),
            ]
        )
        with client:
            self.assertEqual(len(client.collection("Items")), 2)
            self.assertEqual(client.session.cookies.get("B1SESSION"), "session")
            self.assertEqual(client.login_info["version"], "10")
        for call in client.session.request.call_args_list:
            self.assertIs(call.kwargs["verify"], True)
            self.assertFalse(call.kwargs["allow_redirects"])
        self.assertFalse(client.session.trust_env)

    def test_external_next_link_cannot_receive_cookies(self):
        client = self.client(
            [
                response(SessionId="session"),
                response(value=[], **{"@odata.nextLink": "https://attacker.invalid/Items"}),
            ]
        )
        with self.assertRaises(sap.SAPError) as error:
            client.collection("Items")
        self.assertEqual(error.exception.code, "UNSAFE_NEXT_LINK")
        self.assertEqual(client.session.request.call_count, 2)

    def test_unauthorized_session_refreshes_once(self):
        client = self.client(
            [
                response(SessionId="one"),
                response(401),
                response(SessionId="two"),
                response(value=[{"ItemCode": "A"}]),
            ]
        )
        self.assertEqual(len(client.collection("Items")), 1)
        self.assertEqual(client.session.request.call_count, 4)

    def test_tls_error_is_sanitized_and_not_retried(self):
        client = self.client([requests.exceptions.SSLError("secret-must-not-be-logged")])
        with self.assertRaises(sap.SAPError) as error:
            client.login()
        self.assertEqual(error.exception.code, "TLS_CERTIFICATE")
        self.assertNotIn("secret-must-not-be-logged", str(error.exception))
        self.assertEqual(client.session.request.call_count, 1)

    def test_transient_failure_is_bounded(self):
        client = self.client([requests.exceptions.ConnectionError("private-address")] * 3)
        with self.assertRaises(sap.SAPError) as error:
            client.login()
        self.assertTrue(error.exception.retryable)
        self.assertEqual(client.session.request.call_count, 3)
        self.assertNotIn("private-address", str(error.exception))

    def test_truncated_snapshot_and_pagination_loop_are_rejected(self):
        client = self.client([response(SessionId="s"), response(value=[{}, {}])])
        client.max_records = 1
        with self.assertRaises(sap.SAPError) as error:
            client.collection("Items")
        self.assertEqual(error.exception.code, "RECORD_LIMIT")
        client = self.client(
            [response(SessionId="s"), response(value=[], **{"odata.nextLink": "Items"})]
        )
        with self.assertRaises(sap.SAPError) as error:
            client.collection("Items")
        self.assertEqual(error.exception.code, "PAGINATION_LOOP")

    def test_credentials_in_url_plain_http_or_unverified_tls_are_refused(self):
        for url in [
            "http://sap/b1s/v2",
            "https://u:p@sap/b1s/v2",
            "https://sap/b1s/v2?password=x",
            "https://sap/other",
        ]:
            with self.subTest(url=url), self.assertRaises(sap.SAPError):
                sap.base_url(url)
        with self.assertRaises(sap.SAPError):
            sap.ServiceLayerClient("https://sap/b1s/v2", "db", "u", "p", ca_bundle=False)

    def test_invalid_json_or_unapproved_entity_is_rejected(self):
        client = self.client([response(SessionId="s"), response(value="not a list")])
        with self.assertRaises(sap.SAPError):
            client.collection("Items")
        with self.assertRaises(sap.SAPError):
            client.collection("Invoices")
        self.assertNotIn("secret-must-not-be-logged", json.dumps(str(client.login_info)))

    def test_profile_credentials_can_only_be_sent_to_server_approved_endpoint(self):
        profile = SimpleNamespace(
            environment_prefix="SAP_B1", base_url="https://attacker.invalid/b1s/v2", max_records=100
        )
        values = {
            "SAP_B1_BASE_URL": "https://sap.example.invalid/b1s/v2",
            "SAP_B1_COMPANY_DB": "db",
            "SAP_B1_USERNAME": "u",
            "SAP_B1_PASSWORD": "secret",
        }
        with (
            patch.dict(sap.os.environ, values, clear=True),
            self.assertRaises(sap.SAPError) as error,
        ):
            sap.ServiceLayerClient.from_profile(profile)
        self.assertEqual(error.exception.code, "CONFIG_APPROVED_ENDPOINT")

    def test_mounted_password_file_wins_over_environment_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "password"
            path.write_text("mounted-private-secret\n")
            profile = SimpleNamespace(environment_prefix="SAP_B1", base_url=False, max_records=100)
            values = {
                "SAP_B1_BASE_URL": "https://sap.example.invalid/b1s/v2",
                "SAP_B1_COMPANY_DB": "db",
                "SAP_B1_USERNAME": "u",
                "SAP_B1_PASSWORD": "ignored",
                "SAP_B1_PASSWORD_FILE": str(path),
            }
            with patch.dict(sap.os.environ, values, clear=True):
                client = sap.ServiceLayerClient.from_profile(profile)
            self.assertEqual(client.credentials["Password"], "mounted-private-secret")
            client.close()
