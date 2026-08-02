# Docker Compose Homelab

A modular, reproducible, and security-focused homelab platform for Linux `amd64` and `arm64`.

The established Traefik, InfluxDB, Telegraf, Grafana, Portainer, Netdata, Mosquitto, openHAB, and k6 stack remains compatible with the previous operator commands. Optional modules add Uptime Kuma, Homepage, guarded AdGuard Home, Authelia, and read-only Dozzle. The repository also provides verified local backups, encrypted restic transport, diagnostics, real runtime tests, CycloneDX SBOMs, and pinned Trivy policy enforcement.

Project version: [`VERSION`](VERSION). Release history: [`CHANGELOG.md`](CHANGELOG.md). Module catalog: [`docs/MODULES.md`](docs/MODULES.md).

## Principles

- root `compose.yaml` assembled from independently owned files under `modules/`;
- Docker Compose profiles for every non-core group;
- no `latest` or implicit image tags;
- image verification for both `linux/amd64` and `linux/arm64`;
- file-backed local credentials under ignored `.secrets/`;
- unchanged `make up` scope: core + monitoring + Portainer;
- no implicit DNS activation through `make full` or `make community`;
- named volumes preserved by `make down` and included in verified backup/restore;
- read-only `make doctor` diagnostics;
- isolated runtime workflows with bounded waits, diagnostics, and scoped cleanup;
- Renovate, registry manifest checks, Trivy scans, and CycloneDX SBOMs;
- TLS delivered as explicit deployment overrides, never as a fictitious default.

## Requirements

- Linux Docker Engine and Docker Compose **2.20.3 or newer** for top-level `include`;
- Python 3.11+, `make`, a POSIX shell, OpenSSL, and `curl`;
- Docker Buildx for image-platform verification;
- permission to access the Docker daemon.

## Quick start

```bash
git clone https://github.com/646826/docker-compose-files.git
cd docker-compose-files
make doctor
make init
make up
```

`make doctor` checks Docker, Compose, architecture, memory, disk, listeners, `.env`, secret permissions, resource names, and common DNS conflicts without changing the host.

`make init` creates `.env` only when missing and creates only missing established credentials. Existing values are never silently rotated. Traefik uses cost-12 bcrypt. Mosquitto uses SHA512-PBKDF2 with exactly 220000 iterations; plaintext is supplied through standard input rather than process arguments.

## Modules

```text
compose.yaml
modules/
├── core/          # socket proxy, Traefik, whoami
├── monitoring/    # InfluxDB, Telegraf, Grafana, Netdata, k6
├── tools/         # Portainer
├── iot/           # Mosquitto, openHAB
├── uptime/        # Uptime Kuma
├── dns/           # guarded AdGuard Home
├── dashboard/     # static Homepage
├── auth/          # Authelia and ForwardAuth
└── logs/          # Dozzle through the restricted socket proxy
```

Shared networks, volumes, and Compose secret declarations remain in the root file. Support level, profile, storage, privileges, secrets, and runtime ownership are documented in [`docs/MODULES.md`](docs/MODULES.md).

## Endpoints

With `BASE_DOMAIN=localhost`:

| Service | Address | Activation |
| --- | --- | --- |
| Traefik | `http://traefik.localhost/dashboard/` | core |
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
| AdGuard Home | `http://dns.localhost`, TCP/UDP `${DNS_PORT:-53}` | explicit `make dns` |

Inside the Compose network, openHAB must use the internal MQTT broker address `mosquitto:1883`; this does not depend on the published host port.

`HTTP_HOST_IP` and `MQTT_HOST_IP` default to `0.0.0.0`; use `127.0.0.1` for local-only publication. `NETDATA_PORT` defaults to `19999`. AdGuard's initial setup port binds to loopback by default.

## Commands

| Command | Purpose |
| --- | --- |
| `make help` | list commands |
| `make doctor` | read-only host and configuration diagnosis |
| `make init` | create established configuration and missing credentials |
| `make core` | start Traefik, socket proxy, and whoami |
| `make up` | start core + monitoring + Portainer |
| `make full` | start established persistent services; excludes DNS and community web modules |
| `make monitoring` | start InfluxDB, Telegraf, and Grafana |
| `make netdata` | start opt-in full host monitoring |
| `make tools` | start Portainer |
| `make iot` | start Mosquitto and openHAB |
| `make uptime` | start Uptime Kuma |
| `make dashboard` | start static Homepage without Docker API access |
| `make dozzle` | start protected read-only container logs |
| `make community` | start Uptime Kuma, Homepage, and Dozzle; Authelia only when selected |
| `make dns-preflight` | check TCP/UDP DNS listeners without mutation |
| `make dns` | run preflight and explicitly start AdGuard Home |
| `make auth-init` | create missing local Authelia files without rotation |
| `make auth-check` | validate Authelia configuration with the pinned image |
| `make auth` | validate and start Authelia |
| `make check-auth-runtime` | verify an isolated Authelia portal and Traefik ForwardAuth redirect |
| `make k6` | run the committed bounded smoke test |
| `make pull` | pull every locally configured image version |
| `make ps` | show containers from every locally configured profile |
| `make logs` | follow logs from every locally configured profile |
| `make down` | stop locally configured profiles while preserving volumes |

## Authentication

Community HTTP applications use Traefik Basic Auth by default:

```dotenv
AUTH_MIDDLEWARE=local-auth@docker
```

Homepage receives no Docker socket or Docker API endpoint. Dozzle uses only `docker-socket-proxy`; actions and shell access are disabled.

Enable Authelia only after validation:

```bash
make auth-init
make auth-check
make check-auth-runtime
# Set AUTH_MIDDLEWARE=authelia@docker in .env
make community
```

`make check-auth-runtime` creates a disposable normal domain and credentials, validates the generated configuration with the pinned Authelia image, starts core + Homepage + Authelia, verifies the portal through Traefik, and proves that the protected Homepage route redirects to Authelia. It does not read deployment `.env` or `.secrets/`.

Recovery and rollback are documented in [`docs/AUTHELIA.md`](docs/AUTHELIA.md). To roll back, restore `AUTH_MIDDLEWARE=local-auth@docker`, restart affected profiles, verify access, and then stop Authelia.

## Credentials

No deployment credential belongs in Git. Local values live under `.secrets/`, whose directory mode is `0700`.

| Consumer | Files |
| --- | --- |
| Traefik | `traefik_password`, `traefik_users` |
| InfluxDB | `influxdb_username`, `influxdb_password`, `influxdb_token` |
| Grafana | `grafana_admin_password` |
| Mosquitto | `mosquitto_password`, `mosquitto_passwords` |
| Authelia | password, users/configuration, JWT/session/storage secret files |
| Remote backup | `restic_repository`, `restic_password`, optional `restic_environment` |

Operator plaintext files use mode `0600`. Some Compose secret sources use mode `0644` inside the private directory because ordinary Compose bind mounts do not remap ownership. Each service receives only its declared secrets.

Never publish `.env`, `.secrets/`, TLS private keys, ACME state, or restic credentials.

## Backups

Create and verify a cold local snapshot:

```bash
make down
make backup
make verify-backup BACKUP=backups/<snapshot-id>
```

Prefer side-by-side restore:

```bash
HOMELAB_PROJECT_NAME=homelab-recovery \
  make restore BACKUP=backups/<snapshot-id>
```

The snapshot format uses a canonical manifest, SHA-256 checksums, strict tar validation, image inventory, and atomic publication. See [`docs/BACKUP.md`](docs/BACKUP.md).

Encrypted off-host transport supports SFTP, S3-compatible, and other restic backends:

```bash
make remote-init
make remote-backup BACKUP=backups/<snapshot-id>
make remote-snapshots
make verify-remote-backup
make remote-retention
```

The wrapper verifies the local snapshot before upload and reads credentials from files. See [`docs/REMOTE_BACKUP.md`](docs/REMOTE_BACKUP.md).

## AdGuard Home

AdGuard Home never starts through `make up`, `make full`, or `make community`. Run:

```bash
make dns-preflight
make dns
```

Review port `53`, `systemd-resolved`, router DHCP, upstream DNS, and rollback first. See [`docs/ADGUARD.md`](docs/ADGUARD.md).

## Uptime Kuma image choice

The maintained default is `louislam/uptime-kuma:2.4.0-slim`. It supports the normal SQLite-backed installation and standard monitor types while substantially reducing image size and attack surface. The slim image intentionally omits embedded MariaDB and embedded Chromium. Browser Engine monitors therefore need an external Chromium setup, and embedded MariaDB users must switch to the full pinned image through a local override after reviewing the additional dependencies and security scan results.

## TLS

The default remains local HTTP. Public DNS, certificates, private keys, provider credentials, and ACME state are never enabled or committed automatically.

- LAN TLS: [`docs/TLS-LAN.md`](docs/TLS-LAN.md)
- Public DNS-01 TLS: [`docs/TLS-PUBLIC.md`](docs/TLS-PUBLIC.md)
- Opt-in override: `examples/tls/compose.tls.yaml`

Keep certificate material under ignored `local/` paths or another operator-controlled location outside Git.

## Image versions

| Component | Image version |
| --- | --- |
| Bootstrap helper Apache httpd | `2.4.68` |
| Backup helper Alpine | `3.24.1` |
| Docker socket proxy | `0.4.2` |
| Traefik | `3.7.10` |
| whoami | `1.11.0` |
| InfluxDB | `2.9.1` |
| Telegraf | `1.39.2` |
| Grafana | `13.1.0` |
| Portainer CE LTS | `2.39.5` |
| Netdata | `2.10.3` |
| Eclipse Mosquitto | `2.1.2` |
| openHAB | `5.2.0` |
| k6 | `2.1.0` |
| Uptime Kuma | `2.4.0-slim` |
| AdGuard Home | `0.107.76` |
| Homepage | `1.13.1` |
| Authelia | `4.39.20` |
| Dozzle | `10.6.2` |
| restic helper | `0.18.1` |
| Trivy helper | `0.70.0` |

Renovate proposes reviewable updates; running containers are not updated automatically outside Git and CI.

## Security and SBOMs

The repository invokes a pinned Trivy container directly rather than mutable setup actions.

```bash
make scan-images
make sbom
make check-security
```

Reports are ignored under `security-reports/` and `sbom/`. `make check-security` fails on fixable `CRITICAL` findings without a non-expired exact entry in `security/exceptions.json` containing ID, image, owner, reason, and expiration date.

## Six verification levels

### 1. Fast configuration check

```bash
make check
```

Runs static policies, unit and behavior tests, shell syntax, secret placeholders, TLS/release/security policy, English-only tracked-file validation, and the merged Compose model. It starts no application containers and performs no registry vulnerability scan.

### 2. Registry manifest check

```bash
make check-images
```

Uses Docker Buildx raw manifests to verify every service and helper image publishes `linux/amd64` and `linux/arm64`.

### 3. Isolated default-stack runtime check

```bash
make check-runtime
```

Starts a unique core + monitoring + Portainer project on a random `127.0.0.1` HTTP port. Stateful application data is replaced with disposable `tmpfs` mounts where the harness defines them. It verifies authentication, health, Grafana provisioning, real Telegraf data, and scoped cleanup. The harness does not read deployment `.env` or `.secrets/`.

### 4. Isolated IoT runtime check

```bash
make check-iot-runtime
```

Starts core + IoT on random loopback ports. It verifies anonymous rejection, authenticated QoS 1 retained messages, persistence after restart, openHAB readiness, and cleanup. `MQTT_HOST_IP` remains configurable.

### 5. Isolated backup/restore runtime check

```bash
make check-backup-runtime
```

Exercises real local backup, offline verification, tamper rejection, restore, byte/metadata comparison, non-empty target rejection, and scoped cleanup.

### 6. Isolated optional-profile runtime check

```bash
make check-optional-runtime
```

Chooses a random `NETDATA_PORT`, starts Netdata and the direct k6 target, verifies `/api/v1/info`, a real `system.cpu` sample, committed k6 thresholds, service scope, and cleanup.

## Additional verification

```bash
make check-community-runtime
make check-auth-runtime
make check-remote-backup-runtime
make check-security
```

Community runtime verifies authenticated Uptime Kuma, Homepage, and Dozzle routes. Auth runtime validates a real Authelia portal and Traefik ForwardAuth redirect. Remote runtime proves restic init/backup/check/restore and wrong-password rejection. Security CI generates SBOMs and enforces the fixable-CRITICAL policy.

## Further documentation

- [`docs/MODULES.md`](docs/MODULES.md) — lifecycle, profiles, ports, volumes, secrets, privileges, runtime ownership;
- [`docs/MIGRATION.md`](docs/MIGRATION.md) — migration from legacy data layout;
- [`docs/K3S.md`](docs/K3S.md) — separate same-host k3s guidance;
- [`SECURITY.md`](SECURITY.md) — credentials, privileged interfaces, DNS, authentication, backups, TLS, and scanning.

k3s remains separate from this Compose application. Rootless Docker, SELinux, Docker Desktop, NAS wrappers, custom sockets, multicast, USB devices, and public TLS may require local overrides and are never silently enabled.
