#!/usr/bin/env python3
"""Upload verified cold snapshots to an encrypted restic repository."""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import backup

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"
RESTIC_IMAGE = "restic/restic:0.18.1"
ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
ACTIONS = {"init", "upload", "snapshots", "check", "retention"}


class RemoteBackupError(RuntimeError):
    """Raised when remote backup inputs or execution are unsafe."""


def parse_environment(text: str) -> dict[str, str]:
    """Parse a literal Docker env-file subset without shell evaluation."""
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RemoteBackupError(f"environment line {number} has no '=' separator")
        key, value = line.split("=", 1)
        if ENV_KEY_RE.fullmatch(key) is None:
            raise RemoteBackupError(f"environment line {number} has an invalid key")
        if key in values:
            raise RemoteBackupError(f"environment key is duplicated: {key}")
        if "\x00" in value or "\r" in value or "\n" in value:
            raise RemoteBackupError(f"environment value contains a control character: {key}")
        values[key] = value
    return values


def retention_arguments() -> list[str]:
    return [
        "forget",
        "--keep-daily", "7",
        "--keep-weekly", "5",
        "--keep-monthly", "12",
        "--keep-yearly", "3",
        "--prune",
    ]


def _mount(path: Path, target: str, *, read_only: bool) -> str:
    suffix = ":ro" if read_only else ""
    return f"{path.resolve()}:{target}{suffix}"


def build_docker_command(
    action: str,
    *,
    project: str,
    repository_file: Path,
    password_file: Path,
    environment_file: Path | None,
    snapshot: Path | None,
) -> list[str]:
    """Build a restic container command without secret values in arguments."""
    if action not in ACTIONS:
        raise RemoteBackupError(f"unsupported remote backup action: {action}")
    backup.validate_project_name(project)
    if action == "upload":
        if snapshot is None or not snapshot.is_dir():
            raise RemoteBackupError("upload requires an existing snapshot directory")
    elif snapshot is not None:
        raise RemoteBackupError(f"{action} does not accept a snapshot directory")

    command = [
        "docker", "run", "--rm",
        "--volume", _mount(repository_file, "/run/secrets/restic_repository", read_only=True),
        "--volume", _mount(password_file, "/run/secrets/restic_password", read_only=True),
        "--volume", f"{project}_restic_cache:/root/.cache/restic",
        "--env", "RESTIC_REPOSITORY_FILE=/run/secrets/restic_repository",
        "--env", "RESTIC_PASSWORD_FILE=/run/secrets/restic_password",
    ]
    if environment_file is not None:
        command.extend(("--env-file", str(environment_file.resolve())))
    if action == "upload":
        assert snapshot is not None
        command.extend(("--volume", _mount(snapshot, "/snapshot", read_only=True)))

    command.append(RESTIC_IMAGE)
    if action == "init":
        command.append("init")
    elif action == "upload":
        command.extend((
            "backup", "/snapshot",
            "--tag", "docker-compose-files",
            "--host", project,
        ))
    elif action == "snapshots":
        command.extend(("snapshots", "--tag", "docker-compose-files"))
    elif action == "check":
        command.extend(("check", "--read-data-subset=5%"))
    elif action == "retention":
        command.extend(retention_arguments())
    return command


def _validate_private_file(path: Path, label: str, *, allow_empty: bool = False) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RemoteBackupError(f"{label} is unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RemoteBackupError(f"{label} must be a regular file, not a symlink")
    if metadata.st_mode & 0o077:
        raise RemoteBackupError(f"{label} must not be accessible by group or other users")
    if not allow_empty and metadata.st_size == 0:
        raise RemoteBackupError(f"{label} is empty")


def _project_from_env() -> str:
    env_path = ROOT / ".env"
    if env_path.is_file():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("HOMELAB_PROJECT_NAME="):
                value = raw.split("=", 1)[1].strip()
                backup.validate_project_name(value)
                return value
    return "homelab"


def run_command(command: Sequence[str]) -> int:
    try:
        result = subprocess.run(
            list(command),
            cwd=ROOT,
            check=False,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RemoteBackupError("Docker CLI is required") from exc
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ACTIONS))
    parser.add_argument("snapshot", nargs="?", type=Path)
    parser.add_argument("--project", default=None)
    parser.add_argument("--repository-file", type=Path, default=SECRETS / "restic_repository")
    parser.add_argument("--password-file", type=Path, default=SECRETS / "restic_password")
    parser.add_argument("--environment-file", type=Path, default=SECRETS / "restic_environment")
    args = parser.parse_args()

    try:
        project = args.project or _project_from_env()
        backup.validate_project_name(project)
        _validate_private_file(args.repository_file, "restic repository file")
        _validate_private_file(args.password_file, "restic password file")

        environment_file: Path | None = args.environment_file
        if environment_file.exists():
            _validate_private_file(environment_file, "restic environment file", allow_empty=True)
            parse_environment(environment_file.read_text(encoding="utf-8"))
        else:
            environment_file = None

        snapshot: Path | None = args.snapshot
        if args.action == "upload":
            if snapshot is None:
                raise RemoteBackupError("upload requires BACKUP/snapshot path")
            snapshot = snapshot.resolve()
            backup.verify_snapshot(snapshot)
            print(f"Verified local snapshot before remote upload: {snapshot.name}")
        elif snapshot is not None:
            raise RemoteBackupError(f"{args.action} does not accept a snapshot path")

        command = build_docker_command(
            args.action,
            project=project,
            repository_file=args.repository_file,
            password_file=args.password_file,
            environment_file=environment_file,
            snapshot=snapshot,
        )
        return run_command(command)
    except (backup.BackupError, OSError, RemoteBackupError, UnicodeError) as exc:
        print(f"Remote backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
