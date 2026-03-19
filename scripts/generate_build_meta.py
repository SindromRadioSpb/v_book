"""Generate runtime build metadata for traceability."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run_git(repo_root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return (result.stdout or "").strip()


def _is_dirty(repo_root: Path) -> int:
    try:
        unstaged = subprocess.run(["git", "diff", "--quiet"], cwd=repo_root, check=False)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_root, check=False)
    except FileNotFoundError:
        return 0
    return 1 if (unstaged.returncode != 0 or staged.returncode != 0) else 0


def _render_module(commit: str, dirty: int, built_at_utc: str) -> str:
    return "\n".join(
        [
            '"""Auto-generated build metadata.',
            "",
            "This file is updated by scripts/generate_build_meta.py during build flows.",
            '"""',
            "",
            f'BUILD_COMMIT = "{commit}"',
            f"BUILD_DIRTY = {dirty}",
            f'BUILD_TIME_UTC = "{built_at_utc}"',
            "",
        ]
    )


def main() -> int:
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    output_path = repo_root / "app" / "_generated" / "build_info.py"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    commit = _run_git(repo_root, ["rev-parse", "HEAD"]) or "unknown"
    dirty = _is_dirty(repo_root)
    built_at_utc = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )

    output_path.write_text(
        _render_module(commit=commit, dirty=dirty, built_at_utc=built_at_utc), encoding="utf-8"
    )

    print(
        f"Generated build metadata: version_source=app.__version__ "
        f"commit={commit} dirty={dirty} built_at={built_at_utc}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
