# Module Catalog

The root `compose.yaml` assembles the application with Docker Compose `include`. Each file under `modules/<name>/compose.yaml` owns only its services. Shared networks, named volumes, and Compose secret declarations remain in the root file so resource names stay stable across upgrades.

## Support levels

- **Established:** migrated from the original maintained stack; existing commands and resource names are compatibility contracts.
- **Community:** fully integrated, version-pinned, documented, included in image-platform checks, and covered by repository policy or a real runtime workflow.
- **Guarded:** supported, but deliberately requires a separate operator action because enabling it can affect the whole network.
- **Advanced:** supported and validated, but requires the operator to understand authentication, recovery, and domain implications before enabling it.

## Module matrix

| Module | Support level | Profile | Services | Primary command | Default route or listener | Persistent volumes | Secrets | Elevated access | Runtime verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `core` | Established | none | Docker socket proxy, Traefik, whoami | `make core` | `traefik.${BASE_DOMAIN}`, `whoami.${BASE_DOMAIN}`, host HTTP port | none | Traefik users file | socket proxy mounts the Docker socket read-only; Traefik receives only the proxy endpoint | `make check-runtime`, IoT, community, and Auth runtime workflows |
| `monitoring` | Established | `monitoring` | InfluxDB, Telegraf, Grafana | `make monitoring` | `influxdb.${BASE_DOMAIN}`, `grafana.${BASE_DOMAIN}` | `influxdb_data`, `influxdb_config`, `grafana_data` | InfluxDB username/password/token; Grafana admin password | Telegraf mounts host files read-only and receives selected socket-proxy APIs | `make check-runtime` |
| `tools` | Established | `tools` | Portainer | `make tools` | `portainer.${BASE_DOMAIN}` | `portainer_data` | application-managed first-run account | direct Docker socket because full host administration is its purpose | `make check-runtime` |
| `iot` | Established | `iot` | Eclipse Mosquitto, openHAB | `make iot` | MQTT host listener; `openhab.${BASE_DOMAIN}` | `mosquitto_data`, `openhab_addons`, `openhab_conf`, `openhab_userdata` | Mosquitto SHA512-PBKDF2 password file | optional local hardware overrides may add devices or host networking | `make check-iot-runtime` |
| `uptime` | Community | `uptime` | Uptime Kuma | `make uptime` | `uptime.${BASE_DOMAIN}` | `uptime_kuma_data` | protected by selected Traefik middleware | none | `make check-community-runtime` |
| `dns` | Guarded | `dns` | AdGuard Home | `make dns` | TCP/UDP `${DNS_PORT:-53}` and loopback setup port `${ADGUARD_SETUP_PORT:-3000}` | `adguard_work`, `adguard_config` | application-managed first-run account | binds a host DNS listener and can affect every client using that resolver | `make dns-preflight`, static policy, image-platform check |
| `dashboard` | Community | `dashboard` | Homepage | `make dashboard` | `home.${BASE_DOMAIN}` | none; configuration is committed and read-only | protected by selected Traefik middleware | no Docker socket or Docker API endpoint | `make check-community-runtime`; protected-route integration also covered by `make check-auth-runtime` |
| `auth` | Advanced | `auth` | Authelia | `make auth` | `auth.${BASE_DOMAIN}` and `authelia@docker` ForwardAuth middleware | `authelia_data` | JWT, session, storage key, configuration, and users files under `.secrets/` | none | unit/policy checks, `make auth-check`, and real portal/ForwardAuth verification through `make check-auth-runtime` |
| `logs` | Community | `logs` | Dozzle | `make dozzle` | `logs.${BASE_DOMAIN}` | none | protected by selected Traefik middleware | read-only selected Docker APIs through the socket proxy; actions and shell are disabled | `make check-community-runtime` |

## Shared lifecycle commands

```bash
make init                 # established local settings and secrets
make doctor               # read-only host and configuration diagnosis
make up                   # established core + monitoring + Portainer scope
make full                 # established persistent stack only
make community            # Uptime Kuma + Homepage + Dozzle; Authelia only when selected
make dns-preflight        # DNS listener check with no host mutation
make dns                  # explicit AdGuard Home activation after preflight
make down                 # stop every locally configured profile while preserving named volumes
```

`make full` and `make community` never include `--profile dns`. AdGuard Home must always be activated through `make dns` so a port conflict or `systemd-resolved` listener cannot be bypassed accidentally.

General commands such as `make config`, `make pull`, `make ps`, `make logs`, and `make down` include the `auth` profile only after `.secrets/authelia_configuration.yml` exists. This preserves first-run usability while still managing Authelia after initialization.

## Authentication selection

The default remains:

```dotenv
AUTH_MIDDLEWARE=local-auth@docker
```

This protects Uptime Kuma, Homepage, Dozzle, and the AdGuard web route with the existing Traefik Basic Auth middleware. To enable Authelia:

```bash
make auth-init
make auth-check
make check-auth-runtime
# Set AUTH_MIDDLEWARE=authelia@docker in .env
make community
```

`make check-auth-runtime` uses a disposable normal domain, creates isolated credentials and configuration, validates them with the pinned Authelia image, starts core + Homepage + Authelia, verifies the portal through Traefik, and proves that the protected Homepage route redirects to Authelia. It never reads deployment `.env` or `.secrets/`.

Rollback is immediate: restore `AUTH_MIDDLEWARE=local-auth@docker`, start the affected profiles again, and stop the `auth` profile after confirming access. Full setup and recovery guidance is in [`AUTHELIA.md`](AUTHELIA.md).

## Persistent data and recovery

The verified backup inventory includes every named application volume listed above, including Uptime Kuma, AdGuard Home, and Authelia. Homepage and Dozzle are stateless. Local snapshots are documented in [`BACKUP.md`](BACKUP.md); encrypted off-host transport is documented in [`REMOTE_BACKUP.md`](REMOTE_BACKUP.md).

Always create and verify a snapshot before upgrading a stateful service:

```bash
make down
make backup
make verify-backup BACKUP=backups/<snapshot-id>
```

## Adding a module

A maintained module must satisfy all of these requirements:

1. one owner directory at `modules/<name>/compose.yaml`;
2. an explicit image version, never `latest` or an implicit tag;
3. an opt-in profile unless the service is part of `core`;
4. `no-new-privileges` wherever the image supports it;
5. the smallest necessary networks, mounts, capabilities, and API permissions;
6. a bounded health check for long-running HTTP applications;
7. all named volumes declared in the root and included in verified backup inventory;
8. file-backed secrets declared in the root and ignored by Git;
9. `linux/amd64` and `linux/arm64` image-manifest verification;
10. Renovate discovery, operator documentation, static policy, and behavior or runtime verification;
11. no change to the default `make up`, `make full`, or `make community` scope unless the release explicitly documents that compatibility change.

## Verification ownership

| Verification | Modules covered |
| --- | --- |
| `make check` | all modules, configuration, policies, unit tests, secrets, shell syntax, and merged Compose model |
| `make check-images` | every service image plus bootstrap, backup, restic, and Trivy helper images |
| `make check-runtime` | `core`, `monitoring`, `tools` |
| `make check-iot-runtime` | `core`, `iot` |
| `make check-optional-runtime` | Netdata and k6 from `monitoring` |
| `make check-community-runtime` | `core`, `uptime`, `dashboard`, `logs` |
| `make check-auth-runtime` | `core`, `dashboard`, `auth`; validates the portal and Traefik ForwardAuth redirect |
| `make check-backup-runtime` | local snapshot, verification, and restore engine |
| `make check-remote-backup-runtime` | encrypted restic backup, check, restore, and wrong-password rejection |
| `make check-security` | every maintained service and helper image |
