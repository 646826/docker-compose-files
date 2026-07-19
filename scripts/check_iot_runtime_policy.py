#!/usr/bin/env python3
"""Focused static policy checks for the isolated IoT runtime workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
PBKDF2_COMMAND = "mosquitto_passwd -H sha512-pbkdf2 -I 220000 -c"


def error(message: str) -> None:
    ERRORS.append(message)


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        error(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def target_block(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
        makefile,
    )
    return match.group(0) if match else ""


def without_client_config_heredoc(script: str) -> str:
    return re.sub(
        r'(?ms)^cat >"\$WORKDIR/mosquitto-client\.conf" <<EOF\n.*?^EOF\n',
        "",
        script,
    )


def check_hashing_contract(label: str, script: str) -> None:
    if PBKDF2_COMMAND not in script:
        error(f"{label} must explicitly create a 220000-iteration SHA512-PBKDF2 record")
    for forbidden in (
        "mosquitto_passwd -H argon2id",
        "mosquitto_passwd -b",
        "mosquitto_passwd -U",
    ):
        if forbidden in script:
            error(f"{label} contains unsupported or unsafe password hashing behavior: {forbidden}")


def main() -> int:
    compose = read_required("compose.yaml")
    env_example = read_required(".env.example")
    makefile = read_required("Makefile")
    readme = read_required("README.md")
    security = read_required("SECURITY.md")
    init_script = read_required("scripts/init.sh")
    script = read_required("scripts/check_iot_runtime.sh")
    test_script = read_required("scripts/test_iot_runtime.py")
    workflow = read_required(".github/workflows/iot-runtime.yml")

    mqtt_binding = '"${MQTT_HOST_IP:-0.0.0.0}:${MQTT_PORT:-1883}:1883"'
    if compose and mqtt_binding not in compose:
        error("compose.yaml must support MQTT_HOST_IP with a 0.0.0.0 default")

    if env_example and "MQTT_HOST_IP=0.0.0.0" not in env_example:
        error(".env.example must document MQTT_HOST_IP=0.0.0.0")

    if makefile:
        block = target_block(makefile, "check-iot-runtime")
        if not block:
            error("Makefile target is missing: check-iot-runtime")
        else:
            if "sh ./scripts/check_iot_runtime.sh" not in block:
                error("make check-iot-runtime must run the IoT harness through POSIX sh")
            if re.search(r"(?m)^check-iot-runtime:\s+init\b", block):
                error("make check-iot-runtime must not reuse production initialization")

    if init_script:
        check_hashing_contract("normal bootstrap", init_script)

    if script:
        required_fragments = (
            "--profile iot",
            "MQTT_HOST_IP=127.0.0.1",
            "HTTP_HOST_IP=127.0.0.1",
            "--network host",
            "-o /run/mosquitto-client.conf",
            "-q 1",
            "-r",
            "-C 1",
            "-W 20",
            "restart --timeout 20 mosquitto",
            "down --volumes --remove-orphans --timeout 30",
            "logs --no-color --tail=200",
            "anonymous MQTT publish unexpectedly succeeded",
            "IoT runtime smoke test passed",
            "while [ \"$attempt\" -le 60 ]",
            "while [ \"$attempt\" -le 120 ]",
        )
        for fragment in required_fragments:
            if fragment not in script:
                error(f"IoT runtime harness is missing: {fragment}")

        check_hashing_contract("IoT runtime harness", script)

        forbidden_fragments = (
            "--profile monitoring",
            "--profile tools",
            "--profile netdata",
            "--profile test",
            '"$ROOT/.env"',
            '"$ROOT/.secrets',
            "docker system prune",
            "git reset --hard",
            "--env MQTT_PASSWORD",
            "--env-file $ROOT/.env",
        )
        for fragment in forbidden_fragments:
            if fragment in script:
                error(f"IoT runtime harness contains forbidden behavior: {fragment}")

        command_source = without_client_config_heredoc(script)
        if re.search(r"(?m)(?:^|\s)(?:-P|--pw)(?:\s|$)", command_source):
            error("MQTT password must not be passed in a client process argument")

    if test_script:
        for contract in (
            "test_success_is_isolated_and_proves_restart_persistence",
            "test_anonymous_publish_must_be_rejected",
            "test_startup_failure_prints_diagnostics_and_cleans_up",
            "-o /run/mosquitto-client.conf",
            "restart --timeout 20 mosquitto",
            PBKDF2_COMMAND,
        ):
            if contract not in test_script:
                error(f"IoT runtime behavioral contract is missing: {contract}")

    if workflow:
        required_workflow = (
            "make check-iot-runtime",
            "timeout-minutes: 30",
            "pull_request:",
            "schedule:",
            "contents: read",
            "retention-days: 3",
        )
        for fragment in required_workflow:
            if fragment not in workflow:
                error(f"IoT runtime workflow is missing: {fragment}")
        if "make init" in workflow:
            error("IoT runtime workflow must not initialize or reuse production credentials")

    for label, document in (("README", readme), ("SECURITY.md", security)):
        if document:
            if "SHA512-PBKDF2" not in document or "220000" not in document:
                error(f"{label} must document the supported Mosquitto hashing algorithm and work factor")
            if "Argon2id" in document:
                error(f"{label} must not claim Argon2id support for the official Mosquitto 2.1.2 images")

    if readme:
        if "make check-iot-runtime" not in readme:
            error("README must document make check-iot-runtime")
        if "MQTT_HOST_IP" not in readme:
            error("README must document MQTT_HOST_IP")

    check_script = read_required("scripts/check.sh")
    if check_script:
        if "python3 scripts/check_iot_runtime_policy.py" not in check_script:
            error("scripts/check.sh must run IoT runtime policy checks")
        if "python3 scripts/test_iot_runtime.py" not in check_script:
            error("scripts/check.sh must run IoT runtime behavioral tests")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print("IoT runtime policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
