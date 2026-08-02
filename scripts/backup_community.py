#!/usr/bin/env python3
"""Run the verified backup engine with all community-platform volumes."""

from __future__ import annotations

import backup

COMMUNITY_VOLUMES = (
    "uptime_kuma_data",
    "adguard_work",
    "adguard_config",
    "authelia_data",
)


def configured_inventory() -> tuple[str, ...]:
    """Return the stable complete logical-volume inventory."""
    combined = (*backup.CURRENT_VOLUMES, *COMMUNITY_VOLUMES)
    if len(combined) != len(set(combined)):
        raise backup.BackupError("community backup inventory contains duplicates")
    return combined


def configure() -> None:
    backup.CURRENT_VOLUMES = configured_inventory()


def main() -> int:
    configure()
    return backup.main()


if __name__ == "__main__":
    raise SystemExit(main())
