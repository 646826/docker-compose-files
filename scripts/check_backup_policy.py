#!/usr/bin/env python3
"""Focused static acceptance checks for verified volume backup and restore."""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
EXPECTED_VOLUMES = (
    "influxdb_data",
    "influxdb_config",
    "grafana_data",
    "portainer_data",
    "netdata_config",
    "netdata_lib",
    "netdata_cache",
    "mosquitto_data",
    "openhab_addons",
    "openhab_conf",
    "openhab_userdata",
)


def error(message: str) -> None:
    ERRORS.append(message)


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        error(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def target_block(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
        makefile,
    )
    return match.group(0) if match else ""


def load_backup_module():
    path = ROOT / "scripts/backup.py"
    if not path.is_file():
        error("scripts/backup.py is missing")
        return None
    spec = importlib.util.spec_from_file_location("backup_policy_module", path)
    if spec is None or spec.loader is None:
        error("scripts/backup.py cannot be imported")
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - diagnostic path
        error(f"scripts/backup.py import failed: {exc}")
        return None
    return module


def main() -> int:
    backup_source = read_required("scripts/backup.py")
    tests = read_required("scripts/test_backup.py")
    runtime = read_required("scripts/check_backup_runtime.sh")
    workflow = read_required(".github/workflows/backup-runtime.yml")
    makefile = read_required("Makefile")
    gitignore = read_required(".gitignore")
    check_script = read_required("scripts/check.sh")
    image_checker = read_required("scripts/check_images.py")
    image_tests = read_required("scripts/test_check_images.py")
    readme = read_required("README.md")
    backup_doc = read_required("docs/BACKUP.md")
    migration = read_required("docs/MIGRATION.md")
    module = load_backup_module()

    if module is not None:
        if tuple(module.CURRENT_VOLUMES) != EXPECTED_VOLUMES:
            error("backup inventory must match the exact eleven Compose volumes")
        if module.HELPER_IMAGE != "alpine:3.24.1":
            error("backup helper image must be pinned to alpine:3.24.1")
        verify_source = inspect.getsource(module.verify_snapshot)
        if "docker" in verify_source.lower():
            error("offline verify_snapshot must not invoke Docker")

    required_backup_fragments = (
        "readonly,volume-nocopy",
        "dst=/volume,volume-nocopy",
        "com.docker.compose.project",
        "com.docker.compose.volume",
        "project_containers",
        "volume_users",
        "volume_empty",
        "os.replace(staging, final_path)",
        "inspect_archive",
        "source_git_dirty",
        "declared_volumes",
        "snapshot entry must not be a symlink",
        "target volume {name} is not empty",
    )
    for fragment in required_backup_fragments:
        if fragment not in backup_source:
            error(f"backup implementation is missing: {fragment}")

    forbidden = (
        "docker volume " + "prune",
        "docker system " + "prune",
        "/var/lib/docker/" + "volumes",
        "docker compose " + "stop",
        "docker compose " + "down",
    )
    for fragment in forbidden:
        if fragment in backup_source or fragment in runtime:
            error(f"backup implementation contains forbidden host-wide behavior: {fragment}")

    for target, command in (
        ("backup", 'python3 scripts/backup.py create'),
        ("verify-backup", 'python3 scripts/backup.py verify "$(BACKUP)"'),
        ("restore", 'python3 scripts/backup.py restore "$(BACKUP)"'),
        ("check-backup-runtime", "sh ./scripts/check_backup_runtime.sh"),
    ):
        block = target_block(makefile, target)
        if not block:
            error(f"Makefile target is missing: {target}")
        elif command not in block:
            error(f"Makefile target {target} must run: {command}")
    for target in ("verify-backup", "restore"):
        if 'BACKUP is required' not in target_block(makefile, target):
            error(f"Makefile target {target} must reject an empty BACKUP")

    if "/backups/" not in gitignore:
        error(".gitignore must ignore only the repository-root /backups/ directory")
    if "python3 scripts/check_backup_policy.py" not in check_script:
        error("scripts/check.sh must run backup policy checks")
    if "python3 scripts/test_backup.py" not in check_script:
        error("scripts/check.sh must run backup tests")

    if 'BACKUP_HELPER_IMAGE = "alpine:3.24.1"' not in image_checker:
        error("image verification must include the backup helper image")
    if "BACKUP_HELPER_IMAGE" not in image_tests:
        error("image tests must cover the backup helper image")

    required_test_names = (
        "test_tar_rejects_unsafe_members",
        "test_verify_rejects_checksum_mismatch",
        "test_create_publishes_atomically_and_records_missing",
        "test_restore_refuses_non_empty_target_before_creating_any_volume",
        "test_failed_restore_removes_only_created_volumes",
        "test_cli_verify_has_no_traceback",
        "test_tar_rejects_non_directory_root_member",
        "test_later_restore_failure_reports_populated_preexisting_volume",
    )
    for name in required_test_names:
        if name not in tests:
            error(f"backup behavioral contract is missing: {name}")
    if (ROOT / "scripts/test_backup_tar_root.py").exists():
        error("backup regressions must live in scripts/test_backup.py, not a separate test file")

    required_runtime = (
        "HOMELAB_PROJECT_NAME=\"$PROJECT\" BACKUP_ROOT=\"$BACKUP_ROOT\"",
        "python3 \"$ROOT/scripts/backup.py\" verify",
        "HOMELAB_PROJECT_NAME=\"$RESTORE_PROJECT\"",
        "Tampered snapshot unexpectedly passed verification",
        "Restore unexpectedly accepted a non-empty target volume",
        "Backup runtime round trip passed",
        "alpine:3.24.1",
    )
    for fragment in required_runtime:
        if fragment not in runtime:
            error(f"backup runtime harness is missing: {fragment}")

    required_workflow = (
        "name: Backup runtime",
        "pull_request:",
        "schedule:",
        "workflow_dispatch:",
        "contents: read",
        "timeout-minutes: 15",
        "make check-backup-runtime",
        "if: failure()",
        "retention-days: 3",
    )
    for fragment in required_workflow:
        if fragment not in workflow:
            error(f"backup runtime workflow is missing: {fragment}")
    if "backups/" in re.sub(r'path:\s*backup-runtime\.log', "", workflow):
        error("backup runtime workflow must not upload snapshot directories")

    for fragment in (
        "make backup",
        "make verify-backup",
        "make restore",
        "HOMELAB_PROJECT_NAME=homelab-recovery",
        "checksums",
        "not encryption",
        ".env",
        ".secrets/",
    ):
        if fragment not in backup_doc:
            error(f"docs/BACKUP.md is missing: {fragment}")
    if "docs/BACKUP.md" not in readme:
        error("README must link to docs/BACKUP.md")
    if "docs/BACKUP.md" not in migration:
        error("migration guide must link to docs/BACKUP.md")
    for fragment in (
        "### 5. Изолированная backup/restore runtime-проверка",
        "make check-backup-runtime",
    ):
        if fragment not in readme:
            error(f"README backup verification documentation is missing: {fragment}")

    for executable in ("scripts/backup.py", "scripts/check_backup_runtime.sh"):
        path = ROOT / executable
        if path.is_file() and not path.stat().st_mode & 0o100:
            error(f"{executable} must be executable")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Backup policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
