#!/usr/bin/env python3
"""Static policy checks specific to isolated runtime verification."""

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


def make_target_block(makefile: str, target: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(target)}:.*?(?=^[a-zA-Z0-9_-]+:|\Z)",
        makefile,
    )
    return match.group(0) if match else ""


def main() -> int:
    runtime_path = ROOT / "scripts/check_runtime.sh"
    if runtime_path.is_file() and not os.access(runtime_path, os.X_OK):
        error("scripts/check_runtime.sh must remain executable")

    makefile = read_required("Makefile")
    if makefile:
        runtime_target = make_target_block(makefile, "check-runtime")
        if not runtime_target:
            error("Makefile target is missing: check-runtime")
        elif "./scripts/check_runtime.sh" not in runtime_target:
            error("make check-runtime must execute scripts/check_runtime.sh")

        fast_target = make_target_block(makefile, "check")
        if "check-runtime" in fast_target or "check_runtime.sh" in fast_target:
            error("make check must not start the runtime stack")

    workflow = read_required(".github/workflows/runtime.yml")
    if workflow:
        required_workflow_fragments = (
            "name: Runtime smoke",
            "pull_request:",
            "schedule:",
            "workflow_dispatch:",
            "contents: read",
            "timeout-minutes: 25",
            "make check-runtime",
            "if: failure()",
            "actions/upload-artifact@v4",
            "retention-days: 3",
        )
        for fragment in required_workflow_fragments:
            if fragment not in workflow:
                error(f"runtime workflow is missing: {fragment}")
        if "make init" in workflow:
            error("runtime workflow must use disposable credentials, not make init")

    readme = read_required("README.md")
    if readme:
        required_readme_fragments = (
            "### 3. Изолированная runtime-проверка default stack",
            "make check-runtime",
            "127.0.0.1",
            "tmpfs",
            "Telegraf",
            "не читает рабочие `.env`/`.secrets/`",
        )
        for fragment in required_readme_fragments:
            if fragment not in readme:
                error(f"README runtime documentation is missing: {fragment}")

    init_script = read_required("scripts/init.sh")
    if init_script:
        required_init_fragments = (
            'printf \'%s\' "$value" >"$path"',
            'normalize_single_line_secret "$SECRETS_DIR/influxdb_token" influxdb_token',
            'printf \'%s\\n\' "$(cat "$SECRETS_DIR/traefik_password")"',
            'printf \'%s\\n\' "$(cat "$SECRETS_DIR/mosquitto_password")"',
        )
        for fragment in required_init_fragments:
            if fragment not in init_script:
                error(f"bootstrap newline-safety rule is missing: {fragment}")

    runtime_script = read_required("scripts/check_runtime.sh")
    if runtime_script:
        safe_token_write = (
            'printf \'%s\' "$INFLUXDB_TOKEN" '
            '>"$WORKDIR/.secrets/influxdb_token"'
        )
        if safe_token_write not in runtime_script:
            error("runtime InfluxDB token must be written without a line ending")
        unsafe_token_write = (
            'printf \'%s\\n\' "$INFLUXDB_TOKEN" '
            '>"$WORKDIR/.secrets/influxdb_token"'
        )
        if unsafe_token_write in runtime_script:
            error("runtime InfluxDB token must not contain a trailing newline")

    check_script = read_required("scripts/check.sh")
    if check_script and "python3 scripts/check_runtime_policy.py" not in check_script:
        error("scripts/check.sh must run the runtime policy checker")

    if ERRORS:
        for message in ERRORS:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    print("Runtime policy checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
