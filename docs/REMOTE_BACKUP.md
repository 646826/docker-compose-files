# Encrypted remote backups with restic

The local backup command remains the only producer of application snapshots. Remote backup does not read live Docker volumes. It accepts only a snapshot that passes the same strict offline verifier used by `make verify-backup`.

## Data flow

```text
named Docker volumes
    -> make backup
    -> verified cold snapshot
    -> restic encryption and deduplication
    -> SFTP, S3-compatible storage, local repository, or another restic backend
```

## Local secret files

Create the following mode-`0600` files under the private mode-`0700` `.secrets` directory:

```text
.secrets/restic_repository
.secrets/restic_password
.secrets/restic_environment   # optional
```

`restic_repository` contains one repository URL, for example:

```text
sftp:backup@example.net:/srv/restic/homelab
```

or an S3-compatible repository:

```text
s3:https://s3.example.net/homelab-backups
```

`restic_password` contains a long independent encryption password. Losing this password makes the repository unrecoverable. Store a second encrypted copy outside the Docker host.

`restic_environment` is optional and uses literal `KEY=value` lines. It is passed to Docker as an env file, so provider credential **values** are not placed in process arguments. Example:

```dotenv
AWS_ACCESS_KEY_ID=replace-locally
AWS_SECRET_ACCESS_KEY=replace-locally
```

Do not commit these files, paste them into issues, or include them in unencrypted backups.

## Initialize the remote repository

```bash
make remote-init
```

Run this once for a new empty repository. Existing repositories return an error rather than being overwritten.

## Upload a verified local snapshot

First stop the stack and create a local verified snapshot:

```bash
make down
make backup
```

Then upload the selected snapshot:

```bash
make remote-backup BACKUP=backups/<snapshot-id>
```

The wrapper verifies the full snapshot locally before starting restic. The snapshot directory is mounted read-only into the pinned restic container.

## Inspect and verify

```bash
make remote-snapshots
make verify-remote-backup
```

`verify-remote-backup` runs a repository consistency check with a bounded data subset. Periodically perform a full restore on a separate host as well; repository checks do not replace recovery drills.

## Retention

Retention is never automatic. Review the snapshot list, then explicitly run:

```bash
make remote-retention
```

The maintained policy keeps 7 daily, 5 weekly, 12 monthly, and 3 yearly snapshots, followed by `prune`. This can remove remote data and therefore is intentionally separated from upload.

## Runtime verification

```bash
make check-remote-backup-runtime
```

This uses a disposable local restic repository and a generated password. It proves repository initialization, encrypted backup, snapshot listing, data verification, restore, byte/metadata comparison, wrong-password rejection, and scoped cleanup. It does not read `.env`, deployment secrets, Docker volumes, or network storage credentials.

## Recovery outline

1. Provision a clean host with Docker.
2. Restore `.secrets/restic_repository` and `.secrets/restic_password` from encrypted operator storage.
3. Use restic to restore the required local snapshot directory.
4. Run `make verify-backup BACKUP=...` against the restored snapshot.
5. Restore side by side under a new `HOMELAB_PROJECT_NAME` following `docs/BACKUP.md`.
6. Validate applications before switching DNS or traffic.

For SFTP, restrict the remote account to the repository path. For S3, use a dedicated bucket and least-privilege credentials. Append-only storage reduces ransomware risk, but retention/pruning must then run through a separately protected administrative identity.
