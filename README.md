# Docker Compose Homelab

A modular, reproducible, and security-focused homelab platform for Linux `amd64` and `arm64`.

The root Compose application preserves the established Traefik, InfluxDB, Telegraf, Grafana, Portainer, Netdata, Mosquitto, openHAB, and k6 stack. Optional modules add Uptime Kuma, Homepage, guarded AdGuard Home, Authelia, and read-only Dozzle. The repository also provides verified local backups, encrypted restic transport, host diagnostics, image-platform checks, real runtime tests, CycloneDX SBOMs, and pinned Trivy policy enforcement.

Current project release: [`VERSION`](VERSION). Release history: [`CHANGELOG.md`](CHANGELOG.md). Complete module inventory: [`docs/MODULES.md`](docs/MODULES.md).

## Design principles

- one root `compose.yaml` assembled from independently owned files under `modules/`;
- Docker Compose profiles for every non-core service group;
- no `latest` or implicit image tags;
- maintained image support for both `linux/amd64` and `linux/arm64`;
- locally generated, file-backed credentials under ignored `.secrets/`;
- unchanged default `make up` scope: core + monitoring + Portainer;
- no implicit DNS activation through `make full` or `make community`;
- named volumes preserved by `make down` and covered by verified backup/restore;
- read-only host diagnosis through `make doctor`;
- isolated application-level runtime tests with unique projects and scoped cleanup;
- registry manifest verification, Renovate updates, Trivy scans, and CycloneDX SBOMs;
- LAN and public TLS documented as deployment-specific overrides rather than unsafe defaults.

## Requirements

- Linux Docker Engine with the current `docker compose` plugin;
- Docker Compose **2.20.3 or newer**, required for the top-level `include` element;
- Python 3.11+, `make`, a POSIX shell, OpenSSL, and `curl`;
- Docker Buildx for multi-platform manifest verification;
- a user account allowed to access the Docker daemon.

Run the non-mutating diagnostic before deployment:

```bash
make doctor
```

It checks Docker availability, Compose version, host architecture, memory, disk space, listener conflicts, `.env`, local secret permissions, resource names, and common DNS conflicts. It reports corrective guidance but does not change the host.

## Quick start

```bash
git clone https://github.com/646826/docker-compose-files.git
cd docker-compose-files
make doctor
make init
make up
```

`make init` creates `.env` only when missing and creates only missing established credentials. Existing values are not silently replaced or rotated. Traefik receives a cost-12 bcrypt record. Mosquitto receives a SHA512-PBKDF2 record with exactly 220000 iterations; plaintext is supplied through standard input rather than process arguments.

`make up` starts the compatibility scope:

```text
core + monitoring + Portainer
```

Community applications remain opt-in.

## Module layout

```text
compose.yaml
modules/
├── core/          # socket proxy, Traefik, whoami
├── monitoring/    # InfluxDB, Telegraf, Grafana, Netdata, k6
├── tools/         # Portainer
├── iot/           # Mosquitto and openHAB
├── uptime/        # Uptime Kuma
├── dns/           # guarded AdGuard Home
├── dashboard/     # static Homepage
├── auth/          # Authelia and ForwardAuth middleware
└── logs/          # Dozzle through the restricted socket proxy
```

Shared networks, named volumes, and Compose secret declarations stay in the root file. Service ownership, profiles, privileges, storage, commands, and runtime coverage are documented in [`docs/MODULES.md`](docs/MODULES.md).

## Endpoints

With `BASE_DOMAIN=localhost` and default ports:

| Service | Address | Activation |
| --- | --- | --- |
| Traefik dashboard | `http://traefik.localhost/dashboard/` | core |
| whoami | `http://whoami.localhost` | core |
| InfluxDB | `http://influxdb.localhost` | `make up` / `make monitoring` |
| Grafana | `http://grafana.localhost` | `make up` / `make monitoring` |
| Portainer | `http://portainer.localhost` | `make up` / `make tools` |
| Netdata | `http://localhost:${NETDATA_PORT}`; default `19999` | `make full` / `make netdata` |
| openHAB | `http://openhab.localhost` | `make full` / `make iot` |
| Mosquitto | `mqtt://localhost:1883` | `make full` / `make iot` |
| Uptime Kuma | `http://uptime.localhost` | `make uptime` / `make community` |
| Homepage | `http://home.localhost` | `make dashboard` / `make community` |
| Dozzle | `http://logs.localhost` | `make dozzle` / `make community` |
| Authelia | `http://auth.localhost` | `make auth` or selected by `make community` |
| AdGuard Home UI | `http://dns.localhost` | explicit `make dns` |
| AdGuard DNS | TCP/UDP `${DNS_HOST_IP}:${DNS_PORT}`; default port `53` | explicit `make dns` |

`HTTP_HOST_IP` and `MQTT_HOST_IP` default to `0.0.0.0`; set them to `127.0.0.1` for host-local publication. `NETDATA_PORT` defaults to `19999`. AdGuard's initial setup listener defaults to loopback. Before changing router or client DNS, follow [`docs/ADGUARD.md`](docs/ADGUARD.md).

## Main commands

| Command | Purpose |
| --- | --- |
| `make help` | show all operator commands |
| `make doctor` | diagnose the host and local configuration without mutation |
| `make init` | create established configuration and missing credentials |
| `make core` | start the core reverse-proxy services |
| `make up` | start core + monitoring + Portainer |
| `make full` | start all established persistent services; excludes DNS and community web modules |
| `make monitoring` | start InfluxDB, Telegraf, and Grafana |
| `make netdata` | start opt-in full host monitoring |
| `make tools` | start Portainer |
| `make iot` | start Mosquitto and openHAB |
| `make uptime` | start Uptime Kuma |
| `make dashboard` | start Homepage without Docker API access |
| `make dozzle` | start protected read-only container logs |
| `make community` | start Uptime Kuma, Homepage, and Dozzle; includes Authelia only when selected |
| `make dns-preflight` | check TCP/UDP DNS listeners without modifying the host |
| `make dns` | run preflight and explicitly start AdGuard Home |
| `make auth-init` | create or refresh missing local Authelia files without rotation |
| `make auth-check` | validate generated Authelia configuration with the pinned image |
| `make auth` | validate and start Authelia |
| `make k6` | run the bounded committed smoke test |
| `make pull` | pull every explicitly selected image version |
| `make ps` | show containers from every profile |
| `make logs` | follow logs from every profile |
| `make down` | stop all known profiles while preserving named volumes |

## Authentication

Community HTTP applications use the existing Traefik Basic Auth middleware by default:

```dotenv
AUTH_MIDDLEWARE=local-auth@docker
```

This is the safest immediate migration path. Homepage receives no Docker socket or API endpoint. Dozzle talks only to `docker-socket-proxy`; its actions and shell features are disabled.

To enable Authelia:

```bash
make auth-init
make auth-check
# Change .env:
# AUTH_MIDDLEWARE=authelia@docker
make community
```

Configuration, enrollment, recovery, and rollback are documented in [`docs/AUTHELIA.md`](docs/AUTHELIA.md). To roll back, restore `AUTH_MIDDLEWARE=local-auth@docker`, restart the affected profiles, verify access, and then stop Authelia.

## Credentials

No production credential belongs in Git. Local values are stored under `.secrets/`, whose directory mode is `0700`.

| Consumer | Local files |
| --- | --- |
| Traefik and protected routes | `traefik_password`, `traefik_users` |
| InfluxDB | `influxdb_username`, `influxdb_password`, `influxdb_token` |
| Grafana | `grafana_admin_password` |
| Mosquitto | `mosquitto_password`, `mosquitto_passwords` |
| Authelia | `authelia_password`, `authelia_users.yml`, `authelia_configuration.yml`, JWT/session/storage secret files |
| Remote backup | `restic_repository`, `restic_password`, optional `restic_environment` |

Operator-only plaintext files use mode `0600`. Some Compose secret source files use mode `0644` inside the private directory because ordinary Compose bind mounts do not remap ownership; each container receives only explicitly assigned secrets.

Never place `.env`, `.secrets/`, TLS private keys, ACME state, or restic credentials in issues, logs, screenshots, or unencrypted archives.

## Local and remote backups

Stateful services use project-prefixed named volumes. `make down` preserves them.

Create and verify a cold local snapshot:

```bash
make down
make backup
make verify-backup BACKUP=backups/<snapshot-id>
```

Restore side by side under another project name whenever possible:

```bash
HOMELAB_PROJECT_NAME=homelab-recovery \
  make restore BACKUP=backups/<snapshot-id>
```

The snapshot format includes a canonical manifest, SHA-256 checksums, strict tar-member validation, image inventory, and atomic publication. See [`docs/BACKUP.md`](docs/BACKUP.md).

For encrypted off-host storage through SFTP, S3-compatible storage, or another restic backend:

```bash
make remote-init
make remote-backup BACKUP=backups/<snapshot-id>
make remote-snapshots
make verify-remote-backup
make remote-retention
```

Remote transport always verifies the local snapshot before upload and reads repository/password values from files. See [`docs/REMOTE_BACKUP.md`](docs/REMOTE_BACKUP.md).

## TLS

The default remains local HTTP. No public domain, certificate, key, DNS-provider credential, or ACME resolver is enabled automatically.

- Trusted LAN certificate deployment: [`docs/TLS-LAN.md`](docs/TLS-LAN.md)
- Public DNS-01 deployment: [`docs/TLS-PUBLIC.md`](docs/TLS-PUBLIC.md)
- Opt-in override: `examples/tls/compose.tls.yaml`

Certificate material must live under ignored `local/` paths or another operator-controlled location outside the repository.

## Image versions

| Component | Image version |
| --- | --- |
| Bootstrap helper Apache httpd | `2.4.68` |
| Backup helper Alpine | `3.24.1` |
| Docker socket proxy | `0.4.2` |
| Traefik | `3.7.8` |
| whoami | `1.11.0` |
| InfluxDB | `2.9.1` |
| Telegraf | `1.39.1` |
| Grafana | `13.1.0` |
| Portainer CE LTS | `2.39.5` |
| Netdata | `2.10.3` |
| Eclipse Mosquitto | `2.1.2` |
| openHAB | `5.2.0` |
| k6 | `2.1.0` |
| Uptime Kuma | `2.3.2` |
| AdGuard Home | `0.107.76` |
| Homepage | `1.13.1` |
| Authelia | `4.39.20` |
| Dozzle | `10.6.2` |
| restic helper | `0.18.1` |
| Trivy helper | `0.70.0` |

Renovate proposes reviewable updates. Runtime containers are never updated automatically outside Git and CI.

## Security scans and SBOMs

The repository invokes the pinned Trivy container directly. It does not depend on mutable Trivy setup actions.

```bash
make scan-images     # JSON HIGH/CRITICAL vulnerability reports
make sbom            # one CycloneDX JSON document per maintained image
make check-security  # fail on fixable CRITICAL findings without an active exact exception
```

Generated files are ignored under `security-reports/` and `sbom/`. Exceptions are explicit entries in `security/exceptions.json` containing vulnerability ID, exact image, owner, reason, and a future expiration date. Expired or malformed exceptions fail `make check`.

## Six verification levels

### 1. Fast configuration check

```bash
make check
```

Runs static policies, unit and behavior tests, shell syntax validation, secret-source placeholders, TLS/release/security policy validation, English-only tracked-file validation, and the fully rendered Compose model. It starts no application containers and performs no registry scan.

### 2. Registry manifest check

```bash
make check-images
```

Uses Docker Buildx raw manifests to verify every service and helper image publishes both `linux/amd64` and `linux/arm64`.

### 3. Isolated default-stack runtime check

```bash
make check-runtime
```

Starts a unique disposable core + monitoring + Portainer project on a random loopback HTTP port. It verifies Basic Auth, application health, Grafana provisioning, a real Telegraf measurement in InfluxDB, and scoped cleanup.

### 4. Isolated IoT runtime check

```bash
make check-iot-runtime
```

Starts a unique core + IoT project on random loopback HTTP and MQTT ports. It verifies anonymous rejection, authenticated QoS 1 retained publish/subscribe, retained-message persistence after Mosquitto restart, openHAB readiness, and scoped cleanup. The deployment variable `MQTT_HOST_IP` remains supported.

### 5. Isolated backup/restore runtime check

```bash
make check-backup-runtime
```

Creates disposable volumes, executes the real local snapshot/verification/restore engine, compares bytes and metadata, rejects tampering and non-empty targets, and removes only its own fixtures.

### 6. Isolated optional-profile runtime check

```bash
make check-optional-runtime
```

Chooses a random `NETDATA_PORT`, starts only Netdata and the direct k6 target, verifies `/api/v1/info`, a real `system.cpu` sample, the committed k6 thresholds, expected service scope, and scoped cleanup.

## Additional community verification

```bash
make check-community-runtime
make check-remote-backup-runtime
make check-security
```

The community workflow verifies authenticated Uptime Kuma, Homepage, and Dozzle routes. The remote-backup workflow proves an encrypted restic init/backup/check/restore round trip and wrong-password rejection. The Security workflow generates SBOMs and enforces the fixable-CRITICAL policy. All real runtime workflows use unique resource names, bounded waits, failure diagnostics, and project-scoped cleanup.

## Migration and advanced deployment

- legacy data migration: [`docs/MIGRATION.md`](docs/MIGRATION.md)
- k3s same-host guidance: [`docs/K3S.md`](docs/K3S.md)
- AdGuard network rollout: [`docs/ADGUARD.md`](docs/ADGUARD.md)
- Authelia setup and recovery: [`docs/AUTHELIA.md`](docs/AUTHELIA.md)
- module lifecycle and privileges: [`docs/MODULES.md`](docs/MODULES.md)

k3s remains separate from this Compose application. Rootless Docker, SELinux, NAS wrappers, Docker Desktop, custom socket locations, multicast discovery, USB devices, and public TLS may require local overrides; they are not silently enabled by the repository.
