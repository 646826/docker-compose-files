#!/usr/bin/env python3
"""Run the IoT policy against the modular Compose model."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "scripts" / "check_iot_runtime_policy.py"

spec = importlib.util.spec_from_file_location("legacy_iot_policy", LEGACY)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load scripts/check_iot_runtime_policy.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
original_read_required = legacy.read_required


def read_required(path: str) -> str:
    text = original_read_required(path)
    if path == "compose.yaml":
        text += "\n" + original_read_required("modules/iot/compose.yaml")
    return text


legacy.read_required = read_required
raise SystemExit(legacy.main())
