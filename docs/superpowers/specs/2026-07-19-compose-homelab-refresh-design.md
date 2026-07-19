# Compose Homelab Refresh Design

## Goal

Modernize the repository into a secure, reproducible Linux homelab for `amd64` and `arm64` while preserving the existing Traefik, InfluxDB, Telegraf, Grafana, and Portainer workflow and completing the explicitly planned Mosquitto, openHAB, Netdata, k6, and k3s work.

## Design principles

1. **Simple default:** `make up` starts the same functional stack as before: reverse proxy, metrics pipeline, dashboards, and Portainer.
2. **Opt-in expansion:** IoT and test workloads use Compose profiles; they do not burden the default deployment.
3. **No committed credentials:** secrets are generated locally, stored under ignored `.secrets/`, and mounted through Compose secrets.
4. **Reproducible releases:** every container image has an explicit stable version; no `latest` tags.
5. **Safe operations:** lifecycle commands affect only this Compose project and never prune the host or delete volumes implicitly.
6. **Portable core:** the default stack runs on Linux Docker Engine on both `amd64` and `arm64`.
7. **No premature platform layer:** k3s is documented separately rather than nested in Docker Compose.

## Architecture

The repository contains one root `compose.yaml` using the current Compose Specification. Services share purpose-specific networks:

- `proxy`: Traefik and HTTP applications.
- `backend`: internal metrics traffic between InfluxDB, Telegraf, and Grafana.
- `socket`: internal access to the read-only Docker API proxy.
- `iot`: Mosquitto and openHAB traffic.

Traefik and a small `whoami` endpoint form the profile-free core. `docker-socket-proxy` mediates read-only Docker API access so Traefik and Telegraf do not mount the Docker socket. Portainer remains opt-in and mounts the socket because host management is its explicit purpose.

## Profiles and compatibility

| Profile | Services | Entry command |
| --- | --- | --- |
| Core (no profile) | docker-socket-proxy, Traefik, whoami | `make core` |
| `monitoring` | InfluxDB, Telegraf, Grafana, Netdata | `make monitoring` |
| `tools` | Portainer | `make tools` |
| `iot` | Mosquitto, openHAB | `make iot` |
| `test` | one-shot k6 smoke test | `make k6` |

`make up` starts core + monitoring + tools, preserving the former operational scope. `make full` additionally starts IoT. `make down` preserves named volumes.

## Security model

- `.env` contains only non-secret settings such as domain, timezone, organization, and bucket names.
- `scripts/init.sh` creates strong random secrets only when files are missing and never overwrites existing credentials.
- Traefik's dashboard is routed through Traefik and protected by Basic Auth; the insecure dashboard port is disabled.
- Docker API access for discovery and metrics is restricted through `docker-socket-proxy` on an internal network.
- Containers use `no-new-privileges`, read-only filesystems, and reduced capabilities where supported.
- Netdata is the documented exception: full host telemetry requires host PID/network access and additional read-only mounts/capabilities. It remains profile-gated.
- Historical committed credentials must be considered compromised and rotated during migration.

## Data and migration

State moves from repository-relative bind mounts to named volumes. This prevents accidental commits and makes lifecycle commands safer. `docs/MIGRATION.md` provides explicit copy commands for existing Grafana, InfluxDB, and Portainer data; migration is never automatic or destructive.

## Service configuration

- InfluxDB remains on the v2 line to retain Flux and existing Grafana/Telegraf behavior.
- Telegraf uses a concise maintained configuration instead of a generated multi-thousand-line sample.
- Grafana provisions the InfluxDB datasource and a small host dashboard from version-controlled files.
- Mosquitto requires authentication and persists data/logs.
- openHAB uses persistent named volumes and Traefik; host networking for discovery-heavy bindings is documented as an optional deployment-specific override.
- k6 is an ephemeral profile and targets the internal `whoami` endpoint by default.
- k3s installation and port coexistence constraints are documented, but it is not a Compose service.

## Validation and maintenance

Local and CI validation must:

1. parse every JSON and TOML configuration;
2. validate the rendered Compose model for all profiles;
3. reject `latest`/implicit image tags, known leaked values, and destructive host-wide commands;
4. ensure required planned services and local-secret declarations remain present;
5. validate shell syntax.

GitHub Actions runs these checks for pushes and pull requests. Renovate tracks container and workflow updates in grouped pull requests.

## Non-goals

This refresh does not add Pi-hole, SmokePing, Home Assistant, PostgreSQL, Airflow, or Adminer because they were comments rather than committed roadmap items. It does not add automatic public TLS, external DNS, Kubernetes manifests, backup orchestration, or an application platform abstraction. Those additions would require deployment-specific decisions and would make the default harder to understand.
