#!/usr/bin/env python3
"""Verify image manifests for every established and community profile."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "check_images.py"

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
raise SystemExit(legacy.main())
