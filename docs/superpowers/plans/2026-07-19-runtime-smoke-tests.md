# Runtime Smoke Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start the legacy-equivalent default stack in an isolated Docker Compose project and prove routing, authentication, Grafana provisioning, and the Telegraf-to-InfluxDB metrics path.

**Architecture:** Production resource names are parameterized through `HOMELAB_PROJECT_NAME` while retaining `homelab` defaults. A small Compose override replaces stateful test mounts with `tmpfs`; a POSIX shell harness copies only required inputs to a private temporary directory, generates disposable newline-safe credentials, starts core + `monitoring` + `tools`, performs bounded assertions, emits safe diagnostics on failure, and always destroys the unique project.

**Tech Stack:** Docker Engine, Docker Compose v2, POSIX shell, Python 3.11 standard library, curl, OpenSSL, GitHub Actions.

## Global Constraints

- Default production names and `make up` behavior must remain unchanged.
- Runtime resources must use a unique project prefix and a loopback-only random HTTP port.
- Runtime state for InfluxDB, Grafana, and Portainer must be ephemeral.
- The test must not read the repository's working `.env` or `.secrets/`.
- Exactly core + `monitoring` + `tools` may start; `iot`, `netdata`, and `test` remain out of scope.
- Startup timeout is 240 seconds; every poll and workflow has a hard bound.
- Cleanup must preserve the original exit status and remove only the unique test project.
- Raw credentials used as file-backed secrets must not contain CR/LF terminators.
- `make check`, `make check-images`, and `make check-runtime` remain separate validation levels.
- No third-party Python package or new task runner is allowed.

---

### Task 1: Isolate Compose names and state

**Files:**
- Modify: `compose.yaml`
- Create: `compose.runtime.yaml`
- Modify: `.env.example`
- Modify: `scripts/check_static.py`

**Interfaces:**
- Produces: `HOMELAB_PROJECT_NAME`, `HTTP_HOST_IP`, and an ephemeral runtime override.

- [x] **Step 1: Add failing static rules for project interpolation**

Require the production model to contain:

```yaml
name: ${HOMELAB_PROJECT_NAME:-homelab}
```

```yaml
ports:
  - "${HTTP_HOST_IP:-0.0.0.0}:${HTTP_PORT:-80}:80"
```

All explicit networks, volumes, Traefik provider settings, and `traefik.docker.network` labels use the same project prefix.

- [x] **Step 2: Preserve production defaults**

Add to `.env.example`:

```dotenv
HOMELAB_PROJECT_NAME=homelab
HTTP_HOST_IP=0.0.0.0
```

Expected: rendering without overrides still produces the original `homelab`, `homelab_proxy`, and `homelab_*` names.

- [x] **Step 3: Add the ephemeral override**

`compose.runtime.yaml` replaces mounts by container target:

```yaml
services:
  influxdb:
    volumes:
      - type: tmpfs
        target: /var/lib/influxdb2
        tmpfs:
          mode: 0777
      - type: tmpfs
        target: /etc/influxdb2
        tmpfs:
          mode: 0777
  grafana:
    volumes:
      - type: tmpfs
        target: /var/lib/grafana
        tmpfs:
          mode: 0777
  portainer:
    volumes:
      - type: tmpfs
        target: /data
        tmpfs:
          mode: 0777
```

The permissive modes apply only to disposable in-memory filesystems.

- [x] **Step 4: Verify both models**

```bash
python3 scripts/check_static.py
docker compose --env-file .env.example \
  --profile monitoring --profile tools config --quiet
HOMELAB_PROJECT_NAME=homelab-runtime-plan \
HTTP_HOST_IP=127.0.0.1 HTTP_PORT=18080 \
  docker compose --env-file .env.example \
  -f compose.yaml -f compose.runtime.yaml \
  --profile monitoring --profile tools config --quiet
```

Expected: exit `0`; the isolated render uses its own network names, volume names, loopback binding, and `tmpfs` targets.

### Task 2: Define runtime behavior before implementation

**Files:**
- Create: `scripts/test_runtime.py`
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: future `scripts/check_runtime.sh`.
- Produces: fake Docker/curl/OpenSSL behavioral tests.

- [x] **Step 1: Write the RED tests**

Cover:

- both Compose files;
- exactly `monitoring` and `tools` profiles;
- unique `homelab-runtime-*` project name;
- `up --wait --wait-timeout 240`;
- expected seven services;
- every HTTP, datasource, and Flux query path;
- diagnostics and cleanup after simulated startup failure;
- preservation of source `.env` and `.secrets/`;
- newline-free runtime `influxdb_token`.

- [x] **Step 2: Observe the intended RED state**

```bash
python3 scripts/test_runtime.py
```

Observed: CI failed because `scripts/check_runtime.sh` did not yet exist. No prior test failed first.

### Task 3: Implement the isolated runtime harness

**Files:**
- Create: `scripts/check_runtime.sh`
- Test: `scripts/test_runtime.py`

**Interfaces:**
- Produces: executable zero-argument runtime checker.

- [x] **Step 1: Create a private disposable workspace**

The harness:

```sh
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-runtime.XXXXXX")
chmod 700 "$WORKDIR"
PROJECT_NAME="homelab-runtime-$$-$(openssl rand -hex 4)"
```

It copies only `compose.yaml`, `compose.runtime.yaml`, and `config/`, then creates a temporary `.env` and `.secrets/` inside that directory.

- [x] **Step 2: Keep file-backed raw credentials newline-free**

```sh
printf '%s' "$INFLUXDB_USERNAME" >"$WORKDIR/.secrets/influxdb_username"
printf '%s' "$INFLUXDB_PASSWORD" >"$WORKDIR/.secrets/influxdb_password"
printf '%s' "$INFLUXDB_TOKEN" >"$WORKDIR/.secrets/influxdb_token"
printf '%s' "$GRAFANA_ADMIN_PASSWORD" >"$WORKDIR/.secrets/grafana_admin_password"
```

Password-file records for Traefik and Mosquitto remain line-oriented and retain their record terminator.

- [x] **Step 3: Start the exact default stack scope**

The Compose wrapper always includes:

```sh
--project-name "$PROJECT_NAME"
--env-file "$WORKDIR/.env"
-f "$WORKDIR/compose.yaml"
-f "$WORKDIR/compose.runtime.yaml"
--profile monitoring
--profile tools
```

Startup command:

```bash
docker compose ... up --wait --wait-timeout 240
```

- [x] **Step 4: Assert application behavior**

The harness checks:

```text
whoami anonymous               -> 401
whoami generated Basic Auth    -> 200
Traefik dashboard anonymous    -> 401
Traefik dashboard authenticated-> 200
InfluxDB /health               -> 200, status pass
Grafana /api/health            -> 200, database ok
Portainer /api/status          -> 200
Grafana datasource UID         -> 200, influxdb
InfluxDB Flux query            -> recent system measurement
```

- [x] **Step 5: Guarantee bounded diagnostics and cleanup**

On failure print only status, service names, state/health, and the last 200 log lines. Always execute:

```bash
docker compose ... down --volumes --remove-orphans --timeout 20
```

The command is scoped by the unique project name; source deployment resources are never addressed.

### Task 4: Fix the runtime-discovered secret defect

**Files:**
- Modify: `scripts/test_init.py`
- Modify: `scripts/test_runtime.py`
- Modify: `scripts/init.sh`
- Modify: `scripts/check_runtime.sh`

**Interfaces:**
- Produces: newline-safe raw secrets for both normal bootstrap and runtime tests.

- [x] **Step 1: Capture the real failure**

The first real runtime job started all containers but never observed Telegraf data. Diagnostics showed:

```text
invalid header field value for "Authorization"
```

The Docker secret store returned the exact token-file bytes, including the old trailing newline.

- [x] **Step 2: Add failing regressions**

`test_init.py` rejects CR/LF endings on generated random secrets. The fake runtime Docker command inspects `.secrets/influxdb_token` before simulated startup and rejects a trailing line ending.

Observed: CI failed while the image-manifest check stayed green.

- [x] **Step 3: Correct generation without rotating credentials**

New random files use:

```sh
value=$(openssl rand -hex "$bytes")
printf '%s' "$value" >"$path"
```

Existing `influxdb_token` files are read as a single value, embedded line endings are rejected, and only trailing LF/CRLF is removed. The credential value is unchanged.

When plaintext is sent to line-oriented hashing tools, the delimiter is added only to stdin:

```sh
printf '%s\n' "$(cat "$SECRETS_DIR/traefik_password")" | docker run ...
printf '%s\n' "$(cat "$SECRETS_DIR/mosquitto_password")" | docker run ...
```

- [x] **Step 4: Re-run all gates**

Observed on the corrected head:

```text
CI                success
Image platforms   success
Runtime smoke     success
```

The runtime job observed the real Telegraf `system` measurement in InfluxDB.

### Task 5: Expose and protect the three validation levels

**Files:**
- Modify: `Makefile`
- Create: `.github/workflows/runtime.yml`
- Create: `scripts/check_runtime_policy.py`
- Modify: `scripts/check.sh`
- Modify: `README.md`

**Interfaces:**
- Produces: `make check-runtime` and scheduled runtime verification.

- [x] **Step 1: Add the Make target**

```make
check-runtime: ## Pull missing layers, start the isolated default stack, and run runtime assertions
	@./scripts/check_runtime.sh
```

It is not a prerequisite of `make check` or `make check-images`.

- [x] **Step 2: Add the runtime workflow**

The workflow uses:

```yaml
permissions:
  contents: read
```

It runs for relevant pull requests, pushes to `main`, manual dispatches, and a weekly schedule. The job timeout is 25 minutes. A three-day log artifact is uploaded only after failure.

- [x] **Step 3: Add runtime-specific static policy**

`scripts/check_runtime_policy.py` enforces:

- executable runtime script;
- Make target separation;
- read-only, bounded, scheduled workflow;
- README coverage of all three levels;
- newline-safe bootstrap and runtime token writes;
- inclusion of the policy checker in `make check`.

- [x] **Step 4: Document operator behavior**

README explains:

```text
make check          configuration and behavior tests, no application containers
make check-images   registry manifests only, no layers or containers
make check-runtime  isolated real stack, layers and containers permitted
```

It also documents one-time normalization of an older generated InfluxDB token without rotation.

### Task 6: Final verification and integration

**Files:**
- No production changes unless review or fresh verification identifies a concrete defect.

- [x] **Step 1: Verify the final pull-request head**

Required results:

```text
CI                success
Image platforms   success
Runtime smoke     success
```

- [x] **Step 2: Review scope and safety**

Confirm:

- default production resource names are unchanged;
- source `.env` and `.secrets/` are untouched;
- HTTP binds to `127.0.0.1` during runtime verification;
- exactly seven expected services start;
- data is disposable;
- loops and jobs are bounded;
- cleanup is scoped to the unique project;
- no credential is printed intentionally;
- IoT, Netdata, public TLS, backups, and performance remain out of scope.

- [ ] **Step 3: Squash merge after fresh green checks**

Expected subject:

```text
Add isolated runtime smoke tests (#3)
```

After merge, verify the new commit is the latest on `main` and the push-triggered `Runtime smoke` workflow succeeds.
