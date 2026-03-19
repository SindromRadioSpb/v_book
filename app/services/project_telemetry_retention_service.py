"""Retention planning and cleanup for project-scoped processor telemetry."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.dto import ProjectTelemetryRetentionSummaryDTO
from app.infra.sa_models import DictProject

logger = logging.getLogger(__name__)


class ProjectTelemetryRetentionService:
    """Dry-run/apply retention helper for processor_run/run_error growth."""

    def build_summary(
        self,
        session: Session,
        project_id: int,
        *,
        keep_latest_ok: int = 200,
    ) -> ProjectTelemetryRetentionSummaryDTO:
        keep_latest_ok = self._normalize_keep_latest_ok(keep_latest_ok)
        project = session.get(DictProject, int(project_id))
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        total_runs = self._scalar(
            session,
            "SELECT COUNT(*) FROM processor_run WHERE project_id = :pid",
            {"pid": int(project_id)},
        )
        ok_runs = self._scalar(
            session,
            "SELECT COUNT(*) FROM processor_run WHERE project_id = :pid AND status = 'ok'",
            {"pid": int(project_id)},
        )
        noted_ok_runs = self._scalar(
            session,
            "SELECT COUNT(*) FROM processor_run "
            "WHERE project_id = :pid AND status = 'ok' "
            "AND note IS NOT NULL AND trim(note) <> ''",
            {"pid": int(project_id)},
        )
        kept_recent_ok_runs = min(int(keep_latest_ok), int(ok_runs))
        prunable_ok_runs = self._candidate_scalar(
            session,
            "SELECT COUNT(*) FROM candidates",
            int(project_id),
            int(keep_latest_ok),
        )
        prunable_run_error_rows = self._candidate_scalar(
            session,
            "SELECT COUNT(*) FROM run_error WHERE run_id IN (SELECT run_id FROM candidates)",
            int(project_id),
            int(keep_latest_ok),
        )
        oldest_prunable_run_id, newest_prunable_run_id = self._candidate_row(
            session,
            "SELECT MIN(run_id) AS oldest_run_id, MAX(run_id) AS newest_run_id FROM candidates",
            int(project_id),
            int(keep_latest_ok),
        )
        non_ok_runs = max(int(total_runs) - int(ok_runs), 0)

        return ProjectTelemetryRetentionSummaryDTO(
            project_id=int(project.project_id),
            project_name=str(project.name or f"Project {int(project_id)}"),
            keep_latest_ok=int(keep_latest_ok),
            total_runs=int(total_runs),
            ok_runs=int(ok_runs),
            non_ok_runs=int(non_ok_runs),
            noted_ok_runs=int(noted_ok_runs),
            kept_recent_ok_runs=int(kept_recent_ok_runs),
            prunable_ok_runs=int(prunable_ok_runs),
            prunable_run_error_rows=int(prunable_run_error_rows),
            oldest_prunable_run_id=self._as_int_or_none(oldest_prunable_run_id),
            newest_prunable_run_id=self._as_int_or_none(newest_prunable_run_id),
            applied=False,
            deleted_runs=0,
            deleted_run_errors=0,
            summary_note=(
                "Dry-run only. Retention prunes old successful runs with empty notes, "
                "while preserving recent successful rows, all non-ok rows, and successful "
                "rows that still carry explicit note/evidence metadata."
            ),
            vacuum_note=(
                "SQLite file size will not shrink automatically after deletion. "
                "Run VACUUM only as a separate explicit maintenance step if space reclaim becomes necessary."
            ),
        )

    def apply_retention(
        self,
        session: Session,
        project_id: int,
        *,
        keep_latest_ok: int = 200,
    ) -> ProjectTelemetryRetentionSummaryDTO:
        summary = self.build_summary(session, int(project_id), keep_latest_ok=keep_latest_ok)
        if int(summary.prunable_ok_runs) <= 0:
            summary.applied = True
            return summary

        delete_stmt = self._candidate_cte_sql(
            "DELETE FROM processor_run WHERE run_id IN (SELECT run_id FROM candidates)"
        )
        session.execute(
            text(delete_stmt),
            {
                "pid": int(project_id),
                "keep_latest_ok": int(summary.keep_latest_ok),
            },
        )

        summary.applied = True
        summary.deleted_runs = int(summary.prunable_ok_runs)
        summary.deleted_run_errors = int(summary.prunable_run_error_rows)
        summary.summary_note = (
            "Retention applied. Old successful rows without note metadata were removed; "
            "recent successful rows, non-ok rows, and noted evidence rows were preserved."
        )
        logger.info(
            "Applied processor telemetry retention for project %s: deleted_runs=%s, kept_recent_ok=%s, preserved_non_ok=%s, preserved_noted_ok=%s",
            int(project_id),
            int(summary.deleted_runs),
            int(summary.kept_recent_ok_runs),
            int(summary.non_ok_runs),
            int(summary.noted_ok_runs),
        )
        return summary

    @staticmethod
    def _normalize_keep_latest_ok(value: int) -> int:
        keep_latest_ok = int(value)
        if keep_latest_ok < 0:
            raise ValueError("keep_latest_ok must be >= 0")
        return keep_latest_ok

    @staticmethod
    def _as_int_or_none(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _scalar(session: Session, sql_text: str, params: dict[str, Any]) -> int:
        value = session.execute(text(sql_text), params).scalar()
        return int(value or 0)

    def _candidate_scalar(
        self, session: Session, sql_text: str, project_id: int, keep_latest_ok: int
    ) -> int:
        value = session.execute(
            text(self._candidate_cte_sql(sql_text)),
            {"pid": int(project_id), "keep_latest_ok": int(keep_latest_ok)},
        ).scalar()
        return int(value or 0)

    def _candidate_row(
        self,
        session: Session,
        sql_text: str,
        project_id: int,
        keep_latest_ok: int,
    ) -> tuple[int | None, int | None]:
        row = (
            session.execute(
                text(self._candidate_cte_sql(sql_text)),
                {"pid": int(project_id), "keep_latest_ok": int(keep_latest_ok)},
            )
            .mappings()
            .one()
        )
        return self._as_int_or_none(row.get("oldest_run_id")), self._as_int_or_none(
            row.get("newest_run_id")
        )

    @staticmethod
    def _candidate_cte_sql(body_sql: str) -> str:
        return (
            "WITH keep_ok AS ("
            "  SELECT run_id FROM processor_run "
            "  WHERE project_id = :pid AND status = 'ok' "
            "  ORDER BY run_id DESC "
            "  LIMIT :keep_latest_ok"
            "), candidates AS ("
            "  SELECT run_id FROM processor_run "
            "  WHERE project_id = :pid "
            "    AND status = 'ok' "
            "    AND (note IS NULL OR trim(note) = '') "
            "    AND run_id NOT IN (SELECT run_id FROM keep_ok)"
            ") "
            f"{body_sql}"
        )
