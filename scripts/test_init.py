#!/usr/bin/env python3
"""Behavioral tests for the idempotent local-secret bootstrap."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise AssertionError(message)


def write_fake_docker(path: Path) -> None:
    path.write_text(
        r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"

case "${1:-}" in
  version)
    exit 0
    ;;
  run)
    case " $* " in
      *" --entrypoint htpasswd "*)
        username=
        for argument in "$@"; do
          username=$argument
        done
        IFS= read -r password
        [ -n "$password" ]
        printf '%s:$2y$12$abcdefghijklmnopqrstuuuuuuuuuuuuuuuuuuuuuuuuuuuu\n' "$username"
        ;;
      *" --entrypoint /bin/ash "*)
        username=
        for argument in "$@"; do
          case "$argument" in
            MOSQUITTO_USERNAME=*) username=${argument#MOSQUITTO_USERNAME=} ;;
          esac
        done
        [ -n "$username" ]
        IFS= read -r password
        [ -n "$password" ]
        printf '%s:$argon2id$v=19$m=19456,t=2,p=1$ZmFrZXNhbHQ$ZmFrZWhhc2g\n' "$username"
        ;;
      *)
        printf 'Unexpected docker run invocation: %s\n' "$*" >&2
        exit 2
        ;;
    esac
    ;;
  *)
    printf 'Unexpected docker invocation: %s\n' "$*" >&2
    exit 2
    ;;
esac
''',
        encoding="utf-8",
    )
    path.chmod(0o755)


def bootstrap_project(temp_root: Path, env_text: str) -> tuple[Path, dict[str, str]]:
    project = temp_root / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/init.sh", project / "scripts/init.sh")
    (project / ".env.example").write_text(env_text, encoding="utf-8")

    fake_bin = temp_root / "bin"
    fake_bin.mkdir()
    write_fake_docker(fake_bin / "docker")
    docker_log = temp_root / "docker.log"

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}"
    environment["FAKE_DOCKER_LOG"] = str(docker_log)
    return project, environment


def run_init(project: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "scripts/init.sh"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def assert_mode(path: Path, expected: int) -> None:
    actual = stat.S_IMODE(path.stat().st_mode)
    if actual != expected:
        fail(f"{path.name} mode is {actual:o}, expected {expected:o}")


def test_creates_secure_idempotent_secrets() -> None:
    env_text = """\
BASE_DOMAIN=localhost
TRAEFIK_USERNAME=test-admin
GRAFANA_ADMIN_USER=grafana-admin
INFLUXDB_USERNAME=test-influx
MOSQUITTO_USERNAME=test-mqtt
"""
    with tempfile.TemporaryDirectory(prefix="homelab-init-") as directory:
        temp_root = Path(directory)
        project, environment = bootstrap_project(temp_root, env_text)

        first = run_init(project, environment)
        if first.returncode != 0:
            fail(f"first init failed:\nstdout:\n{first.stdout}\nstderr:\n{first.stderr}")

        if (project / ".env").read_text(encoding="utf-8") != env_text:
            fail(".env was not copied exactly from .env.example")

        secrets = project / ".secrets"
        expected_files = {
            "influxdb_username",
            "influxdb_password",
            "influxdb_token",
            "grafana_admin_password",
            "traefik_password",
            "traefik_users",
            "mosquitto_password",
            "mosquitto_passwords",
        }
        if {path.name for path in secrets.iterdir()} != expected_files:
            fail("bootstrap created an unexpected secret-file set")

        assert_mode(secrets, 0o700)
        compose_secret_files = {
            "influxdb_username",
            "influxdb_password",
            "influxdb_token",
            "grafana_admin_password",
            "traefik_users",
            "mosquitto_passwords",
        }
        plaintext_files = {"traefik_password", "mosquitto_password"}
        for name in compose_secret_files:
            assert_mode(secrets / name, 0o644)
        for name in plaintext_files:
            assert_mode(secrets / name, 0o600)

        if (secrets / "influxdb_username").read_text(encoding="utf-8").strip() != "test-influx":
            fail("InfluxDB username did not come from .env")

        hex_lengths = {
            "influxdb_password": 48,
            "influxdb_token": 64,
            "grafana_admin_password": 48,
            "traefik_password": 36,
            "mosquitto_password": 36,
        }
        plaintext_values: list[str] = []
        for name, length in hex_lengths.items():
            raw = (secrets / name).read_bytes()
            if raw.endswith((b"\n", b"\r")):
                fail(f"{name} must not contain a trailing line ending")
            value = raw.decode("utf-8")
            plaintext_values.append(value)
            if not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
                fail(f"{name} is not a {length}-character random hex value")

        traefik_users = (secrets / "traefik_users").read_text(encoding="utf-8").strip()
        if not traefik_users.startswith("test-admin:$2y$12$"):
            fail("Traefik password file is not a cost-12 bcrypt record")

        mosquitto_users = (secrets / "mosquitto_passwords").read_text(encoding="utf-8").strip()
        if not mosquitto_users.startswith("test-mqtt:$argon2id$"):
            fail("Mosquitto password file is not an Argon2id record for the configured username")

        docker_log = Path(environment["FAKE_DOCKER_LOG"])
        docker_calls = docker_log.read_text(encoding="utf-8")
        if "mosquitto_passwd -b" in docker_calls:
            fail("bootstrap exposes the Mosquitto password through batch-mode arguments")
        if "mosquitto_passwd -U" not in docker_calls:
            fail("bootstrap does not convert the Mosquitto plaintext record with -U")
        if "--volume" in next(
            line for line in docker_calls.splitlines() if "eclipse-mosquitto:" in line
        ):
            fail("Mosquitto hashing should not mount the host secrets directory")

        combined_output = first.stdout + first.stderr
        for secret in plaintext_values:
            if secret in combined_output:
                fail("bootstrap printed a generated plaintext secret")

        before = {path.name: path.read_bytes() for path in secrets.iterdir()}
        docker_calls_before = docker_log.read_text(encoding="utf-8")

        second = run_init(project, environment)
        if second.returncode != 0:
            fail(f"second init failed:\nstdout:\n{second.stdout}\nstderr:\n{second.stderr}")
        after = {path.name: path.read_bytes() for path in secrets.iterdir()}
        if after != before:
            fail("second bootstrap changed an existing credential")
        if docker_log.read_text(encoding="utf-8") != docker_calls_before:
            fail("second bootstrap unnecessarily regenerated password hashes")


def test_rejects_username_drift_without_overwriting() -> None:
    env_text = """\
TRAEFIK_USERNAME=first-admin
INFLUXDB_USERNAME=first-influx
MOSQUITTO_USERNAME=first-mqtt
"""
    with tempfile.TemporaryDirectory(prefix="homelab-init-drift-") as directory:
        temp_root = Path(directory)
        project, environment = bootstrap_project(temp_root, env_text)

        first = run_init(project, environment)
        if first.returncode != 0:
            fail(f"initial setup failed before drift test: {first.stderr}")

        secrets = project / ".secrets"
        before = {path.name: path.read_bytes() for path in secrets.iterdir()}
        (project / ".env").write_text(
            env_text.replace("TRAEFIK_USERNAME=first-admin", "TRAEFIK_USERNAME=second-admin"),
            encoding="utf-8",
        )

        second = run_init(project, environment)
        if second.returncode == 0:
            fail("bootstrap silently accepted a username that no longer matches its hash file")
        if "TRAEFIK_USERNAME" not in second.stderr or "traefik_users" not in second.stderr:
            fail("bootstrap did not explain how to resolve username drift")
        after = {path.name: path.read_bytes() for path in secrets.iterdir()}
        if after != before:
            fail("username-drift validation modified an existing credential")


def test_rejects_unsafe_usernames_before_hashing() -> None:
    env_text = """\
TRAEFIK_USERNAME=bad:name
INFLUXDB_USERNAME=admin
MOSQUITTO_USERNAME=home
"""
    with tempfile.TemporaryDirectory(prefix="homelab-init-invalid-") as directory:
        temp_root = Path(directory)
        project, environment = bootstrap_project(temp_root, env_text)
        result = run_init(project, environment)
        if result.returncode == 0:
            fail("bootstrap accepted an unsafe Basic Auth username")
        if "TRAEFIK_USERNAME" not in result.stderr:
            fail("bootstrap did not explain the invalid username")
        docker_log = Path(environment["FAKE_DOCKER_LOG"])
        if docker_log.exists() and docker_log.read_text(encoding="utf-8"):
            fail("bootstrap invoked Docker before validating usernames")


def main() -> int:
    test_creates_secure_idempotent_secrets()
    test_rejects_username_drift_without_overwriting()
    test_rejects_unsafe_usernames_before_hashing()
    print("Bootstrap tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
