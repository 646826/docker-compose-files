#!/usr/bin/env python3
"""Focused static policy checks for the isolated IoT runtime workflow."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        error(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def main() -> int:
    compose = read_required("compose.yaml")
    env_example = read_required(".env.example")

    mqtt_binding = '"${MQTT_HOST_IP:-0.0.0.0}:${MQTT_PORT:-1883}:1883"'
    if compose and mqtt_binding not in compose:
        error("compose.yaml must support MQTT_HOST_IP with a 0.0.0.0 default")

    if env_example and "MQTT_HOST_IP=0.0.0.0" not in env_example:
        error(".env.example must document MQTT_HOST_IP=0.0.0.0")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print("IoT runtime policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
