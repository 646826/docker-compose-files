#!/usr/bin/env python3
"""Static policy for versioned releases and complete community documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
MODULES = (
    "core",
    "monitoring",
    "tools",
    "iot",
    "uptime",
    "dns",
    "dashboard",
    "auth",
    "logs",
)


def read_required(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        ERRORS.append(f"{path} is missing")
        return ""
    return target.read_text(encoding="utf-8")


def main() -> int:
    version = read_required("VERSION").strip()
    changelog = read_required("CHANGELOG.md")
    modules = read_required("docs/MODULES.md")
    workflow = read_required(".github/workflows/release.yml")
    readme = read_required("README.md")
    security = read_required("SECURITY.md")
    check = read_required("scripts/check.sh")

    if version and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        ERRORS.append("VERSION must contain one semantic version")
    if version and version != "2.0.0":
        ERRORS.append("the initial modular platform release must be VERSION 2.0.0")

    for fragment in (
        "# Changelog",
        "## [2.0.0] - 2026-08-02",
        "Modular Compose",
        "Remote backup",
        "Uptime Kuma",
        "AdGuard Home",
        "Authelia",
        "Dozzle",
        "Trivy",
    ):
        if fragment not in changelog:
            ERRORS.append(f"CHANGELOG.md is missing: {fragment}")

    for module in MODULES:
        if f"`{module}`" not in modules:
            ERRORS.append(f"docs/MODULES.md does not document module: {module}")
    for fragment in (
        "Support level",
        "Profile",
        "Persistent volumes",
        "Secrets",
        "Elevated access",
        "Runtime verification",
        "make community",
        "make dns",
    ):
        if fragment not in modules:
            ERRORS.append(f"docs/MODULES.md is missing: {fragment}")

    for fragment in (
        "name: Release",
        'tags:\n      - "v*"',
        "contents: write",
        'test "$GITHUB_REF_NAME" = "v$(cat VERSION)"',
        "./scripts/check.sh",
        'gh release create "$GITHUB_REF_NAME"',
        "--verify-tag",
        "--generate-notes",
        "GH_TOKEN: ${{ github.token }}",
        "timeout-minutes: 20",
    ):
        if fragment not in workflow:
            ERRORS.append(f"release workflow is missing: {fragment}")
    for forbidden in ("softprops/action-gh-release", "ncipollo/release-action"):
        if forbidden in workflow:
            ERRORS.append(f"release workflow uses an unnecessary external action: {forbidden}")

    for fragment in (
        "docs/MODULES.md",
        "CHANGELOG.md",
        "VERSION",
        "make doctor",
        "make community",
        "make check-security",
    ):
        if fragment not in readme:
            ERRORS.append(f"README.md is missing release documentation: {fragment}")

    for fragment in (
        "Authelia",
        "AdGuard Home",
        "Dozzle",
        "restic",
        "Trivy",
        "security/exceptions.json",
    ):
        if fragment not in security:
            ERRORS.append(f"SECURITY.md is missing: {fragment}")

    if "python3 scripts/check_release_policy.py" not in check:
        ERRORS.append("scripts/check.sh must run the release policy")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    print("Release and documentation policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
