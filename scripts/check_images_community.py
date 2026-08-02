#!/usr/bin/env python3
"""Verify image manifests for every established and community profile."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "check_images.py"
RESTIC_IMAGE = "restic/restic:0.18.1"

spec = importlib.util.spec_from_file_location("legacy_check_images", SOURCE)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load scripts/check_images.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
legacy.PROFILES = (
    "--profile", "monitoring",
    "--profile", "tools",
    "--profile", "iot",
    "--profile", "netdata",
    "--profile", "test",
    "--profile", "uptime",
    "--profile", "dns",
    "--profile", "dashboard",
    "--profile", "auth",
    "--profile", "logs",
)
original_configured_images = legacy.configured_images


def configured_images() -> set[str]:
    images = original_configured_images()
    images.add(RESTIC_IMAGE)
    return images


legacy.configured_images = configured_images
raise SystemExit(legacy.main())
