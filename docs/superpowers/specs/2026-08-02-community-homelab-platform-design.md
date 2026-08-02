# Community Homelab Platform Design

## Goal

Turn the repository from one useful homelab stack into a reusable, modular community platform while preserving its safe default behavior.

A new user must still be able to run:

```bash
make init
make up
```

and receive only the existing core, monitoring, and Portainer stack. Every newly added application remains explicit and opt-in.

## Design principles

1. **Safe defaults:** no DNS replacement, public exposure, automatic container update, SSO migration, or remote upload happens implicitly.
2. **Modular ownership:** each service group has one Compose module, one operator command, documentation, static policy, image verification, backup inventory, and a runtime or configuration check.
3. **Git-controlled changes:** images stay pinned; Renovate proposes updates; Dozzle and other tools cannot update containers.
4. **Recoverability first:** persistent state is covered by the existing verified cold-snapshot format before remote transfer is added.
5. **No credential disclosure:** secrets remain local file-backed values and are never embedded in Compose, process arguments, CI output, or tracked files.
6. **Portable support target:** current Linux Docker Engine, Docker Compose 2.20.3 or newer, `linux/amd64`, and `linux/arm64`.
7. **No service duplication:** the project keeps InfluxDB/Telegraf/Grafana/Netdata rather than adding a second observability stack, and keeps openHAB rather than starting two home-automation platforms by default.

## Architecture

### Root application

The root `compose.yaml` becomes a small composition manifest using the Docker Compose top-level `include` feature:

```yaml
name: ${HOMELAB_PROJECT_NAME:-homelab}

include:
  - modules/core/compose.yaml
  - modules/monitoring/compose.yaml
  - modules/tools/compose.yaml
  - modules/iot/compose.yaml
  - modules/uptime/compose.yaml
  - modules/dns/compose.yaml
  - modules/dashboard/compose.yaml
  - modules/auth/compose.yaml
  - modules/logs/compose.yaml
```

Shared networks, volumes, and secrets are declared in the root file. Included services reference these resources from the final application model. `docker compose config` is the acceptance test for this cross-module contract.

### Module ownership

| Module | Services | Profiles |
| --- | --- | --- |
| `core` | Docker socket proxy, Traefik, whoami | always enabled |
| `monitoring` | InfluxDB, Telegraf, Grafana, Netdata, k6 | `monitoring`, `netdata`, `test` |
| `tools` | Portainer | `tools` |
| `iot` | Mosquitto, openHAB | `iot` |
| `uptime` | Uptime Kuma | `uptime` |
| `dns` | AdGuard Home | `dns` |
| `dashboard` | Homepage | `dashboard` |
| `auth` | Authelia | `auth` |
| `logs` | Dozzle | `logs` |

Each module file is intentionally small enough to understand without reading another service implementation. Common resources remain centralized so included files do not declare conflicting network or volume keys.

### Module contract

Every persistent or user-facing service must satisfy all applicable rules:

- explicit image version, never `latest`;
- published `linux/amd64` and `linux/arm64` manifests;
- opt-in profile unless it belongs to the existing core/default stack;
- health check when the upstream image provides the required utility or endpoint;
- `restart: unless-stopped` for persistent applications;
- `no-new-privileges` where compatible;
- read-only filesystem where compatible;
- no direct host port unless the protocol requires it;
- Traefik route for web applications;
- authentication middleware for private web applications;
- named volumes included in backup inventory;
- documented first-run behavior and limitations;
- Renovate discovery;
- static policy and behavioral or runtime verification.

## Operator interface

The Makefile remains the stable user interface.

Existing targets keep their meaning. New targets are:

```text
make doctor
make uptime
make dns-preflight
make dns
make dashboard
make auth
make logs
make community
make remote-backup BACKUP=...
make remote-snapshots
make verify-remote-backup
make remote-retention
make check-remote-backup-runtime
make scan-images
make sbom
make check-security
```

`make community` starts core plus Uptime Kuma, Homepage, Authelia, and Dozzle. It does **not** start AdGuard Home because changing DNS infrastructure must remain a deliberate operation.

## `make doctor`

`scripts/doctor.py` is a dependency-free, read-only diagnostic command. It returns non-zero only for blocking errors; warnings are reported but do not fail the command unless `--strict` is supplied.

Checks include:

- operating system and CPU architecture;
- Docker client/daemon and Compose availability;
- Compose version at least 2.20.3;
- writable repository-local configuration paths;
- `.env` and required secret-source presence and permissions;
- free disk space and available memory;
- conflicts on configured HTTP, MQTT, Netdata, DNS, and AdGuard setup ports;
- `systemd-resolved` ownership of port 53;
- selected domain syntax and local hostname resolution;
- existing project containers, networks, and volumes;
- supported versus advisory environments such as rootless Docker, Docker Desktop, SELinux, and non-default socket paths.

The checker exposes pure parsing and classification functions so it can be unit-tested without Docker or privileged host access.

## Remote encrypted backups

The existing backup command remains the only producer of application snapshots. Remote backup never reads live Docker volumes.

Flow:

```text
named volumes
    -> verified cold snapshot
    -> offline snapshot verification
    -> restic encryption/deduplication
    -> configured restic repository
```

Pinned helper image:

```text
restic/restic:0.18.1
```

Configuration is file-backed:

```text
.secrets/restic_repository
.secrets/restic_password
.secrets/restic_environment
```

`restic_environment` is an optional mode-`0600` file containing provider-specific non-command-line environment assignments such as S3 credentials. The wrapper validates key syntax, rejects shell metacharacter evaluation, and passes parsed values directly to the container environment.

Remote commands operate only on an explicitly selected verified snapshot directory. Retention defaults are not executed automatically. The documented example is:

```text
7 daily, 5 weekly, 12 monthly, 3 yearly snapshots
```

but pruning requires an explicit `make remote-retention` invocation.

The runtime test uses a disposable local restic repository and proves init, upload, snapshot listing, integrity check, restore, byte comparison, wrong-password rejection, and cleanup without network credentials.

## Uptime Kuma

Pinned image:

```text
louislam/uptime-kuma:2.3.2
```

The service is available at `uptime.${BASE_DOMAIN}`, protected by the configured Traefik middleware, and stores state in `uptime_kuma_data`.

The repository does not attempt to configure private Uptime Kuma APIs automatically. Documentation provides a concrete monitor checklist for Traefik, Grafana, InfluxDB, Portainer, Netdata, openHAB, Mosquitto TCP, backup push monitors, and certificate expiration.

Runtime verification starts Uptime Kuma in a disposable project, checks its health/readiness endpoint, and verifies persistence across restart where practical.

## AdGuard Home

Pinned image:

```text
adguard/adguardhome:v0.107.76
```

The DNS module is deliberately separate from `make community` and `make full`.

Published ports:

- TCP/UDP `53` through `DNS_HOST_IP` and `DNS_PORT`;
- setup/admin port through loopback-bound `ADGUARD_SETUP_HOST_IP` and `ADGUARD_SETUP_PORT` by default.

Persistent volumes:

```text
adguard_work
adguard_config
```

`make dns-preflight` blocks startup when:

- TCP or UDP port 53 is occupied;
- `systemd-resolved` owns the listener;
- the selected bind address is invalid;
- another project container already publishes the port;
- required host networking assumptions are not met.

The preflight prints exact remediation guidance but never changes resolver configuration. First-run setup remains an explicit browser action. Documentation clearly states DNS blocking limitations, including same-domain advertising.

## Homepage

Pinned image:

```text
ghcr.io/gethomepage/homepage:v1.13.1
```

Homepage uses committed static YAML configuration and no Docker socket by default. It links to the repository services grouped as Monitoring, Infrastructure, Home Automation, and Operations.

The dashboard is routed at `home.${BASE_DOMAIN}` and protected by the selected authentication middleware. Optional Docker discovery is documented as a local override, not enabled in the maintained default.

## Authentication with Authelia

Pinned image:

```text
authelia/authelia:4.39.19
```

Authelia is an opt-in single-node configuration using:

- file-based users;
- SQLite storage;
- filesystem notifications;
- one-factor policy by default, with documented TOTP enrollment;
- Traefik ForwardAuth.

Generated local files:

```text
.secrets/authelia_password
.secrets/authelia_session_secret
.secrets/authelia_storage_encryption_key
.secrets/authelia_jwt_secret
.secrets/authelia_users.yml
```

The bootstrap uses the existing pinned Apache helper to create a cost-12 bcrypt record without exposing the plaintext password in process arguments. A generated runtime configuration derives the cookie domain and portal URL from validated `.env` settings.

`AUTH_MIDDLEWARE` defaults to the existing Basic Auth middleware. An operator enables Authelia protection explicitly by setting:

```dotenv
AUTH_MIDDLEWARE=authelia@docker
```

This preserves current installations and permits rollback by changing one non-secret setting.

## Dozzle

Pinned image:

```text
amir20/dozzle:v10.6.2
```

Dozzle connects to the existing internal Docker socket proxy using:

```text
DOZZLE_REMOTE_HOST=tcp://docker-socket-proxy:2375
```

It does not mount the Docker socket. Container actions and shell access remain disabled. Anonymous analytics are disabled. The route `logs.${BASE_DOMAIN}` uses `AUTH_MIDDLEWARE`.

## TLS guidance

Two separate deployment recipes are added:

1. `docs/TLS-LAN.md` — a local certificate authority, trust distribution, certificate storage outside Git, and a Traefik file-provider override.
2. `docs/TLS-PUBLIC.md` — public DNS, ACME DNS-01, provider-specific credentials as file-backed secrets, staging before production, certificate backup, and rollback.

No universal certificate configuration or DNS provider is enabled in the default stack.

## Security scanning and SBOM

Pinned scanner image:

```text
aquasec/trivy:0.70.0
```

The project uses the container image directly rather than mutable Trivy GitHub Action tags. This avoids the compromised mutable-action path documented in the March 2026 Trivy security advisory.

Commands:

```text
make scan-images
make sbom
make check-security
```

Behavior:

- discover the complete rendered image list, including helper images;
- create per-image CycloneDX JSON SBOMs;
- scan `CRITICAL` and `HIGH` vulnerabilities;
- fail CI only for fixable `CRITICAL` vulnerabilities by default;
- preserve complete reports as short-retention workflow artifacts;
- support an explicit, documented exception file with vulnerability ID, image, reason, owner, and expiration date.

No exception is permanent and expired exceptions fail validation.

## Release management

The repository gains:

```text
VERSION
CHANGELOG.md
.github/workflows/release.yml
```

The first modular community release is `2.0.0`. Tag-triggered release automation runs the fast checks, verifies that the tag equals `VERSION`, and creates GitHub release notes through the preinstalled GitHub CLI. Releases never deploy a host or rotate credentials.

## Testing and CI

The final quality model includes:

1. fast static and behavioral checks;
2. full Compose rendering for every profile;
3. image tag and multi-architecture manifest verification;
4. existing default-stack runtime test;
5. existing IoT runtime test;
6. existing Netdata/k6 runtime test;
7. existing backup/restore runtime test;
8. local-restic backup runtime test;
9. community web-service runtime test;
10. security scan and SBOM workflow.

Runtime tests use unique project names, random loopback ports, disposable credentials, bounded polling, failure diagnostics, and trap-based project-scoped cleanup.

## Migration and compatibility

The modular split must render the same existing services, images, network names, volume names, secrets, ports, profiles, and labels before any new module is enabled.

`make up`, `make monitoring`, `make tools`, `make iot`, `make full`, backup/restore, and all existing runtime workflows retain their interfaces.

The minimum Compose version increases to 2.20.3 because `include` is now required. `make doctor` and `make check` report this explicitly.

## Non-goals

This release does not add Watchtower, automatic application updates, a second metrics/logging/tracing platform, a shared PostgreSQL or Redis instance, public tunnels, automatic router/DHCP changes, automatic DNS replacement, automatic ACME enrollment, or simultaneous openHAB/Home Assistant operation.
