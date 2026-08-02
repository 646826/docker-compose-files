#!/usr/bin/env python3
"""Run IoT runtime behavioral tests with modular Compose fixtures."""

from __future__ import annotations

import importlib.util
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "test_iot_runtime.py"

spec = importlib.util.spec_from_file_location("legacy_test_iot_runtime", SOURCE)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load scripts/test_iot_runtime.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
original_set_up = legacy.IoTRuntimeHarnessTests.setUp


def set_up(self: unittest.TestCase) -> None:
    original_set_up(self)
    shutil.copytree(ROOT / "modules", self.fixture / "modules")


legacy.IoTRuntimeHarnessTests.setUp = set_up
unittest.main(module=legacy, verbosity=2)
