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

TEST_SPEC = importlib.util.spec_from_file_location("backup_tests_module", ROOT / "scripts/test_backup.py")
assert TEST_SPEC and TEST_SPEC.loader
backup_tests = importlib.util.module_from_spec(TEST_SPEC)
TEST_SPEC.loader.exec_module(backup_tests)


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


class RestoreFailureDiagnosticsTests(unittest.TestCase):
    def test_later_failure_reports_already_populated_preexisting_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = backup_tests.build_snapshot(
                Path(directory),
                declared=("grafana_data", "mosquitto_data"),
                archived=("grafana_data", "mosquitto_data"),
            )
            docker = backup_tests.FakeDocker()
            preexisting = "recovery_grafana_data"
            failing_created = "recovery_mosquitto_data"
            docker.volumes[preexisting] = {
                "Name": preexisting,
                "Driver": "local",
                "Options": {},
                "Labels": {},
            }
            docker.empty[preexisting] = True
            docker.fail_restore_for = failing_created
            with self.assertRaisesRegex(
                backup.BackupError,
                "pre-existing volumes may be partially populated: recovery_grafana_data",
            ):
                backup.restore_snapshot(snapshot, "recovery", docker)
            self.assertIn(preexisting, docker.volumes)
            self.assertNotIn(failing_created, docker.volumes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
