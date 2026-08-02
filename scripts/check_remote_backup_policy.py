#!/usr/bin/env python3
"""Static policy for encrypted restic snapshot transport."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        ERRORS.append(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def target_block(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
        makefile,
    )
    return match.group(0) if match else ""


def main() -> int:
    wrapper = read_required("scripts/remote_backup.py")
    tests = read_required("scripts/test_remote_backup.py")
    runtime = read_required("scripts/check_remote_backup_runtime.sh")
    workflow = read_required(".github/workflows/remote-backup-runtime.yml")
    docs = read_required("docs/REMOTE_BACKUP.md")
    makefile = read_required("Makefile")
    check = read_required("scripts/check.sh")

    if wrapper:
        for fragment in (
            'RESTIC_IMAGE = "restic/restic:0.18.1"',
            "backup.verify_snapshot(snapshot)",
            'RESTIC_REPOSITORY_FILE=/run/secrets/restic_repository',
            'RESTIC_PASSWORD_FILE=/run/secrets/restic_password',
            '"--env-file"',
            '"/snapshot", read_only=True',
        ):
            if fragment not in wrapper:
                ERRORS.append(f"remote backup wrapper is missing: {fragment}")
        for forbidden in (
            "shell=True",
            "docker system " + "prune",
            "subprocess.run(command, shell",
        ):
            if forbidden in wrapper:
                ERRORS.append(f"remote backup wrapper contains forbidden behavior: {forbidden}")

    if tests:
        for name in (
            "test_upload_uses_verified_snapshot_and_file_backed_credentials",
            "test_rejects_invalid_or_duplicate_keys",
            "test_retention_is_explicit_and_stable",
            "test_runtime_restic_uses_calling_uid_gid",
        ):
            if name not in tests:
                ERRORS.append(f"remote backup regression test is missing: {name}")

    if runtime:
        for fragment in (
            "restic/restic:0.18.1",
            'for command in docker python3 openssl id; do',
            '--user "$(id -u):$(id -g)"',
            "restic init",
            "restic_source backup",
            "restic check --read-data",
            "restic_restore restore latest",
            "Wrong restic password unexpectedly succeeded",
            "Remote backup runtime test passed",
        ):
            if fragment not in runtime:
                ERRORS.append(f"remote backup runtime is missing: {fragment}")

    targets = {
        "remote-init": "remote_backup.py init",
        "remote-backup": "remote_backup.py upload",
        "remote-snapshots": "remote_backup.py snapshots",
        "verify-remote-backup": "remote_backup.py check",
        "remote-retention": "remote_backup.py retention",
        "check-remote-backup-runtime": "check_remote_backup_runtime.sh",
    }
    for target, command in targets.items():
        block = target_block(makefile, target)
        if not block:
            ERRORS.append(f"Makefile target is missing: {target}")
        elif command not in block:
            ERRORS.append(f"Makefile target {target} must run {command}")

    if check:
        for command in (
            "python3 scripts/check_remote_backup_policy.py",
            "python3 scripts/test_remote_backup.py",
        ):
            if command not in check:
                ERRORS.append(f"fast checks must run: {command}")

    if workflow:
        for fragment in (
            "name: Remote backup runtime",
            "contents: read",
            "make check-remote-backup-runtime",
            "timeout-minutes: 20",
            "retention-days: 3",
        ):
            if fragment not in workflow:
                ERRORS.append(f"remote backup workflow is missing: {fragment}")

    if docs:
        for fragment in (
            "make remote-init",
            "make remote-backup BACKUP=",
            "make remote-retention",
            ".secrets/restic_repository",
            ".secrets/restic_password",
            "SFTP",
            "S3",
        ):
            if fragment not in docs:
                ERRORS.append(f"remote backup documentation is missing: {fragment}")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Remote backup policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
