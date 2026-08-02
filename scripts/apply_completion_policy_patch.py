#!/usr/bin/env python3
"""Apply one deterministic source migration, then remove this temporary helper."""

from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


static_path = Path("scripts/check_static.py")
static = static_path.read_text(encoding="utf-8")

static = replace_once(
    static,
    '''        "scripts/check_images.py",
        "scripts/check_runtime.sh",
        "scripts/backup.py",
        "scripts/check_backup_policy.py",
        "scripts/check_backup_runtime.sh",
        "scripts/test_backup.py",
        "scripts/test_init.py",
        "scripts/test_check_images.py",
        "scripts/test_runtime.py",
        ".github/workflows/ci.yml",
        ".github/workflows/images.yml",
        ".github/workflows/backup-runtime.yml",
''',
    '''        "scripts/check_images.py",
        "scripts/check_runtime.sh",
        "scripts/check_runtime_policy.py",
        "scripts/check_iot_runtime.sh",
        "scripts/check_iot_runtime_policy.py",
        "scripts/check_optional_runtime.sh",
        "scripts/check_optional_runtime_policy.py",
        "scripts/check_english_only.py",
        "scripts/backup.py",
        "scripts/check_backup_policy.py",
        "scripts/check_backup_runtime.sh",
        "scripts/test_backup.py",
        "scripts/test_init.py",
        "scripts/test_check_images.py",
        "scripts/test_runtime.py",
        "scripts/test_iot_runtime.py",
        "scripts/test_optional_runtime.py",
        "scripts/test_english_only.py",
        ".github/workflows/ci.yml",
        ".github/workflows/images.yml",
        ".github/workflows/runtime.yml",
        ".github/workflows/iot-runtime.yml",
        ".github/workflows/optional-runtime.yml",
        ".github/workflows/backup-runtime.yml",
''',
    "required files",
)

static = replace_once(
    static,
    '''        for setting in (
            "HOMELAB_PROJECT_NAME=homelab",
            "HTTP_HOST_IP=0.0.0.0",
        ):
''',
    '''        for setting in (
            "HOMELAB_PROJECT_NAME=homelab",
            "HTTP_HOST_IP=0.0.0.0",
            "MQTT_HOST_IP=0.0.0.0",
            "NETDATA_PORT=19999",
        ):
''',
    "environment defaults",
)

static = replace_once(
    static,
    '''            "check",
            "check-images",
            "backup",
''',
    '''            "check",
            "check-images",
            "check-runtime",
            "check-iot-runtime",
            "check-optional-runtime",
            "backup",
''',
    "Make targets",
)

static = replace_once(
    static,
    '''    check_script = read_required("scripts/check.sh")
    if check_script:
        if "python3 scripts/test_check_images.py" not in check_script:
            error("scripts/check.sh must run image verification unit tests")
        if "python3 scripts/test_runtime.py" not in check_script:
            error("scripts/check.sh must run runtime harness behavior tests")
        if "python3 scripts/test_backup.py" not in check_script:
            error("scripts/check.sh must run backup behavior tests")
        if "python3 scripts/check_backup_policy.py" not in check_script:
            error("scripts/check.sh must run backup policy checks")
''',
    '''    check_script = read_required("scripts/check.sh")
    if check_script:
        required_fast_checks = (
            "python3 scripts/check_runtime_policy.py",
            "python3 scripts/check_iot_runtime_policy.py",
            "python3 scripts/check_backup_policy.py",
            "python3 scripts/check_optional_runtime_policy.py",
            "python3 scripts/test_check_images.py",
            "python3 scripts/test_runtime.py",
            "python3 scripts/test_iot_runtime.py",
            "python3 scripts/test_backup.py",
            "python3 scripts/test_english_only.py",
            "python3 scripts/check_english_only.py",
            "python3 scripts/test_optional_runtime.py",
        )
        for command in required_fast_checks:
            if command not in check_script:
                error(f"scripts/check.sh must run: {command}")
''',
    "fast check contract",
)

static = replace_once(
    static,
    '''        netdata_block = service_block(compose, "netdata")
        if "profiles: [netdata]" not in netdata_block:
            error("Netdata must use its own opt-in profile")
''',
    '''        netdata_block = service_block(compose, "netdata")
        if "profiles: [netdata]" not in netdata_block:
            error("Netdata must use its own opt-in profile")
        if "NETDATA_LISTENER_PORT: ${NETDATA_PORT:-19999}" not in netdata_block:
            error("Netdata must preserve a configurable listener with port 19999 as the default")
''',
    "Netdata listener contract",
)

static = replace_once(
    static,
    '''            "## Five verification levels",
            "make check",
            "make check-images",
            "make check-runtime",
            "make check-iot-runtime",
            "make check-backup-runtime",
''',
    '''            "## Six verification levels",
            "make check",
            "make check-images",
            "make check-runtime",
            "make check-iot-runtime",
            "make check-backup-runtime",
            "make check-optional-runtime",
''',
    "README verification contract",
)

static_path.write_text(static, encoding="utf-8")

test_path = Path("scripts/test_optional_runtime.py")
test = test_path.read_text(encoding="utf-8")
test = replace_once(
    test,
    '''    printf '%s\\n' '{"id":"system.cpu","data":[[1,2.5]]}' >"$output"
''',
    '''    printf '%s\\n' '{"id":"chart://hosts:test/instance:system.cpu/dimensions:*/after:-10","name":"chart://hosts:test/instance:system.cpu","data":[[1,2.5]]}' >"$output"
''',
    "Netdata response fixture",
)
test_path.write_text(test, encoding="utf-8")

print("Completion policy source migration applied")
