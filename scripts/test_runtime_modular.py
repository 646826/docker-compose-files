#!/usr/bin/env python3
"""Run default runtime behavioral tests with modular Compose fixtures."""

from __future__ import annotations

import importlib.util
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "test_runtime.py"

spec = importlib.util.spec_from_file_location("legacy_test_runtime", SOURCE)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load scripts/test_runtime.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
original_set_up = legacy.RuntimeHarnessTests.setUp


def set_up(self: unittest.TestCase) -> None:
    original_set_up(self)
    shutil.copytree(ROOT / "modules", self.fixture / "modules")


legacy.RuntimeHarnessTests.setUp = set_up
unittest.main(module=legacy, verbosity=2)
