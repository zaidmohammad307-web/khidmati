import os
from pathlib import Path
import tempfile
import unittest
from _support import ROOT  # noqa: F401
from lib.encryption import create_key, decrypt_file, encrypt_file, is_encrypted, load_key
from lib.pki import setup_pki
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding


class EncryptionTests(unittest.TestCase):
    def test_randomized_roundtrip_and_private_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "backup.key"
            create_key(key)
            self.assertFalse(create_key(key))
            source = root / "source"
            source.write_bytes(os.urandom(2_100_000))
            a, b = root / "a", root / "b"
            encrypt_file(source, a, load_key(key))
            encrypt_file(source, b, load_key(key))
            self.assertTrue(is_encrypted(a))
            self.assertNotEqual(a.read_bytes(), b.read_bytes())
            restored = root / "restored"
            decrypt_file(a, restored, load_key(key))
            self.assertEqual(source.read_bytes(), restored.read_bytes())
            if os.name != "nt":
                self.assertEqual(restored.stat().st_mode & 0o777, 0o600)

    def test_wrong_key_or_tampering_never_publishes_plaintext(self):
        for mode in ["wrong-key", "ciphertext", "header", "tag", "truncated"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, encrypted, output = root / "source", root / "backup", root / "restored"
                source.write_bytes(b"confidential database content")
                key = os.urandom(32)
                encrypt_file(source, encrypted, key)
                data = bytearray(encrypted.read_bytes())
                if mode == "wrong-key":
                    key = os.urandom(32)
                elif mode == "truncated":
                    data = data[:12]
                else:
                    index = {"ciphertext": 22, "header": 9, "tag": -1}[mode]
                    data[index] ^= 1
                encrypted.write_bytes(data)
                with self.assertRaises(ValueError):
                    decrypt_file(encrypted, output, key)
                self.assertFalse(output.exists())
                self.assertFalse(list(root.glob(".crypto-*")))

    def test_existing_output_and_invalid_key_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "keep"
            source.write_bytes(b"source")
            output.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                encrypt_file(source, output, os.urandom(32))
            self.assertEqual(output.read_bytes(), b"keep")
            with self.assertRaises(ValueError):
                encrypt_file(source, root / "invalid", b"short")

    def test_pki_is_repeatable_and_signed_for_exact_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(setup_pki(root, "vpn.example.internal"))
            original = (root / "secrets/ca.key").read_bytes()
            self.assertFalse(setup_pki(root, "vpn.example.internal"))
            self.assertEqual((root / "secrets/ca.key").read_bytes(), original)
            ca = x509.load_pem_x509_certificate((root / "secrets/ca.crt").read_bytes())
            for name, host in [("web", "vpn.example.internal"), ("db", "db")]:
                cert = x509.load_pem_x509_certificate(
                    (root / ("secrets/" + name + ".crt")).read_bytes()
                )
                ca.public_key().verify(
                    cert.signature,
                    cert.tbs_certificate_bytes,
                    padding.PKCS1v15(),
                    cert.signature_hash_algorithm,
                )
                self.assertIn(
                    host,
                    cert.extensions.get_extension_for_class(
                        x509.SubjectAlternativeName
                    ).value.get_values_for_type(x509.DNSName),
                )
            with self.assertRaises(ValueError):
                setup_pki(root, "other.example.internal")
