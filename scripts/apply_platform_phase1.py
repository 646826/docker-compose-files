#!/usr/bin/env python3
"""Apply the modular Compose and doctor implementation for phase 1."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n.*?(?=^  [a-zA-Z0-9_-]+:\s*\n|^networks:\s*\n)",
        compose,
    )
    if match is None:
        raise RuntimeError(f"service is missing from legacy compose: {service}")
    return match.group(0).rstrip() + "\n"


compose_path = ROOT / "compose.yaml"
legacy = compose_path.read_text(encoding="utf-8")
resources_index = legacy.index("networks:\n")
resources = legacy[resources_index:]
resources = replace_once(
    resources,
    "\nsecrets:\n",
    """
  uptime_kuma_data:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_uptime_kuma_data
  adguard_work:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_adguard_work
  adguard_config:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_adguard_config
  authelia_data:
    name: ${HOMELAB_PROJECT_NAME:-homelab}_authelia_data

secrets:
""",
    "new volume inventory",
)

module_groups = {
    "core": ("docker-socket-proxy", "traefik", "whoami"),
    "monitoring": ("influxdb", "telegraf", "grafana", "netdata", "k6"),
    "tools": ("portainer",),
    "iot": ("mosquitto", "openhab"),
}

for module, services in module_groups.items():
    blocks = []
    for service in services:
        block = service_block(legacy, service)
        if module in {"monitoring", "iot"}:
            block = block.replace("- ./config/", "- ../../config/")
        blocks.append(block)
    target = ROOT / "modules" / module / "compose.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"x-module-owner: {module}\n\nservices:\n" + "\n".join(blocks),
        encoding="utf-8",
    )

new_modules = {
    "uptime": '''x-module-owner: uptime

services:
  uptime-kuma:
    image: louislam/uptime-kuma:2.3.2
    profiles: [uptime]
    restart: unless-stopped
    volumes:
      - uptime_kuma_data:/app/data
    networks:
      - proxy
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD-SHELL", "node -e \"fetch('http://127.0.0.1:3001').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))\""]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 30s
    labels:
      traefik.enable: "true"
      traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
      traefik.http.routers.uptime.rule: Host(`uptime.${BASE_DOMAIN:-localhost}`)
      traefik.http.routers.uptime.entrypoints: web
      traefik.http.routers.uptime.middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}
      traefik.http.services.uptime.loadbalancer.server.port: "3001"
''',
    "dns": '''x-module-owner: dns

services:
  adguard-home:
    image: adguard/adguardhome:v0.107.76
    profiles: [dns]
    restart: unless-stopped
    ports:
      - "${DNS_HOST_IP:-0.0.0.0}:${DNS_PORT:-53}:53/tcp"
      - "${DNS_HOST_IP:-0.0.0.0}:${DNS_PORT:-53}:53/udp"
      - "${ADGUARD_SETUP_HOST_IP:-127.0.0.1}:${ADGUARD_SETUP_PORT:-3000}:3000/tcp"
    volumes:
      - adguard_work:/opt/adguardhome/work
      - adguard_config:/opt/adguardhome/conf
    networks:
      - proxy
    security_opt:
      - no-new-privileges:true
    labels:
      traefik.enable: "true"
      traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
      traefik.http.routers.adguard.rule: Host(`dns.${BASE_DOMAIN:-localhost}`)
      traefik.http.routers.adguard.entrypoints: web
      traefik.http.routers.adguard.middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}
      traefik.http.services.adguard.loadbalancer.server.port: "3000"
''',
    "dashboard": '''x-module-owner: dashboard

services:
  homepage:
    image: ghcr.io/gethomepage/homepage:v1.13.1
    profiles: [dashboard]
    restart: unless-stopped
    environment:
      HOMEPAGE_ALLOWED_HOSTS: home.${BASE_DOMAIN:-localhost}
    networks:
      - proxy
    security_opt:
      - no-new-privileges:true
    labels:
      traefik.enable: "true"
      traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
      traefik.http.routers.homepage.rule: Host(`home.${BASE_DOMAIN:-localhost}`)
      traefik.http.routers.homepage.entrypoints: web
      traefik.http.routers.homepage.middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}
      traefik.http.services.homepage.loadbalancer.server.port: "3000"
''',
    "auth": '''x-module-owner: auth

services:
  authelia:
    image: authelia/authelia:4.39.19
    profiles: [auth]
    restart: unless-stopped
    volumes:
      - authelia_data:/config
    networks:
      - proxy
    security_opt:
      - no-new-privileges:true
    labels:
      traefik.enable: "true"
      traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
      traefik.http.routers.authelia.rule: Host(`auth.${BASE_DOMAIN:-localhost}`)
      traefik.http.routers.authelia.entrypoints: web
      traefik.http.services.authelia.loadbalancer.server.port: "9091"
      traefik.http.middlewares.authelia.forwardauth.address: http://authelia:9091/api/authz/forward-auth
      traefik.http.middlewares.authelia.forwardauth.trustForwardHeader: "true"
      traefik.http.middlewares.authelia.forwardauth.authResponseHeaders: Remote-User,Remote-Groups,Remote-Email,Remote-Name
''',
    "logs": '''x-module-owner: logs

services:
  dozzle:
    image: amir20/dozzle:v10.6.2
    profiles: [logs]
    restart: unless-stopped
    depends_on:
      docker-socket-proxy:
        condition: service_healthy
    environment:
      DOZZLE_REMOTE_HOST: tcp://docker-socket-proxy:2375
      DOZZLE_NO_ANALYTICS: "true"
      DOZZLE_ENABLE_ACTIONS: "false"
      DOZZLE_ENABLE_SHELL: "false"
    networks:
      - proxy
      - socket
    security_opt:
      - no-new-privileges:true
    labels:
      traefik.enable: "true"
      traefik.docker.network: ${HOMELAB_PROJECT_NAME:-homelab}_proxy
      traefik.http.routers.dozzle.rule: Host(`logs.${BASE_DOMAIN:-localhost}`)
      traefik.http.routers.dozzle.entrypoints: web
      traefik.http.routers.dozzle.middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}
      traefik.http.services.dozzle.loadbalancer.server.port: "8080"
''',
}

for module, content in new_modules.items():
    target = ROOT / "modules" / module / "compose.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

include_lines = "\n".join(
    f"  - modules/{module}/compose.yaml"
    for module in ("core", "monitoring", "tools", "iot", "uptime", "dns", "dashboard", "auth", "logs")
)
compose_path.write_text(
    "name: ${HOMELAB_PROJECT_NAME:-homelab}\n\ninclude:\n"
    + include_lines
    + "\n\n"
    + resources,
    encoding="utf-8",
)

doctor_source = r'''#!/usr/bin/env python3
"""Read-only diagnostics for the homelab Compose project."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

ROOT = Path(__file__).resolve().parents[1]
MIN_COMPOSE_VERSION = (2, 20, 3)
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DOMAIN_RE = re.compile(r"^(?:localhost|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*)$")


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
    free_gib = disk.free / (1024 ** 3)
    if free_gib < 2:
        report.error("disk", f"only {free_gib:.1f} GiB is free")
    elif free_gib < 10:
        report.warning("disk", f"only {free_gib:.1f} GiB is free")
    else:
        report.ok("disk", f"{free_gib:.1f} GiB is free")

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", meminfo.read_text(), re.MULTILINE)
        if match:
            available_gib = int(match.group(1)) / (1024 ** 2)
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
        state = classify_port(host, port, listeners)
        if state == "conflict":
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
'''
(ROOT / "scripts" / "doctor.py").write_text(doctor_source, encoding="utf-8")

makefile_path = ROOT / "Makefile"
makefile = makefile_path.read_text(encoding="utf-8")
makefile = replace_once(
    makefile,
    "ALL_PROFILES := --profile monitoring --profile tools --profile iot --profile netdata --profile test",
    "ALL_PROFILES := --profile monitoring --profile tools --profile iot --profile netdata --profile test --profile uptime --profile dns --profile dashboard --profile auth --profile logs",
    "all profiles",
)
makefile = replace_once(
    makefile,
    ".PHONY: help init check",
    ".PHONY: help init doctor check",
    "doctor phony",
)
makefile = replace_once(
    makefile,
    "check: ## Validate static files, bootstrap behavior, shell scripts, and the full Compose model\n\t@./scripts/check.sh\n",
    "doctor: ## Diagnose Docker, Compose, host resources, ports, and local configuration\n\t@python3 scripts/doctor.py\n\ncheck: ## Validate static files, bootstrap behavior, shell scripts, and the full Compose model\n\t@./scripts/check.sh\n",
    "doctor target",
)
makefile_path.write_text(makefile, encoding="utf-8")

check_path = ROOT / "scripts" / "check.sh"
check = check_path.read_text(encoding="utf-8")
check = replace_once(
    check,
    'PROFILES="--profile monitoring --profile tools --profile iot --profile netdata --profile test"',
    'PROFILES="--profile monitoring --profile tools --profile iot --profile netdata --profile test --profile uptime --profile dns --profile dashboard --profile auth --profile logs"',
    "fast profile list",
)
check_path.write_text(check, encoding="utf-8")

images_path = ROOT / "scripts" / "check_images.py"
images = images_path.read_text(encoding="utf-8")
images = replace_once(
    images,
    '''    "--profile",
    "test",
)''',
    '''    "--profile",
    "test",
    "--profile",
    "uptime",
    "--profile",
    "dns",
    "--profile",
    "dashboard",
    "--profile",
    "auth",
    "--profile",
    "logs",
)''',
    "image profile list",
)
images_path.write_text(images, encoding="utf-8")

for relative in (
    "scripts/check_runtime.sh",
    "scripts/check_iot_runtime.sh",
    "scripts/check_optional_runtime.sh",
):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    marker = 'cp "$ROOT/compose.yaml" "$WORKDIR/compose.yaml"\n'
    if marker in text and 'cp -R "$ROOT/modules" "$WORKDIR/modules"' not in text:
        text = text.replace(marker, marker + 'cp -R "$ROOT/modules" "$WORKDIR/modules"\n', 1)
    path.write_text(text, encoding="utf-8")

static_path = ROOT / "scripts" / "check_static.py"
static = static_path.read_text(encoding="utf-8")
static = static.replace('        ROOT / "config",\n', '        ROOT / "config",\n        ROOT / "modules",\n', 1)
static = replace_once(
    static,
    '        "scripts/check_images.py",\n',
    '        "scripts/check_images.py",\n        "scripts/check_modules.py",\n        "scripts/doctor.py",\n        "scripts/test_doctor.py",\n',
    "static required platform files",
)
static = replace_once(
    static,
    '    compose = read_required("compose.yaml")\n    if compose:\n',
    '''    compose = read_required("compose.yaml")
    module_paths = (
        "modules/core/compose.yaml",
        "modules/monitoring/compose.yaml",
        "modules/tools/compose.yaml",
        "modules/iot/compose.yaml",
        "modules/uptime/compose.yaml",
        "modules/dns/compose.yaml",
        "modules/dashboard/compose.yaml",
        "modules/auth/compose.yaml",
        "modules/logs/compose.yaml",
    )
    module_text = "\n".join(read_required(path) for path in module_paths)
    compose_model = f"{compose}\n{module_text}"
    if compose:
''',
    "combined Compose model",
)
static = static.replace('if not service_block(compose, service):', 'if not service_block(compose_model, service):')
static = static.replace('re.search(rf"profiles:\\s*\\[[^\\]]*\\b{profile}\\b", compose)', 're.search(rf"profiles:\\s*\\[[^\\]]*\\b{profile}\\b", compose_model)')
static = static.replace('        check_images(compose)\n', '        check_images(compose_model)\n')
static = static.replace('if fragment not in compose:\n                error(f"runtime isolation interpolation is missing: {fragment}")', 'if fragment not in compose_model:\n                error(f"runtime isolation interpolation is missing: {fragment}")')
for service in ("traefik", "whoami", "telegraf", "grafana", "portainer", "netdata", "mosquitto"):
    static = static.replace(f'service_block(compose, "{service}")', f'service_block(compose_model, "{service}")')
static_path.write_text(static, encoding="utf-8")

iot_policy_path = ROOT / "scripts" / "check_iot_runtime_policy.py"
iot_policy = iot_policy_path.read_text(encoding="utf-8")
iot_policy = replace_once(
    iot_policy,
    '    compose = read_required("compose.yaml")\n',
    '    compose = read_required("compose.yaml") + "\\n" + read_required("modules/iot/compose.yaml")\n',
    "IoT module policy source",
)
iot_policy_path.write_text(iot_policy, encoding="utf-8")

optional_policy_path = ROOT / "scripts" / "check_optional_runtime_policy.py"
optional_policy = optional_policy_path.read_text(encoding="utf-8")
optional_policy = replace_once(
    optional_policy,
    '    compose = read_required("compose.yaml")\n',
    '    compose = read_required("compose.yaml") + "\\n" + read_required("modules/monitoring/compose.yaml")\n',
    "optional module policy source",
)
optional_policy_path.write_text(optional_policy, encoding="utf-8")

for workflow_path in (ROOT / ".github" / "workflows").glob("*.yml"):
    text = workflow_path.read_text(encoding="utf-8")
    if '"compose.yaml"' in text and '"modules/**"' not in text:
        text = text.replace('      - "compose.yaml"\n', '      - "compose.yaml"\n      - "modules/**"\n')
    workflow_path.write_text(text, encoding="utf-8")

readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8")
readme = replace_once(
    readme,
    '| `make init` | create local configuration and missing secrets |\n',
    '| `make init` | create local configuration and missing secrets |\n| `make doctor` | diagnose Docker, Compose, ports, resources, and local configuration without changing the host |\n',
    "doctor README command",
)
readme = replace_once(
    readme,
    '- one root `compose.yaml` instead of a collection of independent files;\n',
    '- one small root `compose.yaml` with independently maintained modules under `modules/`;\n',
    "modular README summary",
)
readme_path.write_text(readme, encoding="utf-8")

print("Platform phase 1 applied")
