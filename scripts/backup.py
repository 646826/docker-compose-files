#!/usr/bin/env python3
"""Cold, verified backup and safe restore for the homelab Docker volumes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "docker-compose-files-volume-backup"
FORMAT_VERSION = 1
HELPER_IMAGE = "alpine:3.24.1"
CURRENT_VOLUMES = (
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
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
LOGICAL_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SNAPSHOT_RE = re.compile(
    r"^(?P<project>[a-z0-9][a-z0-9_-]*)-"
    r"(?P<stamp>[0-9]{8}T[0-9]{6}Z)-(?P<random>[0-9a-f]{8})$"
)
CHECKSUM_RE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)")
EXPECTED_TOP_LEVEL = {"manifest.json", "SHA256SUMS", "RECOVERY.md", "volumes"}
MANIFEST_KEYS = {
    "format",
    "format_version",
    "snapshot_id",
    "created_at",
    "source_project",
    "source_git_commit",
    "source_git_dirty",
    "helper_image",
    "container_images",
    "declared_volumes",
    "volumes",
    "missing_volumes",
}
VOLUME_KEYS = {
    "logical_name",
    "source_name",
    "archive",
    "archive_size_bytes",
    "archive_sha256",
    "member_count",
    "uncompressed_file_bytes",
    "driver",
}
CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """An expected, operator-facing backup or restore failure."""


class DockerAPI(Protocol):
    def ensure_ready(self) -> None: ...

    def project_containers(self, project: str) -> list[str]: ...

    def inspect_volume(self, name: str) -> dict[str, object] | None: ...

    def volume_users(self, name: str) -> list[str]: ...

    def stream_archive(self, name: str, destination: Path) -> str: ...

    def volume_empty(self, name: str) -> bool: ...

    def create_volume(self, name: str, project: str, logical: str) -> None: ...

    def remove_volume(self, name: str) -> None: ...

    def stream_restore(self, archive: Path, name: str) -> None: ...


def validate_project_name(value: str) -> str:
    if not PROJECT_RE.fullmatch(value):
        raise BackupError(
            "HOMELAB_PROJECT_NAME must start with a lowercase letter or digit "
            "and contain only lowercase letters, digits, hyphen, or underscore"
        )
    return value


def _read_env_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    value: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeError as exc:
        raise BackupError(f"cannot read {path}: {exc}") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, current_value = line.split("=", 1)
        if current_key == key:
            value = current_value
    return value


def resolve_project_name(environ: Mapping[str, str], env_file: Path) -> str:
    if "HOMELAB_PROJECT_NAME" in environ:
        return validate_project_name(environ["HOMELAB_PROJECT_NAME"])
    from_file = _read_env_value(env_file, "HOMELAB_PROJECT_NAME")
    return validate_project_name(from_file if from_file is not None else "homelab")


def actual_volume_name(project: str, logical: str) -> str:
    return f"{validate_project_name(project)}_{logical}"


def _contains_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _canonical_member_name(name: str) -> tuple[str, ...]:
    if not name or _contains_control(name):
        raise BackupError("tar member name is empty or contains control characters")
    pure = PurePosixPath(name)
    if pure.is_absolute():
        raise BackupError(f"absolute tar member path is forbidden: {name}")
    parts: list[str] = []
    for part in pure.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise BackupError(f"parent traversal is forbidden: {name}")
        parts.append(part)
    return tuple(parts)


def _resolve_link(member_parts: tuple[str, ...], linkname: str, *, hard: bool) -> None:
    if not linkname or _contains_control(linkname):
        raise BackupError("tar link target is empty or contains control characters")
    target = PurePosixPath(linkname)
    if target.is_absolute():
        raise BackupError(f"absolute tar link target is forbidden: {linkname}")
    stack = [] if hard else list(member_parts[:-1])
    for part in target.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise BackupError(f"tar link escapes archive root: {linkname}")
            stack.pop()
        else:
            stack.append(part)


def inspect_archive(path: Path) -> tuple[int, int]:
    seen: set[tuple[str, ...]] = set()
    member_count = 0
    uncompressed_file_bytes = 0
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for member in archive:
                canonical = _canonical_member_name(member.name)
                if not canonical and not member.isdir():
                    raise BackupError("tar archive root member must be a directory")
                if canonical in seen:
                    raise BackupError(f"duplicate tar member: {member.name}")
                seen.add(canonical)
                if member.isdir():
                    pass
                elif member.isreg():
                    if member.size < 0:
                        raise BackupError(f"negative tar member size: {member.name}")
                    uncompressed_file_bytes += member.size
                elif member.issym():
                    _resolve_link(canonical, member.linkname, hard=False)
                elif member.islnk():
                    _resolve_link(canonical, member.linkname, hard=True)
                else:
                    raise BackupError(f"unsupported tar member type: {member.name}")
                member_count += 1
    except BackupError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise BackupError(f"cannot inspect archive {path}: {exc}") from exc
    return member_count, uncompressed_file_bytes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BackupError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def _canonical_json(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path: Path) -> Path:
    absolute = _absolute_without_resolving(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BackupError(f"cannot inspect path component {current}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise BackupError(f"snapshot path must not traverse a symlink: {current}")
    return absolute


def _private_mode(path: Path, *, directory: bool) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BackupError(f"cannot inspect {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise BackupError(f"snapshot entry must not be a symlink: {path}")
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(metadata.st_mode):
        kind = "directory" if directory else "regular file"
        raise BackupError(f"snapshot entry must be a {kind}: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise BackupError(f"snapshot entry has unsafe permissions: {path}")
    return metadata


def _safe_checksum_relative(value: str) -> str:
    pure = PurePosixPath(value)
    if pure.is_absolute() or _contains_control(value):
        raise BackupError(f"unsafe checksum path: {value}")
    parts = pure.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise BackupError(f"unsafe checksum path: {value}")
    normalized = "/".join(parts)
    if normalized not in {"manifest.json", "RECOVERY.md"} and not re.fullmatch(
        r"volumes/[a-z0-9][a-z0-9_]*\.tar\.gz", normalized
    ):
        raise BackupError(f"unsupported checksum path: {value}")
    return normalized


def _parse_checksums(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BackupError(f"cannot read SHA256SUMS: {exc}") from exc
    if raw and not raw.endswith("\n"):
        raise BackupError("SHA256SUMS must end with a newline")
    checksums: dict[str, str] = {}
    previous: str | None = None
    for line_number, line in enumerate(raw.splitlines(), start=1):
        match = CHECKSUM_RE.fullmatch(line)
        if match is None:
            raise BackupError(f"invalid SHA256SUMS line {line_number}")
        digest, relative = match.groups()
        relative = _safe_checksum_relative(relative)
        if relative in checksums:
            raise BackupError(f"duplicate checksum path: {relative}")
        if previous is not None and relative <= previous:
            raise BackupError("SHA256SUMS paths must be strictly sorted")
        previous = relative
        checksums[relative] = digest
    return checksums


def _expect_type(value: object, expected: type, label: str) -> None:
    if type(value) is not expected:
        raise BackupError(f"{label} has an invalid type")


def _validate_sorted_unique_strings(
    value: object,
    label: str,
    *,
    nonempty: bool = False,
    logical: bool = False,
    images: bool = False,
) -> list[str]:
    _expect_type(value, list, label)
    result = value
    assert isinstance(result, list)
    if nonempty and not result:
        raise BackupError(f"{label} must not be empty")
    if any(type(item) is not str for item in result):
        raise BackupError(f"{label} must contain only strings")
    strings = list(result)
    if strings != sorted(set(strings)):
        raise BackupError(f"{label} must be sorted and unique")
    if logical and any(LOGICAL_RE.fullmatch(item) is None for item in strings):
        raise BackupError(f"{label} contains an invalid logical volume name")
    if images:
        for image in strings:
            final = image.rsplit("/", 1)[-1]
            if "@sha256:" not in image and ":" not in final:
                raise BackupError(f"container image has an implicit tag: {image}")
            if final.endswith(":latest"):
                raise BackupError(f"container image uses latest: {image}")
    return strings


def _validate_manifest(document: object) -> dict[str, object]:
    _expect_type(document, dict, "manifest")
    manifest = document
    assert isinstance(manifest, dict)
    if set(manifest) != MANIFEST_KEYS:
        missing = sorted(MANIFEST_KEYS - set(manifest))
        unknown = sorted(set(manifest) - MANIFEST_KEYS)
        raise BackupError(f"manifest keys mismatch; missing={missing}, unknown={unknown}")
    if manifest["format"] != FORMAT or manifest["format_version"] != FORMAT_VERSION:
        raise BackupError("unsupported backup format or version")

    for key in ("snapshot_id", "created_at", "source_project", "helper_image"):
        _expect_type(manifest[key], str, key)
    snapshot_id = manifest["snapshot_id"]
    created_at = manifest["created_at"]
    source_project = manifest["source_project"]
    assert isinstance(snapshot_id, str) and isinstance(created_at, str) and isinstance(source_project, str)
    match = SNAPSHOT_RE.fullmatch(snapshot_id)
    if match is None:
        raise BackupError("snapshot_id is invalid")
    validate_project_name(source_project)
    if match.group("project") != source_project:
        raise BackupError("snapshot_id project does not match source_project")
    try:
        parsed_time = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise BackupError("created_at must be a UTC second timestamp") from exc
    if parsed_time.strftime("%Y%m%dT%H%M%SZ") != match.group("stamp"):
        raise BackupError("snapshot_id timestamp does not match created_at")

    git_commit = manifest["source_git_commit"]
    git_dirty = manifest["source_git_dirty"]
    if git_commit is None or git_dirty is None:
        if git_commit is not None or git_dirty is not None:
            raise BackupError("source Git fields must both be null or both be set")
    else:
        if type(git_commit) is not str or GIT_SHA_RE.fullmatch(git_commit) is None:
            raise BackupError("source_git_commit is invalid")
        if type(git_dirty) is not bool:
            raise BackupError("source_git_dirty is invalid")

    _validate_sorted_unique_strings(manifest["container_images"], "container_images", nonempty=True, images=True)
    declared = _validate_sorted_unique_strings(
        manifest["declared_volumes"], "declared_volumes", nonempty=True, logical=True
    )
    missing = _validate_sorted_unique_strings(manifest["missing_volumes"], "missing_volumes", logical=True)

    _expect_type(manifest["volumes"], list, "volumes")
    raw_entries = manifest["volumes"]
    assert isinstance(raw_entries, list)
    if not raw_entries:
        raise BackupError("snapshot contains no archived volumes")
    entries: list[dict[str, object]] = []
    logical_names: list[str] = []
    for index, raw_entry in enumerate(raw_entries):
        _expect_type(raw_entry, dict, f"volumes[{index}]")
        entry = raw_entry
        assert isinstance(entry, dict)
        if set(entry) != VOLUME_KEYS:
            raise BackupError(f"volume entry {index} has invalid keys")
        for key in ("logical_name", "source_name", "archive", "archive_sha256", "driver"):
            _expect_type(entry[key], str, f"volumes[{index}].{key}")
        for key in ("archive_size_bytes", "member_count", "uncompressed_file_bytes"):
            if type(entry[key]) is not int or entry[key] < 0:
                raise BackupError(f"volumes[{index}].{key} must be a non-negative integer")
        logical_name = entry["logical_name"]
        assert isinstance(logical_name, str)
        if logical_name not in declared:
            raise BackupError(f"archived logical volume is not declared: {logical_name}")
        if entry["source_name"] != f"{source_project}_{logical_name}":
            raise BackupError(f"source volume name mismatch for {logical_name}")
        if entry["archive"] != f"volumes/{logical_name}.tar.gz":
            raise BackupError(f"archive path mismatch for {logical_name}")
        if SHA256_RE.fullmatch(entry["archive_sha256"]) is None:
            raise BackupError(f"archive SHA-256 is invalid for {logical_name}")
        if entry["driver"] != "local":
            raise BackupError(f"unsupported source volume driver for {logical_name}")
        logical_names.append(logical_name)
        entries.append(dict(entry))
    if logical_names != sorted(set(logical_names)):
        raise BackupError("volume entries must be sorted and unique by logical_name")
    if set(logical_names) & set(missing):
        raise BackupError("archived and missing volume sets overlap")
    if set(logical_names) | set(missing) != set(declared):
        raise BackupError("archived and missing volumes do not cover declared_volumes")
    manifest["volumes"] = entries
    return manifest


def _validate_snapshot_directory_name(path: Path, snapshot_id: str) -> None:
    if path.name == snapshot_id:
        return
    if path.name.startswith(f".{snapshot_id}.tmp-"):
        return
    raise BackupError("snapshot directory name does not match manifest snapshot_id")


def verify_snapshot(path: Path) -> dict[str, object]:
    snapshot = _reject_symlink_components(path)
    _private_mode(snapshot, directory=True)
    actual_top = {entry.name for entry in snapshot.iterdir()}
    if actual_top != EXPECTED_TOP_LEVEL:
        raise BackupError(
            f"snapshot top-level entries mismatch; missing={sorted(EXPECTED_TOP_LEVEL - actual_top)}, "
            f"unexpected={sorted(actual_top - EXPECTED_TOP_LEVEL)}"
        )

    manifest_path = snapshot / "manifest.json"
    sums_path = snapshot / "SHA256SUMS"
    recovery_path = snapshot / "RECOVERY.md"
    volumes_dir = snapshot / "volumes"
    for fixed in (manifest_path, sums_path, recovery_path):
        _private_mode(fixed, directory=False)
    _private_mode(volumes_dir, directory=True)

    checksums = _parse_checksums(sums_path)
    for relative, expected in checksums.items():
        candidate = snapshot / PurePosixPath(relative)
        _reject_symlink_components(candidate)
        _private_mode(candidate, directory=False)
        actual = sha256_file(candidate)
        if actual != expected:
            raise BackupError(f"checksum mismatch for {relative}")

    try:
        raw_manifest = manifest_path.read_bytes()
        document = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"cannot parse manifest.json: {exc}") from exc
    manifest = _validate_manifest(document)
    if raw_manifest != _canonical_json(manifest):
        raise BackupError("manifest.json is not in canonical format")
    snapshot_id = manifest["snapshot_id"]
    assert isinstance(snapshot_id, str)
    _validate_snapshot_directory_name(snapshot, snapshot_id)

    entries = manifest["volumes"]
    assert isinstance(entries, list)
    expected_archives = {entry["archive"] for entry in entries}
    actual_archives = {f"volumes/{entry.name}" for entry in volumes_dir.iterdir()}
    unexpected = actual_archives - expected_archives
    missing = expected_archives - actual_archives
    if unexpected:
        raise BackupError(f"unexpected archive files: {sorted(unexpected)}")
    if missing:
        raise BackupError(f"missing archive files: {sorted(missing)}")

    expected_checksum_paths = {"manifest.json", "RECOVERY.md", *expected_archives}
    if set(checksums) != expected_checksum_paths:
        raise BackupError(
            "checksum path set mismatch; "
            f"missing={sorted(expected_checksum_paths - set(checksums))}, "
            f"unexpected={sorted(set(checksums) - expected_checksum_paths)}"
        )

    for entry in entries:
        assert isinstance(entry, dict)
        relative = entry["archive"]
        assert isinstance(relative, str)
        archive_path = snapshot / PurePosixPath(relative)
        metadata = _private_mode(archive_path, directory=False)
        if metadata.st_size != entry["archive_size_bytes"]:
            raise BackupError(f"archive size mismatch for {relative}")
        actual_hash = sha256_file(archive_path)
        if actual_hash != entry["archive_sha256"] or checksums[relative] != actual_hash:
            raise BackupError(f"archive checksum mismatch for {relative}")
        member_count, uncompressed = inspect_archive(archive_path)
        if member_count != entry["member_count"]:
            raise BackupError(f"archive member count mismatch for {relative}")
        if uncompressed != entry["uncompressed_file_bytes"]:
            raise BackupError(f"archive uncompressed size mismatch for {relative}")

    return manifest


def _bounded_detail(path: tempfile._TemporaryFileWrapper | object, limit: int = 8192) -> str:
    # The object is a TemporaryFile opened in binary mode.
    handle = path
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(max(0, size - limit))
    return handle.read().decode("utf-8", errors="replace").strip()


class DockerClient:
    STDERR_LIMIT = 8192

    def run_text(self, command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                list(command),
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise BackupError(f"cannot run {command[0]}: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout)[-self.STDERR_LIMIT :].strip()
            raise BackupError(f"{' '.join(command[:3])} failed: {detail or 'no diagnostics'}")
        return result

    def ensure_ready(self) -> None:
        self.run_text(["docker", "version"])
        self.run_text(["docker", "compose", "version"])

    def project_containers(self, project: str) -> list[str]:
        result = self.run_text(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.ID}} {{.Names}}",
            ]
        )
        return [line for line in result.stdout.splitlines() if line]

    def inspect_volume(self, name: str) -> dict[str, object] | None:
        result = self.run_text(["docker", "volume", "inspect", name], check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            if "no such volume" in detail.lower():
                return None
            raise BackupError(f"docker volume inspect failed for {name}: {detail}")
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BackupError(f"invalid Docker volume inspect JSON for {name}") from exc
        if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
            raise BackupError(f"unexpected Docker volume inspect response for {name}")
        return document[0]

    def volume_users(self, name: str) -> list[str]:
        result = self.run_text(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"volume={name}",
                "--format",
                "{{.ID}} {{.Names}}",
            ]
        )
        return [line for line in result.stdout.splitlines() if line]

    def stream_archive(self, name: str, destination: Path) -> str:
        command = [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=volume,src={name},dst=/volume,readonly,volume-nocopy",
            HELPER_IMAGE,
            "tar",
            "-C",
            "/volume",
            "-czf",
            "-",
            ".",
        ]
        digest = hashlib.sha256()
        try:
            with tempfile.TemporaryFile() as stderr_handle, destination.open("xb") as output:
                os.chmod(destination, 0o600)
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=stderr_handle,
                )
                assert process.stdout is not None
                for chunk in iter(lambda: process.stdout.read(CHUNK_SIZE), b""):
                    output.write(chunk)
                    digest.update(chunk)
                process.stdout.close()
                return_code = process.wait()
                if return_code != 0:
                    detail = _bounded_detail(stderr_handle, self.STDERR_LIMIT)
                    raise BackupError(f"archive helper failed for {name}: {detail or 'no diagnostics'}")
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(f"cannot archive volume {name}: {exc}") from exc
        return digest.hexdigest()

    def volume_empty(self, name: str) -> bool:
        result = self.run_text(
            [
                "docker",
                "run",
                "--rm",
                "--mount",
                f"type=volume,src={name},dst=/volume,readonly,volume-nocopy",
                HELPER_IMAGE,
                "sh",
                "-euc",
                'test -z "$(find /volume -mindepth 1 -maxdepth 1 -print -quit)"',
            ],
            check=False,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        detail = (result.stderr or result.stdout).strip()
        raise BackupError(f"cannot inspect whether volume {name} is empty: {detail}")

    def create_volume(self, name: str, project: str, logical: str) -> None:
        result = self.run_text(
            [
                "docker",
                "volume",
                "create",
                "--driver",
                "local",
                "--label",
                f"com.docker.compose.project={project}",
                "--label",
                f"com.docker.compose.volume={logical}",
                name,
            ]
        )
        if result.stdout.strip() != name:
            raise BackupError(f"Docker created an unexpected volume name for {name}")

    def remove_volume(self, name: str) -> None:
        self.run_text(["docker", "volume", "rm", name])

    def stream_restore(self, archive: Path, name: str) -> None:
        command = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--mount",
            f"type=volume,src={name},dst=/volume,volume-nocopy",
            HELPER_IMAGE,
            "tar",
            "-C",
            "/volume",
            "-xzf",
            "-",
        ]
        try:
            with archive.open("rb") as source, tempfile.TemporaryFile() as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_handle,
                )
                assert process.stdin is not None
                try:
                    for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                        process.stdin.write(chunk)
                    process.stdin.close()
                except BrokenPipeError:
                    process.stdin.close()
                return_code = process.wait()
                if return_code != 0:
                    detail = _bounded_detail(stderr_handle, self.STDERR_LIMIT)
                    raise BackupError(f"restore helper failed for {name}: {detail or 'no diagnostics'}")
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(f"cannot restore volume {name}: {exc}") from exc


def _validate_volume_info(name: str, info: dict[str, object]) -> None:
    if info.get("Name") not in (None, name):
        raise BackupError(f"Docker inspect name mismatch for volume {name}")
    if info.get("Driver") != "local":
        raise BackupError(f"volume {name} must use the local driver")
    if info.get("Options") not in (None, {}):
        raise BackupError(f"volume {name} must not use driver options")


def _ensure_backup_root(path: Path) -> Path:
    absolute = _reject_symlink_components(path)
    if absolute.exists():
        _private_mode(absolute, directory=True)
        return absolute
    missing: list[Path] = []
    current = absolute
    while not current.exists():
        missing.append(current)
        current = current.parent
    _reject_symlink_components(current)
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
            directory.chmod(0o700)
        except OSError as exc:
            raise BackupError(f"cannot create backup root {directory}: {exc}") from exc
    return absolute


def _write_private(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as handle:
            os.chmod(path, 0o600)
            handle.write(data)
    except OSError as exc:
        raise BackupError(f"cannot write {path}: {exc}") from exc


def _repository_images() -> list[str]:
    compose_path = ROOT / "compose.yaml"
    init_path = ROOT / "scripts" / "init.sh"
    try:
        compose = compose_path.read_text(encoding="utf-8")
        init_script = init_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"cannot read repository image declarations: {exc}") from exc
    images = set(re.findall(r"(?m)^\s{4}image:\s*['\"]?([^'\"#\s]+)", compose))
    for key in ("HTPASSWD_IMAGE", "MOSQUITTO_IMAGE"):
        match = re.search(rf"(?m)^{key}=([^\s#]+)\s*$", init_script)
        if match is None:
            raise BackupError(f"missing {key} in scripts/init.sh")
        images.add(match.group(1))
    images.add(HELPER_IMAGE)
    return _validate_sorted_unique_strings(sorted(images), "container_images", nonempty=True, images=True)


def _git_metadata() -> tuple[str | None, bool | None]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None, None
    if head.returncode != 0:
        return None, None
    commit = head.stdout.strip()
    if GIT_SHA_RE.fullmatch(commit) is None:
        raise BackupError("git rev-parse returned an invalid commit SHA")
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if status_result.returncode != 0:
        raise BackupError("git status failed while recording snapshot metadata")
    return commit, bool(status_result.stdout.strip())


def _recovery_document(snapshot_id: str, source_project: str) -> str:
    recovery_project = f"{source_project}-recovery"
    return f"""# Recovery for `{snapshot_id}`

This is a cold Docker volume snapshot from Compose project `{source_project}`.

Verify without Docker:

```bash
make verify-backup BACKUP=backups/{snapshot_id}
```

Restore beside the original project:

```bash
HOMELAB_PROJECT_NAME={recovery_project} \\
  make restore BACKUP=backups/{snapshot_id}
```

Keep the original volumes until the recovered applications have passed their own checks.
The snapshot does not contain repository `.env` or `.secrets/`; preserve current credentials separately in encrypted storage.
SHA-256 checksums detect accidental corruption but do not encrypt or authenticate this snapshot.
"""


def _snapshot_timestamp() -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_checksums(snapshot: Path, paths: Sequence[str]) -> None:
    lines = [f"{sha256_file(snapshot / PurePosixPath(relative))}  {relative}\n" for relative in sorted(paths)]
    _write_private(snapshot / "SHA256SUMS", "".join(lines).encode("utf-8"))


def create_snapshot(project: str, backup_root: Path, docker: DockerAPI) -> Path:
    project = validate_project_name(project)
    root = _ensure_backup_root(backup_root)
    docker.ensure_ready()
    containers = docker.project_containers(project)
    if containers:
        raise BackupError(
            f"Compose project {project} still has containers; run make down first: {', '.join(containers)}"
        )

    existing: list[tuple[str, str, dict[str, object]]] = []
    missing: list[str] = []
    for logical in CURRENT_VOLUMES:
        name = actual_volume_name(project, logical)
        info = docker.inspect_volume(name)
        if info is None:
            missing.append(logical)
            continue
        _validate_volume_info(name, info)
        users = docker.volume_users(name)
        if users:
            raise BackupError(f"volume {name} is attached to containers: {', '.join(users)}")
        existing.append((logical, name, info))
    if not existing:
        raise BackupError(f"project {project} has no existing persistent volumes to back up")

    stamp, created_at = _snapshot_timestamp()
    snapshot_id = f"{project}-{stamp}-{secrets.token_hex(4)}"
    final_path = root / snapshot_id
    if final_path.exists():
        raise BackupError(f"snapshot destination already exists: {final_path}")
    staging = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.tmp-", dir=root))
    staging.chmod(0o700)
    volumes_dir = staging / "volumes"
    volumes_dir.mkdir(mode=0o700)
    volumes_dir.chmod(0o700)

    try:
        volume_entries: list[dict[str, object]] = []
        archive_relatives: list[str] = []
        for logical, name, info in sorted(existing):
            relative = f"volumes/{logical}.tar.gz"
            archive_path = staging / PurePosixPath(relative)
            digest = docker.stream_archive(name, archive_path)
            if not SHA256_RE.fullmatch(digest):
                raise BackupError(f"archive helper returned an invalid SHA-256 for {name}")
            member_count, uncompressed = inspect_archive(archive_path)
            metadata = archive_path.stat()
            volume_entries.append(
                {
                    "logical_name": logical,
                    "source_name": name,
                    "archive": relative,
                    "archive_size_bytes": metadata.st_size,
                    "archive_sha256": digest,
                    "member_count": member_count,
                    "uncompressed_file_bytes": uncompressed,
                    "driver": "local",
                }
            )
            archive_relatives.append(relative)

        git_commit, git_dirty = _git_metadata()
        manifest: dict[str, object] = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "source_project": project,
            "source_git_commit": git_commit,
            "source_git_dirty": git_dirty,
            "helper_image": HELPER_IMAGE,
            "container_images": _repository_images(),
            "declared_volumes": sorted(CURRENT_VOLUMES),
            "volumes": volume_entries,
            "missing_volumes": sorted(missing),
        }
        _write_private(staging / "RECOVERY.md", _recovery_document(snapshot_id, project).encode("utf-8"))
        _write_private(staging / "manifest.json", _canonical_json(manifest))
        _write_checksums(staging, ["manifest.json", "RECOVERY.md", *archive_relatives])
        verify_snapshot(staging)
        os.replace(staging, final_path)
        return final_path
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate_existing_target_labels(
    name: str, info: dict[str, object], project: str, logical: str
) -> None:
    raw_labels = info.get("Labels")
    if raw_labels is None:
        labels: dict[str, object] = {}
    elif isinstance(raw_labels, dict):
        labels = raw_labels
    else:
        raise BackupError(f"volume {name} has invalid Docker labels")
    project_key = "com.docker.compose.project"
    volume_key = "com.docker.compose.volume"
    has_ownership = project_key in labels or volume_key in labels
    if has_ownership and (
        labels.get(project_key) != project or labels.get(volume_key) != logical
    ):
        raise BackupError(f"volume {name} has conflicting Compose ownership labels")


def restore_snapshot(snapshot: Path, project: str, docker: DockerAPI) -> list[str]:
    manifest = verify_snapshot(snapshot)
    entries = manifest["volumes"]
    assert isinstance(entries, list)
    unsupported = sorted(
        entry["logical_name"]
        for entry in entries
        if isinstance(entry, dict) and entry["logical_name"] not in CURRENT_VOLUMES
    )
    if unsupported:
        raise BackupError(f"snapshot contains unsupported logical volumes: {', '.join(unsupported)}")

    project = validate_project_name(project)
    docker.ensure_ready()
    containers = docker.project_containers(project)
    if containers:
        raise BackupError(
            f"target Compose project {project} still has containers; run make down first: {', '.join(containers)}"
        )

    plan: list[tuple[str, str, Path, bool]] = []
    snapshot_path = _absolute_without_resolving(snapshot)
    for entry in entries:
        assert isinstance(entry, dict)
        logical = entry["logical_name"]
        archive_relative = entry["archive"]
        assert isinstance(logical, str) and isinstance(archive_relative, str)
        name = actual_volume_name(project, logical)
        info = docker.inspect_volume(name)
        existed = info is not None
        if info is not None:
            _validate_volume_info(name, info)
            _validate_existing_target_labels(name, info, project, logical)
            users = docker.volume_users(name)
            if users:
                raise BackupError(f"target volume {name} is attached to containers: {', '.join(users)}")
            if not docker.volume_empty(name):
                raise BackupError(f"target volume {name} is not empty")
        plan.append((logical, name, snapshot_path / PurePosixPath(archive_relative), existed))

    created: list[str] = []
    current_name: str | None = None
    current_preexisting = False
    try:
        for logical, name, _archive, existed in plan:
            if not existed:
                docker.create_volume(name, project, logical)
                created.append(name)
        for _logical, name, archive, existed in plan:
            current_name = name
            current_preexisting = existed
            docker.stream_restore(archive, name)
        return [name for _logical, name, _archive, _existed in plan]
    except Exception as exc:
        cleanup_errors: list[str] = []
        for name in reversed(created):
            try:
                docker.remove_volume(name)
            except Exception as cleanup_exc:  # pragma: no cover - real Docker diagnostic path
                cleanup_errors.append(f"{name}: {cleanup_exc}")
        detail = str(exc)
        if current_name is not None and current_preexisting:
            detail += f"; pre-existing volume {current_name} may be partially populated"
        if cleanup_errors:
            detail += f"; cleanup failures: {', '.join(cleanup_errors)}"
        if isinstance(exc, BackupError):
            raise BackupError(detail) from exc
        raise BackupError(detail) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cold Docker volume backup and restore")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="create and verify a cold snapshot")
    verify = commands.add_parser("verify", help="verify a snapshot without Docker")
    verify.add_argument("snapshot", type=Path)
    restore = commands.add_parser("restore", help="restore into absent or empty volumes")
    restore.add_argument("snapshot", type=Path)
    return parser


def _backup_root_from_environment() -> Path:
    configured = os.environ.get("BACKUP_ROOT", "backups")
    path = Path(configured)
    return path if path.is_absolute() else ROOT / path


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            manifest = verify_snapshot(args.snapshot)
            volumes = manifest["volumes"]
            assert isinstance(volumes, list)
            print(f"Backup verification passed: {args.snapshot} ({len(volumes)} archived volumes)")
            return 0

        project = resolve_project_name(os.environ, ROOT / ".env")
        docker = DockerClient()
        if args.command == "create":
            snapshot = create_snapshot(project, _backup_root_from_environment(), docker)
            print(f"Backup created and verified: {snapshot}")
            return 0
        if args.command == "restore":
            restored = restore_snapshot(args.snapshot, project, docker)
            print(f"Backup restored into project {project}: {len(restored)} volumes")
            return 0
        parser.error("unknown command")
    except (BackupError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Backup operation failed: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
