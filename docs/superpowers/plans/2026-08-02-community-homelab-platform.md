# Community Homelab Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a modular, recoverable, secure community homelab platform with diagnostics, encrypted remote backup, Uptime Kuma, AdGuard Home, Homepage, Authelia, Dozzle, Trivy/SBOM, TLS recipes, and release automation.

**Architecture:** The root Compose file uses `include` to assemble independently owned service modules while centralizing shared networks, volumes, and secrets. New applications are opt-in profiles. Python standard-library policy and behavior tests run before production changes; GitHub Actions provides real Docker, registry, backup, and security verification.

**Tech Stack:** Docker Compose 2.20.3+, Python 3.11 standard library, POSIX shell, GitHub Actions, Traefik, restic 0.18.1, Uptime Kuma 2.3.2, AdGuard Home 0.107.76, Homepage 1.13.1, Authelia 4.39.19, Dozzle 10.6.2, Trivy 0.70.0.

## Global Constraints

- Preserve the behavior of `make init`, `make up`, `make monitoring`, `make tools`, `make iot`, `make full`, backup, restore, and all existing runtime checks.
- Keep every new user-facing service opt-in.
- Never start AdGuard Home through `make full` or `make community`.
- Keep all image references explicitly versioned and verify `linux/amd64` plus `linux/arm64`.
- Keep application secrets file-backed under `.secrets/`; never pass plaintext passwords in process arguments.
- Keep `make check` free of registry access and application-container startup.
- Use only Python standard library code in repository validation and operator wrappers.
- Preserve existing named network, volume, and secret names for migrated services.
- Do not add Watchtower, public tunnels, a duplicate observability stack, shared PostgreSQL/Redis, or Home Assistant.
- Every runtime workflow must use a unique project name, random loopback ports where possible, bounded waits, failure diagnostics, and scoped cleanup.

---

### Task 1: Define modular Compose and doctor contracts with failing tests

**Files:**
- Create: `scripts/check_modules.py`
- Create: `scripts/test_doctor.py`
- Modify: `scripts/check.sh`
- Modify: `scripts/check_static.py`

**Interfaces:**
- Produces `MODULE_PATHS: tuple[str, ...]`, `parse_compose_version(text: str) -> tuple[int, ...]`, `classify_port(bind_ip: str, port: int, listeners: set[tuple[str, int]]) -> str`, and `DoctorResult` records.

- [ ] Add a module policy requiring root `include` entries for `core`, `monitoring`, `tools`, `iot`, `uptime`, `dns`, `dashboard`, `auth`, and `logs`.
- [ ] Require each module service to have a declared owner profile, explicit image tag, and expected service list.
- [ ] Add doctor unit tests for Compose versions `2.20.2` (unsupported), `2.20.3` (supported), and `v2.38.2` (supported).
- [ ] Add tests for wildcard versus loopback port conflicts and warning/error aggregation.
- [ ] Connect the new policy/tests to `scripts/check.sh` before implementation.
- [ ] Run CI and record the intended RED result for missing modules and `scripts/doctor.py`.

Commit:

```bash
git add scripts/check_modules.py scripts/test_doctor.py scripts/check.sh scripts/check_static.py
git commit -m "test: define modular platform and doctor contracts"
```

### Task 2: Split the existing stack into Compose include modules

**Files:**
- Replace: `compose.yaml`
- Create: `modules/core/compose.yaml`
- Create: `modules/monitoring/compose.yaml`
- Create: `modules/tools/compose.yaml`
- Create: `modules/iot/compose.yaml`
- Create: `modules/uptime/compose.yaml`
- Create: `modules/dns/compose.yaml`
- Create: `modules/dashboard/compose.yaml`
- Create: `modules/auth/compose.yaml`
- Create: `modules/logs/compose.yaml`
- Modify: `scripts/check_runtime.sh`
- Modify: `scripts/check_iot_runtime.sh`
- Modify: `scripts/check_optional_runtime.sh`
- Modify: `.github/workflows/*.yml`

**Interfaces:**
- Root `compose.yaml` owns `name`, `include`, shared networks, shared named volumes, and file-backed secrets.
- Included files own services only.

Root structure:

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

- [ ] Move existing services without changing images, commands, profiles, labels, ports, mounts, health checks, or restart policies.
- [ ] Preserve exact existing network and volume names in the root resource declarations.
- [ ] Add empty, policy-valid new module files containing the new profile services in later tasks; until then each file contains only an explanatory Compose extension key such as `x-module-owner`.
- [ ] Update runtime harnesses to copy `modules/` into their disposable work directories.
- [ ] Add `modules/**` to all relevant workflow path filters.
- [ ] Run `./scripts/check.sh`, all existing runtime workflows, and image-platform verification.

Commit:

```bash
git add compose.yaml modules scripts/check_* .github/workflows
git commit -m "refactor: modularize the Compose application"
```

### Task 3: Implement read-only host diagnostics

**Files:**
- Create: `scripts/doctor.py`
- Modify: `Makefile`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- CLI: `python3 scripts/doctor.py [--strict] [--json]`.
- Make target: `make doctor`.

- [ ] Implement pure version, address, port, memory, disk, environment, and permission classification helpers to satisfy Task 1 tests.
- [ ] Use `docker info`, `docker compose version --short`, `docker ps`, `docker network ls`, and `docker volume ls` through bounded subprocess calls.
- [ ] Parse `/proc/meminfo`, `shutil.disk_usage`, `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, and `/proc/net/udp6` without external packages.
- [ ] Detect port 53 ownership through `ss` when available and report `systemd-resolved` guidance without changing the host.
- [ ] Validate `BASE_DOMAIN`, `HOMELAB_PROJECT_NAME`, configured bind addresses, `.secrets` permissions, and minimum Compose 2.20.3.
- [ ] Add human and JSON output with exit codes: `0` healthy/warnings, `1` blocking error, `2` invalid invocation.
- [ ] Run `python3 scripts/test_doctor.py`, policy checks, and the full fast suite.

Commit:

```bash
git add scripts/doctor.py scripts/test_doctor.py Makefile .env.example README.md
git commit -m "feat: add read-only homelab diagnostics"
```

### Task 4: Add restic remote-backup contracts and implementation

**Files:**
- Create: `scripts/remote_backup.py`
- Create: `scripts/test_remote_backup.py`
- Create: `scripts/check_remote_backup_policy.py`
- Create: `scripts/check_remote_backup_runtime.sh`
- Create: `docs/REMOTE_BACKUP.md`
- Create: `.github/workflows/remote-backup-runtime.yml`
- Modify: `Makefile`
- Modify: `scripts/check.sh`
- Modify: `scripts/check_images.py`
- Modify: `scripts/backup.py`
- Modify: `renovate.json`

**Interfaces:**
- Helper image constant: `RESTIC_IMAGE = "restic/restic:0.18.1"`.
- Commands: `upload`, `snapshots`, `check`, `forget`, `restore-test`.
- Secret files: `.secrets/restic_repository`, `.secrets/restic_password`, optional `.secrets/restic_environment`.

- [ ] Write tests first for strict `KEY=value` environment parsing, duplicate keys, forbidden control characters, missing secrets, snapshot verification ordering, and exact Docker command construction.
- [ ] Require upload to call the existing offline verifier before invoking restic.
- [ ] Mount the selected snapshot read-only at `/snapshot`, restic cache in a named cache volume, and password/repository files as read-only secrets.
- [ ] Implement explicit retention flags `--keep-daily 7 --keep-weekly 5 --keep-monthly 12 --keep-yearly 3` only for the retention command.
- [ ] Add a disposable local-repository runtime test proving upload, list, check, restore, byte equality, wrong-password rejection, and cleanup.
- [ ] Add restic to image-platform and Renovate coverage.
- [ ] Document SFTP, S3-compatible, and rclone repository examples without hard-coding a provider.

Commit:

```bash
git add scripts/remote_backup.py scripts/test_remote_backup.py scripts/check_remote_backup_policy.py scripts/check_remote_backup_runtime.sh docs/REMOTE_BACKUP.md .github/workflows/remote-backup-runtime.yml Makefile scripts/check.sh scripts/check_images.py scripts/backup.py renovate.json
git commit -m "feat: add encrypted remote snapshot backups"
```

### Task 5: Add Uptime Kuma and Homepage

**Files:**
- Modify: `modules/uptime/compose.yaml`
- Modify: `modules/dashboard/compose.yaml`
- Create: `config/homepage/settings.yaml`
- Create: `config/homepage/services.yaml`
- Create: `config/homepage/widgets.yaml`
- Create: `config/homepage/bookmarks.yaml`
- Create: `scripts/check_community_services.py`
- Create: `scripts/test_community_runtime.py`
- Create: `scripts/check_community_runtime.sh`
- Create: `.github/workflows/community-runtime.yml`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Images: `louislam/uptime-kuma:2.3.2`, `ghcr.io/gethomepage/homepage:v1.13.1`.
- Profiles: `uptime`, `dashboard`.
- Routes: `uptime.${BASE_DOMAIN}`, `home.${BASE_DOMAIN}`.
- Volumes: `uptime_kuma_data`.

- [ ] Add policy tests requiring pinned images, profile isolation, Traefik routes, `AUTH_MIDDLEWARE`, no Docker socket for Homepage, and backup inventory coverage.
- [ ] Implement both services with `no-new-privileges`, bounded health checks, and explicit networks.
- [ ] Keep Homepage configuration static and mount it read-only.
- [ ] Add dashboard links for all maintained services without embedding credentials or API keys.
- [ ] Add `make uptime`, `make dashboard`, and the partial `make community` command.
- [ ] Runtime-test anonymous/authenticated Traefik behavior, both health endpoints, expected service scope, and persistence metadata.

Commit:

```bash
git add modules/uptime modules/dashboard config/homepage scripts/check_community_services.py scripts/test_community_runtime.py scripts/check_community_runtime.sh .github/workflows/community-runtime.yml Makefile README.md scripts/backup.py
git commit -m "feat: add uptime monitoring and service dashboard"
```

### Task 6: Add guarded AdGuard Home DNS

**Files:**
- Modify: `modules/dns/compose.yaml`
- Create: `scripts/dns_preflight.py`
- Create: `scripts/test_dns_preflight.py`
- Create: `docs/ADGUARD.md`
- Modify: `Makefile`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `scripts/backup.py`

**Interfaces:**
- Image: `adguard/adguardhome:v0.107.76`.
- Profile: `dns`.
- Variables: `DNS_HOST_IP`, `DNS_PORT`, `ADGUARD_SETUP_HOST_IP`, `ADGUARD_SETUP_PORT`.
- Volumes: `adguard_work`, `adguard_config`.
- Commands: `make dns-preflight`, `make dns`.

- [ ] Write tests for TCP/UDP port conflicts, wildcard binds, `systemd-resolved`, invalid addresses, and exact remediation messages.
- [ ] Implement a read-only preflight; `make dns` must depend on it.
- [ ] Publish TCP and UDP 53 only through explicit environment settings and bind the setup UI to loopback by default.
- [ ] Keep the service out of `make full` and `make community`; add a static policy rejecting either inclusion.
- [ ] Document first-run setup, router/DHCP changes, rollback, DNS encryption, and same-domain advertising limitations.
- [ ] Add volumes to backup inventory and tests.

Commit:

```bash
git add modules/dns scripts/dns_preflight.py scripts/test_dns_preflight.py docs/ADGUARD.md Makefile .env.example README.md scripts/backup.py
git commit -m "feat: add guarded network-wide DNS filtering"
```

### Task 7: Add Authelia and explicit authentication switching

**Files:**
- Modify: `modules/auth/compose.yaml`
- Create: `config/authelia/configuration.template.yml`
- Create: `scripts/render_authelia_config.py`
- Create: `scripts/test_authelia_config.py`
- Modify: `scripts/init.sh`
- Modify: `scripts/test_init.py`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Image: `authelia/authelia:4.39.19`.
- Profile: `auth`.
- Middleware selector: `AUTH_MIDDLEWARE=local-auth@docker` or `authelia@docker`.
- Route: `auth.${BASE_DOMAIN}`.
- Volume: `authelia_data`.

- [ ] Write tests first for domain validation, template rendering, secret-file permissions, idempotency, username drift, and a cost-12 bcrypt user record.
- [ ] Extend `make init` to create Authelia plaintext/operator secrets and `authelia_users.yml` without rotating existing values.
- [ ] Render runtime configuration atomically from the committed template and validated `.env` values.
- [ ] Configure file users, SQLite storage, filesystem notifier, one-factor default rules, and ForwardAuth response headers.
- [ ] Use `AUTH_MIDDLEWARE` for Uptime Kuma, Homepage, and Dozzle while keeping Basic Auth as the default.
- [ ] Add `make auth` and document enabling, TOTP enrollment, rollback, and recovery.
- [ ] Runtime-test portal readiness and ForwardAuth redirect/allow behavior using disposable credentials.

Commit:

```bash
git add modules/auth config/authelia scripts/render_authelia_config.py scripts/test_authelia_config.py scripts/init.sh scripts/test_init.py compose.yaml .env.example Makefile README.md
git commit -m "feat: add optional Authelia single sign-on"
```

### Task 8: Add read-only Dozzle logs

**Files:**
- Modify: `modules/logs/compose.yaml`
- Modify: `scripts/check_community_services.py`
- Modify: `scripts/check_community_runtime.sh`
- Modify: `Makefile`
- Modify: `README.md`

**Interfaces:**
- Image: `amir20/dozzle:v10.6.2`.
- Profile: `logs`.
- Route: `logs.${BASE_DOMAIN}`.
- Docker endpoint: `tcp://docker-socket-proxy:2375`.

- [ ] Add failing policy assertions rejecting a Docker socket mount, enabled actions, enabled shell, analytics, and missing authentication middleware.
- [ ] Implement Dozzle with `DOZZLE_REMOTE_HOST`, `DOZZLE_NO_ANALYTICS=true`, and no local socket mount.
- [ ] Add `make logs` and complete `make community` with profiles `uptime`, `dashboard`, `auth`, and `logs` only.
- [ ] Runtime-test UI readiness through Traefik and prove the service can list the disposable containers through the proxy.

Commit:

```bash
git add modules/logs scripts/check_community_services.py scripts/check_community_runtime.sh Makefile README.md
git commit -m "feat: add protected read-only container logs"
```

### Task 9: Add TLS deployment recipes

**Files:**
- Create: `docs/TLS-LAN.md`
- Create: `docs/TLS-PUBLIC.md`
- Create: `examples/tls/compose.tls.yaml`
- Create: `examples/tls/traefik-dynamic.template.yaml`
- Create: `scripts/check_tls_examples.py`
- Modify: `scripts/check.sh`
- Modify: `README.md`

**Interfaces:**
- Examples are opt-in overrides and never loaded by root Compose.

- [ ] Add policy tests rejecting tracked certificate/key material, real domains, provider credentials, and enabled public exposure in the default stack.
- [ ] Document local CA creation, trust distribution, file permissions, renewal, and rollback.
- [ ] Document public DNS, DNS-01 staging, provider-specific file secrets, certificate backup, and rate-limit-safe promotion.
- [ ] Validate example YAML and ensure every certificate/key path points outside tracked files.

Commit:

```bash
git add docs/TLS-LAN.md docs/TLS-PUBLIC.md examples/tls scripts/check_tls_examples.py scripts/check.sh README.md
git commit -m "docs: add safe LAN and public TLS recipes"
```

### Task 10: Add Trivy scanning, SBOM, and expiring exceptions

**Files:**
- Create: `scripts/security.py`
- Create: `scripts/test_security.py`
- Create: `security/exceptions.json`
- Create: `.github/workflows/security.yml`
- Modify: `Makefile`
- Modify: `scripts/check.sh`
- Modify: `scripts/check_images.py`
- Modify: `renovate.json`
- Modify: `README.md`

**Interfaces:**
- Image: `aquasec/trivy:0.70.0`.
- Commands: `make scan-images`, `make sbom`, `make check-security`.
- Exception fields: `id`, `image`, `reason`, `owner`, `expires`.

- [ ] Write tests first for image discovery, command construction, exception schema, duplicate IDs, invalid dates, and expired exceptions.
- [ ] Invoke the pinned Trivy container directly, never a mutable GitHub Action tag.
- [ ] Generate one CycloneDX JSON file per rendered image and one summarized vulnerability JSON report.
- [ ] Fail on fixable `CRITICAL` vulnerabilities not covered by a non-expired exact exception.
- [ ] Upload reports only as short-retention workflow artifacts.
- [ ] Add the scanner image to multi-architecture and Renovate checks.

Commit:

```bash
git add scripts/security.py scripts/test_security.py security/exceptions.json .github/workflows/security.yml Makefile scripts/check.sh scripts/check_images.py renovate.json README.md
git commit -m "feat: add pinned image security scans and SBOMs"
```

### Task 11: Add release management and complete documentation

**Files:**
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Create: `.github/workflows/release.yml`
- Create: `docs/MODULES.md`
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `renovate.json`

**Interfaces:**
- Initial community-platform release: `2.0.0` / tag `v2.0.0`.

- [ ] Document module lifecycle, support level, ports, volumes, secrets, commands, elevated permissions, and runtime coverage.
- [ ] Add a tag workflow that requires `v${VERSION}`, runs `./scripts/check.sh`, and creates release notes with `gh release create`.
- [ ] Add a changelog section covering modularization, diagnostics, remote backup, community services, authentication, DNS, security scanning, and migration.
- [ ] Update security guidance for Authelia recovery, DNS exposure, Dozzle proxy access, restic secrets, and Trivy's 2026 supply-chain incident.
- [ ] Ensure Renovate covers every helper image constant and all module Compose files.

Commit:

```bash
git add VERSION CHANGELOG.md .github/workflows/release.yml docs/MODULES.md README.md SECURITY.md renovate.json
git commit -m "docs: prepare the modular platform release"
```

### Task 12: Final verification, review, merge, and release

**Files:**
- Modify only files required by concrete verification or review findings.

- [ ] Run the complete fast suite on one exact head.
- [ ] Require successful workflows: CI, Image platforms, Runtime smoke, IoT runtime smoke, Optional runtime smoke, Backup runtime, Remote backup runtime, Community runtime, Security.
- [ ] Review the complete diff for credentials, mutable image tags, direct Docker sockets outside explicitly documented host-management services, hidden public exposure, unbounded commands, missing backup inventory, and temporary workflows/scripts.
- [ ] Request an independent code review; resolve all Critical and Important findings.
- [ ] Mark the PR ready only after all final-head checks pass.
- [ ] Squash merge with `expected_head_sha` into `main`.
- [ ] Verify the squash SHA is the newest `main` commit.
- [ ] Create tag `v2.0.0`, verify the release workflow succeeds, and confirm the GitHub release exists.
