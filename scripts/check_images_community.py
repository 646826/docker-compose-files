#!/usr/bin/env python3
"""Verify image manifests for every established and community profile."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "check_images.py"
RESTIC_IMAGE = "restic/restic:0.18.1"
TRIVY_IMAGE = "ghcr.io/aquasecurity/trivy:0.70.0"

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
legacy.PLACEHOLDER_SECRETS.update(
    {
        "authelia_jwt_secret": "manifest-check-jwt",
        "authelia_session_secret": "manifest-check-session",
        "authelia_storage_encryption_key": "manifest-check-storage",
        "authelia_configuration.yml": "server: {address: tcp4://0.0.0.0:9091}",
        "authelia_users.yml": "users: {}",
    }
)
original_configured_images = legacy.configured_images


def configured_images() -> set[str]:
    images = original_configured_images()
    images.add(RESTIC_IMAGE)
    images.add(TRIVY_IMAGE)
    return images


legacy.configured_images = configured_images
raise SystemExit(legacy.main())
