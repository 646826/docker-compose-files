#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("backup_module", ROOT / "scripts/backup.py")
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class TarRootMemberTests(unittest.TestCase):
    def test_regular_root_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "regular-root.tar.gz"
            member = tarfile.TarInfo("./")
            member.size = 1
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(backup.BackupError, "root member"):
                backup.inspect_archive(archive_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
