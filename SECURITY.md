# Security Policy

## Historical credentials

Earlier revisions of this public repository contained reusable passwords and tokens. Treat every credential ever committed to repository history as compromised, even after the current files are cleaned up.

Before exposing any service beyond the local machine:

1. run `make init` to generate new local credentials;
2. follow `docs/MIGRATION.md` if old persistent data is retained;
3. rotate credentials stored inside migrated InfluxDB, Grafana, Portainer, openHAB, or other application databases;
4. review listening ports with `docker compose --profile monitoring --profile tools --profile iot --profile netdata ps` and the host firewall.

Deleting a secret from the latest commit does not remove it from Git history. History rewriting can reduce accidental discovery but cannot revoke a value that was already public; rotation is mandatory.

## Secret handling

- `.env` is for non-secret deployment settings only.
- Generated credentials live under an ignored `.secrets/` directory with mode `0700`. Operator-only plaintext files use mode `0600`. Files mounted as Compose secrets use mode `0644` because file-backed secrets are bind mounts and Compose cannot remap their UID/GID; the private parent directory still prevents access by other host users.
- Each service receives only its explicitly granted Compose secrets. Grafana uses the image's official `GF_SECURITY_ADMIN_PASSWORD__FILE` convention, Traefik Basic Auth uses bcrypt with cost 12, and Mosquitto credentials use Argon2id.
- `scripts/init.sh` creates only missing files and never silently rotates an existing deployment. Mosquitto hashing uses `mosquitto_passwd -U`, so the plaintext password is read from standard input rather than exposed in process arguments.
- After initialization, username settings and their generated password files are treated as one credential. The bootstrap rejects username drift instead of silently producing a mismatched deployment; rotate an active service account through the application before changing its local files.
- Mosquitto copies its read-only hash secret into a private runtime `tmpfs`, applies UID/GID `1883` and mode `0600`, and authenticates through the Mosquitto 2.1 password-file plugin.
- The default MQTT listener on port `1883` is authenticated but not encrypted. Keep it on a trusted LAN; use a deployment-specific TLS listener and firewall rules for untrusted networks.
- Do not paste secrets into issues, CI logs, screenshots, dashboard exports, or unencrypted backups.

## Privileged interfaces

Most containers receive no Docker socket and use `no-new-privileges` where compatible. Three components require special attention:

- `docker-socket-proxy` holds the socket and exposes only selected read API sections on an internal Docker network;
- Portainer mounts the socket directly because its purpose is full host administration;
- Netdata uses documented host mounts, capabilities, host network/PID, and a read-only Docker socket for full host observability.

Portainer and the separate opt-in Netdata profile should be enabled only on trusted hosts and protected by host firewall rules. Do not publish their interfaces directly to the public internet.

## Supported deployment

The maintained target is a current Linux Docker Engine with the Compose plugin (`docker compose`) on `amd64` or `arm64`. Rootless Docker, SELinux, custom socket locations, Docker Desktop, and NAS vendor wrappers may need local overrides and can reduce available monitoring or management features.

## Dependency updates

Container images are pinned to explicit versions. Renovate opens reviewable update pull requests. Before merging an update, review upstream release notes, back up stateful volumes, run `make check`, and test startup on a non-critical host where practical.

## Reporting a vulnerability

Do not open a public issue containing an exploit, token, password, private host name, or personal network details. Contact the repository owner privately or use GitHub's private vulnerability reporting feature when it is enabled. Include the affected file/version, impact, reproducible steps with redacted values, and a proposed mitigation when available.
