#!/usr/bin/env python3
"""Read-only preflight for starting AdGuard Home on a DNS listener."""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
import sys
from pathlib import Path

import doctor

ROOT = Path(__file__).resolve().parents[1]


def validate_bind_address(value: str) -> str:
    return str(ipaddress.ip_address(value))


def parse_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def diagnose_dns_port(
    bind_ip: str,
    port: int,
    listeners: set[tuple[str, int]],
    owner_text: str,
) -> list[str]:
    if doctor.classify_port(bind_ip, port, listeners) == "free":
        return []
    if "systemd-resolved" in owner_text or "systemd-resolve" in owner_text:
        return [
            f"{bind_ip}:{port} is owned by systemd-resolved; inspect the host resolver "
            "configuration and Docker's DNS requirements, but do not disable it automatically"
        ]
    owner = owner_text.strip() or "an existing process or container"
    return [f"{bind_ip}:{port} is already in use by {owner}"]


def read_env() -> dict[str, str]:
    return doctor.read_env(ROOT / ".env") or doctor.read_env(ROOT / ".env.example")


def listener_owner(port: int) -> str:
    ss = shutil.which("ss")
    if ss is None:
        return ""
    result = subprocess.run(
        [ss, "-lntup", f"sport = :{port}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode not in (0, 1):
        return ""
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return " | ".join(lines[1:] if len(lines) > 1 else lines)


def main() -> int:
    env = read_env()
    try:
        bind_ip = validate_bind_address(env.get("DNS_HOST_IP", "0.0.0.0"))
        port = parse_port(env.get("DNS_PORT", "53"))
    except (TypeError, ValueError) as exc:
        print(f"DNS preflight failed: invalid DNS_HOST_IP or DNS_PORT: {exc}", file=sys.stderr)
        return 1

    issues = diagnose_dns_port(
        bind_ip,
        port,
        doctor.listeners_from_proc(),
        listener_owner(port),
    )
    if issues:
        for issue in issues:
            print(f"DNS preflight failed: {issue}", file=sys.stderr)
        print(
            "Review docs/ADGUARD.md. No resolver, DHCP, firewall, or router setting was changed.",
            file=sys.stderr,
        )
        return 1

    print(f"DNS preflight passed: TCP/UDP listener {bind_ip}:{port} is available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
