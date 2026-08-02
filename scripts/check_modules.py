#!/usr/bin/env python3
"""Static contract for the modular Compose application."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "core": {"docker-socket-proxy", "traefik", "whoami"},
    "monitoring": {"influxdb", "telegraf", "grafana", "netdata", "k6"},
    "tools": {"portainer"},
    "iot": {"mosquitto", "openhab"},
    "uptime": {"uptime-kuma"},
    "dns": {"adguard-home"},
    "dashboard": {"homepage"},
    "auth": {"authelia"},
    "logs": {"dozzle"},
}


def service_names(text: str) -> set[str]:
    """Return service keys from a Compose file with two-space service indentation."""
    services_match = re.search(r"(?ms)^services:\s*\n(.*?)(?=^[a-zA-Z][\w-]*:\s*\n|\Z)", text)
    if services_match is None:
        return set()
    return set(re.findall(r"(?m)^  ([a-zA-Z0-9_-]+):\s*$", services_match.group(1)))


def main() -> int:
    errors: list[str] = []
    root_path = ROOT / "compose.yaml"
    if not root_path.is_file():
        errors.append("compose.yaml is missing")
        root = ""
    else:
        root = root_path.read_text(encoding="utf-8")

    if "include:" not in root:
        errors.append("compose.yaml must use the top-level include element")

    seen: set[str] = set()
    for module, expected in MODULES.items():
        relative = f"modules/{module}/compose.yaml"
        if relative not in root:
            errors.append(f"compose.yaml must include {relative}")
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"{relative} is missing")
            continue
        text = path.read_text(encoding="utf-8")
        actual = service_names(text)
        missing = expected - actual
        unexpected_duplicates = actual & seen
        for service in sorted(missing):
            errors.append(f"{relative} is missing service: {service}")
        for service in sorted(unexpected_duplicates):
            errors.append(f"service is declared by multiple modules: {service}")
        seen.update(actual)

        for image in re.findall(r"(?m)^\s{4}image:\s*([^\s#]+)", text):
            final = image.rsplit("/", 1)[-1]
            if ":" not in final or final.endswith(":latest"):
                errors.append(f"{relative} has an unpinned image: {image}")

    expected_services = set().union(*MODULES.values())
    if seen != expected_services:
        missing = expected_services - seen
        extra = seen - expected_services
        if missing:
            errors.append(f"modular service inventory is incomplete: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"modular service inventory has unknown entries: {', '.join(sorted(extra))}")

    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print("Compose module policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
