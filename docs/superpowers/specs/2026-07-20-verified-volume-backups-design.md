# Verified Volume Backup and Restore Design

## Goal

Add a small, dependency-free backup subsystem that can create, verify, and safely restore cold snapshots of every persistent named volume declared by the homelab Compose project.

The defining requirement is not merely that archives can be created. The repository must regularly prove that a snapshot can be verified, restored into fresh project-scoped volumes, and read back with data and relevant filesystem metadata intact.

## Current gap

The repository currently:

- stores persistent state in eleven explicitly named Docker volumes;
- preserves those volumes during `make down`;
- documents a manual one-volume Grafana archive example;
- recommends backups before database and Portainer upgrades;
- does not provide a single command that covers the complete volume inventory;
- does not generate a machine-readable manifest or checksums;
- does not validate tar member safety before extraction;
- does not exercise restore in CI.

A backup instruction that is never restored is not sufficient evidence of recoverability.

## Scope

The backup inventory is the exact set of persistent volumes declared by `compose.yaml`:

1. `influxdb_data`;
2. `influxdb_config`;
3. `grafana_data`;
4. `portainer_data`;
5. `netdata_config`;
6. `netdata_lib`;
7. `netdata_cache`;
8. `mosquitto_data`;
9. `openhab_addons`;
10. `openhab_conf`;
11. `openhab_userdata`.

The actual Docker volume name is derived from the target project name exactly as the current Compose model does:

```text
<HOMELAB_PROJECT_NAME>_<logical-volume-name>
```

For the default project, `grafana_data` therefore resolves to `homelab_grafana_data`.

Volumes that do not exist are recorded as missing rather than created during backup. This supports installations that have never enabled Netdata or IoT profiles. Snapshot creation fails when none of the declared volumes exist because an all-missing snapshot has no recovery value.

## User interface

The Makefile exposes four operations:

```bash
make backup
make verify-backup BACKUP=backups/<snapshot-id>
make restore BACKUP=backups/<snapshot-id>
make check-backup-runtime
```

Optional configuration:

```bash
BACKUP_ROOT=/trusted/path make backup
HOMELAB_PROJECT_NAME=homelab-recovery make restore BACKUP=/trusted/path/<snapshot-id>
```

Defaults:

```text
BACKUP_ROOT=backups
HOMELAB_PROJECT_NAME=<environment value, then .env value, then homelab>
```

The `backups/` directory is ignored by Git.

The Make targets are thin wrappers around one operational CLI:

```text
scripts/backup.py create
scripts/backup.py verify <snapshot-path>
scripts/backup.py restore <snapshot-path>
```

The implementation uses only Python 3.11+ standard-library modules and the Docker CLI. No `jq`, PyYAML, `jsonschema`, rsync, restic, or application SDK is added.

## Architecture

### Host-side Python controller

`scripts/backup.py` owns:

- project-name and path validation;
- the authoritative logical volume inventory;
- Docker preflight checks;
- snapshot directory creation and atomic publication;
- streaming archive creation and extraction;
- manifest and checksum generation;
- strict offline snapshot verification;
- safe restore planning and cleanup;
- concise, secret-free diagnostics.

The script does not access `/var/lib/docker/volumes` directly. Docker documents direct host interaction with volume storage as unsupported; all data access occurs through a short-lived helper container with an explicit volume mount.

### Pinned helper image

The helper image is pinned in `scripts/backup.py`:

```text
alpine:3.24.1
```

Alpine 3.24.1 is the current supported 3.24 maintenance release as of this design. The existing image-platform checker is extended so this helper image must publish both `linux/amd64` and `linux/arm64` manifests.

The helper performs only:

- `tar` streaming;
- an emptiness probe with `find`;
- fixture setup and assertion commands in the real runtime test.

It is never installed as a permanent service.

### Streaming instead of host bind mounts

Backup streams compressed tar data from the helper container directly into a host file:

```text
docker run --rm \
  --mount type=volume,src=<source>,dst=/volume,readonly,volume-nocopy \
  alpine:3.24.1 \
  tar -C /volume -czf - .
```

The Python process writes stdout incrementally to `volumes/<logical>.tar.gz` and computes SHA-256 without buffering the archive in memory.

Restore performs the inverse operation and streams the already verified archive through stdin:

```text
docker run --rm -i \
  --mount type=volume,src=<target>,dst=/volume,volume-nocopy \
  alpine:3.24.1 \
  tar -C /volume -xzf -
```

This avoids backup-path quoting problems, avoids direct host access to Docker storage, and keeps memory usage bounded by the stream buffer.

`volume-nocopy` prevents helper-image files from being copied into an empty target volume.

## Cold-backup safety contract

### Project must be down

`create` and `restore` refuse to continue when any container, including a stopped container, has the target Compose project label:

```text
com.docker.compose.project=<project-name>
```

The check uses all containers, not only running ones.

The operator-facing remediation is explicit:

```bash
make down
```

The scripts never stop or remove production containers automatically.

### No volume may be attached elsewhere

For every source or target volume, the controller also checks whether any Docker container from any project references that volume. A volume attached to an unrelated container is rejected even when the homelab project itself is down.

This prevents a misleading cold backup when another container is still mutating the same data.

### Supported volume type

The maintained Compose model creates local volumes with no driver options. Snapshot creation and restoration require:

```text
driver == local
options are empty
```

A custom driver or driver option fails with a clear message instead of being silently recreated as different storage. Deployment-specific NFS, CIFS, block-storage, and plugin-backed volumes remain outside this subsystem.

## Snapshot layout

A successful snapshot is published as:

```text
backups/
└── homelab-20260720T120000Z-a1b2c3d4/
    ├── manifest.json
    ├── SHA256SUMS
    ├── RECOVERY.md
    └── volumes/
        ├── grafana_data.tar.gz
        ├── influxdb_config.tar.gz
        └── ...
```

The snapshot identifier contains:

- validated source project name;
- UTC timestamp with second precision;
- eight random hexadecimal characters.

The backup root and snapshot directory use mode `0700`. Snapshot files use mode `0600` because application volumes may contain private dashboards, tokens stored inside databases, personal automation configuration, or other sensitive state even though `.secrets/` is excluded.

## Atomic publication

Creation uses a private sibling directory under `BACKUP_ROOT`:

```text
.<snapshot-id>.tmp-<random>
```

The sequence is:

1. create the private temporary directory;
2. archive every existing volume;
3. write `RECOVERY.md`;
4. write the canonical manifest;
5. write `SHA256SUMS`;
6. run the same complete verifier used by `verify`;
7. atomically rename the temporary directory to the final snapshot identifier.

On any error, only the temporary directory is removed. A partially created snapshot is never published under its final name.

Atomic rename guarantees publication as one directory entry on the same filesystem. It is not described as a substitute for storage-level power-loss protection.

## Manifest format

`manifest.json` is UTF-8 JSON with sorted keys, two-space indentation, and a trailing newline.

Top-level structure:

```json
{
  "format": "docker-compose-files-volume-backup",
  "format_version": 1,
  "snapshot_id": "homelab-20260720T120000Z-a1b2c3d4",
  "created_at": "2026-07-20T12:00:00Z",
  "source_project": "homelab",
  "source_git_commit": "defa081b5c5dd1699e5d8d2c9623438fad67e113",
  "helper_image": "alpine:3.24.1",
  "container_images": [
    "grafana/grafana:13.1.0"
  ],
  "volumes": [],
  "missing_volumes": []
}
```

Each archived-volume object contains exactly:

```json
{
  "logical_name": "grafana_data",
  "source_name": "homelab_grafana_data",
  "archive": "volumes/grafana_data.tar.gz",
  "archive_size_bytes": 12345,
  "archive_sha256": "<64 lowercase hex characters>",
  "member_count": 42,
  "uncompressed_file_bytes": 67890,
  "driver": "local"
}
```

Rules:

- unknown top-level and volume-entry keys are rejected for format version 1;
- logical names must be unique and belong to the committed inventory;
- archived and missing logical names must be disjoint;
- together, archived and missing names must equal the complete inventory;
- paths must use forward slashes and remain beneath the snapshot root;
- archive size must match the file on disk;
- archive hash must match both the manifest and `SHA256SUMS`;
- `container_images` is the sorted unique set of pinned service and helper image references present in the repository at snapshot creation;
- Git commit is `null` only when the source directory is not a Git checkout.

`SHA256SUMS` contains checksums for `manifest.json`, `RECOVERY.md`, and every archive, using paths relative to the snapshot root. It detects accidental corruption; it does not authenticate a snapshot against a malicious party.

## Offline verification

`verify` requires Python only. It neither contacts Docker nor creates any Docker resource.

Verification proceeds in this order:

1. validate the snapshot path and required fixed files;
2. reject unexpected top-level files and unexpected files under `volumes/`;
3. parse `SHA256SUMS` with strict lowercase SHA-256 syntax and unique paths;
4. verify every listed file checksum;
5. parse `manifest.json` and enforce the version-1 schema in code;
6. cross-check the manifest, checksum file, archive directory, and complete logical inventory;
7. inspect every tar archive without extracting it;
8. recompute `member_count` and `uncompressed_file_bytes` from tar headers;
9. reject unsafe or unsupported archive members.

### Tar member policy

Allowed member types:

- directory;
- regular file;
- symbolic link;
- hard link.

Rejected member types include:

- character and block devices;
- FIFOs;
- sockets;
- unknown special types.

Every member name must:

- be valid text without NUL or control characters;
- be relative;
- contain no `..` path component;
- normalize beneath the archive root;
- be unique within its archive.

Every symbolic-link and hard-link target must:

- be relative;
- contain no NUL or control characters;
- resolve beneath the archive root according to its tar semantics.

The verifier explicitly rejects absolute paths, parent traversal, escaping links, duplicate members, and special files before restore begins.

Python's tar extraction filters are not used as the only defense. The controller performs its own complete header inspection because the actual extraction occurs inside the helper container and because the project intentionally permits safe relative symlinks while preserving Unix metadata.

## Backup operation

`create` performs the following preflight before opening a snapshot directory:

1. validate `HOMELAB_PROJECT_NAME` against Compose project-name rules;
2. verify Python version and required repository files;
3. verify the Docker CLI and daemon;
4. verify no project container exists;
5. inspect all eleven expected actual volume names;
6. reject attached, non-local, or option-bearing existing volumes;
7. fail if no expected volume exists;
8. verify the pinned helper image reference is explicit.

It then archives existing volumes in sorted logical-name order.

The source volume is always mounted read-only. Container stderr is captured with a fixed diagnostic limit; archive bytes are never interpreted as text and are never printed.

The backup does not invoke `make init`, does not start services, and does not create missing application volumes.

## Restore operation

### Target mapping

Restore does not force the manifest's source project name onto the host. The target is the current `HOMELAB_PROJECT_NAME`, enabling side-by-side recovery:

```bash
HOMELAB_PROJECT_NAME=homelab-recovery \
  make restore BACKUP=backups/homelab-20260720T120000Z-a1b2c3d4
```

`grafana_data` from the snapshot is restored to:

```text
homelab-recovery_grafana_data
```

Only archived volumes are created or populated. Logical volumes recorded as missing remain absent.

### Complete preflight before writes

Restore performs all of these checks before creating or writing any target volume:

1. complete offline snapshot verification;
2. target project-name validation;
3. Docker CLI and daemon verification;
4. rejection of every target-project container, including stopped containers;
5. target actual-name collision checks;
6. attachment checks against containers from any project;
7. local-driver and empty-options checks for existing targets;
8. emptiness checks for every existing target volume.

An existing target is accepted only when a read-only `volume-nocopy` helper probe finds no entry below its root. A non-empty target is never cleared, merged, or overwritten.

### Volume creation

Missing target volumes are created with the Compose ownership labels documented by Docker Compose:

```text
com.docker.compose.project=<target-project>
com.docker.compose.volume=<logical-name>
```

The driver is explicitly `local`.

The controller records exactly which volumes it created in the current run.

### Extraction and failure behavior

Archives are restored in sorted logical-name order only after the global preflight succeeds.

If extraction fails:

- volumes created by the current restore attempt are removed after their helper containers exit;
- pre-existing empty volumes are never automatically deleted or cleared;
- the command reports which pre-existing volume may have been partially populated;
- production containers are never started automatically.

This preserves the rule that the tool may delete only resources it created itself. Because existing empty volumes cannot be transactionally renamed by Docker, the documentation recommends restoring into a fresh project name for the strongest rollback boundary.

After success, the operator starts and validates the recovered project separately.

## Generated recovery instructions

Every snapshot includes `RECOVERY.md` with concrete commands for:

- offline verification;
- side-by-side restore into a fresh project name;
- inspecting restored volumes;
- running the existing default and IoT runtime checks where appropriate;
- starting the recovered profiles manually;
- retaining the original volumes until application-level validation succeeds.

The generated document includes the snapshot identifier and source project but never embeds secrets.

## Secret and privacy model

The snapshot intentionally excludes:

- repository `.env`;
- repository `.secrets/`;
- Git credentials;
- Docker registry credentials;
- CI credentials.

This does not make the snapshot public data. Application volumes can contain:

- Grafana users and sessions;
- Portainer configuration and authentication state;
- InfluxDB metadata and tokens stored in its database;
- Mosquitto retained messages;
- openHAB configuration, automation data, and user state;
- host information collected by Netdata.

Therefore:

- snapshot files default to mode `0600` inside a mode-`0700` directory;
- operators are told to encrypt backups at rest and in transit;
- SHA-256 checksums are described as corruption detection, not encryption or authenticity;
- complete disaster recovery also requires separately protected current `.env` and `.secrets/` values or application-specific credential rotation.

The project does not invent a custom encryption format in this stage.

## Behavioral and unit tests

Create `scripts/test_backup.py` using only the standard library and fake Docker executables.

Tests cover at least:

- project-name precedence and validation;
- exact eleven-volume inventory;
- snapshot identifier validation;
- strict manifest key and type validation;
- checksum parsing and mismatch rejection;
- missing and unexpected archive detection;
- absolute tar paths;
- parent traversal;
- duplicate members;
- device/FIFO rejection;
- escaping symlink and hardlink targets;
- acceptance of a safe relative symlink;
- all-missing backup refusal;
- project-container refusal;
- attached-volume refusal;
- non-local/option-bearing volume refusal;
- streaming archive command shape with read-only `volume-nocopy` source mounts;
- restore preflight before volume creation;
- non-empty target refusal;
- creation of Compose labels;
- cleanup of only volumes created by a failed restore;
- source `.env` and `.secrets/` preservation;
- atomic publication and temporary-directory cleanup;
- absence of credentials in output and Docker arguments.

The fast `make check` suite runs these tests but never creates a real backup or Docker volume beyond its existing Compose render check.

## Real backup/restore runtime test

Create `scripts/check_backup_runtime.sh` and a separate GitHub Actions workflow.

The test uses a unique project name and a private temporary backup root. It creates a representative subset of the logical volumes rather than all eleven, so the missing-volume path is exercised naturally.

Fixtures include:

- nested directories;
- an empty file;
- deterministic text and binary files;
- non-default file and directory permissions;
- a relative symlink that remains inside the volume.

The workflow then executes:

```text
create fixture source volumes
→ run backup
→ run offline verify
→ remove fixture source volumes
→ restore into a different project name
→ assert file bytes, modes, directories, and symlink target
→ verify missing volumes were not created
→ test refusal against a non-empty target volume
→ clean every uniquely named fixture resource
```

The test also tampers with a copied checksum or archive and confirms that offline verification fails before Docker restore resources are created.

The workflow does not start InfluxDB, Grafana, Portainer, Netdata, Mosquitto, or openHAB. It tests backup mechanics independently from application startup workflows.

## GitHub Actions

Add `.github/workflows/backup-runtime.yml` with:

- relevant pull-request path filters;
- push to `main` for backup-related files;
- manual dispatch;
- a weekly schedule that does not overlap the other runtime workflows;
- `contents: read` permissions only;
- concurrency cancellation;
- a 15-minute job timeout;
- Docker and Compose version output;
- `make check-backup-runtime` with `pipefail` and a captured log;
- a three-day diagnostic artifact uploaded only on failure.

The workflow must not upload generated snapshots because volume fixtures may contain sensitive data in future expansions.

## Static acceptance policy

Add `scripts/check_backup_policy.py` and extend existing static checks to require:

- the exact eleven logical volumes;
- the pinned `alpine:3.24.1` helper image;
- inclusion of the helper in image-platform verification;
- `backup`, `verify-backup`, `restore`, and `check-backup-runtime` Make targets;
- `/backups/` in `.gitignore`;
- offline verification without Docker calls;
- read-only source mounts;
- `volume-nocopy` on helper mounts;
- project and attachment preflight checks;
- strict tar member validation;
- atomic temporary-directory publication;
- restore refusal for non-empty targets;
- Compose project/volume labels on created targets;
- bounded diagnostics;
- no `docker volume prune`, `docker system prune`, host Docker storage access, or automatic service shutdown;
- no inclusion of `.env` or `.secrets/` in snapshots;
- the dedicated runtime workflow and documentation.

## Documentation changes

Create `docs/BACKUP.md` and replace the one-off README Grafana example with a concise pointer to the verified workflow.

Documentation covers:

- cold-backup requirement and `make down`;
- all commands and variables;
- snapshot layout and verification;
- safe side-by-side restore;
- application-level checks after restore;
- backup confidentiality;
- separate secret preservation;
- checksum limitations;
- supported local-volume boundary;
- rollback behavior.

`docs/MIGRATION.md` points to `docs/BACKUP.md` for current named-volume backups while retaining its legacy bind-mount migration instructions.

## Non-goals

This stage does not implement:

- live or crash-consistent backup while services run;
- application-native InfluxDB export;
- selective Grafana dashboards or InfluxDB measurements;
- automatic production service stop/start;
- S3, SFTP, SMB, NFS, or cloud upload;
- deduplication or incremental snapshots;
- retention pruning;
- production scheduling;
- encryption key management;
- snapshot signing;
- custom Docker volume drivers;
- direct access to Docker's host storage directory;
- Kubernetes or k3s persistent-volume backup.

## Authoritative references

- Docker Docs, **Volumes**, including the documented backup/restore pattern and the requirement to interact with volume data through containers: <https://docs.docker.com/engine/storage/volumes/>
- Docker Compose Docs, **Define and manage volumes**, including `name` behavior and automatic `com.docker.compose.project` / `com.docker.compose.volume` labels: <https://docs.docker.com/reference/compose-file/volumes/>
- Python 3.11 documentation, **tarfile extraction filters and security considerations**: <https://docs.python.org/3.11/library/tarfile.html#extraction-filters>
- Alpine Linux, **3.24.1 release**: <https://www.alpinelinux.org/posts/Alpine-3.24.1-released.html>
