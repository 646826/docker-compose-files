#!/usr/bin/env python3
"""Rewrite the one-time translator so its source contains no Cyrillic characters."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATOR = ROOT / "scripts/translate_repository_to_english.py"

MAPPINGS = (
    (
        "\u0427\u0435\u0442\u044b\u0440\u0435 \u0443\u0440\u043e\u0432\u043d\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438",
        "Four verification levels",
    ),
    (
        "\u041f\u044f\u0442\u044c \u0443\u0440\u043e\u0432\u043d\u0435\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438",
        "Five verification levels",
    ),
    (
        "\u0418\u0437\u043e\u043b\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u0430\u044f runtime-\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 default stack",
        "Isolated default-stack runtime check",
    ),
    (
        "\u0418\u0437\u043e\u043b\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u0430\u044f backup/restore runtime-\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430",
        "Isolated backup/restore runtime check",
    ),
    (
        "\u043d\u0435 \u0447\u0438\u0442\u0430\u0435\u0442 \u0440\u0430\u0431\u043e\u0447\u0438\u0435 `.env`/`.secrets/`",
        "does not read deployment `.env` or `.secrets/`",
    ),
    (
        "\u0421\u043e\u0437\u0434\u0430\u0451\u0442 \u0443\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0435 \u043e\u0434\u043d\u043e\u0440\u0430\u0437\u043e\u0432\u044b\u0435 local volumes \u0441 \u0432\u043b\u043e\u0436\u0435\u043d\u043d\u044b\u043c\u0438 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u044b\u043c\u0438 \u0438 \u0431\u0438\u043d\u0430\u0440\u043d\u044b\u043c\u0438 \u0444\u0430\u0439\u043b\u0430\u043c\u0438, \u043f\u0443\u0441\u0442\u044b\u043c \u0444\u0430\u0439\u043b\u043e\u043c, \u043d\u0435\u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u043d\u044b\u043c\u0438 permissions \u0438 \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u044b\u043c \u043e\u0442\u043d\u043e\u0441\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u043c symlink. \u0417\u0430\u0442\u0435\u043c \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442 cold backup, \u043e\u0444\u043b\u0430\u0439\u043d-\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443, \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u0435 source volumes \u0438 side-by-side restore \u0432 \u0434\u0440\u0443\u0433\u043e\u0439 project name.",
        "Creates unique disposable local volumes with nested text and binary files, an empty file, unusual permissions, and a safe relative symbolic link. It then performs a cold backup, offline verification, source-volume deletion, and a side-by-side restore under a different project name.",
    ),
    (
        "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u0440\u0430\u0432\u043d\u0438\u0432\u0430\u0435\u0442 bytes \u0438 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0435 filesystem metadata, \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442 \u043e\u0442\u043a\u0430\u0437 \u0434\u043b\u044f \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0451\u043d\u043d\u043e\u0433\u043e snapshot \u0438 \u043d\u0435\u043f\u0443\u0441\u0442\u043e\u0433\u043e target volume, \u0430 \u0437\u0430\u0442\u0435\u043c \u0443\u0434\u0430\u043b\u044f\u0435\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u0441\u043e\u0431\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0435 fixture-\u0440\u0435\u0441\u0443\u0440\u0441\u044b. \u041e\u043d\u0430 \u043d\u0435 \u0437\u0430\u043f\u0443\u0441\u043a\u0430\u0435\u0442 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f homelab \u0438 \u043d\u0435 \u0447\u0438\u0442\u0430\u0435\u0442 \u0440\u0430\u0431\u043e\u0447\u0438\u0435 `.env` \u0438\u043b\u0438 `.secrets/`; \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u0430\u044f \u043f\u0440\u043e\u0446\u0435\u0434\u0443\u0440\u0430 \u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f \u043d\u0430\u0445\u043e\u0434\u0438\u0442\u0441\u044f \u0432 [`docs/BACKUP.md`](docs/BACKUP.md).",
        "The check compares bytes and relevant filesystem metadata, confirms rejection of a tampered snapshot and a non-empty target volume, and then removes only its own fixture resources. It does not start homelab applications or read deployment `.env` or `.secrets/`; the detailed recovery procedure is in [`docs/BACKUP.md`](docs/BACKUP.md).",
    ),
)


def escaped_literal(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


def main() -> int:
    text = TRANSLATOR.read_text(encoding="utf-8")
    start = text.index("REPLACEMENTS = {")
    end = text.index("\n}\n\nTARGETS = (", start) + 2

    lines = ["REPLACEMENTS = {"]
    for source, replacement in MAPPINGS:
        lines.append(f'    "{escaped_literal(source)}": "{replacement}",')
    lines.append("}")

    rewritten = text[:start] + "\n".join(lines) + text[end:]
    TRANSLATOR.write_text(rewritten, encoding="utf-8")
    print("Prepared an ASCII-only translation map.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
