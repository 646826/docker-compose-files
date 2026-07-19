# IoT Runtime Smoke Tests Design

## Goal

Add a real, isolated runtime smoke test for the `iot` profile that proves Mosquitto authentication, authenticated MQTT publish/subscribe, retained-message persistence across a broker restart, and openHAB HTTP readiness through Traefik.

The test must remain independent of the existing default-stack runtime workflow. A failure in the slower openHAB startup path must not block diagnosis of Traefik, monitoring, Grafana, or Portainer.

## Scope

The test starts the profile-free core plus the `iot` profile:

- `docker-socket-proxy`;
- Traefik;
- whoami;
- Eclipse Mosquitto;
- openHAB.

The assertions cover:

- Mosquitto rejects an anonymous publish;
- Mosquitto accepts an authenticated retained publish;
- an authenticated subscriber receives the exact payload;
- the same retained payload is available after Mosquitto is restarted;
- openHAB becomes reachable through its Traefik router and returns an openHAB page.

The test does not install the openHAB MQTT Binding, create Things or Items, use multicast discovery, attach USB devices, start Netdata, or execute k6.

## Design principles

1. **Independent verification layer:** expose `make check-iot-runtime` separately from `make check`, `make check-images`, and `make check-runtime`.
2. **No production-state reuse:** never read or modify the repository's existing `.env` or `.secrets/`.
3. **Project-scoped isolation:** use a unique `HOMELAB_PROJECT_NAME` so all containers, networks, and named volumes are disposable.
4. **Real persistence:** keep Mosquitto on its unique named volume rather than `tmpfs`, because the test must prove that the SQLite persistence plugin restores a retained message after a process restart.
5. **Loopback-only exposure:** publish both HTTP and MQTT only on random `127.0.0.1` ports.
6. **No secret arguments:** MQTT passwords live only in a mode-`0600` Mosquitto client config mounted read-only into short-lived client containers.
7. **Bounded execution:** every startup check, MQTT operation, HTTP poll, diagnostic command, and workflow has an explicit limit.

## Compose changes

### MQTT bind address

Parameterize the Mosquitto host binding without changing the normal deployment default:

```yaml
ports:
  - "${MQTT_HOST_IP:-0.0.0.0}:${MQTT_PORT:-1883}:1883"
```

Add the non-secret default to `.env.example`:

```dotenv
MQTT_HOST_IP=0.0.0.0
```

Existing deployments that do not define the variable continue listening on all interfaces, exactly as before. The runtime script sets `MQTT_HOST_IP=127.0.0.1` and chooses a free high port.

### No IoT override file

No `compose.iot-runtime.yaml` is needed. The existing `HOMELAB_PROJECT_NAME` interpolation already isolates the Mosquitto and openHAB named volumes. The script removes those volumes with the unique project during cleanup.

Keeping the normal Mosquitto volume is intentional: replacing `/mosquitto/data` with `tmpfs` could lose the SQLite database when the broker container is stopped, invalidating the persistence assertion.

## Temporary runtime project

`scripts/check_iot_runtime.sh` creates a mode-`0700` temporary directory and copies only:

- `compose.yaml`;
- `config/`;
- the pinned helper-image assignments read from `scripts/init.sh`.

It generates its own:

- `.env`;
- `.secrets/`;
- Mosquitto client config;
- bounded response and diagnostic files.

The source repository's `.env` and `.secrets/` are neither copied nor opened.

The project name follows this pattern:

```text
homelab-iot-runtime-<pid>-<random-hex>
```

The generated environment uses:

```dotenv
HOMELAB_PROJECT_NAME=<unique-project>
BASE_DOMAIN=iot-runtime.localhost
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=<free-port>
MQTT_HOST_IP=127.0.0.1
MQTT_PORT=<free-port>
MOSQUITTO_USERNAME=runtime
```

All unrelated settings receive harmless non-secret runtime values.

## Disposable credentials

### Mosquitto broker password file

Generate a random MQTT password with OpenSSL. Convert it into a Mosquitto 2.1 Argon2id password record through the pinned `MOSQUITTO_IMAGE` and `mosquitto_passwd -U`, using standard input rather than a password argument.

Write only the resulting hash record to `.secrets/mosquitto_passwords`. Write no plaintext MQTT password to a Compose secret.

### MQTT client config

Create a mode-`0600` file with the Mosquitto 2.1 client-option format:

```text
-u runtime
-P <disposable-password>
```

Both `mosquitto_pub` and `mosquitto_sub` receive the file through:

```text
-o /run/mosquitto-client.conf
```

The official Mosquitto 2.1 clients support `-o` and recommend config files for authentication so usernames and passwords do not appear in command-line arguments.

### Other declared secrets

Compose validates file-backed secret sources even for services outside the selected profile. Create private disposable placeholders for InfluxDB and Grafana secrets, plus a valid generated Traefik bcrypt record. These files exist only inside the temporary runtime directory.

Raw token/password placeholders that could be interpreted as HTTP credentials are written without CR or LF terminators.

## Container startup

Verify `docker`, `docker compose`, `curl`, `python3`, and `openssl`, then verify access to the Docker daemon.

Render the selected model before starting:

```bash
docker compose \
  --project-name "$PROJECT_NAME" \
  --env-file "$WORKDIR/.env" \
  -f "$WORKDIR/compose.yaml" \
  --profile iot \
  config --quiet
```

Start only core plus `iot`:

```bash
docker compose ... --profile iot up -d
```

Do not use the `monitoring`, `tools`, `netdata`, or `test` profiles.

The script then confirms that the exact expected service set is present. It does not rely solely on openHAB's image healthcheck because the upstream image deliberately uses a long first-start healthcheck period. Instead, the script performs its own bounded HTTP readiness poll.

## MQTT client execution

Use the same pinned official Mosquitto image as short-lived client containers. Run them with Linux host networking so they exercise the actual loopback-only published MQTT port:

```text
docker run --rm --network host \
  --volume <client-config>:/run/mosquitto-client.conf:ro \
  --entrypoint mosquitto_pub|mosquitto_sub \
  <MOSQUITTO_IMAGE> ...
```

The maintained runtime target is Linux Docker Engine; Docker Desktop and non-Linux host-network semantics remain outside the supported test environment.

No client invocation contains `-P`, `--pw`, the password value, or a password-bearing environment variable.

## MQTT assertions

### 1. Authenticated readiness

Retry an authenticated non-retained publish to a unique probe topic until it succeeds or the 120-second broker deadline expires. This distinguishes broker startup from the anonymous-authentication assertion.

### 2. Anonymous rejection

Run `mosquitto_pub` without the client config against the same loopback port. The command must exit non-zero. Success is a test failure.

### 3. Retained round trip

Generate a unique topic and payload:

```text
homelab/runtime/<project>/retained
<payload-random-hex>
```

Publish the payload with authentication, QoS 1, and the retain flag. Then subscribe with authentication using `-C 1` and `-W 20`. The command must exit zero and stdout must equal the payload exactly after removing only the command's final line delimiter.

### 4. SQLite persistence after restart

Restart only the Mosquitto service with a bounded stop timeout:

```bash
docker compose ... restart --timeout 20 mosquitto
```

Wait for authenticated broker readiness again, then subscribe to the retained topic a second time. The exact payload must still be returned.

Because the process has restarted and the message remains available, this proves the configured SQLite persistence plugin stored and restored retained state from the project-scoped Mosquitto volume.

## openHAB readiness assertion

Poll the openHAB route for up to 10 minutes. Use curl `--resolve` so redirects and requests remain pinned to the random loopback HTTP port while preserving the real router hostname:

```text
openhab.iot-runtime.localhost
```

Follow at most five redirects. Success requires:

- final HTTP status `200`;
- response body containing `openhab`, case-insensitively.

This proves that openHAB completed enough initialization to serve its web application, that the proxy network is functional, and that the Traefik router/service labels are correct.

The test does not complete the openHAB setup wizard or assert MQTT Binding behavior.

## Cleanup and diagnostics

Install cleanup traps immediately after the temporary directory is created. Cleanup runs after success, failure, `HUP`, `INT`, and `TERM`, while preserving the original exit status.

Cleanup performs only project-scoped operations:

```bash
docker compose ... down --volumes --remove-orphans --timeout 30
```

It then removes the temporary directory. It never invokes Docker prune commands or addresses the production `homelab` project.

On failure, print:

- `docker compose ps --all`;
- selected merged services;
- container status and health summaries;
- the final 200 log lines without ANSI color;
- the final openHAB HTTP status and at most 500 response bytes;
- concise MQTT operation labels and exit statuses.

Never print generated credentials, the client config, authorization material, or secret-file contents.

## Behavioral tests

Create `scripts/test_iot_runtime.py` using only the Python standard library and fake `docker`, `curl`, and `openssl` executables.

Tests must prove:

- the script uses a unique `homelab-iot-runtime-*` project;
- only `--profile iot` is activated;
- HTTP and MQTT bind addresses are `127.0.0.1` with generated ports;
- source `.env` and `.secrets/` sentinels remain unchanged;
- disposable temporary files are removed;
- anonymous publish failure is required;
- authenticated publish/subscription receives an exact payload;
- Mosquitto is restarted and the retained message is read again;
- client commands use `-o` and never contain the plaintext password or `-P`;
- openHAB is probed through its Traefik hostname;
- failure prints diagnostics and still performs scoped `down --volumes` cleanup.

Wire these tests into the fast `scripts/check.sh` suite. The behavioral test is added before the runtime script and must first fail because `scripts/check_iot_runtime.sh` is missing.

## Static acceptance policy

Extend `scripts/check_static.py` to require:

- `MQTT_HOST_IP` interpolation in `compose.yaml`;
- `MQTT_HOST_IP=0.0.0.0` in `.env.example`;
- `scripts/check_iot_runtime.sh`;
- `scripts/test_iot_runtime.py`;
- `.github/workflows/iot-runtime.yml`;
- the `make check-iot-runtime` target;
- profile isolation;
- loopback-only runtime values;
- retained publish and post-restart subscribe assertions;
- `-o` client config usage;
- bounded cleanup and logs.

Reject runtime code that includes:

- `--profile monitoring`, `--profile tools`, `--profile netdata`, or `--profile test`;
- a password argument such as `-P "$MQTT_PASSWORD"`;
- production `.env`/`.secrets/` reuse;
- host-wide prune commands;
- unbounded polling loops.

## GitHub Actions

Add `.github/workflows/iot-runtime.yml` with:

- relevant pull-request path filters;
- pushes to `main` for IoT-runtime-related files;
- manual dispatch;
- a weekly schedule separate from the default runtime workflow;
- `contents: read` permissions only;
- concurrency cancellation;
- a 30-minute job timeout;
- Docker and Compose version output;
- `make check-iot-runtime` with `pipefail` and a captured log;
- a three-day diagnostic artifact uploaded only after failure.

## Documentation

Update the command table and change the verification section from three to four levels:

1. `make check` — static, behavior, shell, and Compose validation;
2. `make check-images` — registry tag and platform validation;
3. `make check-runtime` — default core/monitoring/Portainer application runtime;
4. `make check-iot-runtime` — Mosquitto authentication/persistence and openHAB readiness.

Document `MQTT_HOST_IP` and state that the IoT runtime check pulls missing image layers, uses host networking for short-lived MQTT client containers, and supports Linux Docker Engine only.

## Non-goals

- installing or configuring the openHAB MQTT Binding;
- creating openHAB Things, Channels, Items, Rules, or users;
- validating UPnP, mDNS, multicast, Bluetooth, Zigbee, Z-Wave, GPIO, or USB hardware;
- testing MQTT over TLS or WebSockets;
- testing Mosquitto ACL policies beyond anonymous denial and authenticated access;
- testing Netdata;
- public TLS or ACME;
- backup/restore orchestration;
- load or endurance testing;
- supporting Docker Desktop, rootless Docker, or non-Linux host networking in this workflow.

## Authoritative references

- Eclipse Mosquitto `mosquitto_pub` 2.1 manual: `man/mosquitto_pub.1.xml`.
- Eclipse Mosquitto shared client config format: `man/common/options-intro.xml`.
- Eclipse Mosquitto `mosquitto_sub` 2.1 manual: `man/mosquitto_sub.1.xml`.
- openHAB Docker image healthcheck and exposed paths: `openhab/openhab-docker`, `alpine/Dockerfile`.
