"""Dry-run/apply retention cleanup for project processor telemetry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    parser.add_argument("--project-id", required=True, type=int, help="Project ID to inspect or prune")
    parser.add_argument(
        "--keep-latest-ok",
        type=int,
        default=200,
        help="How many most recent successful runs to preserve (default: 200)",
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
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if int(args.keep_latest_ok) < 0:
        raise SystemExit("--keep-latest-ok must be >= 0")
    if bool(args.apply) and int(args.confirm_project_id or -1) != int(args.project_id):
        raise SystemExit("--apply requires --confirm-project-id matching --project-id")


def _to_dict(summary) -> dict[str, object]:
    return {
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
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_args(args)

    db_path = Path(args.db_path).expanduser()
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

        print(json.dumps(_to_dict(summary), ensure_ascii=False, indent=2))
        return 0
    finally:
        DBService.shutdown()


if __name__ == "__main__":
    sys.exit(main())
