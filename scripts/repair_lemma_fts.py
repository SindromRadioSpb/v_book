#!/usr/bin/env python3
"""Deterministic repair tool for Dictionary lemma_fts health drift."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.infra.fts_manager import inspect_lemma_fts_parity, rebuild_lemma_fts  # noqa: E402


logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def inspect_lemma_fts_health(db_path: Path) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        return inspect_lemma_fts_parity(conn, schema="main")
    finally:
        conn.close()


def repair_lemma_fts(
    db_path: Path,
    *,
    dry_run: bool = False,
    backup: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    before_mtime = db_path.stat().st_mtime_ns
    before = inspect_lemma_fts_health(db_path)
    summary: dict[str, Any] = {
        "db_path": str(db_path),
        "started_at_utc": _utc_now(),
        "dry_run": dry_run,
        "backup_enabled": backup,
        "before": before,
        "issues_detected": before["issues"],
        "actions": [],
        "status": None,
        "error": None,
        "backup_path": None,
        "repair_result": None,
        "after": before,
    }

    if before["healthy"]:
        summary["status"] = "OK"
    elif dry_run:
        summary["status"] = "FAILED"
        summary["error"] = "lemma_fts parity issues detected in dry-run mode"
    else:
        if backup:
            backup_path = db_path.with_suffix(f"{db_path.suffix}.lemma_fts.bak")
            shutil.copy2(db_path, backup_path)
            summary["backup_path"] = str(backup_path)
            summary["actions"].append("backup_created")

        conn = _connect(db_path)
        try:
            repair_result = rebuild_lemma_fts(conn, schema="main")
            summary["repair_result"] = repair_result
            summary["actions"].append("drop_recreate_rebuild")
        except Exception as exc:
            summary["status"] = "FAILED"
            summary["error"] = str(exc)
            logger.error("lemma_fts repair failed: %s", exc)
        finally:
            conn.close()

        if summary["status"] != "FAILED":
            after = inspect_lemma_fts_health(db_path)
            summary["after"] = after
            if after["healthy"]:
                summary["status"] = "REPAIRED"
            else:
                summary["status"] = "FAILED"
                summary["error"] = "lemma_fts parity issues remain after repair: " + ", ".join(
                    after["issues"]
                )

    summary["ended_at_utc"] = _utc_now()
    summary["duration_s"] = round(time.perf_counter() - started, 6)
    summary["db_mtime_changed"] = db_path.stat().st_mtime_ns != before_mtime

    logs_dir = project_root / "build" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = logs_dir / f"lemma_fts_repair_{int(time.time())}.json"
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["report_path"] = str(report_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair lemma_fts health drift")
    parser.add_argument("--db-path", required=True, help="Path to SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Inspect only")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup before repair",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    summary = repair_lemma_fts(
        db_path,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] in {"OK", "REPAIRED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
