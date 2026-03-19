"""Dry-run/preflight/apply retention cleanup for project processor telemetry."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from app.infra.db_path_resolver import classify_db_profile, is_protected_reference_db_path
from app.services.db_service import DBService
from app.services.project_telemetry_retention_service import (
    ProjectTelemetryRetentionService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply retention cleanup for project-scoped processor_run/run_error telemetry. "
            "Dry-run is the default."
        )
    )
    parser.add_argument("--db-path", required=True, help="Path to SQLite database")
    parser.add_argument(
        "--project-id", required=True, type=int, help="Project ID to inspect or prune"
    )
    parser.add_argument(
        "--keep-latest-ok",
        type=int,
        default=200,
        help="How many most recent successful runs to preserve (default: 200)",
    )
    parser.add_argument(
        "--backup-db-path",
        default=None,
        help="Path to a healthy backup DB required for telemetry apply or preflight",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate the telemetry apply package without writing. Requires --backup-db-path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete prunable successful telemetry rows instead of dry-run preview",
    )
    parser.add_argument(
        "--confirm-project-id",
        type=int,
        default=None,
        help="Required when --apply is used; must exactly match --project-id",
    )
    parser.add_argument(
        "--allow-protected-db-telemetry-apply",
        action="store_true",
        help="Explicit decision-gate override for telemetry apply/preflight on the protected baseline DB.",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if int(args.keep_latest_ok) < 0:
        parser.error("--keep-latest-ok must be >= 0")
    if bool(args.preflight_only) and bool(args.apply):
        parser.error("--preflight-only and --apply are mutually exclusive")
    if (bool(args.preflight_only) or bool(args.apply)) and not str(
        args.backup_db_path or ""
    ).strip():
        parser.error("--backup-db-path is required for --preflight-only or --apply")
    if bool(args.apply) and int(args.confirm_project_id or -1) != int(args.project_id):
        parser.error("--apply requires --confirm-project-id matching --project-id")


def _run_quick_check_probe(
    conn: sqlite3.Connection,
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    probe: dict[str, Any] = {
        "ok": True,
        "rows": [],
        "error": None,
        "timed_out": False,
        "timeout_sec": float(timeout_sec),
    }
    started_at = time.perf_counter()

    def _progress_handler() -> int:
        if timeout_sec <= 0:
            return 0
        return 1 if (time.perf_counter() - started_at) >= timeout_sec else 0

    conn.set_progress_handler(_progress_handler, 10_000)
    try:
        rows: list[str] = []
        try:
            rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check(10)").fetchall()]
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower() and timeout_sec > 0:
                probe["timed_out"] = True
            else:
                raise
        probe["rows"] = rows
        if probe["timed_out"]:
            probe["error"] = f"quick_check timed out after {timeout_sec:.1f}s"
        elif not rows or any(str(row).lower() != "ok" for row in rows):
            probe["ok"] = False
            probe["error"] = "; ".join(rows) if rows else "empty quick_check output"
        return probe
    except sqlite3.Error as exc:
        probe["ok"] = False
        probe["error"] = str(exc)
        return probe
    finally:
        conn.set_progress_handler(None, 0)


def _sqlite_health_probe(db_path: Path) -> dict[str, Any]:
    probe: dict[str, Any] = {
        "path": str(db_path),
        "ok": False,
        "schema_version": None,
        "page_count": None,
        "quick_check": {},
        "quick_check_timed_out": False,
        "error": None,
    }
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        conn.execute("PRAGMA busy_timeout=15000")
    except sqlite3.Error as exc:
        probe["error"] = str(exc)
        return probe

    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        probe["schema_version"] = int(row[0]) if row and row[0] is not None else None
        probe["page_count"] = int(conn.execute("PRAGMA page_count").fetchone()[0])
        conn.execute("SELECT 1 FROM processor_run LIMIT 1").fetchone()
        conn.execute("SELECT 1 FROM run_error LIMIT 1").fetchone()

        quick_check = _run_quick_check_probe(conn, timeout_sec=1.0)
        probe["quick_check"] = quick_check
        probe["quick_check_timed_out"] = bool(quick_check.get("timed_out"))
        if quick_check.get("timed_out"):
            probe["ok"] = True
        else:
            probe["ok"] = bool(quick_check.get("ok"))
            if not probe["ok"]:
                probe["error"] = str(quick_check.get("error") or "quick_check failed")
        return probe
    except sqlite3.Error as exc:
        probe["error"] = str(exc)
        return probe
    finally:
        conn.close()


def _run_telemetry_retention_apply_preflight(
    *,
    db_path: Path,
    backup_db_path: Path | None,
    project_id: int,
    allow_protected_db_telemetry_apply: bool,
) -> dict[str, Any]:
    db_path = db_path.resolve()
    db_profile = classify_db_profile(db_path)
    protected_target = is_protected_reference_db_path(db_path)
    report: dict[str, Any] = {
        "ok": False,
        "project_id": int(project_id),
        "db_path": str(db_path),
        "db_profile": db_profile,
        "protected_target": bool(protected_target),
        "backup_db_path": str(backup_db_path.resolve()) if backup_db_path is not None else None,
        "operation_label": "telemetry retention apply",
        "target_probe": {},
        "backup_probe": {},
        "error": None,
    }

    if protected_target and not allow_protected_db_telemetry_apply:
        report["error"] = (
            "Telemetry retention apply is blocked on the protected baseline/main reference DB. "
            "Use a working test DB or disposable clone, or cross the explicit decision gate "
            "with --allow-protected-db-telemetry-apply."
        )
        return report

    if backup_db_path is None:
        report["error"] = "--backup-db-path is required for telemetry retention preflight/apply"
        return report

    backup_db_path = backup_db_path.resolve()
    report["backup_db_path"] = str(backup_db_path)
    if not backup_db_path.exists():
        report["error"] = f"Backup DB not found: {backup_db_path}"
        return report

    if backup_db_path == db_path:
        report["error"] = "--backup-db-path must point to a different DB file"
        return report

    target_probe = _sqlite_health_probe(db_path)
    backup_probe = _sqlite_health_probe(backup_db_path)
    report["target_probe"] = target_probe
    report["backup_probe"] = backup_probe

    if not target_probe.get("ok"):
        report["error"] = "Target DB failed preflight health probe: " + str(
            target_probe.get("error") or "unknown error"
        )
        return report
    if not backup_probe.get("ok"):
        report["error"] = "Backup DB failed preflight health probe: " + str(
            backup_probe.get("error") or "unknown error"
        )
        return report

    report["ok"] = True
    return report


def _to_dict(
    summary,
    *,
    operation_mode: str,
    preflight: dict[str, Any] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "project_id": int(summary.project_id),
        "project_name": str(summary.project_name),
        "keep_latest_ok": int(summary.keep_latest_ok),
        "total_runs": int(summary.total_runs),
        "ok_runs": int(summary.ok_runs),
        "non_ok_runs": int(summary.non_ok_runs),
        "noted_ok_runs": int(summary.noted_ok_runs),
        "kept_recent_ok_runs": int(summary.kept_recent_ok_runs),
        "prunable_ok_runs": int(summary.prunable_ok_runs),
        "prunable_run_error_rows": int(summary.prunable_run_error_rows),
        "oldest_prunable_run_id": summary.oldest_prunable_run_id,
        "newest_prunable_run_id": summary.newest_prunable_run_id,
        "applied": bool(summary.applied),
        "deleted_runs": int(summary.deleted_runs),
        "deleted_run_errors": int(summary.deleted_run_errors),
        "summary_note": summary.summary_note,
        "vacuum_note": summary.vacuum_note,
        "operation_mode": str(operation_mode),
    }
    if preflight is not None:
        payload["preflight"] = preflight
    return payload


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)

    db_path = Path(args.db_path).expanduser().resolve()
    backup_db_path = (
        Path(args.backup_db_path).expanduser().resolve() if args.backup_db_path else None
    )
    preflight_report: dict[str, Any] | None = None

    if bool(args.preflight_only) or bool(args.apply):
        preflight_report = _run_telemetry_retention_apply_preflight(
            db_path=db_path,
            backup_db_path=backup_db_path,
            project_id=int(args.project_id),
            allow_protected_db_telemetry_apply=bool(args.allow_protected_db_telemetry_apply),
        )
        if not preflight_report.get("ok"):
            parser.error(
                str(preflight_report.get("error") or "telemetry retention preflight failed")
            )

    DBService.shutdown()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    service = ProjectTelemetryRetentionService()

    try:
        if bool(args.apply):
            with db.get_session() as session:
                summary = service.apply_retention(
                    session,
                    int(args.project_id),
                    keep_latest_ok=int(args.keep_latest_ok),
                )
                session.commit()
        else:
            with db.get_read_session() as session:
                summary = service.build_summary(
                    session,
                    int(args.project_id),
                    keep_latest_ok=int(args.keep_latest_ok),
                )

        operation_mode = (
            "apply"
            if bool(args.apply)
            else "preflight_only" if bool(args.preflight_only) else "dry_run"
        )
        print(
            json.dumps(
                _to_dict(summary, operation_mode=operation_mode, preflight=preflight_report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        DBService.shutdown()


if __name__ == "__main__":
    sys.exit(main())
