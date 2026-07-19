#!/usr/bin/env python3
"""Fast, dependency-free acceptance checks for the homelab repository."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        error(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n(.*?)(?=^  [a-zA-Z0-9_-]+:\s*\n|^[a-zA-Z][a-zA-Z0-9_-]*:\s*\n|\Z)",
        compose,
    )
    return match.group(0) if match else ""


def check_images(compose: str) -> None:
    images = re.findall(r"(?m)^\s{4}image:\s*['\"]?([^'\"#\s]+)", compose)
    if not images:
        error("compose.yaml contains no service images")
        return

    for image in images:
        final_component = image.rsplit("/", 1)[-1]
        if "@sha256:" not in image and ":" not in final_component:
            error(f"image has an implicit tag: {image}")
        if final_component.endswith(":latest") or final_component == "latest":
            error(f"image uses latest: {image}")


def tracked_secret_check() -> None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", ".env", ".secrets"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return

    if result.returncode == 0 and result.stdout.strip():
        error(f"generated local files are tracked: {result.stdout.strip()}")


def scan_operational_files() -> None:
    roots = [
        ROOT / "compose.yaml",
        ROOT / "Makefile",
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "config",
        ROOT / "scripts",
        ROOT / ".github",
    ]
    files: list[Path] = []
    for item in roots:
        if item.is_file():
            files.append(item)
        elif item.is_dir():
            files.extend(path for path in item.rglob("*") if path.is_file())

    leaked_values = (
        "bc183" + "SEgTbuNqxLyuGTd2s",
        "home-" + "token",
    )
    dangerous_commands = (
        "docker system " + "prune",
        "chmod " + "0777",
        "git reset " + "--hard",
    )

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT)
        for value in leaked_values:
            if value in text:
                error(f"known leaked credential remains in {relative}")
        for command in dangerous_commands:
            if command in text:
                error(f"destructive command remains in {relative}: {command}")


def main() -> int:
    required_files = (
        "compose.yaml",
        ".env.example",
        ".gitignore",
        "Makefile",
        "README.md",
        "SECURITY.md",
        "docs/MIGRATION.md",
        "docs/K3S.md",
        "config/telegraf/telegraf.conf",
        "config/mosquitto/mosquitto.conf",
        "config/grafana/provisioning/datasources/influxdb.yaml",
        "config/grafana/provisioning/dashboards/default.yaml",
        "config/grafana/dashboards/host-overview.json",
        "config/k6/smoke.js",
        "scripts/init.sh",
        "scripts/check.sh",
        "scripts/test_init.py",
        ".github/workflows/ci.yml",
        "renovate.json",
    )
    for path in required_files:
        if not (ROOT / path).is_file():
            error(f"{path} is missing")

    compose = read_required("compose.yaml")
    if compose:
        if re.search(r"(?m)^version:\s*", compose):
            error("compose.yaml uses the obsolete top-level version key")
        if not re.search(r"(?m)^name:\s*homelab\s*$", compose):
            error("compose.yaml must use the stable project name homelab")

        services = (
            "docker-socket-proxy",
            "traefik",
            "whoami",
            "influxdb",
            "telegraf",
            "grafana",
            "portainer",
            "netdata",
            "mosquitto",
            "openhab",
            "k6",
        )
        for service in services:
            if not service_block(compose, service):
                error(f"required service is missing: {service}")

        for profile in ("monitoring", "tools", "iot", "netdata", "test"):
            if not re.search(rf"profiles:\s*\[[^\]]*\b{profile}\b", compose):
                error(f"required Compose profile is missing: {profile}")

        check_images(compose)

        required_secrets = (
            "influxdb_username",
            "influxdb_password",
            "influxdb_token",
            "grafana_admin_password",
            "traefik_users",
            "mosquitto_passwords",
        )
        for secret in required_secrets:
            pattern = rf"(?ms)^  {secret}:\s*\n\s+file:\s+\./\.secrets/{secret}\s*$"
            if not re.search(pattern, compose):
                error(f"secret must be file-backed under .secrets: {secret}")

        traefik = service_block(compose, "traefik")
        if "--api.insecure=false" not in traefik:
            error("Traefik insecure API must be disabled")
        if "tcp://docker-socket-proxy:2375" not in traefik:
            error("Traefik must use docker-socket-proxy")
        if "/var/run/docker.sock" in traefik:
            error("Traefik must not mount the Docker socket directly")
        if "local-auth.basicauth.usersfile: /run/secrets/traefik_users" not in traefik:
            error("Traefik dashboard authentication must use a secret file")

        whoami = service_block(compose, "whoami")
        if "local-auth@docker" not in whoami:
            error("whoami must retain Basic Auth protection")

        telegraf_block = service_block(compose, "telegraf")
        if "/var/run/docker.sock" in telegraf_block:
            error("Telegraf must not mount the Docker socket directly")

        grafana_block = service_block(compose, "grafana")
        if "GF_SECURITY_ADMIN_PASSWORD__FILE: /run/secrets/grafana_admin_password" not in grafana_block:
            error("Grafana must use the official __FILE secret convention")
        if "export GF_SECURITY_ADMIN_PASSWORD=" in grafana_block:
            error("Grafana bootstrap must not duplicate the official password-file handling")

        portainer_block = service_block(compose, "portainer")
        if "command: --http-enabled" not in portainer_block:
            error("Portainer must explicitly keep its internal HTTP listener for Traefik")

        netdata_block = service_block(compose, "netdata")
        if "profiles: [netdata]" not in netdata_block:
            error("Netdata must use its own opt-in profile")

        mosquitto_block = service_block(compose, "mosquitto")
        required_runtime_password_steps = (
            "cp /run/secrets/mosquitto_passwords /run/mosquitto/passwords",
            "chown 1883:1883 /run/mosquitto/passwords",
            "chmod 0600 /run/mosquitto/passwords",
        )
        for step in required_runtime_password_steps:
            if step not in mosquitto_block:
                error(f"Mosquitto must prepare a private runtime password file: {step}")
        if "/run/mosquitto:mode=0700,uid=1883,gid=1883" not in mosquitto_block:
            error("Mosquitto must keep its runtime password file in a private tmpfs")

    gitignore = read_required(".gitignore")
    for ignored in (".env", ".secrets/"):
        if ignored not in gitignore:
            error(f".gitignore must ignore {ignored}")

    makefile = read_required("Makefile")
    if makefile:
        for target in ("init", "check", "core", "up", "full", "monitoring", "netdata", "tools", "iot", "k6", "pull", "ps", "logs", "down"):
            if not re.search(rf"(?m)^{target}:.*$", makefile):
                error(f"Makefile target is missing: {target}")
        down_match = re.search(r"(?ms)^down:.*?(?=^[a-zA-Z0-9_-]+:|\Z)", makefile)
        down_block = down_match.group(0) if down_match else ""
        if re.search(r"(?:^|\s)(?:-v|--volumes)(?:\s|$)", down_block):
            error("make down must preserve named volumes")
        if "DEFAULT_PROFILES := --profile monitoring --profile tools" not in makefile:
            error("make up must preserve the exact legacy monitoring + tools scope")
        if "DEFAULT_PROFILES := --profile monitoring --profile tools --profile netdata" in makefile:
            error("Netdata must remain opt-in and not join the legacy-equivalent default")

        for target in ("core", "up", "full", "monitoring", "netdata", "tools", "iot"):
            target_match = re.search(
                rf"(?ms)^{target}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)", makefile
            )
            target_block = target_match.group(0) if target_match else ""
            if "--remove-orphans" in target_block:
                error(
                    f"make {target} must not remove services started through another profile"
                )

    readme = read_required("README.md")
    if readme and "mosquitto:1883" not in readme:
        error("README must document the internal MQTT broker address for openHAB")

    k3s_doc = read_required("docs/K3S.md")
    if k3s_doc:
        if "/etc/rancher/k3s/config.yaml" not in k3s_doc:
            error("k3s same-host guidance must use a persistent config file")
        if not re.search(r"(?ms)^disable:\s*\n\s+- traefik\s*$", k3s_doc):
            error("k3s same-host guidance must persistently disable bundled Traefik")

    init_script = read_required("scripts/init.sh")
    if init_script:
        if "httpd:2.4.68-alpine" not in init_script:
            error("Traefik bootstrap helper image must be pinned")
        if "-B -C 12" not in init_script:
            error("Traefik bootstrap must generate a cost-12 bcrypt hash")
        if "openssl passwd -apr1" in init_script:
            error("Traefik bootstrap must not use legacy APR1-MD5 hashes")
        if "eclipse-mosquitto:2.1.2-alpine" not in init_script:
            error("Mosquitto bootstrap helper image must be pinned")
        if "mosquitto_passwd -b" in init_script:
            error("Mosquitto bootstrap must not expose passwords through batch-mode arguments")
        if "mosquitto_passwd -U" not in init_script:
            error("Mosquitto bootstrap must convert plaintext input with mosquitto_passwd -U")

    mosquitto_path = ROOT / "config/mosquitto/mosquitto.conf"
    if mosquitto_path.is_file():
        mosquitto = mosquitto_path.read_text(encoding="utf-8")
        required_mosquitto_config = (
            "user mosquitto",
            "global_plugin /usr/lib/mosquitto_persist_sqlite.so",
            "listener_allow_anonymous false",
            "plugin /usr/lib/mosquitto_password_file.so",
            "plugin_opt_password_file /run/mosquitto/passwords",
        )
        for directive in required_mosquitto_config:
            if directive not in mosquitto:
                error(f"Mosquitto 2.1 configuration is missing: {directive}")
        if re.search(r"(?m)^\s*persistence\s+true\s*$", mosquitto):
            error("Mosquitto must use the SQLite persistence plugin, not legacy snapshots")
        if re.search(r"(?m)^\s*password_file\s+", mosquitto):
            error("Mosquitto must use the 2.1 password-file plugin")
        if re.search(r"(?m)^\s*allow_anonymous\s+", mosquitto):
            error("Mosquitto 2.1 must use listener_allow_anonymous")

    dashboard_path = ROOT / "config/grafana/dashboards/host-overview.json"
    if dashboard_path.is_file():
        try:
            dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
            if dashboard.get("uid") != "host-overview":
                error("Grafana dashboard has an unexpected uid")
            if len(dashboard.get("panels", [])) < 4:
                error("Grafana dashboard must retain at least four host panels")
        except json.JSONDecodeError as exc:
            error(f"Grafana dashboard JSON is invalid: {exc}")

    telegraf_path = ROOT / "config/telegraf/telegraf.conf"
    if telegraf_path.is_file():
        try:
            with telegraf_path.open("rb") as handle:
                telegraf = tomllib.load(handle)
            if not telegraf.get("secretstores", {}).get("docker"):
                error("Telegraf Docker secret store is missing")
            outputs = telegraf.get("outputs", {}).get("influxdb_v2", [])
            if not outputs or "@{docker_secretstore:influxdb_token}" not in outputs[0].get("token", ""):
                error("Telegraf InfluxDB output does not use the mounted secret")
            if not telegraf.get("inputs", {}).get("docker"):
                error("Telegraf Docker input is missing")
        except tomllib.TOMLDecodeError as exc:
            error(f"Telegraf TOML is invalid: {exc}")

    renovate_path = ROOT / "renovate.json"
    if renovate_path.is_file():
        try:
            json.loads(renovate_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            error(f"renovate.json is invalid: {exc}")

    tracked_secret_check()
    scan_operational_files()

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print("Static checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
