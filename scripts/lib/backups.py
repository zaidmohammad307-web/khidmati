"""Consistent database + filestore backups and restore to a fresh database only."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import zipfile

from .environment import NAME, read_environment, write_environment
from .encryption import decrypt_file, encrypt_file, is_encrypted, load_key, private_directory

EXPECTED_MEMBERS = {"database.dump", "filestore.tar.gz", "metadata.json"}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_filestore(path: Path) -> None:
    """Reject path traversal, symbolic links, hard links and device files."""
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                raise ValueError("Unsafe file path in the filestore backup.")
            if not (member.isfile() or member.isdir()):
                raise ValueError("The filestore backup may contain only files and directories.")


def unpack_backup(archive_path: Path, destination: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != 3 or set(names) != EXPECTED_MEMBERS:
            raise ValueError(
                "Backup must contain exactly database.dump, filestore.tar.gz and metadata.json."
            )
        for name in names:
            with archive.open(name) as source, (destination / name).open("wb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
    metadata = json.loads((destination / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("format_version") != 1 or metadata.get("odoo_major") != 19:
        raise ValueError("This tool restores only version 1 backups of Odoo 19.")
    for name in ("database.dump", "filestore.tar.gz"):
        if checksum(destination / name) != metadata.get("sha256", {}).get(name):
            raise ValueError(f"Backup checksum failed for {name}.")
    validate_filestore(destination / "filestore.tar.gz")
    return metadata


def backup_key(root, values):
    path = Path(values.get("DEEP_BACKUP_KEY_FILE", "secrets/backup.key"))
    return load_key(path if path.is_absolute() else root / path)


def work_directory(root, values):
    # Plaintext working files must sit on the same encrypted host storage as the live data.
    directory = Path(values.get("DEEP_ENCRYPTED_DATA_DIR") or root / "private-data") / "backup-work"
    if not directory.is_absolute():
        directory = root / directory
    private_directory(directory)
    return directory


def create_backup(docker, root: Path, output: Path | None = None) -> Path:
    values = read_environment(root / ".env")
    key = backup_key(root, values)
    now = datetime.now(timezone.utc)
    output = output or root / "backups" / f"{values['ODOO_DB_NAME']}-{now:%Y%m%dT%H%M%S%fZ}.deepenc"
    if output.exists():
        raise ValueError("Backup output already exists; choose another filename.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="drone-backup-", dir=work_directory(root, values)
    ) as temporary:
        work = Path(temporary)
        with docker.paused_application():
            with (work / "database.dump").open("wb") as stream:
                docker.compose(
                    "exec",
                    "-T",
                    "db",
                    "sh",
                    "-ec",
                    'export PGPASSWORD="$ODOO_DB_PASSWORD"; exec pg_dump '
                    '--host=127.0.0.1 --username="$ODOO_DB_USER" --dbname="$ODOO_DB_NAME" '
                    "--format=custom --no-owner --no-privileges",
                    stdout=stream,
                )
            with (work / "filestore.tar.gz").open("wb") as stream:
                docker.compose(
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "--entrypoint",
                    "sh",
                    "odoo",
                    "-ec",
                    'store="/var/lib/odoo/filestore/$ODOO_DB_NAME"; mkdir -p "$store"; '
                    'exec tar -czf - -C "$store" .',
                    stdout=stream,
                )
        metadata = {
            "format_version": 1,
            "odoo_major": 19,
            "database": values["ODOO_DB_NAME"],
            "created_at": now.isoformat(),
            "odoo_image": values["ODOO_IMAGE"],
            "postgres_image": values["POSTGRES_IMAGE"],
            "sha256": {
                name: checksum(work / name) for name in ("database.dump", "filestore.tar.gz")
            },
        }
        (work / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        # SQL dumps and filestore tarballs are compressed already.
        partial = work / "payload.zip"
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as archive:
                for name in sorted(EXPECTED_MEMBERS):
                    archive.write(work / name, name)
            encrypt_file(partial, output, key)
        finally:
            partial.unlink(missing_ok=True)
    return output


def restore_backup(
    docker, root: Path, archive: Path, target: str, activate: bool, allow_plain_backup: bool = False
) -> None:
    if not NAME.fullmatch(target) or target in {"postgres", "template0", "template1"}:
        raise ValueError("Restore target must be a new lowercase application database name.")
    values = read_environment(root / ".env")
    if target == values["ODOO_DB_NAME"]:
        raise ValueError("Restore will not overwrite the active database. Choose a new target.")
    encrypted = is_encrypted(archive)
    if not encrypted and not allow_plain_backup:
        raise ValueError(
            "Plaintext backup refused. Use --allow-plain-backup only to migrate a trusted older backup."
        )
    key = backup_key(root, values) if encrypted else None
    with tempfile.TemporaryDirectory(
        prefix="drone-restore-", dir=work_directory(root, values)
    ) as temporary:
        work = Path(temporary)
        if encrypted:
            decrypted = work / "authenticated.zip"
            decrypt_file(archive, decrypted, key)
            archive = decrypted
        unpack_backup(archive, work)
        with docker.paused_application():
            # Existing filestore or database makes the restore fail before any overwrite.
            docker.compose(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "-e",
                f"RESTORE_DB={target}",
                "--entrypoint",
                "sh",
                "odoo",
                "-ec",
                'test ! -e "/var/lib/odoo/filestore/$RESTORE_DB" || '
                '{ echo "Restore filestore already exists." >&2; exit 1; }',
            )
            docker.compose(
                "exec",
                "-T",
                "-e",
                f"RESTORE_DB={target}",
                "db",
                "sh",
                "-ec",
                'export PGPASSWORD="$ODOO_DB_PASSWORD"; exec createdb --host=127.0.0.1 '
                '--username="$ODOO_DB_USER" --owner="$ODOO_DB_USER" "$RESTORE_DB"',
            )
            with (work / "database.dump").open("rb") as stream:
                docker.compose(
                    "exec",
                    "-T",
                    "-e",
                    f"RESTORE_DB={target}",
                    "db",
                    "sh",
                    "-ec",
                    'export PGPASSWORD="$ODOO_DB_PASSWORD"; exec pg_restore --host=127.0.0.1 '
                    '--username="$ODOO_DB_USER" --dbname="$RESTORE_DB" --no-owner '
                    "--no-privileges --exit-on-error --single-transaction",
                    stdin=stream,
                )
            with (work / "filestore.tar.gz").open("rb") as stream:
                docker.compose(
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "-e",
                    f"RESTORE_DB={target}",
                    "--entrypoint",
                    "sh",
                    "odoo",
                    "-ec",
                    'store="/var/lib/odoo/filestore/$RESTORE_DB"; mkdir -p "$store"; '
                    'exec tar -xzf - -C "$store" --no-same-owner',
                    stdin=stream,
                )
    if activate:
        values["ODOO_DB_NAME"] = target
        write_environment(root / ".env", values)
        # A recreate is required to apply a new environment; `start` alone would not.
        docker.compose("up", "-d", "--wait", "--wait-timeout", "300")
