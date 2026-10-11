"""Create a private local CA and explicit server certificates without shell OpenSSL."""

from datetime import datetime, timedelta, timezone
import ipaddress
import os
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from .encryption import private_directory


def _save(path, value):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644 if path.suffix == ".crt" else 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _encoded(key):
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def setup_pki(root, hostname="localhost"):
    folder = Path(root) / "secrets"
    private_directory(folder)
    names = ["ca.key", "ca.crt", "web.key", "web.crt", "db.key", "db.crt"]
    present = [(folder / name).exists() for name in names]
    if all(present):
        certificate = x509.load_pem_x509_certificate((folder / "web.crt").read_bytes())
        sans = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if hostname not in sans.get_values_for_type(x509.DNSName) and hostname not in [
            str(v) for v in sans.get_values_for_type(x509.IPAddress)
        ]:
            raise ValueError(
                "Existing web certificate has a different hostname. Renew it deliberately; setup never overwrites keys."
            )
        if certificate.not_valid_after_utc <= datetime.now(timezone.utc) + timedelta(days=7):
            raise ValueError("The web certificate needs renewal; see docs/SECURITY.md.")
        return False
    if any(present):
        raise ValueError(
            "Incomplete TLS key set. Restore the full set or move it aside before generating a new CA."
        )
    now = datetime.now(timezone.utc)
    ca_key = _key()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Deep manufacturing private CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _save(folder / "ca.key", _encoded(ca_key))
    _save(folder / "ca.crt", ca.public_bytes(serialization.Encoding.PEM))
    for label, host in [("web", hostname), ("db", "db")]:
        key = _key()
        try:
            san = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            san = x509.DNSName(host)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        _save(folder / (label + ".key"), _encoded(key))
        _save(folder / (label + ".crt"), cert.public_bytes(serialization.Encoding.PEM))
    return True
