#!/usr/bin/env python3
"""Unit tests for read-only homelab diagnostics."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "scripts" / "doctor.py"


def load_doctor() -> ModuleType | None:
    if not DOCTOR.is_file():
        return None
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doctor = load_doctor()
        self.assertIsNotNone(self.doctor, "scripts/doctor.py is missing")

    def test_compose_version_floor(self) -> None:
        self.assertEqual(self.doctor.parse_compose_version("2.20.2"), (2, 20, 2))
        self.assertEqual(self.doctor.parse_compose_version("v2.20.3"), (2, 20, 3))
        self.assertEqual(self.doctor.parse_compose_version("Docker Compose version v2.38.2"), (2, 38, 2))
        self.assertFalse(self.doctor.compose_version_supported((2, 20, 2)))
        self.assertTrue(self.doctor.compose_version_supported((2, 20, 3)))
        self.assertTrue(self.doctor.compose_version_supported((2, 38, 2)))

    def test_port_conflicts_respect_wildcard_and_loopback(self) -> None:
        listeners = {("0.0.0.0", 80), ("127.0.0.1", 3000), ("::", 53)}
        self.assertEqual(self.doctor.classify_port("127.0.0.1", 80, listeners), "conflict")
        self.assertEqual(self.doctor.classify_port("0.0.0.0", 3000, listeners), "conflict")
        self.assertEqual(self.doctor.classify_port("127.0.0.1", 19999, listeners), "free")
        self.assertEqual(self.doctor.classify_port("::1", 53, listeners), "conflict")

    def test_result_exit_codes(self) -> None:
        result_type = self.doctor.DoctorReport
        warning_only = result_type()
        warning_only.warning("memory", "less than recommended")
        self.assertEqual(warning_only.exit_code(strict=False), 0)
        self.assertEqual(warning_only.exit_code(strict=True), 1)

        blocked = result_type()
        blocked.error("docker", "daemon unavailable")
        self.assertEqual(blocked.exit_code(strict=False), 1)

    def test_domain_and_project_validation(self) -> None:
        self.assertTrue(self.doctor.valid_project_name("homelab-2"))
        self.assertFalse(self.doctor.valid_project_name("Home Lab"))
        self.assertTrue(self.doctor.valid_domain("home.example.com"))
        self.assertTrue(self.doctor.valid_domain("localhost"))
        self.assertFalse(self.doctor.valid_domain("bad domain"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
