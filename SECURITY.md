# Security Policy

## Historical credentials

Earlier revisions of this public repository contained reusable passwords and tokens. Treat every credential ever committed to repository history as compromised, even when it is absent from the current tree.

Before exposing any service beyond the local machine:

1. run `make doctor` and resolve blocking findings;
2. run `make init` to generate new local established credentials;
3. follow `docs/MIGRATION.md` when retaining old persistent data;
4. rotate credentials stored inside migrated InfluxDB, Grafana, Portainer, openHAB, Uptime Kuma, AdGuard Home, Authelia, or other application databases;
5. review all listeners, host firewall rules, DNS settings, and reverse-proxy routes.

Deleting a value from the latest commit does not revoke it or remove it from Git history. Rotation is mandatory.

## Local secret handling

- `.env` contains non-secret deployment settings only.
- Generated credentials and rendered authentication configuration live under ignored `.secrets/`.
- `.secrets/` uses mode `0700`; operator-only plaintext files use mode `0600`.
- Some files used as ordinary Compose secret sources use mode `0644` because Compose bind mounts do not remap ownership. Their private parent directory remains inaccessible to other host users.
- Each service receives only explicitly declared secrets.
- Traefik Basic Auth uses bcrypt with cost 12.
- Mosquitto uses SHA512-PBKDF2 with exactly 220000 iterations. Plaintext and confirmation are supplied through standard input, not process arguments.
- Mosquitto copies its hash file into a private runtime `tmpfs`, applies UID/GID `1883` and mode `0600`, and uses the Mosquitto 2.1 password-file plugin.
- Bootstrap and community initialization create only missing files and never silently rotate an active deployment.
- Username drift is rejected where a username and generated credential must remain one pair.
- Do not paste `.env`, `.secrets/`, private domains, access tokens, passwords, TLS keys, ACME state, or restic credentials into issues, logs, screenshots, or unencrypted archives.

## Authentication and Authelia recovery

Community HTTP applications use `AUTH_MIDDLEWARE=local-auth@docker` by default. This retains the established Traefik Basic Auth path during migration.

Authelia is optional and uses:

- file-backed JWT, session, and storage-encryption secrets;
- a generated local users database with a cost-12 bcrypt password hash;
- committed logic but ignored rendered configuration;
- SQLite state in the `authelia_data` named volume;
- Traefik ForwardAuth through the `authelia@docker` middleware.

Before enabling Authelia:

```bash
make auth-init
make auth-check
```

Keep a known-working Basic Auth credential until Authelia login and recovery have been tested. Recovery procedure:

1. set `AUTH_MIDDLEWARE=local-auth@docker` in `.env`;
2. restart the affected community profiles;
3. verify access through Basic Auth;
4. stop the `auth` profile only after access is restored;
5. repair or regenerate only the affected ignored Authelia file, then rerun `make auth-check`.

Never delete `authelia_data` as a first troubleshooting step. Back it up before upgrades. Full guidance is in `docs/AUTHELIA.md`.

## Docker API and privileged interfaces

Most services receive no Docker socket and use `no-new-privileges` where compatible.

- `docker-socket-proxy` mounts the Docker socket read-only and exposes selected read API sections only on the internal `socket` network.
- Traefik and Telegraf use the restricted proxy rather than the raw socket.
- Homepage has no Docker socket and no Docker API endpoint; its configuration is static and read-only.
- Dozzle uses `tcp://docker-socket-proxy:2375`. Container actions and interactive shell access are disabled.
- Portainer mounts the Docker socket directly because full host administration is its stated purpose.
- Netdata uses host networking, the host PID namespace, documented capabilities, host mounts, and a read-only Docker socket for full host observability.

Portainer and Netdata require a trusted host and host-level firewall protection. The socket proxy reduces API exposure but is still security-sensitive; do not attach arbitrary containers to its network.

## AdGuard Home and DNS exposure

AdGuard Home is a guarded module because binding TCP/UDP port `53` can affect the entire network.

- It is never included in `make up`, `make full`, or `make community`.
- Start it only through `make dns`, which first runs the read-only `make dns-preflight` checks.
- Review `DNS_HOST_IP`, `DNS_PORT`, router DHCP settings, upstream resolvers, and rollback before directing clients to it.
- The initial setup port binds to loopback by default.
- Do not expose the plain DNS listener to the public Internet.
- DNS-over-HTTPS, DNS-over-TLS, and DNS-over-QUIC require deliberate certificates, firewall rules, and client configuration.
- Preserve the previous router/client DNS values so rollback does not depend on the new resolver being healthy.

See `docs/ADGUARD.md` before activation.

## MQTT and IoT transport

The default MQTT listener on port `1883` requires authentication but is not encrypted. Keep it on a trusted LAN. For an untrusted network, create a deployment-specific TLS listener, use certificate validation, and firewall the plaintext listener.

Inside Compose, openHAB should use `mosquitto:1883`, the configured `MOSQUITTO_USERNAME`, and the local operator password. Hardware integrations that require multicast, USB devices, host networking, or extra capabilities belong in a local override with only the minimum required access.

## Backups and restic

Local `make backup` snapshots provide integrity verification, not encryption. The snapshot directory can contain complete application state and must be protected like the source host.

Encrypted remote transport uses restic and local files:

- `.secrets/restic_repository`;
- `.secrets/restic_password`;
- optional `.secrets/restic_environment` for provider variables.

The wrapper verifies the local snapshot before upload and does not place repository passwords or provider values in command arguments. Protect remote repository credentials separately from backup media. Test restoration with `make check-remote-backup-runtime` and periodically run `make verify-remote-backup`.

Retention and prune can delete remote data. `make remote-retention` uses an explicit policy and must be run from an administrative context, not from an append-only backup credential. See `docs/REMOTE_BACKUP.md`.

## TLS and public exposure

The default stack enables neither public TLS nor automatic ACME. Certificates, private keys, provider credentials, and ACME state must remain outside Git under ignored operator-controlled paths.

- LAN certificate workflow: `docs/TLS-LAN.md`.
- Public DNS-01 workflow: `docs/TLS-PUBLIC.md`.
- Opt-in override: `examples/tls/compose.tls.yaml`.

Test ACME against staging first, use a least-privilege DNS token, protect the ACME storage file, and preserve a rollback path. Enabling HTTPS does not make an application safe to expose; authentication, updates, firewall scope, and application-specific hardening remain required.

## Container image security and Trivy

All maintained images use explicit versions and are checked for both `linux/amd64` and `linux/arm64`. Renovate opens reviewable update pull requests; running containers are not updated automatically outside Git and CI.

Security commands:

```bash
make scan-images
make sbom
make check-security
```

The repository invokes the pinned `ghcr.io/aquasecurity/trivy:0.70.0` container directly and does not use mutable Trivy setup actions. The Trivy ecosystem experienced a supply-chain compromise in March 2026; the project advisory is recorded at `https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23`. The selected release is separate from the affected releases, but image updates still require ordinary review and verification.

`make check-security` fails for fixable `CRITICAL` vulnerabilities unless an exact image/vulnerability pair has an active exception in `security/exceptions.json`. Every exception must contain:

- vulnerability ID;
- exact image reference;
- accountable owner;
- concrete reason;
- future expiration date.

Expired, duplicated, empty, or malformed exceptions fail the fast validation suite. Exceptions are temporary risk decisions, not permanent suppressions.

CycloneDX documents and vulnerability reports are generated under ignored `sbom/` and `security-reports/` directories. CI artifacts are short-lived and must not contain deployment secrets.

## Backup before dependency updates

Before merging a stateful image update:

1. review upstream release and migration notes;
2. run `make down` for a cold snapshot where required;
3. run `make backup` and `make verify-backup BACKUP=...`;
4. run `make check`, `make check-images`, and the relevant runtime workflow;
5. test restore or rollback on a non-critical project when the data format changes.

Image pinning controls deployment intent; it does not eliminate upstream vulnerabilities or data-format changes.

## Supported deployment

The maintained target is a current Linux Docker Engine with Docker Compose 2.20.3 or newer on `amd64` or `arm64`. Rootless Docker, SELinux, Docker Desktop, NAS vendor wrappers, custom socket locations, and uncommon filesystems may require local overrides and can reduce monitoring or management functionality.

Run `make doctor` before reporting an environment issue and include only redacted output.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, private hostname, IP layout, or personal network details. Contact the repository owner privately or use GitHub private vulnerability reporting when available.

Include:

- affected project version, image, file, or module;
- security impact and realistic prerequisites;
- reproducible steps using redacted values;
- whether the issue affects default or opt-in profiles;
- a proposed mitigation when known.
