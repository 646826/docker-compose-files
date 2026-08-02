# Changelog

All notable changes to this repository are documented in this file.

The project uses semantic versioning for tagged community-platform releases. Container image updates remain reviewable pull requests and do not independently change the project version.

## [2.0.0] - 2026-08-02

### Added

- Modular Compose assembly through the root `include` list and nine independently owned modules.
- Read-only `make doctor` diagnostics for Docker, Compose, resources, configuration, permissions, and conflicting listeners.
- Remote backup transport through encrypted restic repositories, including explicit retention and a real backup/check/restore runtime test.
- Uptime Kuma as an opt-in availability-monitoring profile.
- Homepage as a static, authenticated service dashboard without Docker socket access.
- Guarded AdGuard Home deployment with TCP/UDP DNS preflight and explicit operator activation.
- Optional Authelia authentication with file-backed secrets, local users, SQLite storage, configuration validation, a real portal/ForwardAuth runtime test, and a Basic Auth rollback path.
- Protected Dozzle log viewing through the restricted Docker socket proxy, with actions and shell access disabled.
- Separate LAN and public TLS deployment recipes that keep certificates, keys, DNS credentials, and ACME state outside Git.
- Pinned Trivy container scanning, CycloneDX SBOM generation, fixable-CRITICAL enforcement, and expiring exact-image exceptions.
- Community-service, Auth, remote-backup, image-platform, security, and existing stack runtime workflows.
- Module catalog, security guidance, release policy, and operator commands for all optional components.

### Changed

- The previous monolithic Compose service definition is now split into `modules/` while preserving the default `make up` service scope, established network names, established volume names, and existing operator commands.
- The Uptime Kuma default uses the pinned `2.4.0-slim` image, retaining SQLite and ordinary monitor types while excluding embedded MariaDB and Chromium from the default attack surface.
- Verified local backups now include persistent Uptime Kuma, AdGuard Home, and Authelia data.
- `make full` remains limited to the established persistent stack and intentionally excludes DNS and community web applications.
- Image-platform verification now covers community services, restic, and the pinned Trivy scanner on both `linux/amd64` and `linux/arm64`.

### Security

- Community web applications remain behind Traefik authentication by default.
- Homepage receives no Docker API access.
- Dozzle uses the read-only socket proxy instead of mounting the Docker socket directly.
- AdGuard Home never starts implicitly and requires a successful host-listener preflight.
- Restic repository and password values are read from local files, not command-line values.
- Trivy is invoked directly through a pinned immutable release image; mutable setup actions are not used.

### Compatibility

- Requires Docker Compose 2.20.3 or newer for top-level `include` support.
- Maintained container platforms remain `linux/amd64` and `linux/arm64`.
- Existing deployments can keep their current `.env`, established secrets, named volumes, and commands.
- Users who require Uptime Kuma Browser Engine monitors or embedded MariaDB can select the full pinned `2.4.0` image through a local override.

## [1.0.0] - 2026-07-19

### Added

- Secure profile-based homelab stack with Traefik, InfluxDB, Telegraf, Grafana, Portainer, Netdata, Mosquitto, openHAB, k6, verified backups, pinned image checks, and isolated runtime tests.
