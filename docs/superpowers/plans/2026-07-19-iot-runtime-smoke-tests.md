# IoT Runtime Smoke Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated IoT runtime test that proves Mosquitto authentication, authenticated MQTT round trips, retained-message persistence after broker restart, and openHAB readiness through Traefik.

**Architecture:** The production Compose model gains an optional MQTT bind address while preserving its existing default. A POSIX shell harness creates a unique project and disposable credentials, starts only core plus the `iot` profile, exercises the published loopback MQTT port with short-lived official Mosquitto client containers, polls openHAB through Traefik, emits bounded diagnostics, and always removes only its own project and volumes. Standard-library behavioral tests use fake commands; a separate GitHub Actions workflow supplies the real Linux Docker integration proof.

**Tech Stack:** Docker Engine, Docker Compose v2, Eclipse Mosquitto 2.1 clients, POSIX shell, Python 3.11 standard library, curl, OpenSSL, GitHub Actions.

## Global Constraints

- The maintained target remains current Linux Docker Engine with Compose v2 on `linux/amd64` and `linux/arm64`.
- Existing deployments keep `0.0.0.0:${MQTT_PORT:-1883}` unless `MQTT_HOST_IP` is explicitly changed.
- The runtime test starts only profile-free core plus `--profile iot`; it must not enable `monitoring`, `tools`, `netdata`, or `test`.
- The runtime test must never read, modify, copy, or reuse the repository's existing `.env` or `.secrets/`.
- MQTT passwords must not appear in Docker command arguments, environment variables, console output, diagnostics, or workflow artifacts.
- MQTT client authentication uses a mode-`0600` config file and Mosquitto 2.1 `-o /run/mosquitto-client.conf`.
- Mosquitto state remains on the unique project-scoped named volume so retained persistence survives `compose restart mosquitto`.
- Both HTTP and MQTT are published only on random `127.0.0.1` ports during the runtime test.
- Broker readiness is bounded to 120 seconds; openHAB readiness is bounded to 600 seconds; Compose cleanup timeout is 30 seconds; workflow timeout is 30 minutes.
- Cleanup runs on success, assertion failure, startup failure, `HUP`, `INT`, and `TERM`, preserving the original exit status.
- `make check`, `make check-images`, and `make check-runtime` retain their existing responsibilities; IoT application runtime is exposed only as `make check-iot-runtime`.
- No third-party Python or shell dependency may be introduced.

---

### Task 1: Parameterize MQTT exposure and define static acceptance rules

**Files:**
- Modify: `scripts/check_static.py`
- Modify: `compose.yaml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: existing `MQTT_PORT` interpolation on the Mosquitto service.
- Produces: `MQTT_HOST_IP` interpolation used by the IoT runtime harness while retaining the production default.

- [ ] **Step 1: Add failing static rules**

In `scripts/check_static.py`, add this fragment to the existing `runtime_interpolation` tuple:

```python
'"${MQTT_HOST_IP:-0.0.0.0}:${MQTT_PORT:-1883}:1883"',
```

Add `MQTT_HOST_IP=0.0.0.0` to the `.env.example` required-setting tuple:

```python
for setting in (
    "HOMELAB_PROJECT_NAME=homelab",
    "HTTP_HOST_IP=0.0.0.0",
    "MQTT_HOST_IP=0.0.0.0",
):
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 scripts/check_static.py
```

Expected: non-zero with errors naming the missing MQTT bind interpolation and missing `.env.example` setting.

- [ ] **Step 3: Parameterize the Mosquitto binding**

Replace the Mosquitto port declaration in `compose.yaml` with:

```yaml
    ports:
      - "${MQTT_HOST_IP:-0.0.0.0}:${MQTT_PORT:-1883}:1883"
```

- [ ] **Step 4: Add the non-secret default**

In `.env.example`, place this directly before `MQTT_PORT=1883`:

```dotenv
# Bind MQTT to all interfaces by default. IoT runtime CI overrides this to 127.0.0.1.
MQTT_HOST_IP=0.0.0.0
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
python3 scripts/check_static.py
```

Expected: `Static checks passed`.

- [ ] **Step 6: Commit**

```bash
git add compose.yaml .env.example scripts/check_static.py
git commit -m "feat: parameterize MQTT host binding"
```

---

### Task 2: Define the IoT harness behavior before implementation

**Files:**
- Create: `scripts/test_iot_runtime.py`
- Modify: `scripts/check.sh`

**Interfaces:**
- Consumes: future `scripts/check_iot_runtime.sh` with no arguments.
- Produces: a fake Docker/curl/OpenSSL/Python contract for isolation, authentication, persistence, readiness, diagnostics, and cleanup.

- [ ] **Step 1: Create the failing behavioral test**

Create `scripts/test_iot_runtime.py` with the following complete content:

```python
#!/usr/bin/env python3
"""Behavioral tests for the isolated IoT runtime smoke-test harness."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOT_SCRIPT = ROOT / "scripts" / "check_iot_runtime.sh"


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


FAKE_DOCKER = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"

if [ "${1:-}" = "version" ]; then
  exit 0
fi

if [ "${1:-}" = "inspect" ]; then
  printf '/fake status=running health=healthy\n'
  exit 0
fi

if [ "${1:-}" = "run" ]; then
  case " $* " in
    *" --entrypoint htpasswd "*)
      IFS= read -r password
      [ -n "$password" ]
      printf 'runtime:$2y$12$abcdefghijklmnopqrstuuuuuuuuuuuuuuuuuuuuuuuuuuuu\n'
      exit 0
      ;;
    *" --entrypoint /bin/ash "*)
      IFS= read -r password
      [ -n "$password" ]
      printf 'runtime:$argon2id$v=19$m=19456,t=2,p=1$ZmFrZXNhbHQ$ZmFrZWhhc2g\n'
      exit 0
      ;;
    *" --entrypoint mosquitto_pub "*)
      case " $* " in
        *" -o /run/mosquitto-client.conf "*)
          case " $* " in
            *" -r "*)
              payload=
              previous=
              for argument in "$@"; do
                if [ "$previous" = "-m" ]; then payload=$argument; fi
                previous=$argument
              done
              printf '%s' "$payload" >"$FAKE_MQTT_STATE"
              ;;
          esac
          exit 0
          ;;
        *)
          if [ "${FAKE_ANONYMOUS_ACCEPT:-0}" = "1" ]; then exit 0; fi
          exit 5
          ;;
      esac
      ;;
    *" --entrypoint mosquitto_sub "*)
      [ -f "$FAKE_MQTT_STATE" ] || exit 6
      cat "$FAKE_MQTT_STATE"
      printf '\n'
      exit 0
      ;;
  esac
fi

case " $* " in
  *" compose version "*) exit 0 ;;
  *" config --quiet "*) exit 0 ;;
  *" config --services "*|*" ps --services --all "*)
    printf '%s\n' docker-socket-proxy traefik whoami mosquitto openhab
    exit 0
    ;;
  *" up -d "*)
    if [ "${FAKE_IOT_RUNTIME_FAIL:-0}" = "1" ]; then
      printf 'simulated IoT startup failure\n' >&2
      exit 42
    fi
    exit 0
    ;;
  *" restart --timeout 20 mosquitto "*) exit 0 ;;
  *" ps -q "*) printf '%s\n' fake-iot-1 fake-iot-2; exit 0 ;;
  *" ps --all "*) printf 'NAME STATUS\nfake running\n'; exit 0 ;;
  *" logs --no-color --tail=200 "*) printf 'bounded IoT diagnostics\n'; exit 0 ;;
  *" down --volumes --remove-orphans --timeout 30 "*) exit 0 ;;
esac

printf 'unexpected fake docker command: %s\n' "$*" >&2
exit 64
'''

FAKE_CURL = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_CURL_LOG"
output=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output|-o) output=$2; shift 2 ;;
    --resolve|--max-time|--max-redirs|--write-out|-w) shift 2 ;;
    --silent|--show-error|--location|-s|-S|-L) shift ;;
    http://*) shift ;;
    *) shift ;;
  esac
done
[ -n "$output" ] || exit 65
printf '<html><title>openHAB</title></html>\n' >"$output"
printf '200'
'''

FAKE_OPENSSL = r'''#!/bin/sh
set -eu
[ "${1:-}" = "rand" ]
[ "${2:-}" = "-hex" ]
case "${3:-}" in
  4) char=c ;;
  12) char=m ;;
  18) char=p ;;
  24) char=q ;;
  32) char=t ;;
  *) char=a ;;
esac
count=$(( ${3:-1} * 2 ))
i=0
while [ "$i" -lt "$count" ]; do printf '%s' "$char"; i=$((i + 1)); done
printf '\n'
'''

FAKE_PYTHON = r'''#!/bin/sh
set -eu
count=0
[ -f "$FAKE_PORT_COUNTER" ] && count=$(cat "$FAKE_PORT_COUNTER")
count=$((count + 1))
printf '%s' "$count" >"$FAKE_PORT_COUNTER"
if [ "$count" -eq 1 ]; then printf '18080\n'; else printf '18883\n'; fi
'''


class IoTRuntimeHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(IOT_SCRIPT.is_file(), "scripts/check_iot_runtime.sh is missing")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = self.root / "fixture"
        self.fake_bin = self.root / "bin"
        self.tmpdir = self.root / "tmp"
        self.fixture.mkdir()
        self.fake_bin.mkdir()
        self.tmpdir.mkdir()
        (self.fixture / "scripts").mkdir()
        shutil.copy2(IOT_SCRIPT, self.fixture / "scripts" / "check_iot_runtime.sh")
        shutil.copy2(ROOT / "scripts/init.sh", self.fixture / "scripts" / "init.sh")
        shutil.copy2(ROOT / "compose.yaml", self.fixture / "compose.yaml")
        shutil.copytree(ROOT / "config", self.fixture / "config")
        (self.fixture / ".env").write_text("SOURCE_ENV_SENTINEL=keep\n", encoding="utf-8")
        (self.fixture / ".secrets").mkdir()
        (self.fixture / ".secrets" / "sentinel").write_text("keep\n", encoding="utf-8")
        write_executable(self.fake_bin / "docker", FAKE_DOCKER)
        write_executable(self.fake_bin / "curl", FAKE_CURL)
        write_executable(self.fake_bin / "openssl", FAKE_OPENSSL)
        write_executable(self.fake_bin / "python3", FAKE_PYTHON)
        self.docker_log = self.root / "docker.log"
        self.curl_log = self.root / "curl.log"
        self.mqtt_state = self.root / "mqtt.state"
        self.port_counter = self.root / "ports"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_harness(
        self,
        *,
        fail: bool = False,
        anonymous_accept: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{environment['PATH']}",
                "TMPDIR": str(self.tmpdir),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_CURL_LOG": str(self.curl_log),
                "FAKE_MQTT_STATE": str(self.mqtt_state),
                "FAKE_PORT_COUNTER": str(self.port_counter),
                "FAKE_IOT_RUNTIME_FAIL": "1" if fail else "0",
                "FAKE_ANONYMOUS_ACCEPT": "1" if anonymous_accept else "0",
            }
        )
        return subprocess.run(
            ["/bin/sh", str(self.fixture / "scripts" / "check_iot_runtime.sh")],
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

    def test_success_is_isolated_and_proves_restart_persistence(self) -> None:
        result = self.run_harness()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("--profile iot", docker_log)
        for forbidden in ("--profile monitoring", "--profile tools", "--profile netdata", "--profile test"):
            self.assertNotIn(forbidden, docker_log)
        self.assertRegex(docker_log, r"--project-name homelab-iot-runtime-[0-9]+-[a-f0-9]+")
        self.assertIn("up -d", docker_log)
        self.assertIn("restart --timeout 20 mosquitto", docker_log)
        self.assertIn("down --volumes --remove-orphans --timeout 30", docker_log)
        self.assertIn("--network host", docker_log)
        self.assertIn("--entrypoint mosquitto_pub", docker_log)
        self.assertGreaterEqual(docker_log.count("--entrypoint mosquitto_sub"), 2)
        self.assertIn("-o /run/mosquitto-client.conf", docker_log)
        self.assertNotRegex(docker_log, r"(^| )-P( |$)")
        self.assertNotIn("p" * 36, docker_log)
        curl_log = self.curl_log.read_text(encoding="utf-8")
        self.assertIn("openhab.iot-runtime.localhost:18080:127.0.0.1", curl_log)
        self.assertIn("http://openhab.iot-runtime.localhost:18080/", curl_log)
        self.assertIn("IoT runtime smoke test passed", result.stdout)
        self.assert_source_state_preserved()

    def test_anonymous_publish_must_be_rejected(self) -> None:
        result = self.run_harness(anonymous_accept=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("anonymous MQTT publish unexpectedly succeeded", result.stdout + result.stderr)
        self.assertIn(
            "down --volumes --remove-orphans --timeout 30",
            self.docker_log.read_text(encoding="utf-8"),
        )
        self.assert_source_state_preserved()

    def test_startup_failure_prints_diagnostics_and_cleans_up(self) -> None:
        result = self.run_harness(fail=True)
        self.assertNotEqual(result.returncode, 0)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("ps --all", docker_log)
        self.assertIn("logs --no-color --tail=200", docker_log)
        self.assertIn("down --volumes --remove-orphans --timeout 30", docker_log)
        self.assertIn("IoT runtime diagnostics", result.stdout + result.stderr)
        self.assert_source_state_preserved()


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Wire the test into the fast suite**

Add this line to `scripts/check.sh` after `python3 scripts/test_runtime.py`:

```sh
python3 scripts/test_iot_runtime.py
```

- [ ] **Step 3: Verify RED**

Run:

```bash
python3 scripts/test_iot_runtime.py
```

Expected: three failures in `setUp` with `scripts/check_iot_runtime.sh is missing`.

- [ ] **Step 4: Commit the RED contract**

```bash
git add scripts/test_iot_runtime.py scripts/check.sh
git commit -m "test: define IoT runtime behavior"
```

---

### Task 3: Implement the isolated IoT runtime harness

**Files:**
- Create: `scripts/check_iot_runtime.sh`
- Test: `scripts/test_iot_runtime.py`

**Interfaces:**
- Consumes: `compose.yaml`, `config/`, `HTPASSWD_IMAGE`, and `MOSQUITTO_IMAGE` from `scripts/init.sh`.
- Produces: `scripts/check_iot_runtime.sh`, exiting `0` only after all MQTT and openHAB assertions pass.

- [ ] **Step 1: Implement the complete harness**

Create `scripts/check_iot_runtime.sh` with these required units and exact external interfaces:

```sh
#!/bin/sh
set -eu

ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
WORKDIR=
PROJECT_NAME=
HTTP_PORT=
MQTT_PORT=
BASE_DOMAIN=iot-runtime.localhost
MOSQUITTO_USERNAME=runtime
OPENHAB_HOST="openhab.$BASE_DOMAIN"
MQTT_STATUS=
OPENHAB_BODY=

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$WORKDIR/.env" \
    -f "$WORKDIR/compose.yaml" \
    --profile iot \
    "$@"
}
```

The final implementation must:

1. require `docker`, `curl`, `python3`, and `openssl`;
2. verify `docker version` and `docker compose version`;
3. create `WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/homelab-iot-runtime.XXXXXX")` and traps immediately;
4. generate `PROJECT_NAME="homelab-iot-runtime-$$-$(openssl rand -hex 4)"`;
5. allocate two distinct loopback ports through `python3 -c`;
6. copy only `compose.yaml` and `config/`;
7. generate private `.env`, `.secrets`, and client files;
8. generate Traefik bcrypt through the pinned `HTPASSWD_IMAGE`;
9. generate a Mosquitto Argon2id record through pinned `MOSQUITTO_IMAGE` and `mosquitto_passwd -U` using stdin;
10. create mode-`0600` client config:

```text
-u runtime
-P <password>
```

11. render `compose config --quiet`, then `compose up -d`;
12. verify exactly `docker-socket-proxy`, `traefik`, `whoami`, `mosquitto`, and `openhab` are present;
13. perform authenticated readiness publishes for at most 60 attempts with two-second sleeps;
14. require anonymous publish to exit non-zero;
15. publish a unique retained QoS 1 payload and subscribe with `-C 1 -W 20`;
16. sleep six seconds, restart with `compose restart --timeout 20 mosquitto`, wait for readiness, and subscribe again;
17. require both subscriptions to equal the exact payload;
18. poll openHAB for at most 120 attempts with five-second sleeps using:

```sh
curl \
  --silent \
  --show-error \
  --location \
  --max-redirs 5 \
  --max-time 15 \
  --resolve "$OPENHAB_HOST:$HTTP_PORT:127.0.0.1" \
  --output "$OPENHAB_BODY" \
  --write-out '%{http_code}' \
  "http://$OPENHAB_HOST:$HTTP_PORT/"
```

19. require final HTTP `200` and case-insensitive `openhab` in the response;
20. print `IoT runtime smoke test passed` only after all assertions;
21. on failure print `IoT runtime diagnostics`, `compose ps --all`, merged services, health summaries, final 200 log lines, safe MQTT operation labels, and at most 500 bytes of the openHAB response;
22. always run `compose down --volumes --remove-orphans --timeout 30` and remove `WORKDIR`.

All Mosquitto client containers must use this pattern, with no password argument or password environment variable:

```sh
docker run --rm --network host \
  --volume "$WORKDIR/mosquitto-client.conf:/run/mosquitto-client.conf:ro" \
  --entrypoint mosquitto_pub \
  "$MOSQUITTO_IMAGE" \
  -o /run/mosquitto-client.conf \
  -h 127.0.0.1 \
  -p "$MQTT_PORT" \
  ...
```

The anonymous probe deliberately omits the mounted config and `-o`.

- [ ] **Step 2: Verify behavioral GREEN**

Run:

```bash
python3 scripts/test_iot_runtime.py
sh -n scripts/check_iot_runtime.sh
```

Expected: all three tests pass and shell syntax exits `0`.

- [ ] **Step 3: Commit**

```bash
git add scripts/check_iot_runtime.sh
git commit -m "feat: add isolated IoT runtime harness"
```

---

### Task 4: Add focused policy enforcement, Make target, workflow, and documentation

**Files:**
- Create: `scripts/check_iot_runtime_policy.py`
- Modify: `scripts/check.sh`
- Modify: `scripts/check_static.py`
- Modify: `Makefile`
- Create: `.github/workflows/iot-runtime.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `scripts/check_iot_runtime.sh` and `scripts/test_iot_runtime.py`.
- Produces: `make check-iot-runtime`, fast policy coverage, and a network-backed GitHub Actions status check.

- [ ] **Step 1: Create the focused policy checker**

Create `scripts/check_iot_runtime_policy.py` using only the standard library. It must require these fragments in `scripts/check_iot_runtime.sh`:

```python
REQUIRED = (
    "--profile iot",
    "MQTT_HOST_IP=127.0.0.1",
    "HTTP_HOST_IP=127.0.0.1",
    "--network host",
    "-o /run/mosquitto-client.conf",
    "restart --timeout 20 mosquitto",
    "down --volumes --remove-orphans --timeout 30",
    "logs --no-color --tail=200",
    "anonymous MQTT publish unexpectedly succeeded",
    "IoT runtime smoke test passed",
)
```

It must reject:

```python
FORBIDDEN = (
    "--profile monitoring",
    "--profile tools",
    "--profile netdata",
    "--profile test",
    '"$ROOT/.env"',
    '"$ROOT/.secrets',
    "docker system prune",
    "git reset --hard",
)
```

It must also reject a regex matching password arguments in runtime client commands:

```python
re.search(r"(?m)(?:^|[\\s])(?:-P|--pw)(?:[\\s]|$)", script_without_client_config_heredoc)
```

The checker must print `IoT runtime policy checks passed` and return `0` on success; otherwise print one `ERROR:` line per violation and return `1`.

- [ ] **Step 2: Wire policy and behavior into `scripts/check.sh`**

Add:

```sh
python3 scripts/check_iot_runtime_policy.py
python3 scripts/test_iot_runtime.py
```

Keep runtime container startup out of `make check`.

- [ ] **Step 3: Extend static repository contracts**

In `scripts/check_static.py`:

- require `scripts/check_iot_runtime.sh`, `scripts/check_iot_runtime_policy.py`, `scripts/test_iot_runtime.py`, and `.github/workflows/iot-runtime.yml`;
- require Make target `check-iot-runtime`;
- require `sh ./scripts/check_iot_runtime.sh` in that target;
- require `make check-iot-runtime`, `timeout-minutes: 30`, `contents: read`, `pull_request:`, and `schedule:` in the workflow;
- require README to contain `make check-iot-runtime` and `MQTT_HOST_IP`.

- [ ] **Step 4: Add the Make target**

Update `.PHONY` and add:

```make
check-iot-runtime: ## Start the isolated IoT stack and verify MQTT auth/persistence plus openHAB readiness
	@sh ./scripts/check_iot_runtime.sh
```

- [ ] **Step 5: Add `.github/workflows/iot-runtime.yml`**

Create:

```yaml
name: IoT runtime smoke

on:
  push:
    branches:
      - main
    paths:
      - "compose.yaml"
      - ".env.example"
      - "Makefile"
      - "config/mosquitto/**"
      - "scripts/init.sh"
      - "scripts/check_iot_runtime.sh"
      - "scripts/check_iot_runtime_policy.py"
      - "scripts/test_iot_runtime.py"
      - ".github/workflows/iot-runtime.yml"
  pull_request:
    paths:
      - "compose.yaml"
      - ".env.example"
      - "Makefile"
      - "config/mosquitto/**"
      - "scripts/init.sh"
      - "scripts/check_iot_runtime.sh"
      - "scripts/check_iot_runtime_policy.py"
      - "scripts/test_iot_runtime.py"
      - ".github/workflows/iot-runtime.yml"
  schedule:
    - cron: "23 5 * * 0"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: iot-runtime-smoke-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  smoke:
    name: Verify MQTT and openHAB runtime
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Check out repository
        uses: actions/checkout@v6

      - name: Verify Docker and Compose
        run: |
          docker version
          docker compose version

      - name: Run isolated IoT runtime smoke test
        shell: bash
        run: |
          set -o pipefail
          make check-iot-runtime 2>&1 | tee iot-runtime-smoke.log

      - name: Upload failure diagnostics
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: iot-runtime-smoke-log
          path: iot-runtime-smoke.log
          if-no-files-found: error
          retention-days: 3
```

- [ ] **Step 6: Document the fourth validation layer**

Update the README command table and verification section to document:

```bash
make check-iot-runtime
```

State explicitly that it:

- runs only on Linux Docker Engine;
- pulls missing Mosquitto/openHAB layers;
- publishes HTTP and MQTT only on loopback random ports;
- verifies anonymous denial, authenticated retained round trip, retained persistence after restart, and openHAB readiness;
- does not install the openHAB MQTT Binding or test hardware/discovery protocols.

Document `MQTT_HOST_IP=0.0.0.0` as the normal deployment default.

- [ ] **Step 7: Run all non-network checks**

Run:

```bash
python3 scripts/check_static.py
python3 scripts/check_runtime_policy.py
python3 scripts/check_iot_runtime_policy.py
python3 scripts/test_init.py
python3 scripts/test_check_images.py
python3 scripts/test_runtime.py
python3 scripts/test_iot_runtime.py
sh -n scripts/*.sh
python3 -m py_compile scripts/*.py
```

Expected: every command exits `0`.

- [ ] **Step 8: Commit**

```bash
git add Makefile README.md scripts/check.sh scripts/check_static.py scripts/check_iot_runtime_policy.py .github/workflows/iot-runtime.yml
git commit -m "ci: verify IoT runtime behavior"
```

---

### Task 5: Prove the real integration and merge safely

**Files:**
- No planned production changes unless the real workflow exposes a reproducible defect.

**Interfaces:**
- Consumes: pull-request head and all four validation workflows.
- Produces: verified squash commit on `main`.

- [ ] **Step 1: Open a draft pull request after the RED commit**

The PR body must distinguish behavioral fake-command evidence from the real Docker integration and explicitly state current RED or GREEN status.

- [ ] **Step 2: Observe the intended RED CI failure**

Expected: normal CI fails only because `scripts/check_iot_runtime.sh` is missing.

- [ ] **Step 3: Push implementation and integration commits**

Expected pull-request workflows:

- `CI` — success;
- `Image platforms` — success when image-related paths changed;
- `Runtime smoke` — success if triggered by shared Compose changes;
- `IoT runtime smoke` — success.

- [ ] **Step 4: Inspect any IoT failure artifact before changing code**

Use the captured artifact to identify the exact failing stage. Fix only reproducible defects and add or strengthen a regression test before the fix.

- [ ] **Step 5: Final review**

Verify:

- no command argument or environment contains the MQTT password;
- no source `.env` or `.secrets/` path is opened;
- only `--profile iot` is enabled;
- no default-stack runtime files were coupled to openHAB startup;
- Mosquitto persistence uses the unique named volume and survives restart;
- cleanup is project-scoped and bounded;
- no third-party dependencies were added.

- [ ] **Step 6: Mark ready and squash merge only after fresh green evidence**

Record the exact final head SHA and workflow run numbers in the PR body or a final comment, then squash merge. Confirm the resulting commit is the newest commit on `main`.
