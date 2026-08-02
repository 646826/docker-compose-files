#!/usr/bin/env python3
"""Static policy for opt-in community web services and authentication."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        ERRORS.append(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def target_block(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
        makefile,
    )
    return match.group(0) if match else ""


def require(text: str, label: str, fragments: tuple[str, ...]) -> None:
    for fragment in fragments:
        if fragment not in text:
            ERRORS.append(f"{label} is missing: {fragment}")


def forbid(text: str, label: str, fragments: tuple[str, ...]) -> None:
    for fragment in fragments:
        if fragment in text:
            ERRORS.append(f"{label} contains forbidden behavior: {fragment}")


def main() -> int:
    uptime = read_required("modules/uptime/compose.yaml")
    homepage = read_required("modules/dashboard/compose.yaml")
    dozzle = read_required("modules/logs/compose.yaml")
    auth = read_required("modules/auth/compose.yaml")
    root = read_required("compose.yaml")
    makefile = read_required("Makefile")
    check = read_required("scripts/check.sh")
    runtime = read_required("scripts/check_community_runtime.sh")
    runtime_tests = read_required("scripts/test_community_runtime.py")
    workflow = read_required(".github/workflows/community-runtime.yml")

    require(
        uptime,
        "Uptime Kuma module",
        (
            "image: louislam/uptime-kuma:2.3.2",
            "profiles: [uptime]",
            "uptime_kuma_data:/app/data",
            "middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}",
            "healthcheck:",
        ),
    )
    require(
        homepage,
        "Homepage module",
        (
            "image: ghcr.io/gethomepage/homepage:v1.13.1",
            "profiles: [dashboard]",
            "../../config/homepage:/app/config:ro",
            "HOMEPAGE_ALLOWED_HOSTS:",
            "middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}",
            "healthcheck:",
        ),
    )
    forbid(homepage, "Homepage module", ("/var/run/docker.sock", "DOCKER_HOST"))

    require(
        dozzle,
        "Dozzle module",
        (
            "image: amir20/dozzle:v10.6.2",
            "profiles: [logs]",
            "DOZZLE_REMOTE_HOST: tcp://docker-socket-proxy:2375",
            'DOZZLE_ENABLE_ACTIONS: "false"',
            'DOZZLE_ENABLE_SHELL: "false"',
            'DOZZLE_NO_ANALYTICS: "true"',
            "middlewares: ${AUTH_MIDDLEWARE:-local-auth@docker}",
        ),
    )
    forbid(dozzle, "Dozzle module", ("/var/run/docker.sock",))

    require(
        auth,
        "Authelia module",
        (
            "image: authelia/authelia:4.39.20",
            "profiles: [auth]",
            "AUTHELIA_SESSION_SECRET_FILE:",
            "AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE:",
            "AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET_FILE:",
            "/api/authz/forward-auth",
            "authelia_data:/data",
        ),
    )
    require(
        root,
        "root Compose secrets",
        (
            "authelia_jwt_secret:",
            "authelia_session_secret:",
            "authelia_storage_encryption_key:",
            "uptime_kuma_data:",
            "authelia_data:",
        ),
    )

    targets = {
        "uptime": "--profile uptime",
        "dashboard": "--profile dashboard",
        "auth-init": "scripts/init_community.py",
        "auth-check": "authelia config validate",
        "auth": "--profile auth",
        "dozzle": "--profile logs",
        "community": "--profile uptime --profile dashboard --profile logs",
    }
    for target, fragment in targets.items():
        block = target_block(makefile, target)
        if not block:
            ERRORS.append(f"Makefile target is missing: {target}")
        elif fragment not in block:
            ERRORS.append(f"Makefile target {target} is missing: {fragment}")

    community = target_block(makefile, "community")
    for forbidden in ("--profile dns", "--profile monitoring", "--profile iot"):
        if forbidden in community:
            ERRORS.append(f"make community must not include {forbidden}")
    full = target_block(makefile, "full")
    if "--profile dns" in full:
        ERRORS.append("make full must never start AdGuard Home")

    if check:
        for command in (
            "python3 scripts/check_community_services.py",
            "python3 scripts/test_community_runtime.py",
        ):
            if command not in check:
                ERRORS.append(f"fast checks must run: {command}")

    if runtime:
        require(
            runtime,
            "community runtime harness",
            (
                "--profile uptime",
                "--profile dashboard",
                "--profile logs",
                "expected_pattern=$5",
                'grep -Fq "$expected_pattern" "$RESPONSE_BODY"',
                'wait_http "uptime accepts generated Basic Auth" "$UPTIME_HOST" "$WORKDIR/auth.curl" 302 "/setup-database"',
                'wait_http "Homepage accepts generated Basic Auth" "$HOMEPAGE_HOST" "$WORKDIR/auth.curl" 200 ""',
                'wait_http "Dozzle accepts generated Basic Auth" "$DOZZLE_HOST" "$WORKDIR/auth.curl" 200 ""',
                "down --volumes --remove-orphans --timeout 30",
                "Community runtime smoke test passed",
            ),
        )
        forbid(runtime, "community runtime harness", ("--profile dns", "--profile auth"))

    if runtime_tests:
        for name in (
            "test_uptime_kuma_first_run_redirect_is_accepted",
            "test_homepage_and_dozzle_still_require_success_responses",
            "test_wait_http_validates_an_optional_response_pattern",
        ):
            if name not in runtime_tests:
                ERRORS.append(f"community runtime regression test is missing: {name}")

    if workflow:
        require(
            workflow,
            "community runtime workflow",
            (
                "name: Community runtime",
                "contents: read",
                "make check-community-runtime",
                "timeout-minutes: 20",
                "retention-days: 3",
            ),
        )

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Community service policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
