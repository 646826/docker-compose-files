#!/usr/bin/env python3
"""Behavioral tests for the isolated Netdata and k6 runtime harness."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = ROOT / "scripts" / "check_optional_runtime.sh"


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


FAKE_DOCKER = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"

if [ "${1:-}" = "version" ]; then
  exit 0
fi

case " $* " in
  *" compose version "*)
    exit 0
    ;;
  *" config --quiet "*)
    env_file=
    previous=
    for argument in "$@"; do
      if [ "$previous" = "--env-file" ]; then
        env_file=$argument
      fi
      previous=$argument
    done
    [ -n "$env_file" ]
    workdir=$(dirname "$env_file")
    expected='runtime:$7$220000$placeholder$placeholder'
    actual=$(cat "$workdir/.secrets/mosquitto_passwords")
    [ "$actual" = "$expected" ] || {
      printf 'unexpected Mosquitto placeholder: %s\n' "$actual" >&2
      exit 65
    }
    netdata_port=$(sed -n 's/^NETDATA_PORT=//p' "$env_file")
    case "$netdata_port" in
      ''|*[!0-9]*)
        printf 'invalid NETDATA_PORT: %s\n' "$netdata_port" >&2
        exit 66
        ;;
    esac
    exit 0
    ;;
  *" up -d netdata "*)
    if [ "${FAKE_NETDATA_FAIL:-0}" = "1" ]; then
      printf 'simulated Netdata startup failure\n' >&2
      exit 42
    fi
    exit 0
    ;;
  *" up -d whoami "*)
    exit 0
    ;;
  *" run --rm k6 "*)
    if [ "${FAKE_K6_FAIL:-0}" = "1" ]; then
      printf 'simulated k6 threshold failure\n' >&2
      exit 43
    fi
    exit 0
    ;;
  *" ps --services --all "*)
    printf '%s\n' netdata whoami
    exit 0
    ;;
  *" ps --all "*)
    printf 'NAME STATUS\noptional-test running\n'
    exit 0
    ;;
  *" logs --no-color --tail=200 "*)
    printf 'bounded optional runtime diagnostics\n'
    exit 0
    ;;
  *" down --volumes --remove-orphans --timeout 30 "*)
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
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output|-o)
      output=$2
      shift 2
      ;;
    --max-time)
      shift 2
      ;;
    --silent|--show-error|--fail|-s|-S|-f)
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

[ -n "$output" ] || exit 65
case "$url" in
  */api/v1/info)
    printf '%s\n' '{"version":"test"}' >"$output"
    ;;
  *chart=system.cpu*)
    printf '%s\n' '{"id":"chart://hosts:test/instance:system.cpu/dimensions:*/after:-10","name":"chart://hosts:test/instance:system.cpu","result":{"labels":["time","user"],"data":[[1,2.5]]}}' >"$output"
    ;;
  *)
    printf 'unexpected fake curl URL: %s\n' "$url" >&2
    exit 66
    ;;
esac
'''


FAKE_OPENSSL = r'''#!/bin/sh
set -eu
[ "${1:-}" = "rand" ]
[ "${2:-}" = "-hex" ]
count=$(( ${3:-1} * 2 ))
i=0
while [ "$i" -lt "$count" ]; do
  printf 'b'
  i=$((i + 1))
done
printf '\n'
'''


class OptionalRuntimeHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(
            RUNTIME_SCRIPT.is_file(),
            "scripts/check_optional_runtime.sh is missing",
        )
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = self.root / "fixture"
        self.fake_bin = self.root / "bin"
        self.tmpdir = self.root / "tmp"
        self.fixture.mkdir()
        self.fake_bin.mkdir()
        self.tmpdir.mkdir()

        (self.fixture / "scripts").mkdir()
        shutil.copy2(
            RUNTIME_SCRIPT,
            self.fixture / "scripts" / "check_optional_runtime.sh",
        )
        shutil.copy2(ROOT / "compose.yaml", self.fixture / "compose.yaml")
        shutil.copytree(ROOT / "config", self.fixture / "config")

        (self.fixture / ".env").write_text(
            "SOURCE_ENV_SENTINEL=keep\n",
            encoding="utf-8",
        )
        (self.fixture / ".secrets").mkdir()
        (self.fixture / ".secrets" / "sentinel").write_text(
            "keep\n",
            encoding="utf-8",
        )

        write_executable(self.fake_bin / "docker", FAKE_DOCKER)
        write_executable(self.fake_bin / "curl", FAKE_CURL)
        write_executable(self.fake_bin / "openssl", FAKE_OPENSSL)
        self.docker_log = self.root / "docker.log"
        self.curl_log = self.root / "curl.log"

    def tearDown(self) -> None:
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def run_harness(
        self,
        *,
        netdata_fail: bool = False,
        k6_fail: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{environment['PATH']}",
                "TMPDIR": str(self.tmpdir),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_CURL_LOG": str(self.curl_log),
                "FAKE_NETDATA_FAIL": "1" if netdata_fail else "0",
                "FAKE_K6_FAIL": "1" if k6_fail else "0",
            }
        )
        return subprocess.run(
            ["sh", str(self.fixture / "scripts" / "check_optional_runtime.sh")],
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

    def test_success_verifies_netdata_and_k6_in_isolation(self) -> None:
        result = self.run_harness()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("--profile netdata --profile test", docker_log)
        self.assertNotIn("--profile monitoring", docker_log)
        self.assertNotIn("--profile tools", docker_log)
        self.assertNotIn("--profile iot", docker_log)
        self.assertRegex(
            docker_log,
            r"--project-name homelab-optional-runtime-[0-9]+-[a-f0-9]+",
        )
        for fragment in (
            "config --quiet",
            "up -d netdata",
            "up -d whoami",
            "run --rm k6",
            "ps --services --all",
            "down --volumes --remove-orphans --timeout 30",
        ):
            self.assertIn(fragment, docker_log)

        curl_log = self.curl_log.read_text(encoding="utf-8")
        self.assertIn("/api/v1/info", curl_log)
        self.assertIn("chart=system.cpu", curl_log)
        self.assertIn("points=1", curl_log)
        self.assertIn("after=-10", curl_log)
        self.assertIn("options=jsonwrap", curl_log)

        self.assertIn(
            "Optional runtime smoke test passed",
            result.stdout + result.stderr,
        )
        self.assert_source_state_preserved()

    def test_netdata_failure_prints_diagnostics_and_cleans_up(self) -> None:
        result = self.run_harness(netdata_fail=True)
        self.assertNotEqual(result.returncode, 0)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("up -d netdata", docker_log)
        self.assertNotIn("run --rm k6", docker_log)
        self.assertIn("ps --all", docker_log)
        self.assertIn("logs --no-color --tail=200", docker_log)
        self.assertIn("down --volumes --remove-orphans --timeout 30", docker_log)
        self.assertIn("Optional runtime diagnostics", result.stdout + result.stderr)
        self.assert_source_state_preserved()

    def test_k6_failure_propagates_and_cleans_up(self) -> None:
        result = self.run_harness(k6_fail=True)
        self.assertNotEqual(result.returncode, 0)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("up -d netdata", docker_log)
        self.assertIn("run --rm k6", docker_log)
        self.assertIn("ps --all", docker_log)
        self.assertIn("logs --no-color --tail=200", docker_log)
        self.assertIn("down --volumes --remove-orphans --timeout 30", docker_log)
        self.assertIn("Optional runtime diagnostics", result.stdout + result.stderr)
        self.assert_source_state_preserved()


if __name__ == "__main__":
    unittest.main(verbosity=2)
