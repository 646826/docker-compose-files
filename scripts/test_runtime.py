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
    env_file=
    previous=
    for argument in "$@"; do
      if [ "$previous" = "--env-file" ]; then
        env_file=$argument
      fi
      previous=$argument
    done
    [ -n "$env_file" ]
    token_file=$(dirname "$env_file")/.secrets/influxdb_token
    python3 - "$token_file" <<'PY'
from pathlib import Path
import sys

data = Path(sys.argv[1]).read_bytes()
if not data:
    raise SystemExit("runtime token is empty")
if data.endswith((b"\n", b"\r")):
    raise SystemExit("runtime token has a trailing line ending")
PY
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
        if hasattr(self, "temporary"):
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

        combined_output = result.stdout + result.stderr
        self.assertIn("Runtime smoke test passed", combined_output)
        self.assertNotIn("a" * 64, combined_output)
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
