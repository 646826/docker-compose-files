#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_PATH = ROOT / "scripts" / "backup.py"
SPEC = importlib.util.spec_from_file_location("backup_module", BACKUP_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load scripts/backup.py")
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def write_tar(path: Path, entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for member, payload in entries:
            archive.addfile(member, io.BytesIO(payload) if payload is not None else None)
    path.chmod(0o600)


def regular(name: str, payload: bytes = b"x", mode: int = 0o640) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = mode
    return member, payload


def directory(name: str, mode: int = 0o750) -> tuple[tarfile.TarInfo, None]:
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = mode
    return member, None


def symlink(name: str, target: str) -> tuple[tarfile.TarInfo, None]:
    member = tarfile.TarInfo(name)
    member.type = tarfile.SYMTYPE
    member.linkname = target
    return member, None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build_snapshot(
    root: Path,
    *,
    declared: tuple[str, ...] = ("grafana_data", "portainer_data"),
    archived: tuple[str, ...] = ("grafana_data",),
    source_project: str = "homelab",
    extra_manifest: dict[str, object] | None = None,
) -> Path:
    snapshot_id = f"{source_project}-20260720T120000Z-a1b2c3d4"
    snapshot = root / snapshot_id
    volumes_dir = snapshot / "volumes"
    volumes_dir.mkdir(parents=True, mode=0o700)
    snapshot.chmod(0o700)
    volumes_dir.chmod(0o700)

    volume_entries: list[dict[str, object]] = []
    declared = tuple(sorted(declared))
    archived = tuple(sorted(archived))
    for logical in archived:
        archive_path = volumes_dir / f"{logical}.tar.gz"
        write_tar(
            archive_path,
            [
                directory("."),
                directory("./nested"),
                regular("./nested/data.bin", b"\x00\x01fixture"),
                regular("./empty", b""),
                symlink("./nested/link", "data.bin"),
            ],
        )
        member_count, uncompressed = backup.inspect_archive(archive_path)
        volume_entries.append(
            {
                "logical_name": logical,
                "source_name": f"{source_project}_{logical}",
                "archive": f"volumes/{logical}.tar.gz",
                "archive_size_bytes": archive_path.stat().st_size,
                "archive_sha256": sha256(archive_path),
                "member_count": member_count,
                "uncompressed_file_bytes": uncompressed,
                "driver": "local",
            }
        )

    manifest: dict[str, object] = {
        "format": backup.FORMAT,
        "format_version": backup.FORMAT_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": "2026-07-20T12:00:00Z",
        "source_project": source_project,
        "source_git_commit": "d" * 40,
        "source_git_dirty": False,
        "helper_image": backup.HELPER_IMAGE,
        "container_images": [backup.HELPER_IMAGE, "grafana/grafana:13.1.0"],
        "declared_volumes": list(declared),
        "volumes": volume_entries,
        "missing_volumes": sorted(set(declared) - set(archived)),
    }
    if extra_manifest:
        manifest.update(extra_manifest)

    recovery = snapshot / "RECOVERY.md"
    recovery.write_text("# Recovery\n", encoding="utf-8")
    recovery.chmod(0o600)
    manifest_path = snapshot / "manifest.json"
    manifest_path.write_bytes(canonical_json(manifest))
    manifest_path.chmod(0o600)

    checksum_paths = ["RECOVERY.md", "manifest.json"] + [
        f"volumes/{logical}.tar.gz" for logical in archived
    ]
    sums = snapshot / "SHA256SUMS"
    sums.write_text(
        "".join(f"{sha256(snapshot / relative)}  {relative}\n" for relative in sorted(checksum_paths)),
        encoding="utf-8",
    )
    sums.chmod(0o600)
    return snapshot


class FakeDocker:
    def __init__(self) -> None:
        self.volumes: dict[str, dict[str, object]] = {}
        self.archive_bytes: dict[str, bytes] = {}
        self.project_container_lines: list[str] = []
        self.users: dict[str, list[str]] = {}
        self.empty: dict[str, bool] = {}
        self.calls: list[tuple[object, ...]] = []
        self.fail_restore_for: str | None = None

    def ensure_ready(self) -> None:
        self.calls.append(("ensure_ready",))

    def project_containers(self, project: str) -> list[str]:
        self.calls.append(("project_containers", project))
        return list(self.project_container_lines)

    def inspect_volume(self, name: str) -> dict[str, object] | None:
        self.calls.append(("inspect_volume", name))
        value = self.volumes.get(name)
        return dict(value) if value is not None else None

    def volume_users(self, name: str) -> list[str]:
        self.calls.append(("volume_users", name))
        return list(self.users.get(name, []))

    def stream_archive(self, name: str, destination: Path) -> str:
        self.calls.append(("stream_archive", name))
        payload = self.archive_bytes[name]
        destination.write_bytes(payload)
        destination.chmod(0o600)
        return hashlib.sha256(payload).hexdigest()

    def volume_empty(self, name: str) -> bool:
        self.calls.append(("volume_empty", name))
        return self.empty.get(name, True)

    def create_volume(self, name: str, project: str, logical: str) -> None:
        self.calls.append(("create_volume", name, project, logical))
        self.volumes[name] = {
            "Name": name,
            "Driver": "local",
            "Options": {},
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.volume": logical,
            },
        }
        self.empty[name] = True

    def remove_volume(self, name: str) -> None:
        self.calls.append(("remove_volume", name))
        self.volumes.pop(name, None)

    def stream_restore(self, archive: Path, name: str) -> None:
        self.calls.append(("stream_restore", archive.name, name))
        if self.fail_restore_for == name:
            raise backup.BackupError(f"simulated restore failure for {name}")
        self.empty[name] = False


class BackupTests(unittest.TestCase):
    def test_exact_inventory_and_helper(self) -> None:
        self.assertEqual(backup.HELPER_IMAGE, "alpine:3.24.1")
        self.assertEqual(
            backup.CURRENT_VOLUMES,
            (
                "influxdb_data", "influxdb_config", "grafana_data",
                "portainer_data", "netdata_config", "netdata_lib",
                "netdata_cache", "mosquitto_data", "openhab_addons",
                "openhab_conf", "openhab_userdata",
            ),
        )

    def test_project_name_precedence_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            env_file = Path(directory_name) / ".env"
            env_file.write_text("HOMELAB_PROJECT_NAME=from-file\n", encoding="utf-8")
            self.assertEqual(
                backup.resolve_project_name({"HOMELAB_PROJECT_NAME": "from-env"}, env_file),
                "from-env",
            )
            self.assertEqual(backup.resolve_project_name({}, env_file), "from-file")
            env_file.unlink()
            self.assertEqual(backup.resolve_project_name({}, env_file), "homelab")
            for invalid in ("", "Upper", "-bad", "bad space", "bad/", ".bad"):
                with self.subTest(invalid=invalid), self.assertRaises(backup.BackupError):
                    backup.validate_project_name(invalid)

    def test_tar_rejects_unsafe_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            bad_cases: list[list[tuple[tarfile.TarInfo, bytes | None]]] = []
            absolute = tarfile.TarInfo("/etc/passwd")
            absolute.size = 1
            bad_cases.append([(absolute, b"x")])
            parent = tarfile.TarInfo("../escape")
            parent.size = 1
            bad_cases.append([(parent, b"x")])
            bad_cases.append([regular("./same"), regular("same")])
            fifo = tarfile.TarInfo("pipe")
            fifo.type = tarfile.FIFOTYPE
            bad_cases.append([(fifo, None)])
            char = tarfile.TarInfo("device")
            char.type = tarfile.CHRTYPE
            bad_cases.append([(char, None)])
            bad_cases.append([symlink("dir/link", "../../outside")])
            hard = tarfile.TarInfo("hard")
            hard.type = tarfile.LNKTYPE
            hard.linkname = "../outside"
            bad_cases.append([(hard, None)])
            for index, entries in enumerate(bad_cases):
                archive = root / f"bad-{index}.tar.gz"
                write_tar(archive, entries)
                with self.subTest(index=index), self.assertRaises(backup.BackupError):
                    backup.inspect_archive(archive)

    def test_tar_accepts_safe_relative_symlink_and_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            archive = Path(directory_name) / "safe.tar.gz"
            hard = tarfile.TarInfo("copy")
            hard.type = tarfile.LNKTYPE
            hard.linkname = "dir/file"
            write_tar(
                archive,
                [directory("dir"), regular("dir/file", b"abc"), symlink("dir/link", "file"), (hard, None)],
            )
            self.assertEqual(backup.inspect_archive(archive), (4, 3))

    def test_verify_valid_snapshot_and_snapshot_declared_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(
                Path(directory_name),
                declared=("grafana_data", "future_volume"),
                archived=("grafana_data",),
            )
            manifest = backup.verify_snapshot(snapshot)
            self.assertEqual(manifest["declared_volumes"], ["future_volume", "grafana_data"])

    def test_verify_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name))
            with (snapshot / "volumes/grafana_data.tar.gz").open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaisesRegex(backup.BackupError, "checksum"):
                backup.verify_snapshot(snapshot)

    def test_verify_rejects_unknown_manifest_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name), extra_manifest={"unknown": True})
            manifest_path = snapshot / "manifest.json"
            # Refresh checksum so schema validation is the failure being exercised.
            sums = snapshot / "SHA256SUMS"
            relatives = []
            for line in sums.read_text(encoding="utf-8").splitlines():
                _, relative = line.split("  ", 1)
                relatives.append(relative)
            sums.write_text(
                "".join(f"{sha256(snapshot / relative)}  {relative}\n" for relative in sorted(relatives)),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(backup.BackupError, "manifest keys"):
                backup.verify_snapshot(snapshot)

    def test_verify_rejects_unexpected_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name))
            extra = snapshot / "volumes/unexpected.tar.gz"
            write_tar(extra, [regular("file")])
            with self.assertRaisesRegex(backup.BackupError, "unexpected archive"):
                backup.verify_snapshot(snapshot)

    def test_verify_rejects_symlinked_fixed_entry(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name))
            recovery = snapshot / "RECOVERY.md"
            target = snapshot.parent / "recovery-real.md"
            recovery.rename(target)
            recovery.symlink_to(target)
            with self.assertRaisesRegex(backup.BackupError, "symlink"):
                backup.verify_snapshot(snapshot)

    def test_create_refuses_unsafe_existing_backup_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "backups"
            root.mkdir(mode=0o755)
            docker = FakeDocker()
            with self.assertRaisesRegex(backup.BackupError, "permissions"):
                backup.create_snapshot("homelab", root, docker)

    def test_create_refuses_all_missing_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            docker = FakeDocker()
            with self.assertRaisesRegex(backup.BackupError, "no existing"):
                backup.create_snapshot("homelab", Path(directory_name) / "backups", docker)

    def test_create_refuses_project_containers(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            docker = FakeDocker()
            docker.project_container_lines = ["abc stopped"]
            with self.assertRaisesRegex(backup.BackupError, "make down"):
                backup.create_snapshot("homelab", Path(directory_name) / "backups", docker)

    def test_create_refuses_attached_and_non_local_volumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "backups"
            docker = FakeDocker()
            name = "homelab_grafana_data"
            docker.volumes[name] = {"Name": name, "Driver": "local", "Options": {}, "Labels": {}}
            docker.users[name] = ["container"]
            with self.assertRaisesRegex(backup.BackupError, "attached"):
                backup.create_snapshot("homelab", root, docker)
            docker.users[name] = []
            docker.volumes[name]["Driver"] = "nfs"
            with self.assertRaisesRegex(backup.BackupError, "local"):
                backup.create_snapshot("homelab", root, docker)

    def test_create_publishes_atomically_and_records_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            base = Path(directory_name)
            root = base / "backups"
            docker = FakeDocker()
            actual = "homelab_grafana_data"
            docker.volumes[actual] = {"Name": actual, "Driver": "local", "Options": {}, "Labels": {}}
            source_archive = base / "source.tar.gz"
            write_tar(source_archive, [directory("."), regular("./data", b"payload")])
            docker.archive_bytes[actual] = source_archive.read_bytes()
            snapshot = backup.create_snapshot("homelab", root, docker)
            self.assertTrue(snapshot.is_dir())
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o700)
            self.assertFalse(any(path.name.startswith(".") for path in root.iterdir()))
            manifest = backup.verify_snapshot(snapshot)
            self.assertEqual(tuple(manifest["declared_volumes"]), tuple(sorted(backup.CURRENT_VOLUMES)))
            self.assertEqual([entry["logical_name"] for entry in manifest["volumes"]], ["grafana_data"])
            self.assertIn("portainer_data", manifest["missing_volumes"])

    def test_restore_refuses_unknown_archived_volume_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(
                Path(directory_name),
                declared=("future_volume",),
                archived=("future_volume",),
            )
            docker = FakeDocker()
            with self.assertRaisesRegex(backup.BackupError, "unsupported logical"):
                backup.restore_snapshot(snapshot, "recovery", docker)
            self.assertEqual(docker.calls, [])

    def test_restore_refuses_non_empty_target_before_creating_any_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name))
            docker = FakeDocker()
            target = "recovery_grafana_data"
            docker.volumes[target] = {"Name": target, "Driver": "local", "Options": {}, "Labels": {}}
            docker.empty[target] = False
            with self.assertRaisesRegex(backup.BackupError, "not empty"):
                backup.restore_snapshot(snapshot, "recovery", docker)
            self.assertFalse(any(call[0] == "create_volume" for call in docker.calls))

    def test_restore_refuses_conflicting_compose_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name))
            docker = FakeDocker()
            target = "recovery_grafana_data"
            docker.volumes[target] = {
                "Name": target,
                "Driver": "local",
                "Options": {},
                "Labels": {"com.docker.compose.project": "other"},
            }
            with self.assertRaisesRegex(backup.BackupError, "labels"):
                backup.restore_snapshot(snapshot, "recovery", docker)

    def test_restore_creates_labels_and_restores_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(
                Path(directory_name),
                declared=("grafana_data", "mosquitto_data"),
                archived=("mosquitto_data", "grafana_data"),
            )
            docker = FakeDocker()
            restored = backup.restore_snapshot(snapshot, "recovery", docker)
            self.assertEqual(restored, ["recovery_grafana_data", "recovery_mosquitto_data"])
            create_calls = [call for call in docker.calls if call[0] == "create_volume"]
            self.assertEqual(
                create_calls,
                [
                    ("create_volume", "recovery_grafana_data", "recovery", "grafana_data"),
                    ("create_volume", "recovery_mosquitto_data", "recovery", "mosquitto_data"),
                ],
            )
            restore_calls = [call for call in docker.calls if call[0] == "stream_restore"]
            self.assertEqual([call[2] for call in restore_calls], restored)

    def test_failed_restore_removes_only_created_volumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(
                Path(directory_name),
                declared=("grafana_data", "mosquitto_data"),
                archived=("grafana_data", "mosquitto_data"),
            )
            docker = FakeDocker()
            preexisting = "recovery_grafana_data"
            created = "recovery_mosquitto_data"
            docker.volumes[preexisting] = {
                "Name": preexisting,
                "Driver": "local",
                "Options": {},
                "Labels": {},
            }
            docker.empty[preexisting] = True
            docker.fail_restore_for = created
            with self.assertRaisesRegex(backup.BackupError, "simulated restore failure"):
                backup.restore_snapshot(snapshot, "recovery", docker)
            remove_calls = [call for call in docker.calls if call[0] == "remove_volume"]
            self.assertEqual(remove_calls, [("remove_volume", created)])
            self.assertIn(preexisting, docker.volumes)

    def test_cli_verify_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            snapshot = build_snapshot(Path(directory_name))
            result = subprocess.run(
                [sys.executable, str(BACKUP_PATH), "verify", str(snapshot)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Backup verification passed", result.stdout)
            bad = subprocess.run(
                [sys.executable, str(BACKUP_PATH), "verify", str(snapshot / "missing")],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertNotIn("Traceback", bad.stderr)


class ConsolidatedBackupRegressionTests(unittest.TestCase):
    def test_tar_rejects_non_directory_root_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "regular-root.tar.gz"
            member = tarfile.TarInfo("./")
            member.size = 1
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.addfile(member, io.BytesIO(b"x"))
            with self.assertRaisesRegex(backup.BackupError, "root member"):
                backup.inspect_archive(archive_path)

    def test_later_restore_failure_reports_populated_preexisting_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = build_snapshot(
                Path(directory),
                declared=("grafana_data", "mosquitto_data"),
                archived=("grafana_data", "mosquitto_data"),
            )
            docker = FakeDocker()
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
