#!/usr/bin/env python3
"""Read-only diagnostics for the homelab Compose project."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
MIN_COMPOSE_VERSION = (2, 20, 3)
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DOMAIN_RE = re.compile(
    r"^(?:localhost|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*)$"
)


class DoctorIssue(NamedTuple):
    severity: str
    check: str
    message: str


class DoctorReport:
    def __init__(self) -> None:
        self.issues: list[DoctorIssue] = []

    def ok(self, check: str, message: str) -> None:
        self.issues.append(DoctorIssue("ok", check, message))

    def warning(self, check: str, message: str) -> None:
        self.issues.append(DoctorIssue("warning", check, message))

    def error(self, check: str, message: str) -> None:
        self.issues.append(DoctorIssue("error", check, message))

    def exit_code(self, *, strict: bool) -> int:
        if any(issue.severity == "error" for issue in self.issues):
            return 1
        if strict and any(issue.severity == "warning" for issue in self.issues):
            return 1
        return 0

    def as_json(self) -> str:
        return json.dumps([issue._asdict() for issue in self.issues], indent=2)


def parse_compose_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(?:^|\D)(\d+)\.(\d+)(?:\.(\d+))?", text)
    if match is None:
        raise ValueError(f"cannot parse Compose version: {text.strip()!r}")
    return tuple(int(value) for value in match.groups(default="0"))


def compose_version_supported(version: Sequence[int]) -> bool:
    padded = tuple(version) + (0,) * max(0, 3 - len(version))
    return padded[:3] >= MIN_COMPOSE_VERSION


def valid_project_name(value: str) -> bool:
    return bool(PROJECT_RE.fullmatch(value))


def valid_domain(value: str) -> bool:
    return bool(DOMAIN_RE.fullmatch(value.lower()))


def classify_port(bind_ip: str, port: int, listeners: set[tuple[str, int]]) -> str:
    requested = ipaddress.ip_address(bind_ip)
    for listener_ip, listener_port in listeners:
        if listener_port != port:
            continue
        current = ipaddress.ip_address(listener_ip)
        if requested.version != current.version:
            if requested.is_unspecified or current.is_unspecified:
                return "conflict"
            continue
        if requested.is_unspecified or current.is_unspecified or requested == current:
            return "conflict"
    return "free"


def run(command: Sequence[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def listeners_from_proc() -> set[tuple[str, int]]:
    listeners: set[tuple[str, int]] = set()
    for relative, family in (
        ("/proc/net/tcp", socket.AF_INET),
        ("/proc/net/udp", socket.AF_INET),
        ("/proc/net/tcp6", socket.AF_INET6),
        ("/proc/net/udp6", socket.AF_INET6),
    ):
        path = Path(relative)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="ascii", errors="ignore").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 2 or ":" not in fields[1]:
                continue
            encoded_host, encoded_port = fields[1].split(":", 1)
            try:
                packed = bytes.fromhex(encoded_host)
                if family == socket.AF_INET:
                    host = socket.inet_ntop(family, packed[::-1])
                else:
                    words = [packed[index:index + 4][::-1] for index in range(0, 16, 4)]
                    host = socket.inet_ntop(family, b"".join(words))
                listeners.add((host, int(encoded_port, 16)))
            except (OSError, ValueError):
                continue
    return listeners


def collect_report() -> DoctorReport:
    report = DoctorReport()
    env = read_env(ROOT / ".env") or read_env(ROOT / ".env.example")

    docker = shutil.which("docker")
    if docker is None:
        report.error("docker", "Docker CLI is not installed")
    else:
        daemon = run((docker, "info", "--format", "{{.ServerVersion}}"))
        if daemon.returncode == 0:
            report.ok("docker", f"Docker daemon is available ({daemon.stdout.strip()})")
        else:
            report.error("docker", daemon.stderr.strip() or "Docker daemon is unavailable")

        compose = run((docker, "compose", "version", "--short"))
        if compose.returncode != 0:
            report.error("compose", compose.stderr.strip() or "Docker Compose plugin is unavailable")
        else:
            try:
                version = parse_compose_version(compose.stdout)
            except ValueError as exc:
                report.error("compose", str(exc))
            else:
                if compose_version_supported(version):
                    report.ok("compose", f"Compose {'.'.join(map(str, version))} supports include")
                else:
                    report.error("compose", "Docker Compose 2.20.3 or newer is required")

    project = env.get("HOMELAB_PROJECT_NAME", "homelab")
    if valid_project_name(project):
        report.ok("project", f"project name is valid: {project}")
    else:
        report.error("project", f"invalid HOMELAB_PROJECT_NAME: {project}")

    domain = env.get("BASE_DOMAIN", "localhost")
    if valid_domain(domain):
        report.ok("domain", f"base domain is valid: {domain}")
    else:
        report.error("domain", f"invalid BASE_DOMAIN: {domain}")

    secrets_dir = ROOT / ".secrets"
    if not secrets_dir.exists():
        report.warning("secrets", "run `make init` to create local secrets")
    elif not secrets_dir.is_dir():
        report.error("secrets", ".secrets exists but is not a directory")
    else:
        mode = secrets_dir.stat().st_mode & 0o777
        if mode == 0o700:
            report.ok("secrets", ".secrets directory mode is 0700")
        else:
            report.error("secrets", f".secrets directory mode is {mode:04o}, expected 0700")

    disk = shutil.disk_usage(ROOT)
    free_gib = disk.free / (1024**3)
    if free_gib < 2:
        report.error("disk", f"only {free_gib:.1f} GiB is free")
    elif free_gib < 10:
        report.warning("disk", f"only {free_gib:.1f} GiB is free")
    else:
        report.ok("disk", f"{free_gib:.1f} GiB is free")

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        match = re.search(
            r"^MemAvailable:\s+(\d+)\s+kB",
            meminfo.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            available_gib = int(match.group(1)) / (1024**2)
            if available_gib < 1:
                report.warning("memory", f"only {available_gib:.1f} GiB is available")
            else:
                report.ok("memory", f"{available_gib:.1f} GiB is available")

    listeners = listeners_from_proc()
    port_settings = (
        ("HTTP_HOST_IP", "HTTP_PORT", "0.0.0.0", 80),
        ("MQTT_HOST_IP", "MQTT_PORT", "0.0.0.0", 1883),
        ("NETDATA_HOST_IP", "NETDATA_PORT", "0.0.0.0", 19999),
        ("DNS_HOST_IP", "DNS_PORT", "0.0.0.0", 53),
        ("ADGUARD_SETUP_HOST_IP", "ADGUARD_SETUP_PORT", "127.0.0.1", 3000),
    )
    for host_key, port_key, default_host, default_port in port_settings:
        host = env.get(host_key, default_host)
        try:
            ipaddress.ip_address(host)
            port = int(env.get(port_key, str(default_port)))
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            report.error("ports", f"invalid {host_key}/{port_key} setting")
            continue
        if classify_port(host, port, listeners) == "conflict":
            report.warning("ports", f"{host}:{port} is already in use")
        else:
            report.ok("ports", f"{host}:{port} is available")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    report = collect_report()
    if args.json_output:
        print(report.as_json())
    else:
        labels = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
        for issue in report.issues:
            print(f"[{labels[issue.severity]}] {issue.check}: {issue.message}")
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
