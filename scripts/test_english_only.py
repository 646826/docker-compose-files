#!/usr/bin/env python3
"""Unit tests for the tracked-file English-only repository check."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_english_only.py"


def load_checker() -> ModuleType | None:
    if not CHECKER.is_file():
        return None
    spec = importlib.util.spec_from_file_location("check_english_only", CHECKER)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnglishOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = load_checker()
        self.assertIsNotNone(
            self.checker,
            "scripts/check_english_only.py is missing",
        )

    def test_clean_english_text_has_no_findings(self) -> None:
        findings = self.checker.find_cyrillic("clean.md", "English only\n")
        self.assertEqual(findings, [])

    def test_reports_exact_locations_across_cyrillic_ranges(self) -> None:
        findings = self.checker.find_cyrillic(
            "mixed.txt",
            "ASCII\nAРB\nextended: Ԁ\n",
        )
        self.assertEqual(
            [(item.path, item.line, item.column, item.character) for item in findings],
            [
                ("mixed.txt", 2, 2, "Р"),
                ("mixed.txt", 3, 11, "Ԁ"),
            ],
        )

    def test_scan_paths_skips_invalid_utf8_and_orders_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "z.txt").write_text("Я\n", encoding="utf-8")
            (root / "a.txt").write_text("AБ\n", encoding="utf-8")
            (root / "binary.bin").write_bytes(b"\xff\xfe\x00")

            findings = self.checker.scan_paths(
                root,
                ["z.txt", "binary.bin", "a.txt"],
            )

        self.assertEqual(
            [(item.path, item.line, item.column) for item in findings],
            [("a.txt", 1, 2), ("z.txt", 1, 1)],
        )

    def test_tracked_paths_excludes_untracked_files_and_is_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=root,
                check=True,
            )
            (root / "z.txt").write_text("z\n", encoding="utf-8")
            (root / "a.txt").write_text("a\n", encoding="utf-8")
            (root / "untracked.txt").write_text("ignored\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "z.txt", "a.txt"],
                cwd=root,
                check=True,
            )

            paths = self.checker.tracked_paths(root)

        self.assertEqual(paths, ["a.txt", "z.txt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
