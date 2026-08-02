#!/usr/bin/env python3
"""Regression tests for the community-platform backup inventory."""

from __future__ import annotations

import unittest
from pathlib import Path

import backup
import backup_community

ROOT = Path(__file__).resolve().parents[1]


class CommunityBackupInventoryTests(unittest.TestCase):
    def test_inventory_extends_the_verified_engine_without_duplicates(self) -> None:
        inventory = backup_community.configured_inventory()
        self.assertEqual(inventory[: len(backup.CURRENT_VOLUMES)], backup.CURRENT_VOLUMES)
        self.assertEqual(inventory[-4:], backup_community.COMMUNITY_VOLUMES)
        self.assertEqual(len(inventory), len(set(inventory)))

    def test_every_community_volume_is_declared_in_root_compose(self) -> None:
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        for logical in backup_community.COMMUNITY_VOLUMES:
            with self.subTest(logical=logical):
                self.assertIn(f"  {logical}:\n", compose)
                self.assertIn(
                    f"name: ${{HOMELAB_PROJECT_NAME:-homelab}}_{logical}",
                    compose,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
