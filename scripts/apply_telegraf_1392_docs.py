#!/usr/bin/env python3
"""Synchronize the documented Telegraf pin, then remove this helper."""

from pathlib import Path

replacements = {
    "README.md": (
        ("| Telegraf | `1.39.1` |", "| Telegraf | `1.39.2` |"),
    ),
    "CHANGELOG.md": (
        (
            "- The Uptime Kuma default uses the pinned `2.4.0-slim` image, retaining SQLite and ordinary monitor types while excluding embedded MariaDB and Chromium from the default attack surface.\n",
            "- The Uptime Kuma default uses the pinned `2.4.0-slim` image, retaining SQLite and ordinary monitor types while excluding embedded MariaDB and Chromium from the default attack surface.\n- Telegraf is updated to the current official `1.39.2-alpine` image.\n",
        ),
    ),
}

for filename, pairs in replacements.items():
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{filename}: expected one match for {old!r}, found {count}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")

print("Telegraf 1.39.2 documentation migration applied")
