import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from _support import ROOT
from lib.backups import checksum, unpack_backup, validate_filestore


def filestore(path, name="./ab/cd", kind=tarfile.REGTYPE):
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.size = 3 if kind == tarfile.REGTYPE else 0
        archive.addfile(member, io.BytesIO(b"abc") if member.size else None)


def backup(root, corrupt=False):
    dump = root / "database.dump"
    store = root / "filestore.tar.gz"
    dump.write_bytes(b"PGDMP-demo-test")
    filestore(store)
    metadata = {
        "format_version": 1,
        "odoo_major": 19,
        "sha256": {"database.dump": checksum(dump), "filestore.tar.gz": checksum(store)},
    }
    if corrupt:
        dump.write_bytes(b"changed-after-checksum")
    output = root / "backup.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.write(dump, "database.dump")
        archive.write(store, "filestore.tar.gz")
        archive.writestr("metadata.json", json.dumps(metadata))
    return output


class BackupTests(unittest.TestCase):
    def test_valid_archive_integrity_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "restored"
            output.mkdir()
            self.assertEqual(unpack_backup(backup(root), output)["odoo_major"], 19)

    def test_corrupt_database_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "restored"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "checksum"):
                unpack_backup(backup(root, corrupt=True), output)

    def test_extra_zip_member_or_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = backup(root)
            with zipfile.ZipFile(archive_path, "a") as archive:
                archive.writestr("../outside", b"unsafe")
            with self.assertRaises(ValueError):
                unpack_backup(archive_path, root)
            self.assertFalse((root.parent / "outside").exists())

    def test_tar_traversal_and_absolute_paths_are_rejected(self):
        for name in ("../outside", "/etc/passwd", "./aa/../../outside", "C:\\outside"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "store.tar.gz"
                filestore(path, name)
                with self.assertRaises(ValueError):
                    validate_filestore(path)

    def test_tar_links_and_device_files_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "store.tar.gz"
                filestore(path, "./entry", kind)
                with self.assertRaises(ValueError):
                    validate_filestore(path)

    def test_restore_cannot_overwrite_active_database(self):
        from lib.backups import restore_backup
        from lib.environment import setup_environment
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_bytes((ROOT / ".env.example").read_bytes())
            setup_environment(root)
            docker = Mock()
            with self.assertRaisesRegex(ValueError, "overwrite"):
                restore_backup(docker, root, root / "backup.zip", "deep_pilot", False)
            docker.compose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
