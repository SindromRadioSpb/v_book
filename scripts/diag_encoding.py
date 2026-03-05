#!/usr/bin/env python3
"""Encoding diagnostics for markdown governance/docs trees.

Scans:
  - docs/
  - .codex/
  - .agents/

Flags:
  - UTF-8 decode errors
  - Mojibake marker sequences
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "docs", ROOT / ".codex", ROOT / ".agents"]
MARKERS = ["вЂ", "Ã", "Â", "\ufffd"]


def iter_markdown_files() -> list[Path]:
    files: list[Path] = []
    for directory in SCAN_DIRS:
        if not directory.exists():
            continue
        files.extend(sorted(directory.rglob("*.md")))
    return files


def main() -> int:
    flagged: list[tuple[str, Path]] = []
    for path in iter_markdown_files():
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            flagged.append(("decode_error:utf8", path))
            continue

        for marker in MARKERS:
            if marker in text:
                flagged.append((f"marker:{marker}", path))

    for reason, path in flagged:
        rel = path.relative_to(ROOT).as_posix()
        print(f"{reason}\t{rel}")

    print(f"total_flagged={len(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
