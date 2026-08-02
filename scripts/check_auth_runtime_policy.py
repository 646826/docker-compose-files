#!/usr/bin/env python3
"""Static policy for isolated Authelia portal and ForwardAuth verification."""

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


def main() -> int:
    runtime = read_required("scripts/check_auth_runtime.sh")
    tests = read_required("scripts/test_auth_runtime.py")
    module = read_required("modules/auth/compose.yaml")
    makefile = read_required("Makefile")
    check = read_required("scripts/check.sh")
    workflow = read_required(".github/workflows/auth-runtime.yml")
    readme = read_required("README.md")
    modules_doc = read_required("docs/MODULES.md")

    if runtime:
        required = (
            'BASE_DOMAIN=auth-runtime.example.test',
            'AUTH_MIDDLEWARE=authelia@docker',
            'python3 "$WORKDIR/scripts/init_community.py"',
            'authelia config validate --config /config/configuration.yml',
            "--profile auth",
            "--profile dashboard",
            'wait_portal "auth.$BASE_DOMAIN"',
            'wait_forwardauth_redirect "home.$BASE_DOMAIN"',
            'https://auth.$BASE_DOMAIN',
            "down --volumes --remove-orphans --timeout 30",
            "Auth runtime smoke test passed",
        )
        for fragment in required:
            if fragment not in runtime:
                ERRORS.append(f"auth runtime harness is missing: {fragment}")
        for forbidden in (
            '"$ROOT/.env"',
            '"$ROOT/.secrets',
            "--profile dns",
            "docker system " + "prune",
        ):
            if forbidden in runtime:
                ERRORS.append(f"auth runtime harness contains forbidden behavior: {forbidden}")

    if tests:
        for name in (
            "test_harness_generates_disposable_configuration_and_validates_it",
            "test_harness_verifies_portal_and_forwardauth_redirect",
            "test_harness_is_isolated_and_cleanup_is_scoped",
            "test_authelia_has_an_explicit_bounded_healthcheck",
            "test_general_commands_include_auth_only_after_initialization",
        ):
            if name not in tests:
                ERRORS.append(f"auth runtime regression test is missing: {name}")

    if module:
        for fragment in (
            "image: authelia/authelia:4.39.20",
            "healthcheck:",
            "/app/healthcheck.sh",
            "start_period: 20s",
        ):
            if fragment not in module:
                ERRORS.append(f"Authelia module runtime contract is missing: {fragment}")

    if makefile:
        for fragment in (
            "AUTH_PROFILE := $(if $(wildcard .secrets/authelia_configuration.yml),--profile auth,)",
            "$(AUTH_PROFILE)",
        ):
            if fragment not in makefile:
                ERRORS.append(f"Makefile optional Auth profile contract is missing: {fragment}")

    block = target_block(makefile, "check-auth-runtime")
    if not block:
        ERRORS.append("Makefile target is missing: check-auth-runtime")
    elif "sh ./scripts/check_auth_runtime.sh" not in block:
        ERRORS.append("make check-auth-runtime must run the POSIX shell harness")

    if check:
        for command in (
            "python3 scripts/check_auth_runtime_policy.py",
            "python3 scripts/test_auth_runtime.py",
        ):
            if command not in check:
                ERRORS.append(f"fast checks must run: {command}")

    if workflow:
        for fragment in (
            "name: Auth runtime",
            "contents: read",
            "make check-auth-runtime",
            "timeout-minutes: 20",
            "retention-days: 3",
        ):
            if fragment not in workflow:
                ERRORS.append(f"auth runtime workflow is missing: {fragment}")

    for document, label in ((readme, "README.md"), (modules_doc, "docs/MODULES.md")):
        if document and "make check-auth-runtime" not in document:
            ERRORS.append(f"{label} must document make check-auth-runtime")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Auth runtime policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
