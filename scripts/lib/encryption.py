"""Versioned AES-256-GCM envelope. Authenticate before exposing restored plaintext."""

import os
from pathlib import Path
import tempfile
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"DEEPENC1"
CHUNK = 1024 * 1024


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)


def create_key(path):
    path = Path(path)
    private_directory(path.parent)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        load_key(path)
        return False
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(os.urandom(32))
        stream.flush()
        os.fsync(stream.fileno())
    return True


def load_key(path):
    path = Path(path)
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("The backup key must be readable only by its owner (chmod 600).")
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("The backup encryption key must contain exactly 32 random bytes.")
    return key


def is_encrypted(path):
    with Path(path).open("rb") as stream:
        return stream.read(len(MAGIC)) == MAGIC


def transform(source, destination, key, decrypt=False):
    source, destination = Path(source), Path(destination)
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte backup key.")
    if destination.exists():
        raise ValueError("Encryption output already exists; no file was overwritten.")
    descriptor, name = tempfile.mkstemp(prefix=".crypto-", dir=destination.parent)
    temporary = Path(name)
    try:
        with source.open("rb") as incoming, os.fdopen(descriptor, "wb") as outgoing:
            if decrypt:
                header = incoming.read(20)
                size = source.stat().st_size
                if size < 36 or header[:8] != MAGIC:
                    raise ValueError("Unrecognized or truncated encrypted backup.")
                incoming.seek(-16, os.SEEK_END)
                tag = incoming.read(16)
                incoming.seek(20)
                cipher = Cipher(algorithms.AES(key), modes.GCM(header[8:], tag)).decryptor()
                remaining = size - 36
            else:
                header = MAGIC + os.urandom(12)
                outgoing.write(header)
                cipher = Cipher(algorithms.AES(key), modes.GCM(header[8:])).encryptor()
                remaining = source.stat().st_size
            cipher.authenticate_additional_data(header)
            while remaining:
                block = incoming.read(min(CHUNK, remaining))
                if not block:
                    raise ValueError("Truncated backup payload.")
                remaining -= len(block)
                outgoing.write(cipher.update(block))
            try:
                outgoing.write(cipher.finalize())
            except InvalidTag:
                raise ValueError(
                    "Backup authentication failed: wrong key, corruption or tampering. Nothing was restored."
                ) from None
            if not decrypt:
                outgoing.write(cipher.tag)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        # A private temporary file is published only after its authentication succeeds.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def encrypt_file(source, destination, key):
    transform(source, destination, key)


def decrypt_file(source, destination, key):
    transform(source, destination, key, decrypt=True)
