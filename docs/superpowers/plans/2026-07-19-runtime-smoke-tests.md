# Runtime Smoke Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated runtime smoke test that starts the legacy-equivalent default stack and proves routing, authentication, Grafana provisioning, and the Telegraf-to-InfluxDB metrics path.

**Architecture:** The production Compose model becomes project-name-aware without changing its default resource names. A small override replaces stateful runtime-test mounts with `tmpfs`; a POSIX shell harness copies only required inputs into a private temporary directory, generates disposable credentials, starts exactly the `monitoring` and `tools` profiles with `docker compose up --wait`, performs bounded HTTP and Flux assertions, prints safe diagnostics on failure, and always destroys the unique temporary project. A fake-command Python test covers shell behavior while a separate GitHub Actions workflow supplies the real Docker integration proof.

**Tech Stack:** Docker Engine, Docker Compose v2, POSIX shell, Python 3.11 standard library, curl, OpenSSL, GitHub Actions.

## Global Constraints

- The maintained runtime target remains current Linux Docker Engine with Docker Compose v2 on `linux/amd64` and `linux/arm64`.
- Normal deployment names remain exactly `homelab`, `homelab_proxy`, `homelab_backend`, `homelab_socket`, `homelab_iot`, and `homelab_*` volumes when `HOMELAB_PROJECT_NAME` is unset.
- Normal HTTP exposure remains `0.0.0.0:${HTTP_PORT:-80}` when `HTTP_HOST_IP` is unset.
- The runtime test starts exactly core + `monitoring` + `tools`; it must not start `iot`, `netdata`, or `test` profiles.
- The runtime test must never read, modify, copy, or reuse the repository's existing `.env` or `.secrets/`.
- Runtime state for InfluxDB, Grafana, and Portainer must be ephemeral and removed by the test.
- Every polling loop is bounded; Compose startup timeout is exactly 240 seconds.
- Cleanup must run on success, assertion failure, startup failure, HUP, INT, and TERM, preserving the original exit status.
- Diagnostics must not print passwords, tokens, authorization headers, curl credential files, or generated secret contents.
- `make check` stays the fast static/configuration check; `make check-images` stays registry-manifest-only; the real runtime test is exposed only as `make check-runtime`.
- No third-party Python or shell dependency may be introduced.

---

### Task 1: Parameterize production resource names and add the ephemeral runtime override

**Files:**
- Modify: `scripts/check_static.py`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Create: `compose.runtime.yaml`

**Interfaces:**
- Consumes: existing logical network keys (`proxy`, `backend`, `socket`, `iot`) and volume keys.
- Produces: `HOMELAB_PROJECT_NAME` and `HTTP_HOST_IP` interpolation points used by the runtime harness; `compose.runtime.yaml` that replaces persistent mounts by container target.

- [ ] **Step 1: Add failing static acceptance rules**

In `scripts/check_static.py`, add `compose.runtime.yaml` to `required_files`, replace the literal project-name assertion with the following contract, and add the runtime override checks immediately after `check_images(compose)`:

```python
        if not re.search(
            r"(?m)^name:\s*\$\{HOMELAB_PROJECT_NAME:-homelab\}\s*$",
            compose,
        ):
            error("compose.yaml must derive the project name from HOMELAB_PROJECT_NAME")

        required_runtime_interpolation = (
            '"${HTTP_HOST_IP:-0.0.0.0}:${HTTP_PORT:-80}:80"',
            "--providers.docker.network=${HOMELAB_PROJECT_NAME:-homelab}_proxy",
            "traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_proxy",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_backend",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_socket",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_iot",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_influxdb_data",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_grafana_data",
            "name: ${HOMELAB_PROJECT_NAME:-homelab}_portainer_data",
        )
        for fragment in required_runtime_interpolation:
            if fragment not in compose:
                error(f"runtime isolation interpolation is missing: {fragment}")
```

After the main `compose` block, read and validate the override:

```python
    runtime_override = read_required("compose.runtime.yaml")
    if runtime_override:
        expected_tmpfs = {
            "influxdb": ("/var/lib/influxdb2", "/etc/influxdb2"),
            "grafana": ("/var/lib/grafana",),
            "portainer": ("/data",),
        }
        for service, targets in expected_tmpfs.items():
            block = service_block(runtime_override, service)
            if not block:
                error(f"runtime override is missing service: {service}")
                continue
            for target in targets:
                target_pattern = rf"(?ms)type:\s*tmpfs\s*\n\s+target:\s*{re.escape(target)}\s*$"
                if not re.search(target_pattern, block):
                    error(f"runtime override must replace {service}:{target} with tmpfs")
        if re.search(r"(?m)^\s*image:\s*", runtime_override):
            error("runtime override must not replace production images")
```

Add `ROOT / "compose.runtime.yaml"` to `scan_operational_files()`.

- [ ] **Step 2: Run the static check and observe the intended failure**

Run:

```bash
python3 scripts/check_static.py
```

Expected: non-zero exit with errors for missing `compose.runtime.yaml`, literal `name: homelab`, the old HTTP port binding, and literal resource names.

- [ ] **Step 3: Parameterize `compose.yaml` without changing defaults**

Apply these exact substitutions:

```yaml
name: ${HOMELAB_PROJECT_NAME:-homelab}
```

```yaml
      - --providers.docker.network=${HOMELAB_PROJECT_NAME:-homelab}_proxy
```

```yaml
    ports:
      - "${HTTP_HOST_IP:-0.0.0.0}:${HTTP_PORT:-80}:80"
```

Every `traefik.docker.network` value becomes:

```yaml
      traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
```

Replace all explicit network names with:

```yaml
networks:
  proxy:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
  backend:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_backend
    internal: true
  socket:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_socket
    internal: true
  iot:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_iot
```

Replace every volume `name:` using the same prefix. The complete volume block must be:

```yaml
volumes:
  influxdb_data:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_influxdb_data
  influxdb_config:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_influxdb_config
  grafana_data:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_grafana_data
  portainer_data:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_portainer_data
  netdata_config:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_netdata_config
  netdata_lib:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_netdata_lib
  netdata_cache:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_netdata_cache
  mosquitto_data:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_mosquitto_data
  openhab_addons:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_openhab_addons
  openhab_conf:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_openhab_conf
  openhab_userdata:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_openhab_userdata
```

- [ ] **Step 4: Add non-secret defaults to `.env.example`**

Insert directly after the opening comment:

```dotenv
# Resource prefix used by the Compose project, explicit networks, and volumes.
HOMELAB_PROJECT_NAME=homelab

# Bind HTTP to all interfaces by default. Runtime CI overrides this to 127.0.0.1.
HTTP_HOST_IP=0.0.0.0
```

Keep `BASE_DOMAIN=localhost` and `HTTP_PORT=80` unchanged.

- [ ] **Step 5: Create `compose.runtime.yaml`**

Create the file with exactly:

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

The permissive mode is confined to disposable in-memory mounts in the isolated test project; the production file remains unchanged.

- [ ] **Step 6: Validate default and isolated merged models**

Create temporary placeholder secret sources, then run:

```bash
python3 scripts/check_static.py
mkdir -p .secrets
for name in influxdb_username influxdb_password influxdb_token grafana_admin_password traefik_users mosquitto_passwords; do
  test -f ".secrets/$name" || printf 'validation\n' >".secrets/$name"
done
docker compose --env-file .env.example --profile monitoring --profile tools config --quiet
HOMELAB_PROJECT_NAME=homelab-runtime-plan \
HTTP_HOST_IP=127.0.0.1 \
HTTP_PORT=18080 \
  docker compose \
    --env-file .env.example \
    -f compose.yaml \
    -f compose.runtime.yaml \
    --profile monitoring \
    --profile tools \
    config --quiet
```

Expected: all commands exit `0`. Inspect the rendered model and confirm the runtime project uses `homelab-runtime-plan_*` resources, `127.0.0.1:18080`, and `tmpfs` at all four state targets.

- [ ] **Step 7: Commit the isolated Compose model**

```bash
git add compose.yaml compose.runtime.yaml .env.example scripts/check_static.py
git commit -m "feat: isolate runtime Compose projects"
```

### Task 2: Define the runtime harness behavior with failing tests

**Files:**
- Create: `scripts/test_runtime.py`
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: future executable `scripts/check_runtime.sh`.
- Produces: a fake Docker/curl contract that verifies unique naming, profile selection, startup timeout, endpoint flow, cleanup, diagnostics, and preservation of source configuration.

- [ ] **Step 1: Create `scripts/test_runtime.py`**

Create the following complete test file:

```python
#!/usr/bin/env python3
"""Behavioral tests for the isolated runtime smoke-test harness."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = ROOT / "scripts" / "check_runtime.sh"
RUNTIME_OVERRIDE = ROOT / "compose.runtime.yaml"
EXPECTED_SERVICES = (
    "docker-socket-proxy",
    "traefik",
    "whoami",
    "influxdb",
    "telegraf",
    "grafana",
    "portainer",
)


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


FAKE_DOCKER = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"

if [ "${1:-}" = "version" ]; then
  exit 0
fi

if [ "${1:-}" = "run" ]; then
  IFS= read -r password
  [ -n "$password" ]
  printf 'runtime:$2y$12$abcdefghijklmnopqrstuuuuuuuuuuuuuuuuuuuuuuuuuuuu\n'
  exit 0
fi

if [ "${1:-}" = "inspect" ]; then
  printf '/fake status=running health=healthy\n'
  exit 0
fi

case " $* " in
  *" compose version "*)
    exit 0
    ;;
  *" config --quiet "*)
    exit 0
    ;;
  *" config --services "*|*" ps --services --all "*)
    printf '%s\n' docker-socket-proxy traefik whoami influxdb telegraf grafana portainer
    exit 0
    ;;
  *" up --wait --wait-timeout 240 "*)
    if [ "${FAKE_RUNTIME_FAIL:-0}" = "1" ]; then
      printf 'simulated startup failure\n' >&2
      exit 42
    fi
    exit 0
    ;;
  *" ps -q "*)
    printf '%s\n' fake-container-1 fake-container-2
    exit 0
    ;;
  *" ps --all "*)
    printf 'NAME STATUS\nfake running\n'
    exit 0
    ;;
  *" logs --no-color --tail=200 "*)
    printf 'bounded fake diagnostics\n'
    exit 0
    ;;
  *" down --volumes --remove-orphans --timeout 20 "*)
    exit 0
    ;;
esac

printf 'unexpected fake docker command: %s\n' "$*" >&2
exit 64
'''


FAKE_CURL = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_CURL_LOG"

output=
config=
host=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output|-o)
      output=$2
      shift 2
      ;;
    --config)
      config=$2
      shift 2
      ;;
    --header|-H)
      case "$2" in Host:*) host=$2 ;; esac
      shift 2
      ;;
    --write-out|-w|--max-time|--data-binary)
      shift 2
      ;;
    --silent|--show-error|-s|-S)
      shift
      ;;
    http://*)
      url=$1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

code=200
body='{}'
case "$host $url" in
  *whoami*|*traefik*/dashboard/*)
    if [ -n "$config" ]; then
      code=200
      body='authenticated'
    else
      code=401
      body='unauthorized'
    fi
    ;;
  *grafana*/api/health*)
    body='{"database":"ok"}'
    ;;
  *grafana*/api/datasources/uid/influxdb*)
    body='{"uid":"influxdb"}'
    ;;
  *influxdb*/health*)
    body='{"status":"pass"}'
    ;;
  *influxdb*/api/v2/query*)
    body='_measurement\nsystem\n'
    ;;
  *portainer*/api/status*)
    body='{"Version":"runtime"}'
    ;;
esac

[ -n "$output" ] || exit 65
printf '%b\n' "$body" >"$output"
printf '%s' "$code"
'''


FAKE_OPENSSL = r'''#!/bin/sh
set -eu
[ "${1:-}" = "rand" ]
[ "${2:-}" = "-hex" ]
count=$(( ${3:-1} * 2 ))
i=0
while [ "$i" -lt "$count" ]; do
  printf 'a'
  i=$((i + 1))
done
printf '\n'
'''


class RuntimeHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(RUNTIME_SCRIPT.is_file(), "scripts/check_runtime.sh is missing")
        self.assertTrue(RUNTIME_OVERRIDE.is_file(), "compose.runtime.yaml is missing")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = self.root / "fixture"
        self.fake_bin = self.root / "bin"
        self.tmpdir = self.root / "tmp"
        self.fixture.mkdir()
        self.fake_bin.mkdir()
        self.tmpdir.mkdir()

        (self.fixture / "scripts").mkdir()
        shutil.copy2(RUNTIME_SCRIPT, self.fixture / "scripts" / "check_runtime.sh")
        shutil.copy2(ROOT / "scripts" / "init.sh", self.fixture / "scripts" / "init.sh")
        shutil.copy2(ROOT / "compose.yaml", self.fixture / "compose.yaml")
        shutil.copy2(RUNTIME_OVERRIDE, self.fixture / "compose.runtime.yaml")
        shutil.copytree(ROOT / "config", self.fixture / "config")

        (self.fixture / ".env").write_text("SOURCE_ENV_SENTINEL=keep\n", encoding="utf-8")
        (self.fixture / ".secrets").mkdir()
        (self.fixture / ".secrets" / "sentinel").write_text(
            "keep\n", encoding="utf-8"
        )

        write_executable(self.fake_bin / "docker", FAKE_DOCKER)
        write_executable(self.fake_bin / "curl", FAKE_CURL)
        write_executable(self.fake_bin / "openssl", FAKE_OPENSSL)
        self.docker_log = self.root / "docker.log"
        self.curl_log = self.root / "curl.log"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_harness(self, *, fail: bool = False) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{environment['PATH']}",
                "TMPDIR": str(self.tmpdir),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_CURL_LOG": str(self.curl_log),
                "FAKE_RUNTIME_FAIL": "1" if fail else "0",
            }
        )
        return subprocess.run(
            [str(self.fixture / "scripts" / "check_runtime.sh")],
            cwd=self.fixture,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_source_state_preserved(self) -> None:
        self.assertEqual(
            (self.fixture / ".env").read_text(encoding="utf-8"),
            "SOURCE_ENV_SENTINEL=keep\n",
        )
        self.assertEqual(
            {path.name for path in (self.fixture / ".secrets").iterdir()},
            {"sentinel"},
        )
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_success_uses_isolated_profiles_and_cleans_up(self) -> None:
        result = self.run_harness()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("compose.runtime.yaml", docker_log)
        self.assertIn("--profile monitoring --profile tools", docker_log)
        self.assertNotIn("--profile iot", docker_log)
        self.assertNotIn("--profile netdata", docker_log)
        self.assertNotIn("--profile test", docker_log)
        self.assertRegex(docker_log, r"--project-name homelab-runtime-[0-9]+-[a-f0-9]+")
        self.assertIn("up --wait --wait-timeout 240", docker_log)
        self.assertIn("down --volumes --remove-orphans --timeout 20", docker_log)
        curl_log = self.curl_log.read_text(encoding="utf-8")
        for fragment in (
            "whoami.runtime.localhost",
            "traefik.runtime.localhost",
            "influxdb.runtime.localhost",
            "grafana.runtime.localhost",
            "portainer.runtime.localhost",
            "/api/datasources/uid/influxdb",
            "/api/v2/query?org=runtime-org",
        ):
            self.assertIn(fragment, curl_log)
        self.assertIn("Runtime smoke test passed", result.stdout)
        self.assert_source_state_preserved()

    def test_startup_failure_prints_diagnostics_and_cleans_up(self) -> None:
        result = self.run_harness(fail=True)
        self.assertNotEqual(result.returncode, 0)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("ps --all", docker_log)
        self.assertIn("logs --no-color --tail=200", docker_log)
        self.assertIn("down --volumes --remove-orphans --timeout 20", docker_log)
        self.assertIn("Runtime diagnostics", result.stdout + result.stderr)
        self.assert_source_state_preserved()


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Wire the behavioral test into the fast suite**

In `scripts/check.sh`, add this line after `python3 scripts/test_check_images.py`:

```sh
python3 scripts/test_runtime.py
```

- [ ] **Step 3: Run the test and observe the intended RED result**

Run:

```bash
python3 scripts/test_runtime.py
```

Expected: both tests fail in `setUp` with `scripts/check_runtime.sh is missing`.

- [ ] **Step 4: Commit the failing behavioral contract**

```bash
git add scripts/test_runtime.py scripts/check.sh
git commit -m "test: define runtime smoke behavior"
```

### Task 3: Implement the isolated POSIX runtime harness

**Files:**
- Create: `scripts/check_runtime.sh`
- Test: `scripts/test_runtime.py`

**Interfaces:**
- Consumes: `compose.yaml`, `compose.runtime.yaml`, `config/`, and `HTPASSWD_IMAGE` from `scripts/init.sh`.
- Produces: executable `scripts/check_runtime.sh` with no arguments; exit `0` only when every runtime assertion passes.

- [ ] **Step 1: Create `scripts/check_runtime.sh`**

Create the following complete script:

```sh
#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
HTTP_PORT=
BASE_DOMAIN=runtime.localhost
TRAEFIK_USERNAME=runtime
GRAFANA_ADMIN_USER=runtime
INFLUXDB_USERNAME=runtime
INFLUXDB_ORG=runtime-org
INFLUXDB_BUCKET=runtime-bucket
RESPONSE_BODY=

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$WORKDIR/.env" \
    -f "$WORKDIR/compose.yaml" \
    -f "$WORKDIR/compose.runtime.yaml" \
    --profile monitoring \
    --profile tools \
    "$@"
}

diagnostics() {
  printf '\nRuntime diagnostics\n'
  printf '%s\n' '===================' 
  compose ps --all || true
  printf '\nMerged services:\n'
  compose config --services || true
  printf '\nContainer states:\n'
  ids=$(compose ps -q 2>/dev/null || true)
  for id in $ids; do
    docker inspect \
      --format '{{.Name}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
      "$id" || true
  done
  printf '\nLast 200 log lines:\n'
  compose logs --no-color --tail=200 || true
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$WORKDIR" ] && [ -d "$WORKDIR" ]; then
    if [ "$status" -ne 0 ]; then
      diagnostics || true
    fi
    compose down --volumes --remove-orphans --timeout 20 >/dev/null 2>&1 || true
    rm -rf "$WORKDIR"
  fi
  exit "$status"
}

http_request() {
  host=$1
  path=$2
  config=$3
  : >"$RESPONSE_BODY"
  set -- \
    --silent \
    --show-error \
    --max-time 10 \
    --output "$RESPONSE_BODY" \
    --write-out '%{http_code}' \
    --header "Host: $host"
  if [ "$config" != "-" ]; then
    set -- "$@" --config "$config"
  fi
  curl "$@" "http://127.0.0.1:$HTTP_PORT$path"
}

wait_http() {
  label=$1
  host=$2
  path=$3
  config=$4
  expected_code=$5
  expected_pattern=$6
  attempt=1
  code=000
  while [ "$attempt" -le 60 ]; do
    if code=$(http_request "$host" "$path" "$config" 2>/dev/null); then
      if [ "$code" = "$expected_code" ]; then
        if [ -z "$expected_pattern" ] || grep -Eq "$expected_pattern" "$RESPONSE_BODY"; then
          printf 'OK: %s\n' "$label"
          return 0
        fi
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: %s returned HTTP %s\n' "$label" "$code" >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

wait_for_metrics() {
  attempt=1
  code=000
  while [ "$attempt" -le 60 ]; do
    : >"$RESPONSE_BODY"
    if code=$(
      curl \
        --silent \
        --show-error \
        --max-time 10 \
        --output "$RESPONSE_BODY" \
        --write-out '%{http_code}' \
        --config "$WORKDIR/influx.curl" \
        --header "Host: influxdb.$BASE_DOMAIN" \
        --data-binary "@$WORKDIR/query.flux" \
        "http://127.0.0.1:$HTTP_PORT/api/v2/query?org=$INFLUXDB_ORG" \
        2>/dev/null
    ); then
      if [ "$code" = "200" ] && grep -q 'system' "$RESPONSE_BODY"; then
        printf 'OK: Telegraf metrics reached InfluxDB\n'
        return 0
      fi
    else
      code=000
    fi
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'FAILED: InfluxDB query returned HTTP %s without a system measurement\n' "$code" >&2
  head -c 500 "$RESPONSE_BODY" >&2 || true
  printf '\n' >&2
  return 1
}

for command in docker curl python3 openssl; do
  require_command "$command"
done

docker version >/dev/null
docker compose version >/dev/null

WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-runtime.XXXXXX")
chmod 700 "$WORKDIR"
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

PROJECT_NAME="homelab-runtime-$$-$(openssl rand -hex 4)"
HTTP_PORT=$(
  python3 -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
)
TRAEFIK_PASSWORD=$(openssl rand -hex 18)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 24)
INFLUXDB_PASSWORD=$(openssl rand -hex 24)
INFLUXDB_TOKEN=$(openssl rand -hex 32)
RESPONSE_BODY="$WORKDIR/response.body"

cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"
cp "$ROOT/compose.runtime.yaml" "$WORKDIR/compose.runtime.yaml"
cp -R "$ROOT/config" "$WORKDIR/config"
mkdir "$WORKDIR/.secrets"
chmod 700 "$WORKDIR/.secrets"

cat >"$WORKDIR/.env" <<EOF
HOMELAB_PROJECT_NAME=$PROJECT_NAME
BASE_DOMAIN=$BASE_DOMAIN
HTTP_HOST_IP=127.0.0.1
HTTP_PORT=$HTTP_PORT
MQTT_PORT=1883
TZ=Etc/UTC
TRAEFIK_LOG_LEVEL=INFO
TRAEFIK_USERNAME=$TRAEFIK_USERNAME
GRAFANA_ADMIN_USER=$GRAFANA_ADMIN_USER
INFLUXDB_USERNAME=$INFLUXDB_USERNAME
INFLUXDB_ORG=$INFLUXDB_ORG
INFLUXDB_BUCKET=$INFLUXDB_BUCKET
INFLUXDB_RETENTION=1h
MOSQUITTO_USERNAME=runtime
OPENHAB_UID=9001
OPENHAB_GID=9001
NETDATA_HOSTNAME=runtime
K6_TARGET_URL=http://whoami
EOF
chmod 600 "$WORKDIR/.env"

printf '%s\n' "$INFLUXDB_USERNAME" >"$WORKDIR/.secrets/influxdb_username"
printf '%s\n' "$INFLUXDB_PASSWORD" >"$WORKDIR/.secrets/influxdb_password"
printf '%s\n' "$INFLUXDB_TOKEN" >"$WORKDIR/.secrets/influxdb_token"
printf '%s\n' "$GRAFANA_ADMIN_PASSWORD" >"$WORKDIR/.secrets/grafana_admin_password"
printf '%s\n' 'runtime:$argon2id$v=19$m=19456,t=2,p=1$placeholder$placeholder' \
  >"$WORKDIR/.secrets/mosquitto_passwords"

HTPASSWD_IMAGE=$(sed -n 's/^HTPASSWD_IMAGE=//p' "$ROOT/scripts/init.sh" | tail -n 1)
if [ -z "$HTPASSWD_IMAGE" ]; then
  printf 'HTPASSWD_IMAGE is missing from scripts/init.sh\n' >&2
  exit 1
fi
traefik_record=$(
  printf '%s\n' "$TRAEFIK_PASSWORD" |
    docker run --rm -i \
      --entrypoint htpasswd \
      "$HTPASSWD_IMAGE" \
      -n -i -B -C 12 "$TRAEFIK_USERNAME"
)
printf '%s\n' "$traefik_record" >"$WORKDIR/.secrets/traefik_users"
chmod 644 "$WORKDIR/.secrets/"*

cat >"$WORKDIR/traefik.curl" <<EOF
user = "$TRAEFIK_USERNAME:$TRAEFIK_PASSWORD"
EOF
cat >"$WORKDIR/grafana.curl" <<EOF
user = "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD"
EOF
cat >"$WORKDIR/influx.curl" <<EOF
header = "Authorization: Token $INFLUXDB_TOKEN"
header = "Content-Type: application/vnd.flux"
header = "Accept: application/csv"
EOF
chmod 600 "$WORKDIR/traefik.curl" "$WORKDIR/grafana.curl" "$WORKDIR/influx.curl"

cat >"$WORKDIR/query.flux" <<EOF
from(bucket: "$INFLUXDB_BUCKET")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "system")
  |> limit(n: 1)
EOF
chmod 600 "$WORKDIR/query.flux"

compose config --quiet
printf 'Starting isolated runtime project %s on 127.0.0.1:%s\n' "$PROJECT_NAME" "$HTTP_PORT"
compose up --wait --wait-timeout 240

actual_services=$(compose ps --services --all)
for service in docker-socket-proxy traefik whoami influxdb telegraf grafana portainer; do
  if ! printf '%s\n' "$actual_services" | grep -qx "$service"; then
    printf 'FAILED: expected service is missing: %s\n' "$service" >&2
    exit 1
  fi
done

wait_http \
  "whoami rejects anonymous requests" \
  "whoami.$BASE_DOMAIN" \
  "/" \
  "-" \
  "401" \
  ""
wait_http \
  "whoami accepts generated Basic Auth" \
  "whoami.$BASE_DOMAIN" \
  "/" \
  "$WORKDIR/traefik.curl" \
  "200" \
  ""
wait_http \
  "Traefik dashboard rejects anonymous requests" \
  "traefik.$BASE_DOMAIN" \
  "/dashboard/" \
  "-" \
  "401" \
  ""
wait_http \
  "Traefik dashboard accepts generated Basic Auth" \
  "traefik.$BASE_DOMAIN" \
  "/dashboard/" \
  "$WORKDIR/traefik.curl" \
  "200" \
  ""
wait_http \
  "InfluxDB health route" \
  "influxdb.$BASE_DOMAIN" \
  "/health" \
  "-" \
  "200" \
  '"status"[[:space:]]*:[[:space:]]*"pass"'
wait_http \
  "Grafana database health" \
  "grafana.$BASE_DOMAIN" \
  "/api/health" \
  "-" \
  "200" \
  '"database"[[:space:]]*:[[:space:]]*"ok"'
wait_http \
  "Portainer status route" \
  "portainer.$BASE_DOMAIN" \
  "/api/status" \
  "-" \
  "200" \
  ""
wait_http \
  "Grafana provisioned InfluxDB datasource" \
  "grafana.$BASE_DOMAIN" \
  "/api/datasources/uid/influxdb" \
  "$WORKDIR/grafana.curl" \
  "200" \
  '"uid"[[:space:]]*:[[:space:]]*"influxdb"'
wait_for_metrics

printf 'Runtime smoke test passed\n'
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x scripts/check_runtime.sh
```

- [ ] **Step 3: Run the behavioral tests and verify GREEN**

Run:

```bash
python3 scripts/test_runtime.py
```

Expected: two tests pass, including the simulated startup-failure cleanup path.

- [ ] **Step 4: Run shell and Python validation**

```bash
sh -n scripts/check_runtime.sh scripts/check.sh scripts/init.sh
python3 -m py_compile scripts/test_runtime.py
python3 scripts/check_static.py
python3 scripts/test_init.py
python3 scripts/test_check_images.py
python3 scripts/test_runtime.py
```

Expected: every command exits `0`; no temporary `homelab-runtime.*` directory remains.

- [ ] **Step 5: Commit the runtime harness**

```bash
git add scripts/check_runtime.sh
git commit -m "feat: add isolated runtime smoke harness"
```

### Task 4: Expose runtime validation through Make, CI, documentation, and static policy

**Files:**
- Modify: `scripts/check_static.py`
- Modify: `Makefile`
- Create: `.github/workflows/runtime.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: `make check-runtime`; GitHub Actions check named `Runtime smoke`; documentation for the three verification levels.

- [ ] **Step 1: Add failing integration-policy checks**

Extend `required_files` in `scripts/check_static.py` with:

```python
        "compose.runtime.yaml",
        "scripts/check_runtime.sh",
        "scripts/test_runtime.py",
        ".github/workflows/runtime.yml",
```

Add `check-runtime` to `required_targets`, then add:

```python
        check_runtime_block = make_target_block(makefile, "check-runtime")
        if "./scripts/check_runtime.sh" not in check_runtime_block:
            error("make check-runtime must run scripts/check_runtime.sh")
        if "check-runtime" in check_block:
            error("make check must not start the runtime stack")
```

After the image workflow checks, add:

```python
    runtime_script = read_required("scripts/check_runtime.sh")
    if runtime_script:
        required_runtime_fragments = (
            "compose.runtime.yaml",
            "--profile monitoring",
            "--profile tools",
            "up --wait --wait-timeout 240",
            "down --volumes --remove-orphans --timeout 20",
            "logs --no-color --tail=200",
            "HTTP_HOST_IP=127.0.0.1",
            "/api/datasources/uid/influxdb",
            "/api/v2/query?org=$INFLUXDB_ORG",
            "Runtime smoke test passed",
        )
        for fragment in required_runtime_fragments:
            if fragment not in runtime_script:
                error(f"runtime harness is missing: {fragment}")
        for forbidden_profile in ("--profile iot", "--profile netdata", "--profile test"):
            if forbidden_profile in runtime_script:
                error(f"runtime harness must not start {forbidden_profile}")
        for forbidden_source in ('"$ROOT/.env"', '"$ROOT/.secrets'):
            if forbidden_source in runtime_script:
                error(f"runtime harness must not reuse source deployment data: {forbidden_source}")

    runtime_workflow = read_required(".github/workflows/runtime.yml")
    if runtime_workflow:
        if "make check-runtime" not in runtime_workflow:
            error("runtime workflow must run make check-runtime")
        if "pull_request:" not in runtime_workflow or "schedule:" not in runtime_workflow:
            error("runtime workflow must run for pull requests and on a schedule")
        if "timeout-minutes: 25" not in runtime_workflow:
            error("runtime workflow must have a 25-minute job timeout")
        if "if: failure()" not in runtime_workflow:
            error("runtime workflow must upload diagnostics only after failure")
        if not re.search(r"(?m)^permissions:\s*\n\s+contents:\s+read\s*$", runtime_workflow):
            error("runtime workflow must use read-only repository permissions")
```

Extend the README checks with:

```python
        if "make check-runtime" not in readme:
            error("README must document real runtime verification")
        if "Три уровня проверки" not in readme:
            error("README must distinguish the three verification levels")
```

- [ ] **Step 2: Run static checks and observe the intended failure**

Run:

```bash
python3 scripts/check_static.py
```

Expected: errors for the missing `check-runtime` target, runtime workflow, and README section.

- [ ] **Step 3: Add the Make target**

Add `check-runtime` to `.PHONY` and insert after `check-images`:

```make
check-runtime: ## Pull missing layers, start the isolated default stack, and run runtime assertions
	@./scripts/check_runtime.sh
```

Do not add it as a prerequisite of `check` or `check-images`.

- [ ] **Step 4: Create `.github/workflows/runtime.yml`**

Create exactly:

```yaml
name: Runtime smoke

on:
  push:
    branches:
      - main
    paths:
      - "compose.yaml"
      - "compose.runtime.yaml"
      - ".env.example"
      - "Makefile"
      - "config/**"
      - "scripts/init.sh"
      - "scripts/check_runtime.sh"
      - "scripts/test_runtime.py"
      - ".github/workflows/runtime.yml"
  pull_request:
    paths:
      - "compose.yaml"
      - "compose.runtime.yaml"
      - ".env.example"
      - "Makefile"
      - "config/**"
      - "scripts/init.sh"
      - "scripts/check_runtime.sh"
      - "scripts/test_runtime.py"
      - ".github/workflows/runtime.yml"
  schedule:
    - cron: "47 4 * * 0"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: runtime-smoke-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  smoke:
    name: Start and verify default stack
    runs-on: ubuntu-latest
    timeout-minutes: 25

    steps:
      - name: Check out repository
        uses: actions/checkout@v6

      - name: Verify Docker and Compose
        run: |
          docker version
          docker compose version

      - name: Run isolated runtime smoke test
        shell: bash
        run: |
          set -o pipefail
          make check-runtime 2>&1 | tee runtime-smoke.log

      - name: Upload failure diagnostics
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: runtime-smoke-log
          path: runtime-smoke.log
          if-no-files-found: error
          retention-days: 3
```

- [ ] **Step 5: Document the three verification levels**

Add `make check-runtime` to the command table:

```markdown
| `make check-runtime` | поднять изолированный default stack и проверить маршруты, auth, provisioning и метрики |
```

Replace the existing verification introduction with:

```markdown
## Три уровня проверки

### 1. Быстрая конфигурационная проверка

```bash
make check
```

Проверяет статические политики, unit/behavior tests, shell syntax и полностью объединённую Compose-модель. Контейнеры приложений не запускаются.

### 2. Проверка registry manifests

```bash
make check-images
```

Проверяет существование каждого зафиксированного image tag и наличие `linux/amd64` и `linux/arm64`, не скачивая слои и не запуская сервисы.

### 3. Изолированная runtime-проверка

```bash
make check-runtime
```

Создаёт одноразовый Compose-проект с уникальными сетями и `tmpfs`-данными, публикует Traefik только на случайном порту `127.0.0.1`, запускает core + monitoring + Portainer и проверяет:

- `401` без Basic Auth и `200` с ним для whoami и Traefik dashboard;
- health endpoints InfluxDB и Grafana;
- Portainer status endpoint;
- provisioned InfluxDB datasource в Grafana;
- появление реальной measurement `system` от Telegraf в InfluxDB.

Проверка скачивает отсутствующие image layers и занимает заметно больше времени. Она не запускает Netdata, Mosquitto, openHAB или k6 и не использует рабочие `.env`/`.secrets`.
```

Keep the existing rejection list under the first level and the existing manifest explanation under the second level.

- [ ] **Step 6: Run the complete non-runtime suite**

```bash
python3 scripts/check_static.py
python3 scripts/test_init.py
python3 scripts/test_check_images.py
python3 scripts/test_runtime.py
sh -n scripts/*.sh
python3 -m py_compile scripts/*.py
./scripts/check.sh
```

Expected: all commands exit `0`. `./scripts/check.sh` must not start application containers.

- [ ] **Step 7: Commit CI and documentation**

```bash
git add Makefile README.md scripts/check_static.py .github/workflows/runtime.yml
git commit -m "ci: run isolated runtime smoke tests"
```

### Task 5: Prove the real Docker integration and merge

**Files:**
- Modify only files implicated by concrete CI failures.

**Interfaces:**
- Consumes: `make check-runtime` and GitHub-hosted Linux Docker runner.
- Produces: a green `Runtime smoke` check plus the existing `CI` and `Image platforms` checks.

- [ ] **Step 1: Review the final branch diff before opening the PR**

Run or inspect:

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Confirm the branch contains the approved spec, this plan, declarative isolation, the fake behavioral test, runtime harness, Make target, workflow, and documentation—nothing unrelated.

- [ ] **Step 2: Open a draft pull request**

Use title:

```text
Add isolated runtime smoke tests
```

The body must state that static/fake tests are already passing, while application-level runtime proof depends on the new GitHub Actions job. It must explicitly state that the test does not cover IoT, Netdata, public TLS, backups, or performance.

- [ ] **Step 3: Verify all three workflows on the current head**

Required conclusions:

```text
CI                          success
Image platforms             success, when triggered by changed paths
Runtime smoke               success
```

For `Runtime smoke`, verify the job output includes:

```text
OK: whoami rejects anonymous requests
OK: whoami accepts generated Basic Auth
OK: Traefik dashboard rejects anonymous requests
OK: Traefik dashboard accepts generated Basic Auth
OK: InfluxDB health route
OK: Grafana database health
OK: Portainer status route
OK: Grafana provisioned InfluxDB datasource
OK: Telegraf metrics reached InfluxDB
Runtime smoke test passed
```

- [ ] **Step 4: Diagnose failures from evidence only**

If the runtime job fails:

1. fetch the exact failed job steps and `runtime-smoke-log` artifact;
2. identify the first failed assertion or unhealthy service;
3. reproduce the failure with a focused test or add a fake-command regression when the bug is in shell control flow;
4. change only the implicated configuration or harness logic;
5. rerun `python3 scripts/test_runtime.py`, `./scripts/check.sh`, and all triggered workflows.

Do not increase timeouts until logs prove the service is healthy but merely slower. Do not suppress a failing assertion.

- [ ] **Step 5: Perform final review and mark the PR ready**

Confirm:

- source `.env` and `.secrets/` are untouched;
- runtime resources are prefixed by the unique project name;
- HTTP binds only to `127.0.0.1` during the test;
- exactly seven expected services start;
- all poll loops and job execution are bounded;
- failure diagnostics are useful and contain no generated credentials;
- `down --volumes --remove-orphans` is scoped to the unique runtime project;
- existing default names and `make up` behavior are unchanged.

- [ ] **Step 6: Squash merge only after fresh green checks**

Expected squash subject:

```text
Add isolated runtime smoke tests (#<PR number>)
```

After merge, verify the merge commit is the latest commit on `main` and that the `push`-triggered `Runtime smoke` workflow also succeeds.