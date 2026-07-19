# Runtime Smoke Tests Design

## Goal

Add a real, isolated runtime smoke test for the legacy-equivalent default stack: Docker socket proxy, Traefik, whoami, InfluxDB, Telegraf, Grafana, and Portainer.

The test must prove more than configuration validity. It must start the containers, wait for readiness, verify routing and authentication, confirm Grafana provisioning, and observe a real Telegraf metric in InfluxDB. It must remain safe to run on a developer workstation that may already host a production copy of the same Compose project.

## Scope

The runtime test covers the services started by `make up`:

- `docker-socket-proxy`;
- `traefik`;
- `whoami`;
- `influxdb`;
- `telegraf`;
- `grafana`;
- `portainer`.

The test does not start the `iot`, `netdata`, or `test` profiles. Mosquitto, openHAB, Netdata, and the existing k6 smoke test remain independent concerns and will be covered by a later, smaller change if needed.

## Architecture

### Isolated Compose project

The base Compose file will keep its normal resource names by default but derive the project, network, and volume prefixes from one optional variable:

```text
HOMELAB_PROJECT_NAME=homelab
```

When the variable is absent, deployed names remain unchanged: `homelab`, `homelab_proxy`, `homelab_backend`, and `homelab_*_data`.

The runtime script generates a unique lowercase project value such as `homelab-runtime-<pid>-<random>`. The same value is used for:

- the top-level Compose project name;
- every explicitly named network;
- every explicitly named volume;
- Traefik's default Docker network setting;
- every `traefik.docker.network` label.

This prevents test containers, networks, and volumes from colliding with a real `homelab` deployment. The implementation must verify the rendered model contains the generated prefix before it starts any container.

### Temporary working directory

`scripts/check_runtime.sh` creates a private temporary directory and copies only the runtime inputs into it:

- `compose.yaml`;
- `compose.runtime.yaml`;
- `config/`;
- a generated `.env`;
- generated test-only `.secrets/` files.

The script never reads, modifies, or reuses the repository's existing `.env` or `.secrets/` directory. Test credentials are disposable and are removed with the temporary directory.

The generated `.env` uses these deterministic non-secret settings:

```text
BASE_DOMAIN=localhost
HTTP_HOST_IP=127.0.0.1
TZ=Etc/UTC
INFLUXDB_ORG=runtime-org
INFLUXDB_BUCKET=runtime-bucket
INFLUXDB_RETENTION=1h
GRAFANA_ADMIN_USER=runtime-admin
```

Passwords, tokens, the project suffix, and the host port are generated per run.

### Runtime override

`compose.runtime.yaml` is a small override file. It replaces the persistent mounts of the services under test with `tmpfs` mounts at the same container targets:

- InfluxDB: `/var/lib/influxdb2` and `/etc/influxdb2`;
- Grafana: `/var/lib/grafana`;
- Portainer: `/data`.

Compose treats service volumes with the same container target as one unique resource, so the override replaces rather than adds to the persistent mount.

The override does not alter service images, commands, healthchecks, dependencies, routing labels, or application configuration. It therefore tests the same runtime model used by normal deployments while ensuring all state is ephemeral.

### Loopback-only HTTP exposure

The Traefik port mapping will support an optional host address while retaining the current default:

```text
HTTP_HOST_IP=0.0.0.0
```

`.env.example` will document this default. Normal deployments continue to listen on all host interfaces. The runtime test sets `HTTP_HOST_IP=127.0.0.1` and selects an available port in the range `20000-45000`, so test services are never published beyond the local runner.

If startup reports that the selected port is already allocated, the script may choose one new port and retry startup once. Other startup failures are not retried.

## Runtime flow

`scripts/check_runtime.sh` performs these stages in order:

1. Verify required commands: `docker`, `docker compose`, `curl`, `python3`, and `openssl`.
2. Verify that the Docker daemon is reachable.
3. Create a private temporary project directory with mode `0700`.
4. Generate disposable values for Traefik Basic Auth, InfluxDB, and Grafana.
5. Generate the Traefik bcrypt users file with the already pinned Apache httpd helper image.
6. Create every declared file-backed secret source, including an inert Mosquitto password record, so Compose model loading does not depend on inactive-profile behavior.
7. Render the merged base and runtime Compose model with exactly the `monitoring` and `tools` profiles.
8. Reject the model unless every named network and volume uses the generated project prefix and every stateful mount in scope resolves to `tmpfs`.
9. Start the stack using `docker compose up --wait --wait-timeout 240`.
10. Run HTTP, provisioning, and metrics assertions.
11. On failure, print Compose status, container health information, and bounded logs.
12. Always run `docker compose down --volumes --remove-orphans --timeout 20` for the unique temporary project and remove the temporary directory.

A trap owns cleanup from immediately after the temporary project is created. Cleanup is idempotent and preserves the original test exit code.

## Assertions

### Compose state

After `up --wait`, every expected service must be present. Services with healthchecks must report healthy; Portainer must be running and then pass its HTTP readiness probe.

The expected service set is exact:

```text
docker-socket-proxy
traefik
whoami
influxdb
telegraf
grafana
portainer
```

The script fails if an IoT, Netdata, or k6 container appears.

### Traefik and Basic Auth

Requests are sent to `127.0.0.1:<temporary-port>` with explicit `Host` headers, so the test does not depend on DNS.

The test verifies:

- `whoami.<base-domain>` returns `401` without credentials;
- the same route returns `200` with the generated Traefik credentials;
- `traefik.<base-domain>/dashboard/` returns `401` without credentials;
- the dashboard returns `200` with credentials.

Each route has a 90-second readiness deadline and is polled every two seconds.

### Application routes

The test polls these endpoints every two seconds, with a 90-second deadline per service:

- InfluxDB: `/health` through `influxdb.<base-domain>`;
- Grafana: `/api/health` through `grafana.<base-domain>`, with JSON field `database` equal to `ok`;
- Portainer: `/api/status` through `portainer.<base-domain>`.

JSON responses are evaluated with Python's standard library rather than `jq`.

### Grafana provisioning

Using the disposable Grafana administrator credentials, the test queries:

```text
/api/datasources/uid/telegraf_unique_uid
```

A `200` response proves that provisioning files were loaded and the administrator secret worked. The response must report datasource type `influxdb` and URL `http://influxdb:8086`.

### Metrics pipeline

The test submits a Flux query to InfluxDB's `/api/v2/query` endpoint using the disposable admin token. It polls every five seconds for at most 120 seconds until the CSV response contains at least one recent `system` measurement written by Telegraf.

This assertion proves the complete path:

```text
host metrics -> Telegraf -> InfluxDB
```

It also confirms that Telegraf can read its mounted token and reach InfluxDB over the internal backend network.

## Error handling and diagnostics

Every poll uses an explicit deadline; no loop is unbounded. HTTP checks retain the final status code and at most 2 KiB of the final response body for diagnostics.

If any assertion fails, the script prints:

- `docker compose ps --all`;
- `docker compose config --services`;
- `docker inspect` status and health data for test containers;
- the last 200 Compose log lines without ANSI colors.

Secrets, plaintext passwords, tokens, bcrypt records, and authorization headers are never printed. Test values are disposable, but logs still avoid echoing them.

## Testing strategy

### Static tests

`scripts/check_static.py` will require:

- `compose.runtime.yaml`;
- `scripts/check_runtime.sh`;
- `scripts/test_runtime.py`;
- `.github/workflows/runtime.yml`;
- the `make check-runtime` target;
- loopback-only runtime configuration;
- project-name parameterization;
- tmpfs replacement for every stateful service in scope;
- bounded cleanup and diagnostics commands.

It will reject a runtime script that invokes host-wide prune commands, accesses the repository's real `.env` or `.secrets/`, omits cleanup, uses unbounded polling, or starts the privileged Netdata/IoT profiles.

### Behavioral shell tests

A dependency-free Python test in `scripts/test_runtime.py` will execute `scripts/check_runtime.sh` against fake `docker` and `curl` commands. It will verify:

- temporary project and secret creation;
- unique project naming;
- use of both Compose files;
- activation of exactly `monitoring` and `tools`;
- rendered-model isolation checks before startup;
- `up --wait` with a 240-second timeout;
- cleanup on success and failure;
- diagnostics on failure;
- preservation of the repository's existing `.env` and `.secrets/`.

The behavioral test is added before the runtime implementation and must initially fail because `scripts/check_runtime.sh` does not exist.

### Real GitHub Actions integration

`.github/workflows/runtime.yml` will run on:

- relevant pull requests;
- pushes to `main` affecting runtime files;
- manual dispatch;
- a weekly schedule.

The job uses read-only repository permissions, `ubuntu-24.04`, a 25-minute job timeout, and `make check-runtime`. Failure diagnostics are uploaded for three days. The workflow does not claim support for Docker Desktop, rootless Docker, or non-Linux hosts.

## User interface

The Makefile adds:

```text
make check-runtime
```

`make check` remains the fast configuration test. `make check-images` remains the registry-manifest test. `make check-runtime` is explicitly slower because it pulls missing layers and starts the default stack.

README documentation will describe the three verification levels and state exactly what each one proves.

## Implementation basis

The implementation relies on documented Docker Compose behavior:

- `docker compose up --wait` waits for services to be running or healthy;
- `depends_on.condition: service_healthy` gates dependent service startup on healthchecks;
- service volume entries in merged Compose files are unique by container target, allowing the runtime override to replace persistent mounts with `tmpfs`;
- all relative paths in multiple Compose files resolve from the first Compose file or the selected project directory.

References:

- <https://docs.docker.com/reference/cli/docker/compose/up/>
- <https://docs.docker.com/compose/how-tos/startup-order/>
- <https://docs.docker.com/reference/compose-file/merge/>
- <https://docs.docker.com/reference/cli/docker/compose/>

## Non-goals

- testing Netdata's privileged host integration;
- testing openHAB discovery, bindings, or USB devices;
- testing Mosquitto MQTT publish/subscribe behavior in this change;
- public TLS or ACME validation;
- vulnerability scanning or SBOM policy;
- production backup and restore testing;
- performance or load testing;
- asserting support for platforms other than Linux Docker Engine on `amd64` and `arm64`.
