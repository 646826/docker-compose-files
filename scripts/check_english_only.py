#!/usr/bin/env python3
"""Reject Cyrillic text in tracked UTF-8 repository files."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
CYRILLIC_RANGES = (
    (0x0400, 0x052F),
    (0x1C80, 0x1C8F),
    (0x2DE0, 0x2DFF),
    (0xA640, 0xA69F),
    (0x1E030, 0x1E08F),
)


class Finding(NamedTuple):
    path: str
    line: int
    column: int
    character: str


def is_cyrillic(character: str) -> bool:
    """Return whether one Unicode character belongs to a Cyrillic block."""
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in CYRILLIC_RANGES)


def find_cyrillic(path: str, text: str) -> list[Finding]:
    """Return exact one-based locations of Cyrillic characters in text."""
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        for column, character in enumerate(line, start=1):
            if is_cyrillic(character):
                findings.append(
                    Finding(
                        path=path,
                        line=line_number,
                        column=column,
                        character=character,
                    )
                )
    return findings


def scan_paths(root: Path, paths: Iterable[str]) -> list[Finding]:
    """Scan tracked paths, skipping only files that are not valid UTF-8."""
    findings: list[Finding] = []
    for relative in sorted(set(paths)):
        target = root / relative
        if not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(find_cyrillic(relative, text))
    return findings


def tracked_paths(root: Path) -> list[str]:
    """Return the deterministic tracked-file list from Git."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required for the English-only check") from exc

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {detail or 'unknown error'}")

    return sorted(
        os.fsdecode(value)
        for value in result.stdout.split(b"\0")
        if value
    )


def main(root: Path = ROOT) -> int:
    try:
        paths = tracked_paths(root)
        findings = scan_paths(root, paths)
    except (OSError, RuntimeError) as exc:
        print(f"English-only check failed: {exc}", file=sys.stderr)
        return 1

    if findings:
        for item in findings:
            codepoint = f"U+{ord(item.character):04X}"
            print(
                f"{item.path}:{item.line}:{item.column}: "
                f"Cyrillic character {codepoint} is not allowed",
                file=sys.stderr,
            )
        return 1

    print(
        f"English-only check passed: {len(paths)} tracked files contain no Cyrillic text"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
