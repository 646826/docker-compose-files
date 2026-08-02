#!/usr/bin/env python3
"""Static policy for pinned Trivy execution, SBOMs, and expiring exceptions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import security

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        ERRORS.append(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def main() -> int:
    implementation = read_required("scripts/security.py")
    tests = read_required("scripts/test_security.py")
    workflow = read_required(".github/workflows/security.yml")
    makefile = read_required("Makefile")
    check = read_required("scripts/check.sh")
    exceptions_path = ROOT / "security" / "exceptions.json"

    if implementation:
        for fragment in (
            'TRIVY_IMAGE = "ghcr.io/aquasecurity/trivy:0.70.0"',
            '"--format", "cyclonedx"',
            '"--ignore-unfixed"',
            '"CRITICAL"',
            "active_exceptions",
            "collect_fixable_critical",
        ):
            if fragment not in implementation:
                ERRORS.append(f"security implementation is missing: {fragment}")
        for forbidden in ("trivy-action", "setup-trivy", "shell=True"):
            if forbidden in implementation:
                ERRORS.append(f"security implementation contains forbidden behavior: {forbidden}")

    if tests:
        for test in (
            "test_active_exceptions_require_exact_image_id_owner_reason_and_future_date",
            "test_expired_duplicate_or_incomplete_exceptions_fail",
            "test_only_fixable_critical_vulnerabilities_are_returned",
            "test_command_uses_pinned_container_and_report_mount",
        ):
            if test not in tests:
                ERRORS.append(f"security regression test is missing: {test}")

    try:
        document = json.loads(exceptions_path.read_text(encoding="utf-8"))
        security.active_exceptions(document)
    except (OSError, UnicodeError, json.JSONDecodeError, security.SecurityPolicyError) as exc:
        ERRORS.append(f"security exceptions are invalid: {exc}")

    for target, fragment in (
        ("scan-images", "scripts/security.py scan"),
        ("sbom", "scripts/security.py sbom"),
        ("check-security", "scripts/security.py check"),
    ):
        if f"{target}:" not in makefile or fragment not in makefile:
            ERRORS.append(f"Makefile target is missing or incorrect: {target}")

    if check:
        for command in (
            "python3 scripts/check_security_policy.py",
            "python3 scripts/test_security.py",
        ):
            if command not in check:
                ERRORS.append(f"fast checks must run: {command}")

    if workflow:
        for fragment in (
            "name: Security",
            "contents: read",
            "make sbom",
            "make check-security",
            "timeout-minutes: 60",
            "retention-days: 3",
        ):
            if fragment not in workflow:
                ERRORS.append(f"security workflow is missing: {fragment}")
        for forbidden in ("aquasecurity/trivy-action", "aquasecurity/setup-trivy"):
            if forbidden in workflow:
                ERRORS.append(f"security workflow uses a forbidden mutable action: {forbidden}")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Security policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
