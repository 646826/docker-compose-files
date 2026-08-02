#!/usr/bin/env python3
"""Run the legacy static policy against the root and all Compose modules."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "scripts" / "check_static.py"
MODULES = (
    "modules/core/compose.yaml",
    "modules/monitoring/compose.yaml",
    "modules/tools/compose.yaml",
    "modules/iot/compose.yaml",
    "modules/uptime/compose.yaml",
    "modules/dns/compose.yaml",
    "modules/dashboard/compose.yaml",
    "modules/auth/compose.yaml",
    "modules/logs/compose.yaml",
)

spec = importlib.util.spec_from_file_location("legacy_check_static", LEGACY)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load scripts/check_static.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
original_read_required = legacy.read_required


def read_required(path: str) -> str:
    text = original_read_required(path)
    if path != "compose.yaml":
        return text
    return "\n".join(
        [text, *(original_read_required(module) for module in MODULES)]
    )


legacy.read_required = read_required
raise SystemExit(legacy.main())
