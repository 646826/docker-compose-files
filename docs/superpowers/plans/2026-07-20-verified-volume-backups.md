# Verified Volume Backups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cold, atomic, verifiable backup and safe restore commands for every current persistent Compose volume, plus a real CI round-trip restore test.

**Architecture:** `scripts/backup.py` is a Python 3.11 standard-library CLI with `create`, `verify`, and `restore` subcommands. It stores a self-contained snapshot manifest and strict checksums, validates tar members before extraction, and reaches Docker volumes only through a pinned Alpine helper container. A separate POSIX runtime harness creates disposable fixture volumes and proves backup, tamper rejection, side-by-side restore, metadata preservation, and scoped cleanup.

**Tech Stack:** Python 3.11 standard library, Docker Engine CLI, Docker Compose V2, POSIX shell, GNU/BusyBox tar inside `alpine:3.24.1`, GitHub Actions.

## Global Constraints

- Support Linux Docker Engine on `linux/amd64` and `linux/arm64`.
- Use only Python 3.11+ standard-library modules and existing shell/Docker tooling.
- Pin the helper image exactly as `alpine:3.24.1`.
- Never access `/var/lib/docker/volumes` directly.
- Never stop or remove production containers automatically.
- `create` and `restore` must reject every target-project container, including stopped containers.
- Reject any source or target volume attached to any container.
- Support only `local` volumes with empty driver options.
- Backup source mounts must be read-only and use `volume-nocopy`.
- Restore may write only to absent or completely empty target volumes.
- Restore may delete only volumes it created during the current failed attempt.
- Offline verification must not invoke Docker.
- Snapshot paths and fixed entries must not traverse symlinks.
- Snapshot directories use mode `0700`; snapshot files use mode `0600`.
- Snapshots never include repository `.env` or `.secrets/`.
- `backups/` is ignored by Git.
- The format identifier is `docker-compose-files-volume-backup`, version `1`.
- Current logical inventory is exactly: `influxdb_data`, `influxdb_config`, `grafana_data`, `portainer_data`, `netdata_config`, `netdata_lib`, `netdata_cache`, `mosquitto_data`, `openhab_addons`, `openhab_conf`, `openhab_userdata`.

---

## File map

- Create `scripts/backup.py`: complete create/verify/restore implementation and CLI.
- Create `scripts/test_backup.py`: unit and behavioral tests using `unittest`, temporary files, and fake Docker commands.
- Create `scripts/check_backup_policy.py`: focused static acceptance rules.
- Create `scripts/check_backup_runtime.sh`: real disposable Docker-volume round-trip test.
- Create `.github/workflows/backup-runtime.yml`: scheduled and PR runtime workflow.
- Create `docs/BACKUP.md`: operator guide and recovery procedure.
- Modify `Makefile`: expose `backup`, `verify-backup`, `restore`, and `check-backup-runtime`.
- Modify `.gitignore`: ignore `/backups/`.
- Modify `scripts/check.sh`: run backup policy and test suite.
- Modify `scripts/check_static.py`: require backup files and documentation.
- Modify `scripts/check_images.py` and `scripts/test_check_images.py`: include `alpine:3.24.1`.
- Modify `.github/workflows/images.yml`: rerun image-platform checks when backup helper code changes.
- Modify `README.md` and `docs/MIGRATION.md`: replace the one-volume example with the verified workflow.

---

### Task 1: Define the snapshot model and strict offline verifier

**Files:**
- Create: `scripts/backup.py`
- Create: `scripts/test_backup.py`

**Interfaces:**
- Produces `BackupError(Exception)`.
- Produces constants `FORMAT`, `FORMAT_VERSION`, `HELPER_IMAGE`, and `CURRENT_VOLUMES`.
- Produces `resolve_project_name(environ: Mapping[str, str], env_file: Path) -> str`.
- Produces `validate_project_name(value: str) -> str`.
- Produces `inspect_archive(path: Path) -> tuple[int, int]`.
- Produces `verify_snapshot(path: Path) -> dict[str, object]`.
- Later tasks consume the verified manifest returned by `verify_snapshot`.

- [ ] **Step 1: Write failing tests for identity, project names, inventory, checksums, and tar safety**

Create `scripts/test_backup.py` with these initial tests and helpers:

```python
#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("backup_module", ROOT / "scripts/backup.py")
assert SPEC and SPEC.loader
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def write_tar(path: Path, members: list[tarfile.TarInfo]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for member in members:
            payload = None
            if member.isreg():
                payload = io.BytesIO(b"x" * member.size)
            archive.addfile(member, payload)


class BackupVerifierTests(unittest.TestCase):
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
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("HOMELAB_PROJECT_NAME=from-file\n", encoding="utf-8")
            self.assertEqual(
                backup.resolve_project_name({"HOMELAB_PROJECT_NAME": "from-env"}, env_file),
                "from-env",
            )
            self.assertEqual(backup.resolve_project_name({}, env_file), "from-file")
            env_file.unlink()
            self.assertEqual(backup.resolve_project_name({}, env_file), "homelab")
            for invalid in ("", "Upper", "-bad", "bad space", "bad/"):
                with self.assertRaises(backup.BackupError):
                    backup.validate_project_name(invalid)

    def test_tar_rejects_absolute_parent_duplicate_and_special_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases: list[list[tarfile.TarInfo]] = []
            absolute = tarfile.TarInfo("/etc/passwd")
            absolute.size = 1
            cases.append([absolute])
            parent = tarfile.TarInfo("../escape")
            parent.size = 1
            cases.append([parent])
            first = tarfile.TarInfo("./same")
            first.size = 1
            second = tarfile.TarInfo("same")
            second.size = 1
            cases.append([first, second])
            fifo = tarfile.TarInfo("pipe")
            fifo.type = tarfile.FIFOTYPE
            cases.append([fifo])
            for index, members in enumerate(cases):
                archive = root / f"bad-{index}.tar.gz"
                write_tar(archive, members)
                with self.assertRaises(backup.BackupError):
                    backup.inspect_archive(archive)

    def test_tar_accepts_safe_relative_symlink_and_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            directory_member = tarfile.TarInfo("dir")
            directory_member.type = tarfile.DIRTYPE
            target = tarfile.TarInfo("dir/file")
            target.size = 1
            safe = tarfile.TarInfo("dir/link")
            safe.type = tarfile.SYMTYPE
            safe.linkname = "file"
            archive = root / "safe.tar.gz"
            write_tar(archive, [directory_member, target, safe])
            self.assertEqual(backup.inspect_archive(archive), (3, 1))

            escape = tarfile.TarInfo("dir/link")
            escape.type = tarfile.SYMTYPE
            escape.linkname = "../../outside"
            bad = root / "escape.tar.gz"
            write_tar(bad, [escape])
            with self.assertRaises(backup.BackupError):
                backup.inspect_archive(bad)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
python3 scripts/test_backup.py
```

Expected: import fails because `scripts/backup.py` does not exist.

- [ ] **Step 3: Implement the foundational module and tar validator**

Create `scripts/backup.py` with this public foundation:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "docker-compose-files-volume-backup"
FORMAT_VERSION = 1
HELPER_IMAGE = "alpine:3.24.1"
CURRENT_VOLUMES = (
    "influxdb_data", "influxdb_config", "grafana_data", "portainer_data",
    "netdata_config", "netdata_lib", "netdata_cache", "mosquitto_data",
    "openhab_addons", "openhab_conf", "openhab_userdata",
)
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_RE = re.compile(
    r"^(?P<project>[a-z0-9][a-z0-9_-]*)-"
    r"(?P<stamp>[0-9]{8}T[0-9]{6}Z)-(?P<random>[0-9a-f]{8})$"
)


class BackupError(RuntimeError):
    pass


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
    for raw in path.read_text(encoding="utf-8").splitlines():
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
    except (OSError, tarfile.TarError) as exc:
        raise BackupError(f"cannot inspect archive {path}: {exc}") from exc
    return member_count, uncompressed_file_bytes
```

Add strict checksum parsing, symlink-free snapshot entry checks, exact manifest schema validation, and `verify_snapshot()` in the same file. `verify_snapshot()` must return the parsed manifest after checking:

```python
EXPECTED_TOP_LEVEL = {"manifest.json", "SHA256SUMS", "RECOVERY.md", "volumes"}
MANIFEST_KEYS = {
    "format", "format_version", "snapshot_id", "created_at",
    "source_project", "source_git_commit", "source_git_dirty",
    "helper_image", "container_images", "declared_volumes",
    "volumes", "missing_volumes",
}
VOLUME_KEYS = {
    "logical_name", "source_name", "archive", "archive_size_bytes",
    "archive_sha256", "member_count", "uncompressed_file_bytes", "driver",
}
```

Use `Path.lstat()` for every fixed entry; reject symlinks and group/other permission bits. Parse checksum lines with:

```python
match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_./-]+)", line)
```

Require sorted unique checksum paths exactly equal to `manifest.json`, `RECOVERY.md`, and all manifest archives. Recompute size, SHA-256, member count, and uncompressed bytes.

- [ ] **Step 4: Expand tests for full offline verification**

Add helpers that build a valid snapshot and tests for:

```python
def test_verify_rejects_checksum_mismatch(self) -> None: ...
def test_verify_rejects_unknown_manifest_keys(self) -> None: ...
def test_verify_rejects_unexpected_archive(self) -> None: ...
def test_verify_rejects_symlinked_fixed_entry(self) -> None: ...
def test_verify_uses_snapshot_declared_inventory(self) -> None: ...
```

The valid fixture must create `manifest.json`, `RECOVERY.md`, one safe tar archive, and `SHA256SUMS`, all with modes `0600` inside a `0700` snapshot directory.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
python3 scripts/test_backup.py
python3 -m py_compile scripts/backup.py scripts/test_backup.py
```

Expected: all offline verifier tests pass.

Commit:

```bash
git add scripts/backup.py scripts/test_backup.py
git commit -m "feat: add strict offline backup verification"
```

---

### Task 2: Implement Docker preflight and atomic cold-backup creation

**Files:**
- Modify: `scripts/backup.py`
- Modify: `scripts/test_backup.py`

**Interfaces:**
- Produces `DockerClient` with `run_text`, `project_containers`, `inspect_volume`, `volume_users`, and `stream_archive`.
- Produces `create_snapshot(project: str, backup_root: Path, docker: DockerClient) -> Path`.
- Consumes `inspect_archive()` and `verify_snapshot()` from Task 1.

- [ ] **Step 1: Add failing tests for backup-root safety and preflight**

Add tests that use a fake `DockerClient` object:

```python
class FakeDocker:
    def __init__(self) -> None:
        self.volumes: dict[str, dict[str, object]] = {}
        self.archives: dict[str, bytes] = {}
        self.calls: list[tuple[object, ...]] = []

    def ensure_ready(self) -> None:
        self.calls.append(("ensure_ready",))

    def project_containers(self, project: str) -> list[str]:
        return []

    def inspect_volume(self, name: str) -> dict[str, object] | None:
        return self.volumes.get(name)

    def volume_users(self, name: str) -> list[str]:
        return []

    def stream_archive(self, name: str, destination: Path) -> str:
        self.calls.append(("stream_archive", name))
        destination.write_bytes(self.archives[name])
        return hashlib.sha256(self.archives[name]).hexdigest()
```

Tests must prove:

```python
def test_create_refuses_unsafe_existing_backup_root(self) -> None: ...
def test_create_refuses_all_missing_inventory(self) -> None: ...
def test_create_refuses_project_containers(self) -> None: ...
def test_create_refuses_attached_or_non_local_volume(self) -> None: ...
def test_create_publishes_atomically_and_records_missing_volumes(self) -> None: ...
```

The successful test must assert that the final directory exists, no hidden temporary sibling remains, every file mode is private, source `.env`/`.secrets/` sentinels are untouched, and the manifest contains the complete `declared_volumes`.

- [ ] **Step 2: Run tests and confirm the new cases fail**

Run:

```bash
python3 scripts/test_backup.py
```

Expected: failures name missing `DockerClient` or `create_snapshot`.

- [ ] **Step 3: Implement Docker command boundaries and archive streaming**

Add:

```python
class DockerClient:
    STDERR_LIMIT = 8192

    def run_text(self, command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, check=False,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout)[-self.STDERR_LIMIT:].strip()
            raise BackupError(f"{' '.join(command[:3])} failed: {detail}")
        return result

    def ensure_ready(self) -> None:
        self.run_text(["docker", "version"])
        self.run_text(["docker", "compose", "version"])

    def project_containers(self, project: str) -> list[str]:
        result = self.run_text([
            "docker", "ps", "-a",
            "--filter", f"label=com.docker.compose.project={project}",
            "--format", "{{.ID}} {{.Names}}",
        ])
        return [line for line in result.stdout.splitlines() if line]

    def inspect_volume(self, name: str) -> dict[str, object] | None:
        result = self.run_text(["docker", "volume", "inspect", name], check=False)
        if result.returncode != 0:
            if "no such volume" in result.stderr.lower():
                return None
            raise BackupError(f"docker volume inspect failed for {name}: {result.stderr.strip()}")
        document = json.loads(result.stdout)
        if not isinstance(document, list) or len(document) != 1:
            raise BackupError(f"unexpected inspect response for {name}")
        return document[0]

    def volume_users(self, name: str) -> list[str]:
        result = self.run_text([
            "docker", "ps", "-a", "--filter", f"volume={name}",
            "--format", "{{.ID}} {{.Names}}",
        ])
        return [line for line in result.stdout.splitlines() if line]
```

Implement `stream_archive()` with `subprocess.Popen`, a temporary stderr file, and chunked stdout reads. The Docker invocation must be exactly equivalent to:

```python
[
    "docker", "run", "--rm",
    "--mount", f"type=volume,src={name},dst=/volume,readonly,volume-nocopy",
    HELPER_IMAGE, "tar", "-C", "/volume", "-czf", "-", ".",
]
```

Compute SHA-256 while writing chunks to a mode-`0600` destination.

- [ ] **Step 4: Implement backup metadata and atomic publication**

Add:

```python
def actual_volume_name(project: str, logical: str) -> str:
    return f"{project}_{logical}"
```

Validate each existing source inspect object:

```python
if info.get("Driver") != "local" or info.get("Options") not in (None, {}):
    raise BackupError(...)
if docker.volume_users(actual_name):
    raise BackupError(...)
```

Create `BACKUP_ROOT` only when absent, with mode `0700`; reject symlinks, non-directories, or mode bits `0o077` on an existing root. Build a timestamped ID and hidden temporary sibling, write archives in sorted order, generate `RECOVERY.md`, canonical manifest, and checksums, call `verify_snapshot(temp_path)`, then publish with `os.replace(temp_path, final_path)`. Remove only the hidden temporary directory on failure.

Extract repository image references from `compose.yaml`, helper assignments from `scripts/init.sh`, and `HELPER_IMAGE`; store a sorted unique list. Capture Git SHA and dirty state through bounded Git commands, using `null` only when the directory is not a Git checkout.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 scripts/test_backup.py
python3 -m py_compile scripts/backup.py scripts/test_backup.py
```

Expected: all creation tests pass.

Commit:

```bash
git add scripts/backup.py scripts/test_backup.py
git commit -m "feat: create atomic cold volume snapshots"
```

---

### Task 3: Implement safe side-by-side restore

**Files:**
- Modify: `scripts/backup.py`
- Modify: `scripts/test_backup.py`

**Interfaces:**
- Extends `DockerClient` with `volume_empty`, `create_volume`, `remove_volume`, and `stream_restore`.
- Produces `restore_snapshot(snapshot: Path, project: str, docker: DockerClient) -> list[str]`.
- Consumes `verify_snapshot()` before every Docker write.

- [ ] **Step 1: Add failing restore tests**

Extend `FakeDocker` with operation logs and add:

```python
def test_restore_verifies_before_any_docker_write(self) -> None: ...
def test_restore_refuses_unknown_current_logical_volume(self) -> None: ...
def test_restore_refuses_non_empty_target(self) -> None: ...
def test_restore_refuses_conflicting_compose_labels(self) -> None: ...
def test_restore_creates_expected_labels_and_restores_sorted(self) -> None: ...
def test_failed_restore_removes_only_newly_created_volumes(self) -> None: ...
```

The failure cleanup test must include one pre-existing empty target and one newly created target. Assert that only the newly created target is removed.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
python3 scripts/test_backup.py
```

Expected: failures name missing restore APIs.

- [ ] **Step 3: Implement Docker restore primitives**

Add:

```python
def volume_empty(self, name: str) -> bool:
    result = self.run_text([
        "docker", "run", "--rm",
        "--mount", f"type=volume,src={name},dst=/volume,readonly,volume-nocopy",
        HELPER_IMAGE, "sh", "-euc",
        'test -z "$(find /volume -mindepth 1 -maxdepth 1 -print -quit)"',
    ], check=False)
    return result.returncode == 0
```

Create volumes with:

```python
[
    "docker", "volume", "create", "--driver", "local",
    "--label", f"com.docker.compose.project={project}",
    "--label", f"com.docker.compose.volume={logical}",
    actual_name,
]
```

Restore by streaming the verified archive into:

```python
[
    "docker", "run", "--rm", "-i",
    "--mount", f"type=volume,src={actual_name},dst=/volume,volume-nocopy",
    HELPER_IMAGE, "tar", "-C", "/volume", "-xzf", "-",
]
```

Capture bounded stderr without loading the archive into memory.

- [ ] **Step 4: Implement complete restore preflight before writes**

`restore_snapshot()` must:

1. call `verify_snapshot(snapshot)`;
2. reject archived logical names absent from `CURRENT_VOLUMES`;
3. validate target project name;
4. call `docker.ensure_ready()`;
5. reject any `docker.project_containers(project)`;
6. inspect every target volume before creating any;
7. reject any target attachment;
8. reject non-local drivers or options;
9. accept existing labels only when absent or exactly matching expected project/logical labels;
10. reject every non-empty target.

Only after all checks pass may it create missing volumes. Track created names. Restore archives in sorted logical-name order. On failure, remove created volumes in reverse order; never remove a pre-existing target. Report the potentially partially populated pre-existing volume in the raised error.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 scripts/test_backup.py
python3 -m py_compile scripts/backup.py scripts/test_backup.py
```

Expected: all restore tests pass.

Commit:

```bash
git add scripts/backup.py scripts/test_backup.py
git commit -m "feat: restore snapshots into empty project volumes"
```

---

### Task 4: Add the CLI, Make targets, policy checks, and helper-image coverage

**Files:**
- Modify: `scripts/backup.py`
- Create: `scripts/check_backup_policy.py`
- Modify: `scripts/check.sh`
- Modify: `scripts/check_static.py`
- Modify: `scripts/check_images.py`
- Modify: `scripts/test_check_images.py`
- Modify: `.github/workflows/images.yml`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- CLI forms: `python3 scripts/backup.py create`, `verify PATH`, `restore PATH`.
- Make variables: `BACKUP_ROOT`, `BACKUP`.
- `make verify-backup` and `make restore` must fail clearly when `BACKUP` is empty.
- `configured_images()` includes `alpine:3.24.1`.

- [ ] **Step 1: Add CLI tests**

Add subprocess tests that run:

```python
result = subprocess.run(
    [sys.executable, str(ROOT / "scripts/backup.py"), "verify", str(snapshot)],
    cwd=ROOT, text=True, capture_output=True, check=False,
)
self.assertEqual(result.returncode, 0, result.stderr)
self.assertIn("Backup verification passed", result.stdout)
```

Also assert invalid usage exits non-zero without traceback.

- [ ] **Step 2: Implement `argparse` CLI**

Use:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cold Docker volume backup and restore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create")
    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("snapshot", type=Path)
    return parser
```

`main()` resolves `.env`, `BACKUP_ROOT`, and project name, prints only concise non-secret results, catches `BackupError`, `OSError`, `ValueError`, and `json.JSONDecodeError`, and exits `1` without traceback.

- [ ] **Step 3: Add Make and ignore rules**

Add to `.PHONY` and `Makefile`:

```make
BACKUP_ROOT ?= backups

backup: ## Create a verified cold snapshot of all existing project volumes
	@BACKUP_ROOT="$(BACKUP_ROOT)" python3 scripts/backup.py create

verify-backup: ## Verify BACKUP offline without touching Docker
	@test -n "$(BACKUP)" || { echo "BACKUP is required" >&2; exit 2; }
	@python3 scripts/backup.py verify "$(BACKUP)"

restore: ## Restore BACKUP into absent or empty volumes for the current project
	@test -n "$(BACKUP)" || { echo "BACKUP is required" >&2; exit 2; }
	@python3 scripts/backup.py restore "$(BACKUP)"

check-backup-runtime: ## Exercise a disposable backup/verify/restore round trip
	@sh ./scripts/check_backup_runtime.sh
```

Add `/backups/` to `.gitignore`.

- [ ] **Step 4: Extend image verification**

In `scripts/check_images.py`, add:

```python
BACKUP_HELPER_IMAGE = "alpine:3.24.1"
```

and include it in `configured_images()`. Extend `scripts/test_check_images.py` to assert the helper appears exactly once. Add backup-related paths to `.github/workflows/images.yml`.

- [ ] **Step 5: Add focused policy checks**

Create `scripts/check_backup_policy.py` to import `scripts/backup.py` and enforce:

```python
required_make_targets = ("backup", "verify-backup", "restore", "check-backup-runtime")
forbidden_fragments = (
    "docker volume prune",
    "docker system prune",
    "/var/lib/docker/volumes",
    "docker compose stop",
    "docker compose down",
)
```

Also require the exact inventory, helper image, `readonly,volume-nocopy`, writable restore `volume-nocopy`, offline verify function separation, Compose labels, `/backups/`, `docs/BACKUP.md`, runtime workflow, and no `.env`/`.secrets/` archive inclusion.

Wire into `scripts/check.sh` before tests:

```sh
python3 scripts/check_backup_policy.py
python3 scripts/test_backup.py
```

Extend `scripts/check_static.py` required files and Make target list.

- [ ] **Step 6: Run fast checks and commit**

Run:

```bash
python3 scripts/test_backup.py
python3 scripts/test_check_images.py
python3 scripts/check_backup_policy.py
sh -n scripts/check.sh
python3 -m py_compile scripts/backup.py scripts/test_backup.py scripts/check_backup_policy.py
```

Expected: all pass.

Commit:

```bash
git add Makefile .gitignore scripts .github/workflows/images.yml
git commit -m "feat: expose verified backup commands"
```

---

### Task 5: Add the real backup/restore runtime harness and workflow

**Files:**
- Create: `scripts/check_backup_runtime.sh`
- Create: `.github/workflows/backup-runtime.yml`
- Modify: `scripts/check_backup_policy.py`

**Interfaces:**
- `scripts/check_backup_runtime.sh` accepts no arguments.
- It creates only uniquely prefixed fixture volumes and a private temporary backup root.
- It must exit `0` only after byte, mode, symlink, missing-volume, tamper, and non-empty-target assertions pass.

- [ ] **Step 1: Create the POSIX runtime harness**

The script must:

```sh
#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
PROJECT="backup-runtime-$$-$(openssl rand -hex 4)"
RESTORE_PROJECT="${PROJECT}-restore"
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-backup-runtime.XXXXXX")
BACKUP_ROOT="$WORKDIR/backups"
SOURCE_VOLUMES="${PROJECT}_grafana_data ${PROJECT}_mosquitto_data ${PROJECT}_openhab_conf"
RESTORE_VOLUMES="${RESTORE_PROJECT}_grafana_data ${RESTORE_PROJECT}_mosquitto_data ${RESTORE_PROJECT}_openhab_conf"

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  for name in $SOURCE_VOLUMES $RESTORE_VOLUMES "${RESTORE_PROJECT}_portainer_data"; do
    docker volume rm -f "$name" >/dev/null 2>&1 || true
  done
  rm -rf "$WORKDIR"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
```

Create source volumes with Compose labels. Populate fixtures through `alpine:3.24.1` with nested files, deterministic binary bytes, modes `0640`/`0750`, an empty file, and a relative symlink.

Run:

```sh
HOMELAB_PROJECT_NAME="$PROJECT" BACKUP_ROOT="$BACKUP_ROOT" \
  python3 "$ROOT/scripts/backup.py" create
SNAPSHOT=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -print -quit)
python3 "$ROOT/scripts/backup.py" verify "$SNAPSHOT"
```

Remove source volumes, restore under `$RESTORE_PROJECT`, and assert contents and metadata with helper containers. Assert a logical volume recorded missing was not created.

Copy the snapshot, alter one archive byte, and require offline verify failure. Create a non-empty target volume and require restore refusal before any other new target appears.

- [ ] **Step 2: Add the workflow**

Create `.github/workflows/backup-runtime.yml`:

```yaml
name: Backup runtime

on:
  push:
    branches: [main]
    paths:
      - "scripts/backup.py"
      - "scripts/check_backup_runtime.sh"
      - "scripts/check_backup_policy.py"
      - "scripts/test_backup.py"
      - "Makefile"
      - ".github/workflows/backup-runtime.yml"
  pull_request:
    paths:
      - "scripts/backup.py"
      - "scripts/check_backup_runtime.sh"
      - "scripts/check_backup_policy.py"
      - "scripts/test_backup.py"
      - "Makefile"
      - ".github/workflows/backup-runtime.yml"
  schedule:
    - cron: "11 6 * * 0"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: backup-runtime-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  roundtrip:
    name: Verify volume backup and restore
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v6
      - name: Verify Docker and Compose
        run: |
          docker version
          docker compose version
      - name: Run backup round trip
        shell: bash
        run: |
          set -o pipefail
          make check-backup-runtime 2>&1 | tee backup-runtime.log
      - name: Upload failure diagnostics
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: backup-runtime-log
          path: backup-runtime.log
          if-no-files-found: error
          retention-days: 3
```

Do not upload the generated snapshot.

- [ ] **Step 3: Extend policy and run**

Require the workflow fragments, 15-minute limit, three-day failure artifact, and absence of snapshot artifact paths.

Run:

```bash
sh -n scripts/check_backup_runtime.sh
python3 scripts/check_backup_policy.py
make check-backup-runtime
```

Expected: real round trip passes and cleans every fixture resource.

- [ ] **Step 4: Commit**

```bash
git add scripts/check_backup_runtime.sh scripts/check_backup_policy.py .github/workflows/backup-runtime.yml
git commit -m "test: prove volume backup restore round trip"
```

---

### Task 6: Document operations, confidentiality, and migration

**Files:**
- Create: `docs/BACKUP.md`
- Modify: `README.md`
- Modify: `docs/MIGRATION.md`
- Modify: `scripts/check_backup_policy.py`
- Modify: `scripts/check_static.py`

**Interfaces:**
- Documentation must use the exact implemented commands and variables.
- `docs/BACKUP.md` is the authoritative operator procedure.

- [ ] **Step 1: Write `docs/BACKUP.md`**

Cover these exact sections:

```markdown
# Verified volume backups

## Safety model
## Create a cold snapshot
## Verify a snapshot offline
## Restore side by side
## Validate applications after restore
## Snapshot layout and manifest
## Confidentiality and separate secrets
## Supported Docker volume boundary
## Failure and rollback behavior
## Deliberate non-goals
```

Document:

```bash
make down
make backup
make verify-backup BACKUP=backups/<snapshot-id>
HOMELAB_PROJECT_NAME=homelab-recovery \
  make restore BACKUP=backups/<snapshot-id>
```

State that stopped project containers must also be removed by `make down`; checksums detect corruption but do not authenticate or encrypt; `.env` and `.secrets/` require separate encrypted preservation; and application-level validation must occur before deleting original volumes.

- [ ] **Step 2: Update README and migration docs**

Replace the manual Grafana tar example with a short summary and link to `docs/BACKUP.md`. Add command-table rows for all four backup targets. Update `docs/MIGRATION.md` step 1 to use the backup guide for current named volumes while preserving the legacy bind-mount archive procedure.

- [ ] **Step 3: Enforce documentation contracts**

Require in policy/static checks:

```text
make backup
make verify-backup
make restore
HOMELAB_PROJECT_NAME=homelab-recovery
checksums
not encryption
.env
.secrets/
```

- [ ] **Step 4: Run fast checks and commit**

Run:

```bash
./scripts/check.sh
```

Expected: static policy, unit tests, shell syntax, and Compose rendering all pass.

Commit:

```bash
git add docs/BACKUP.md docs/MIGRATION.md README.md scripts/check_backup_policy.py scripts/check_static.py
git commit -m "docs: add verified backup recovery guide"
```

---

### Task 7: Final verification, review, and merge preparation

**Files:**
- Review all changed files.

**Interfaces:**
- Final branch must pass every existing and new workflow.
- No temporary workflows, snapshots, fixture volumes, credentials, or diagnostic artifacts are committed.

- [ ] **Step 1: Run the complete local suite**

Run:

```bash
./scripts/check.sh
make check-images
make check-backup-runtime
```

Expected: all commands exit `0`.

- [ ] **Step 2: Inspect the final diff**

Run:

```bash
git diff --check main...HEAD
git status --short
git diff --stat main...HEAD
```

Expected: no whitespace errors and a clean working tree.

- [ ] **Step 3: Request code review**

Review specifically for:

- tar traversal and link-resolution mistakes;
- symlink races in snapshot structure;
- Docker preflight ordering;
- accidental deletion of pre-existing volumes;
- secret leakage through commands or diagnostics;
- old-snapshot compatibility;
- atomic publication behavior.

Fix every critical or important finding and rerun all checks.

- [ ] **Step 4: Open or update the pull request**

The PR body must report:

- commands and snapshot format;
- cold-backup requirement;
- offline verifier guarantees;
- safe side-by-side restore behavior;
- real round-trip evidence;
- confidentiality limits;
- exact final workflow run numbers and conclusions.

- [ ] **Step 5: Merge only the verified head**

After CI, Image platforms, Runtime smoke, IoT runtime smoke, and Backup runtime all pass on the same head, mark the PR ready and squash-merge using the exact verified head SHA.
