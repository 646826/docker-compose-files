#!/usr/bin/env python3
"""Static policy checks for isolated Netdata and k6 runtime verification."""

from __future__ import annotations

import os
import re
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


def target_block(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
        makefile,
    )
    return match.group(0) if match else ""


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n(.*?)(?=^  [a-zA-Z0-9_-]+:\s*\n|^[a-zA-Z][a-zA-Z0-9_-]*:\s*\n|\Z)",
        compose,
    )
    return match.group(0) if match else ""


def main() -> int:
    compose = read_required("compose.yaml")
    env_example = read_required(".env.example")
    makefile = read_required("Makefile")
    readme = read_required("README.md")
    script = read_required("scripts/check_optional_runtime.sh")
    test_script = read_required("scripts/test_optional_runtime.py")
    workflow = read_required(".github/workflows/optional-runtime.yml")
    check_script = read_required("scripts/check.sh")

    script_path = ROOT / "scripts/check_optional_runtime.sh"
    if script_path.is_file() and not os.access(script_path, os.X_OK):
        error("scripts/check_optional_runtime.sh must remain executable")

    netdata = service_block(compose, "netdata") if compose else ""
    if compose and not netdata:
        error("compose.yaml is missing the Netdata service")
    elif netdata and "NETDATA_LISTENER_PORT: ${NETDATA_PORT:-19999}" not in netdata:
        error("Netdata must derive its listener from NETDATA_PORT with a 19999 default")

    if env_example and "NETDATA_PORT=19999" not in env_example:
        error(".env.example must document NETDATA_PORT=19999")

    if makefile:
        block = target_block(makefile, "check-optional-runtime")
        if not block:
            error("Makefile target is missing: check-optional-runtime")
        else:
            if "sh ./scripts/check_optional_runtime.sh" not in block:
                error("make check-optional-runtime must run the harness through POSIX sh")
            if re.search(r"(?m)^check-optional-runtime:\s+init\b", block):
                error("make check-optional-runtime must not reuse production initialization")

        fast_block = target_block(makefile, "check")
        if "check_optional_runtime.sh" in fast_block or "check-optional-runtime" in fast_block:
            error("make check must not start the optional runtime stack")

    if script:
        required_fragments = (
            "mktemp -d",
            'chmod 700 "$WORKDIR"',
            "--profile netdata",
            "--profile test",
            "NETDATA_PORT=$NETDATA_PORT",
            'sock.bind(("127.0.0.1", 0))',
            "/api/v1/info",
            "chart=system.cpu",
            "points=1",
            "after=-10",
            "options=jsonwrap",
            "run --rm k6",
            "down --volumes --remove-orphans --timeout 30",
            "logs --no-color --tail=200",
            "runtime:$7$220000$placeholder$placeholder",
            "Optional runtime smoke test passed",
        )
        for fragment in required_fragments:
            if fragment not in script:
                error(f"optional runtime harness is missing: {fragment}")

        forbidden_fragments = (
            "--profile monitoring",
            "--profile tools",
            "--profile iot",
            '"$ROOT/.env"',
            '"$ROOT/.secrets',
            "docker system " + "prune",
            "git reset " + "--hard",
            "chmod " + "0777",
        )
        for fragment in forbidden_fragments:
            if fragment in script:
                error(f"optional runtime harness contains forbidden behavior: {fragment}")

    if test_script:
        required_tests = (
            "test_success_verifies_netdata_and_k6_in_isolation",
            "test_netdata_failure_prints_diagnostics_and_cleans_up",
            "test_k6_failure_propagates_and_cleans_up",
            "runtime:$7$220000$placeholder$placeholder",
            "down --volumes --remove-orphans --timeout 30",
        )
        for fragment in required_tests:
            if fragment not in test_script:
                error(f"optional runtime behavioral contract is missing: {fragment}")

    if workflow:
        required_workflow = (
            "name: Optional runtime smoke",
            "pull_request:",
            "schedule:",
            "workflow_dispatch:",
            "contents: read",
            "timeout-minutes: 25",
            "make check-optional-runtime",
            "if: failure()",
            "actions/upload-artifact@v4",
            "retention-days: 3",
        )
        for fragment in required_workflow:
            if fragment not in workflow:
                error(f"optional runtime workflow is missing: {fragment}")
        if "make init" in workflow:
            error("optional runtime workflow must not initialize production credentials")

    if readme:
        required_readme = (
            "## Six verification levels",
            "### 6. Isolated optional-profile runtime check",
            "make check-optional-runtime",
            "NETDATA_PORT",
            "system.cpu",
            "k6",
            "random",
        )
        for fragment in required_readme:
            if fragment not in readme:
                error(f"README optional runtime documentation is missing: {fragment}")

    if check_script:
        if "python3 scripts/check_optional_runtime_policy.py" not in check_script:
            error("scripts/check.sh must run optional runtime policy checks")
        if "python3 scripts/test_optional_runtime.py" not in check_script:
            error("scripts/check.sh must run optional runtime behavioral tests")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print("Optional runtime policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
