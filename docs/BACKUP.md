# Verified volume backups

This repository can create, verify, and restore cold snapshots of its persistent Docker volumes. The restore path is exercised in GitHub Actions with disposable volumes; it is not only a documentation example.

## Safety model

A snapshot is deliberately a **cold backup**. Before `create` or `restore`, the tool checks all containers carrying the target Compose project label, including stopped containers. It also rejects a volume attached to a container from any project.

Stop and remove the project containers without deleting named volumes:

```bash
make down
```

The commands never stop production services automatically. They support only Docker `local` volumes without driver options. NFS, CIFS, plugin-backed, block-storage, Docker Desktop, and rootless-specific layouts require a deployment-specific procedure.

## Create a cold snapshot

The default backup root is `backups/`:

```bash
make down
make backup
```

To use a different trusted local path:

```bash
BACKUP_ROOT=/srv/encrypted/homelab-backups make backup
```

An existing backup root must be a real directory, not a symlink, and must have no group or other permission bits. A new root is created with mode `0700`. The tool records every current logical volume; volumes that do not exist are listed as missing instead of being created. Creation fails when none of the project volumes exist.

Archives are streamed from read-only `volume-nocopy` mounts through the pinned helper image `alpine:3.24.1`. The tool never reads Docker's host storage directory directly.

## Verify a snapshot offline

Verification does not invoke Docker and does not create resources:

```bash
make verify-backup BACKUP=backups/<snapshot-id>
```

It checks:

- strict format-version-1 manifest keys and types;
- canonical JSON and a self-contained declared-volume inventory;
- archive sizes and SHA-256 values;
- the complete `SHA256SUMS` path set;
- expected files only, with no symlinked snapshot structure;
- private snapshot permissions;
- tar member counts and uncompressed file bytes;
- relative paths without parent traversal;
- duplicate member rejection;
- safe relative symbolic and hard links;
- rejection of devices, FIFOs, sockets, and unknown special members.

SHA-256 checksums detect accidental corruption. They are **not encryption**, a digital signature, or protection from a malicious party that can replace both the snapshot and its checksum file.

## Restore side by side

The safest recovery target uses a fresh project name, leaving the original volumes untouched:

```bash
HOMELAB_PROJECT_NAME=homelab-recovery \
  make restore BACKUP=backups/<snapshot-id>
```

Restore first performs complete offline verification. Before any volume is created, it checks the target project, attachments, volume drivers/options, Compose ownership labels, and emptiness of every existing target.

An existing target is accepted only when it is completely empty and either has no Compose ownership labels or has the exact expected labels. A non-empty volume is never cleared, merged, or overwritten.

Missing targets are created as local volumes with:

```text
com.docker.compose.project=<target-project>
com.docker.compose.volume=<logical-name>
```

If extraction fails, only volumes created during that restore attempt are removed. A pre-existing empty volume is never deleted automatically and may require operator inspection if its extraction had started.

## Validate applications after restore

Restore does not start containers. After restoring to `homelab-recovery`, use a matching `.env` and separately protected credentials, then start only the profiles needed for validation. Confirm at least:

- InfluxDB accepts writes and Telegraf metrics arrive;
- Grafana loads its datasource and dashboards;
- Portainer opens and shows the expected endpoint data;
- Mosquitto authenticates and restores retained state;
- openHAB loads its configuration and user data;
- `make down` followed by startup preserves state.

Keep the original project volumes until application-level checks succeed. The existing runtime checks create their own disposable projects and do not validate the restored production data itself.

## Snapshot layout and manifest

A successful snapshot is atomically published only after its internal verifier passes:

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

`manifest.json` records the format version, UTC creation time, source project, Git revision and dirty state, pinned images, snapshot-declared volume inventory, missing volumes, archive sizes, SHA-256 hashes, member counts, and uncompressed file bytes.

The snapshot carries its own declared-volume inventory so an older backup remains verifiable after the repository adds a new current volume. Restore is stricter: it refuses an archived logical volume unknown to the current repository.

## Confidentiality and separate secrets

Snapshot directories use mode `0700`; files use mode `0600`. This is necessary because application volumes can contain users, sessions, tokens stored inside databases, retained MQTT data, home-automation configuration, and host information.

The snapshot intentionally excludes repository `.env` and `.secrets/`. Complete disaster recovery therefore also requires current values from those files, or application-specific credential rotation. Preserve them separately in an encrypted password manager, encrypted filesystem, or another trusted secret store.

Encrypt snapshots at rest and in transit when they leave the host. The project does not invent its own encryption or key-management format.

## Supported Docker volume boundary

The maintained path is current Linux Docker Engine with Docker Compose V2 and local named volumes. The controller accesses data only through short-lived helper containers. It does not use `/var/lib/docker/volumes`, custom volume drivers, Kubernetes persistent volumes, cloud APIs, NAS uploads, or application-specific export APIs.

## Failure and rollback behavior

Snapshot creation occurs in a private temporary sibling directory. An error removes only that incomplete directory; the final snapshot name is published with an atomic rename after verification.

Restore performs a global preflight before writes. On failure, it removes only targets created by the current attempt. For the strongest rollback boundary, restore into a fresh `HOMELAB_PROJECT_NAME`, validate the recovered applications, and retain the original volumes until the cutover decision.

## Deliberate non-goals

This subsystem does not implement live or crash-consistent backups, automatic service stop/start, incremental snapshots, retention pruning, S3/SFTP/SMB/NFS upload, encryption-key management, snapshot signing, application-level selective exports, or production scheduling.
