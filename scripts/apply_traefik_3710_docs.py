#!/usr/bin/env python3
"""Synchronize the documented Traefik pin, then remove this helper."""

from pathlib import Path

replacements = {
    "README.md": (
        ("| Traefik | `3.7.8` |", "| Traefik | `3.7.10` |"),
    ),
    "CHANGELOG.md": (
        (
            "- Telegraf is updated to the current official `1.39.2-alpine` image.\n",
            "- Telegraf is updated to the current official `1.39.2-alpine` image.\n- Traefik is updated to the current stable `v3.7.10` release.\n",
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

print("Traefik 3.7.10 documentation migration applied")
