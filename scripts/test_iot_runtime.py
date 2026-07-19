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

FAKE_SLEEP = r'''#!/bin/sh
exit 0
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
        write_executable(self.fake_bin / "sleep", FAKE_SLEEP)
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
