# Docker Compose Homelab

A simple, reproducible, and secure homelab stack for Linux `amd64` and `arm64`.

The repository preserves all previous capabilities—Traefik, InfluxDB, Telegraf, Grafana, and Portainer—and completes the explicitly planned integrations: Netdata, Eclipse Mosquitto, openHAB, k6, and separate k3s guidance. The opt-in `apps`, `dns`, and `updates` profiles add the Homepage dashboard with the Dozzle log viewer, AdGuard Home network DNS, and the Diun image update notifier.

## What changed

- one root `compose.yaml` instead of a collection of independent files;
- Docker Compose profiles for optional service groups;
- pinned image versions instead of `latest`;
- locally generated Compose secrets instead of passwords committed to Git;
- the Traefik dashboard and whoami without an insecure port and protected by shared Basic Auth;
- Traefik and Telegraf access to the Docker API through a restricted socket proxy;
- named volumes that are not removed by `make down`;
- health checks, CI validation, Renovate, and compact maintainable configuration;
- a permanent English-only gate for tracked UTF-8 repository files;
- a separate check for image tag existence and `amd64`/`arm64` manifests;
- an isolated runtime smoke test that launches the actual default stack;
- a separate IoT runtime smoke test for MQTT authentication and persistence, plus openHAB readiness;
- an isolated optional-profile runtime test for Netdata host metrics and the committed k6 smoke script;
- verifiable cold backup and restore for named volumes, with a manifest, checksums, and a real CI round trip;
- k3s kept separate from Compose so the basic stack does not become a complex platform;
- a Homepage dashboard and Dozzle log viewer under the opt-in `apps` profile;
- AdGuard Home network DNS under the opt-in `dns` profile;
- a Diun image update notifier under the opt-in `updates` profile;
- entrypoint-wide security headers, rate limiting, and compression through the Traefik file provider;
- per-service log rotation and resource limits;
- an extended static policy gate that now also protects the new profiles, hardening rules, and Traefik middleware wiring.

## Requirements

- Linux with Docker Engine and a current Compose plugin (`docker compose`, not legacy `docker-compose`);
- `make`, a POSIX shell, and Python 3.11+;
- OpenSSL and `curl`;
- a user account with access to the Docker daemon.

## Quick start

```bash
git clone https://github.com/646826/docker-compose-files.git
cd docker-compose-files
make init
make up
```

`make init`:

1. creates `.env` from `.env.example` when the file does not exist;
2. creates only missing files under `.secrets/`;
3. does not replace existing settings or passwords;
4. generates a cost-12 bcrypt record for Traefik and a SHA512-PBKDF2 password record with 220000 iterations for Mosquitto through pinned official images; plaintext is not passed as a process argument;
5. writes generated raw secrets without a trailing newline so file-backed tokens can be used safely in HTTP headers.

`make up` starts the equivalent of the previous stack: core + monitoring + Portainer.

## Default endpoints

| Service | Address | Started by |
| --- | --- | --- |
| Traefik dashboard | `http://traefik.localhost/dashboard/` | always |
| whoami | `http://whoami.localhost` | always |
| InfluxDB | `http://influxdb.localhost` | `make up` / `make monitoring` |
| Grafana | `http://grafana.localhost` | `make up` / `make monitoring` |
| Portainer | `http://portainer.localhost` | `make up` / `make tools` |
| Netdata | `http://localhost:${NETDATA_PORT}` (`19999` by default) | `make full` / `make netdata` |
| openHAB | `http://openhab.localhost` | `make full` / `make iot` |
| Mosquitto | `mqtt://localhost:1883` | `make full` / `make iot` |
| Homepage | `http://homepage.localhost` | `make apps` / `make full` |
| Dozzle | `http://dozzle.localhost` | `make apps` / `make full` |
| AdGuard Home admin | `http://adguard.localhost` | `make dns` / `make full` |
| AdGuard Home setup wizard | `http://127.0.0.1:${ADGUARD_SETUP_PORT}` (`3000` by default) | `make dns` / `make full` |
| Diun | log-based notifier, no web UI | `make updates` / `make full` |

The domain, bind addresses, HTTP port, MQTT port, Netdata port, and time zone are configured in `.env`. `HTTP_HOST_IP` and `MQTT_HOST_IP` default to `0.0.0.0`; set them to `127.0.0.1` to publish the corresponding port only on the local host. `NETDATA_PORT` defaults to `19999`; Netdata uses host networking, so choose another free port when that listener is already occupied. `HOMELAB_PROJECT_NAME` sets the common prefix for the project, networks, and volumes; the default `homelab` preserves the previous names. For access from another computer, configure local DNS or hosts-file entries for the selected `BASE_DOMAIN`.

## Commands

| Command | Purpose |
| --- | --- |
| `make help` | show available commands |
| `make init` | create local configuration and missing secrets |
| `make core` | start Traefik, the socket proxy, and whoami |
| `make up` | start core + monitoring + Portainer |
| `make full` | start all persistent services, including Netdata, Mosquitto, and openHAB |
| `make monitoring` | start core + InfluxDB + Telegraf + Grafana |
| `make netdata` | start only Netdata for host monitoring |
| `make tools` | start core + Portainer |
| `make iot` | start core + Mosquitto + openHAB |
| `make apps` | start core + the Homepage dashboard and Dozzle log viewer |
| `make dns` | start core + AdGuard Home network DNS |
| `make updates` | start core + the Diun image update notifier |
| `make k6` | run a bounded 10-second smoke test |
| `make pull` | pull the selected versions of all images |
| `make ps` | show containers from all profiles |
| `make logs` | follow logs |
| `make check` | run local static, behavior, shell, and Compose checks |
| `make check-images` | verify registry tags and manifests for `amd64`/`arm64` |
| `make check-runtime` | start an isolated default stack and verify routes, authentication, provisioning, and metrics |
| `make check-iot-runtime` | start an isolated IoT stack and verify MQTT authentication, persistence, and openHAB readiness |
| `make check-optional-runtime` | start isolated Netdata and k6 checks without using deployment configuration |
| `make backup` | create an atomic, verified cold snapshot of existing named volumes |
| `make verify-backup BACKUP=...` | verify the manifest, checksums, and tar safety offline |
| `make restore BACKUP=...` | restore a snapshot into missing or empty volumes for the current project name |
| `make check-backup-runtime` | run a disposable backup, verification, and restore round trip |
| `make down` | stop the project while preserving volumes |

## Credentials

No production passwords or tokens are stored in Git. Local values are kept under `.secrets/`:

| Service | User | Password or token |
| --- | --- | --- |
| Traefik and whoami | `TRAEFIK_USERNAME` from `.env` | `.secrets/traefik_password` |
| Grafana | `GRAFANA_ADMIN_USER` from `.env` | `.secrets/grafana_admin_password` |
| InfluxDB | `.secrets/influxdb_username` | `.secrets/influxdb_password`, `.secrets/influxdb_token` |
| Mosquitto | `MOSQUITTO_USERNAME` from `.env` | `.secrets/mosquitto_password` |
| Portainer | set in the first-run wizard | stored in the Portainer volume |

The `.secrets/` directory has mode `0700`. Plaintext files needed only by the operator have mode `0600`. Sources for file-backed Compose secrets have mode `0644` because Compose bind-mounts them without UID/GID remapping; the private parent directory still prevents other host users from accessing the files. Each container receives only the secrets explicitly assigned to it.

Raw password and token files are created without trailing CR/LF bytes. This matters for `.secrets/influxdb_token`: the Telegraf Docker secret store reads the file bytes directly, so a newline would become part of the HTTP `Authorization` header. On the next `make init`, an old token created by a previous script version is normalized by removing only a trailing LF or CRLF; the token value itself is not rotated.

For Mosquitto, `.secrets/mosquitto_passwords` contains only a SHA512-PBKDF2 hash with 220000 iterations. At container startup, it is copied from the read-only Compose secret into a private `tmpfs`, assigned UID/GID `1883` and mode `0600`; the original plaintext remains only in `.secrets/mosquitto_password`.

The MQTT listener requires a password, but the default port `1883` does not use TLS. Keep it on a trusted local network. For transport across an untrusted network, add a deployment-specific TLS listener on `8883` and do not expose the plaintext listener externally.

Example of reading a local password:

```bash
cat .secrets/grafana_admin_password
```

After the first `make init`, do not change `INFLUXDB_USERNAME`, `TRAEFIK_USERNAME`, or `MOSQUITTO_USERNAME` independently of the credentials already created. The script rejects this mismatch instead of silently creating a broken pair. For a completely new deployment, remove only the corresponding local secret files and run `make init` again. For a running or migrated service, rotate the account through the application first.

Do not add `.env` or `.secrets/` to Git, backups, or logs without encryption.

## Profiles and architecture

- **Core, without a profile:** `docker-socket-proxy`, Traefik, whoami.
- **`monitoring`:** InfluxDB, Telegraf, Grafana.
- **`netdata`:** Netdata with access to Linux host data.
- **`tools`:** Portainer.
- **`iot`:** Mosquitto 2.1 with password-file and SQLite plugins, plus openHAB.
- **`test`:** disposable k6.
- **`apps`:** Homepage dashboard and Dozzle log viewer.
- **`dns`:** AdGuard Home network DNS filtering.
- **`updates`:** Diun image update notifier.

Networks are separated by purpose. With the default `HOMELAB_PROJECT_NAME=homelab`, their names remain unchanged:

- `homelab_proxy` — HTTP applications behind Traefik;
- `homelab_backend` — private metrics backend;
- `homelab_socket` — private access to the Docker API proxy;
- `homelab_iot` — Mosquitto and openHAB.

## Pinned versions

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
| Homepage | `1.13.2` |
| Dozzle | `10.7.1` |
| Diun | `4.33.0` |
| AdGuard Home | `0.107.78` |

Renovate proposes updates in separate pull requests; updates are not applied automatically.

## Data and backups

State is stored in named volumes with a prefix derived from `HOMELAB_PROJECT_NAME`; the default remains `homelab_`. `make down` does not remove them.

Before updating stateful services, run `make down` and then `make backup`. A snapshot is published atomically only after its manifest, SHA-256 checksums, and the safe structure of every tar archive have been verified. Run offline verification with `make verify-backup BACKUP=backups/<snapshot-id>`. For recovery, restoring side by side under a separate `HOMELAB_PROJECT_NAME` is recommended.

The complete procedure, confidentiality model, and rollback guidance are documented in [`docs/BACKUP.md`](docs/BACKUP.md). Migration from the legacy bind-mount layout is documented in [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Important limitations

### Netdata

For complete Linux host monitoring, Netdata uses host networking and PID namespace, `SYS_PTRACE`, `SYS_ADMIN`, read-only host mounts, and the Docker socket. It therefore has a separate opt-in `netdata` profile, is not started by the ordinary `make up` command, and is exposed directly on `NETDATA_PORT` (`19999` by default).

### Portainer

Portainer is intended to administer the Docker host and therefore mounts the Docker socket directly. Do not publish it to the Internet, and restrict access to a trusted network.

### openHAB

For the MQTT Binding, configure the internal broker `mosquitto:1883`, the `MOSQUITTO_USERNAME` user from `.env`, and the password from `.secrets/mosquitto_password`. This address works inside the Compose network and does not depend on the published host port.

The bridge network and Traefik provide a portable, secure default. Some bindings that use UPnP, multicast, or USB devices require host networking, additional capabilities, or `devices`. Add those through a local override file only for the specific hardware.

### TLS

The local default uses HTTP and `*.localhost`. Automatic public TLS is not enabled because it requires a real domain, DNS, and a selected ACME challenge. Add it through a deployment-specific override instead of storing a fictitious universal configuration.

### Homepage

`HOMEPAGE_ALLOWED_HOSTS` includes the routed hostname plus `localhost` and `127.0.0.1` for health probes. The dashboard is served behind the shared Traefik Basic Auth like whoami, and its title is configured through `HOMEPAGE_TITLE` in `.env`.

### Dozzle

Dozzle reads container logs through the socket proxy only; the proxy now also exposes the read-only `LOGS` and `IMAGES` API sections, and no write API is available. Analytics are disabled through `DOZZLE_NO_ANALYTICS`, and the log verbosity is configured through `DOZZLE_LOG_LEVEL`.

### Diun

Diun is notification-only by design. It cannot update containers because the socket proxy has POST disabled. Apply updates with `make pull` and a restart, or review Renovate pull requests. Tune `DIUN_SCHEDULE` (a six-field cron expression, `0 0 6 * * *` by default) and add `DIUN_NOTIF_*` variables in `.env` for alerts.

### AdGuard Home

The first-run wizard is published on `127.0.0.1:${ADGUARD_SETUP_PORT}` (`3000` by default); after setup the admin UI is served through Traefik on `adguard.${BASE_DOMAIN}` with AdGuard's own login. Only the `NET_BIND_SERVICE` capability is added on top of `cap_drop: ALL`; DNS on port 53 (TCP and UDP) binds through `DNS_HOST_IP` and `DNS_PORT`. Set `DNS_HOST_IP=127.0.0.1` to keep DNS local-only.

### Traefik middlewares

Every router on the `web` entrypoint now receives security headers, a per-source-IP rate limit (average 100 requests per second, burst 50), and gzip compression from `config/traefik/dynamic/middlewares.yaml` through the Traefik file provider.

## k3s

k3s does not run inside this Compose project. The reasons and a safe same-host installation option are documented in [`docs/K3S.md`](docs/K3S.md).

## Six verification levels

### 1. Fast configuration check

```bash
make check
```

This runs static policies, unit and behavior tests, shell syntax checks, and validation of the fully merged Compose model. Application containers are not started. The check rejects:

- invalid Compose, JSON, or TOML;
- non-idempotent local credential generation or incorrect permissions;
- newline-terminated raw tokens that cannot be passed safely in HTTP headers;
- missing roadmap services;
- `latest` and implicit image tags;
- known credentials published in earlier revisions;
- destructive host-wide commands;
- Cyrillic text in tracked UTF-8 repository files;
- accidentally tracked `.env` or `.secrets/` files.

### 2. Registry manifest check

```bash
make check-images
```

This retrieves only registry manifests through Docker Buildx; it does not download image layers or start services. The check fails when a tag does not exist or an image does not publish both maintained variants: `linux/amd64` and `linux/arm64`.

### 3. Isolated default-stack runtime check

```bash
make check-runtime
```

This creates a disposable Compose project with unique network and resource names, replaces InfluxDB, Grafana, and Portainer data with `tmpfs`, publishes Traefik only on a random `127.0.0.1` port, and starts core + monitoring + Portainer.

The check verifies:

- `401` without Basic Auth and `200` with it for whoami and the Traefik dashboard;
- InfluxDB and Grafana health endpoints;
- the Portainer status endpoint;
- the provisioned InfluxDB datasource in Grafana;
- a real `system` measurement produced by Telegraf in InfluxDB;
- guaranteed scoped cleanup that removes only disposable runtime volumes.

The check downloads missing image layers and takes noticeably longer. It does not start Netdata, Mosquitto, openHAB, or k6, and does not read deployment `.env` or `.secrets/`.

### 4. Isolated IoT runtime check

```bash
make check-iot-runtime
```

This creates a separate `homelab-iot-runtime-*` project, publishes HTTP and MQTT only on random loopback ports, starts core plus the `iot` profile, and uses the official Mosquitto image for short-lived client containers through Linux host networking.

The check verifies:

- rejection of anonymous MQTT publish operations;
- an authenticated QoS 1 retained publish and exact payload retrieval through subscribe;
- retained-payload persistence after `restart mosquitto`, which verifies SQLite persistence on a project-scoped volume;
- openHAB readiness through its Traefik hostname;
- absence of the MQTT password from process arguments and guaranteed scoped cleanup.

The check downloads missing Mosquitto and openHAB layers and is intended only for Linux Docker Engine. It does not install the openHAB MQTT Binding, complete the setup wizard, or test UPnP, multicast, USB, or other hardware.

### 5. Isolated backup/restore runtime check

```bash
make check-backup-runtime
```

This creates unique disposable local volumes containing nested text and binary files, an empty file, unusual permissions, and a safe relative symbolic link. It then performs a cold backup, offline verification, source-volume deletion, and a side-by-side restore under a different project name.

The check compares bytes and relevant filesystem metadata, confirms rejection of a tampered snapshot and a non-empty target volume, and then removes only its own fixture resources. It does not start homelab applications or read deployment `.env` or `.secrets/`; the detailed recovery procedure is in [`docs/BACKUP.md`](docs/BACKUP.md).

### 6. Isolated optional-profile runtime check

```bash
make check-optional-runtime
```

This creates a separate `homelab-optional-runtime-*` project, chooses a random free `NETDATA_PORT`, and starts only Netdata plus a direct whoami target for the disposable k6 container.

The check verifies:

- Netdata readiness through its local `/api/v1/info` endpoint;
- a real `system.cpu` data sample collected from the Linux host;
- the committed `config/k6/smoke.js` checks and thresholds against whoami;
- absence of monitoring, tools, and IoT application services;
- guaranteed scoped cleanup of the unique project and its volumes.

The check downloads missing Netdata, whoami, and k6 layers and is intended only for Linux Docker Engine because Netdata uses host networking, the host PID namespace, Linux capabilities, and read-only host mounts. It does not read deployment `.env` or `.secrets/` and does not enroll the temporary agent in Netdata Cloud.
