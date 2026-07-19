#!/usr/bin/env python3
"""Verify that pinned container images publish both maintained Linux platforms."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
INIT_SCRIPT = ROOT / "scripts" / "init.sh"
PROFILES = (
    "--profile",
    "monitoring",
    "--profile",
    "tools",
    "--profile",
    "iot",
    "--profile",
    "netdata",
    "--profile",
    "test",
)
HELPER_KEYS = ("HTPASSWD_IMAGE", "MOSQUITTO_IMAGE")
REQUIRED_PLATFORMS = {"linux/amd64", "linux/arm64"}


def compose_images(stdout: str) -> set[str]:
    """Return normalized, unique image references from Compose output."""
    images = {line.strip() for line in stdout.splitlines() if line.strip()}
    if not images:
        raise ValueError("no images were rendered by Docker Compose")
    return images


def helper_images(init_script: str) -> set[str]:
    """Extract the exact pinned bootstrap helper images from init.sh."""
    images: set[str] = set()
    for key in HELPER_KEYS:
        match = re.search(
            rf"^{re.escape(key)}=([^\s#]+)\s*$",
            init_script,
            flags=re.MULTILINE,
        )
        if match is None:
            raise ValueError(f"missing {key} assignment in scripts/init.sh")
        images.add(match.group(1))
    return images


def manifest_platforms(raw_manifest: str) -> set[str]:
    """Return Linux platforms declared by an OCI index or manifest list."""
    try:
        document = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid manifest JSON: {exc.msg}") from exc

    if not isinstance(document, dict):
        raise ValueError("invalid manifest JSON: expected an object")

    descriptors = document.get("manifests")
    if not isinstance(descriptors, list):
        return set()

    platforms: set[str] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        platform = descriptor.get("platform")
        if not isinstance(platform, dict):
            continue
        os_name = platform.get("os")
        architecture = platform.get("architecture")
        if os_name != "linux" or not isinstance(architecture, str):
            continue
        if architecture in {"", "unknown"}:
            continue

        if architecture == "arm64":
            platforms.add("linux/arm64")
            continue

        variant = platform.get("variant")
        if isinstance(variant, str) and variant:
            platforms.add(f"linux/{architecture}/{variant}")
        else:
            platforms.add(f"linux/{architecture}")

    return platforms


def missing_platforms(platforms: set[str], required: set[str]) -> set[str]:
    """Return required platforms absent from an image manifest list."""
    return required - platforms


def run_command(
    command: Sequence[str],
    *,
    attempts: int = 1,
    retry_delays: Sequence[int] = (1, 3),
) -> str:
    """Run a command and return stdout, retrying transient failures."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    last_detail = "command failed without output"
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            list(command),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout

        last_detail = result.stderr.strip() or result.stdout.strip() or last_detail
        if attempt < attempts:
            delay_index = min(attempt - 1, len(retry_delays) - 1)
            delay = retry_delays[delay_index] if retry_delays else 0
            if delay > 0:
                time.sleep(delay)

    raise RuntimeError(
        f"{shlex.join(command)} failed after {attempts} attempt(s): {last_detail}"
    )


def configured_images() -> set[str]:
    """Render all Compose and bootstrap helper image references."""
    if not ENV_FILE.is_file():
        raise RuntimeError(".env is missing; run `make init` first")
    if not INIT_SCRIPT.is_file():
        raise RuntimeError("scripts/init.sh is missing")

    rendered = run_command(
        (
            "docker",
            "compose",
            "--env-file",
            ".env",
            *PROFILES,
            "config",
            "--images",
        )
    )
    images = compose_images(rendered)
    images.update(helper_images(INIT_SCRIPT.read_text(encoding="utf-8")))
    return images


def main() -> int:
    try:
        run_command(("docker", "compose", "version"))
        run_command(("docker", "buildx", "version"))
        images = configured_images()

        for image in sorted(images):
            print(f"Checking {image}", flush=True)
            raw_manifest = run_command(
                ("docker", "buildx", "imagetools", "inspect", "--raw", image),
                attempts=3,
            )
            platforms = manifest_platforms(raw_manifest)
            missing = missing_platforms(platforms, REQUIRED_PLATFORMS)
            if missing:
                available = ", ".join(sorted(platforms)) or "no multi-platform index"
                raise RuntimeError(
                    f"{image} is missing {', '.join(sorted(missing))}; "
                    f"available Linux platforms: {available}"
                )

        required = " and ".join(sorted(REQUIRED_PLATFORMS))
        print(
            f"Image manifest checks passed: {len(images)} images support {required}"
        )
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Image verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
