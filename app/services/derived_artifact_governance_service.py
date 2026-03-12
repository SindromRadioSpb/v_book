"""Read-only governance reporting for large derived processing artifacts."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.dto import (
    DerivedArtifactGovernanceSummaryDTO,
    DerivedArtifactMetricDTO,
)
from app.infra.sa_models import DictProject
from app.services.snapshot_readiness_service import SnapshotReadinessService

logger = logging.getLogger(__name__)


class DerivedArtifactGovernanceService:
    """Read-only service for project-scoped heavy derived artifact visibility."""

    def get_project_summary(
        self,
        session: Session,
        project_id: int,
    ) -> DerivedArtifactGovernanceSummaryDTO:
        started_at = time.perf_counter()
        timings: dict[str, float] = {}

        project = session.get(DictProject, int(project_id))
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        total_docs, timings["total_docs_s"] = self._scalar(
            session,
            text(
                "SELECT COUNT(*) "
                "FROM source_document sd "
                "JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id "
                "WHERE sc.project_id = :pid"
            ),
            {"pid": int(project_id)},
        )

        snapshot_started = time.perf_counter()
        snapshot_summary = SnapshotReadinessService().get_project_summary(session, int(project_id))
        timings["snapshot_summary_s"] = round(time.perf_counter() - snapshot_started, 3)

        lemma_doc_rows, timings["lemma_doc_rows_s"] = self._scalar(
            session,
            text("SELECT COUNT(*) FROM lemma_doc_stat WHERE project_id = :pid"),
            {"pid": int(project_id)},
        )
        lemma_project_rows, timings["lemma_project_rows_s"] = self._scalar(
            session,
            text("SELECT COUNT(*) FROM lemma_project_stat WHERE project_id = :pid"),
            {"pid": int(project_id)},
        )
        processor_run_rows, timings["processor_run_rows_s"] = self._scalar(
            session,
            text("SELECT COUNT(*) FROM processor_run WHERE project_id = :pid"),
            {"pid": int(project_id)},
        )
        run_error_rows, timings["run_error_rows_s"] = self._scalar(
            session,
            text(
                "SELECT COUNT(*) "
                "FROM run_error re "
                "JOIN processor_run pr ON pr.run_id = re.run_id "
                "WHERE pr.project_id = :pid"
            ),
            {"pid": int(project_id)},
        )

        run_status_rows, timings["run_status_rows_s"] = self._rows(
            session,
            text(
                "SELECT status, COUNT(*) AS n "
                "FROM processor_run "
                "WHERE project_id = :pid "
                "GROUP BY status "
                "ORDER BY status"
            ),
            {"pid": int(project_id)},
        )
        run_error_stage_rows, timings["run_error_stage_rows_s"] = self._rows(
            session,
            text(
                "SELECT re.stage, COUNT(*) AS n "
                "FROM run_error re "
                "JOIN processor_run pr ON pr.run_id = re.run_id "
                "WHERE pr.project_id = :pid "
                "GROUP BY re.stage "
                "ORDER BY n DESC, re.stage ASC"
            ),
            {"pid": int(project_id)},
        )

        processed_docs = int(snapshot_summary.processed_docs or 0)
        artifacts = [
            self._build_lemma_doc_stat_metric(
                project_id=int(project_id),
                is_reference_project=bool(getattr(project, "is_general_corpus", 0) or getattr(project, "is_reference", 0)),
                lemma_doc_rows=int(lemma_doc_rows or 0),
                processed_docs=processed_docs,
            ),
            self._build_lemma_project_stat_metric(
                project_id=int(project_id),
                is_reference_project=bool(getattr(project, "is_general_corpus", 0) or getattr(project, "is_reference", 0)),
                lemma_project_rows=int(lemma_project_rows or 0),
                processed_docs=processed_docs,
            ),
            self._build_snapshot_metric(
                snapshot_summary,
                project_id=int(project_id),
                is_reference_project=bool(getattr(project, "is_general_corpus", 0) or getattr(project, "is_reference", 0)),
            ),
            self._build_processor_run_metric(
                project_id=int(project_id),
                processor_run_rows=int(processor_run_rows or 0),
                processed_docs=processed_docs,
                status_rows=run_status_rows,
            ),
            self._build_run_error_metric(
                run_error_rows=int(run_error_rows or 0),
                processor_run_rows=int(processor_run_rows or 0),
                error_stage_rows=run_error_stage_rows,
            ),
        ]

        total_elapsed = round(time.perf_counter() - started_at, 3)
        logger.info(
            "Derived artifact governance summary loaded for project %s in %.3fs (%s)",
            int(project_id),
            total_elapsed,
            ", ".join(f"{key}={value:.3f}s" for key, value in sorted(timings.items())),
        )

        return DerivedArtifactGovernanceSummaryDTO(
            project_id=int(project.project_id),
            project_name=str(project.name or ""),
            is_reference_project=bool(getattr(project, "is_general_corpus", 0) or getattr(project, "is_reference", 0)),
            total_docs=int(total_docs or 0),
            processed_docs=processed_docs,
            snapshot_sentence_coverage_pct=snapshot_summary.sentence_coverage_pct,
            snapshot_doc_coverage_pct=snapshot_summary.doc_coverage_pct,
            observability_note=(
                "Observational only. This view does not delete, compact, or backfill any data."
            ),
            storage_note=(
                "Project-scoped exact counts are shown where they stay affordable on the target DB. "
                "Snapshot volume reuses the existing readiness aggregate because exact project-scoped "
                "snapshot row counts are too expensive on huge reference projects."
            ),
            lifecycle_note=(
                "These artifacts remain project-owned today and are removed by explicit project delete paths. "
                "Processor telemetry still needs a future retention policy; this view is meant to make that "
                "growth visible before it becomes opaque."
            ),
            snapshot_contract_note=snapshot_summary.contract_note,
            last_refreshed_at=self._utc_now(),
            artifacts=artifacts,
        )

    @staticmethod
    def _scalar(session: Session, stmt, params: Optional[dict[str, Any]] = None) -> tuple[int, float]:
        started_at = time.perf_counter()
        value = session.execute(stmt, params or {}).scalar() or 0
        return int(value or 0), round(time.perf_counter() - started_at, 3)

    @staticmethod
    def _rows(session: Session, stmt, params: Optional[dict[str, Any]] = None) -> tuple[list[dict[str, Any]], float]:
        started_at = time.perf_counter()
        rows = [dict(row) for row in session.execute(stmt, params or {}).mappings().all()]
        return rows, round(time.perf_counter() - started_at, 3)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def _format_ratio(numerator: int, denominator: int) -> Optional[str]:
        if denominator <= 0:
            return None
        return f"{(float(numerator) / float(denominator)):.2f}"

    def _build_lemma_doc_stat_metric(
        self,
        *,
        project_id: int,
        is_reference_project: bool,
        lemma_doc_rows: int,
        processed_docs: int,
    ) -> DerivedArtifactMetricDTO:
        detail_lines = [
            "Exact project row count via `lemma_doc_stat.project_id`.",
            "Project-owned derived rows; explicit set-based delete path is already required on project deletion.",
        ]
        ratio = self._format_ratio(lemma_doc_rows, processed_docs)
        if ratio is not None:
            detail_lines.append(f"Approx. {ratio} lemma-doc rows per processed document.")
        return DerivedArtifactMetricDTO(
            artifact_key="lemma_doc_stat",
            display_name="lemma_doc_stat",
            ownership="project-owned stats",
            quantity_value=int(lemma_doc_rows),
            quantity_unit="rows",
            quantity_basis="exact project count",
            status="expected_large",
            summary=(
                "This table is expected to be very large at reference scale. The goal is governance and "
                "delete-path safety, not eliminating the table."
            ),
            detail_lines=detail_lines,
            maintenance_mode="reset_rebuild_only",
            maintenance_note=(
                "No age-based retention is recommended. If storage pressure becomes real, start with a "
                "dry-run rebuild plan, then run a backup-backed preflight before any real write."
            ),
            maintenance_cli_hint=self._build_reference_rebuild_cli(
                project_id=project_id,
                is_reference_project=is_reference_project,
            ),
            maintenance_preflight_hint=self._build_reference_rebuild_preflight_cli(
                project_id=project_id,
                is_reference_project=is_reference_project,
            ),
        )

    def _build_lemma_project_stat_metric(
        self,
        *,
        project_id: int,
        is_reference_project: bool,
        lemma_project_rows: int,
        processed_docs: int,
    ) -> DerivedArtifactMetricDTO:
        detail_lines = [
            "Exact project row count via `lemma_project_stat.project_id`.",
            "Represents project-level aggregates, not raw per-document evidence rows.",
        ]
        ratio = self._format_ratio(lemma_project_rows, processed_docs)
        if ratio is not None:
            detail_lines.append(f"Approx. {ratio} aggregate rows per processed document.")
        return DerivedArtifactMetricDTO(
            artifact_key="lemma_project_stat",
            display_name="lemma_project_stat",
            ownership="project-owned aggregates",
            quantity_value=int(lemma_project_rows),
            quantity_unit="rows",
            quantity_basis="exact project count",
            status="expected_large",
            summary=(
                "Large but expected aggregate layer. Growth should be visible and deletable with the project, "
                "not silently treated as a cache."
            ),
            detail_lines=detail_lines,
            maintenance_mode="reset_rebuild_only",
            maintenance_note=(
                "No incremental retention is recommended. This aggregate layer should only be refreshed through "
                "an explicit project-level reset/rebuild workflow with a dry-run first and backup-backed preflight."
            ),
            maintenance_cli_hint=self._build_reference_rebuild_cli(
                project_id=project_id,
                is_reference_project=is_reference_project,
            ),
            maintenance_preflight_hint=self._build_reference_rebuild_preflight_cli(
                project_id=project_id,
                is_reference_project=is_reference_project,
            ),
        )

    def _build_snapshot_metric(
        self,
        snapshot_summary,
        *,
        project_id: int,
        is_reference_project: bool,
    ) -> DerivedArtifactMetricDTO:
        status = "no_snapshot_coverage"
        if snapshot_summary.contract_state == "stats_rebuild_required":
            status = "stats_rebuild_required"
        elif snapshot_summary.contract_state == "fully_covered":
            status = "fully_covered"
        elif snapshot_summary.snapshot_count_total > 0:
            status = "coverage_partial"

        detail_lines = [
            "Quantity comes from persisted per-document snapshot stats, not from a direct project-scoped snapshot row count.",
            f"Fully covered docs: {int(snapshot_summary.fully_covered_docs):,} / {int(snapshot_summary.processed_docs):,}.",
            f"Remaining uncovered docs: {int(snapshot_summary.remaining_uncovered_docs):,}.",
        ]
        if int(getattr(snapshot_summary, "stats_unknown_docs", 0) or 0) > 0:
            detail_lines.append(
                f"Docs with unknown snapshot stats: {int(snapshot_summary.stats_unknown_docs):,}."
            )
        if int(getattr(snapshot_summary, "stats_invalid_docs", 0) or 0) > 0:
            detail_lines.append(
                f"Docs with invalid snapshot stats: {int(snapshot_summary.stats_invalid_docs):,}."
            )
        if snapshot_summary.contract_note:
            detail_lines.append(str(snapshot_summary.contract_note))

        return DerivedArtifactMetricDTO(
            artifact_key="sentence_nlp_snapshot",
            display_name="sentence_nlp_snapshot",
            ownership="project-owned sentence snapshots",
            quantity_value=int(snapshot_summary.snapshot_count_total or 0),
            quantity_unit="covered sentences",
            quantity_basis="persisted document stats aggregate",
            status=status,
            summary=(
                f"Sentence coverage {self._format_pct(snapshot_summary.sentence_coverage_pct)}; "
                f"doc coverage {self._format_pct(snapshot_summary.doc_coverage_pct)}."
            ),
            detail_lines=detail_lines,
            maintenance_mode="reset_rebuild_only",
            maintenance_note=(
                "Do not prune snapshots by age. If lifecycle pressure becomes real, prefer an explicit "
                "project-level rebuild decision with a dry-run first and backup-backed preflight."
            ),
            maintenance_cli_hint=self._build_reference_rebuild_cli(
                project_id=project_id,
                is_reference_project=is_reference_project,
            ),
            maintenance_preflight_hint=self._build_reference_rebuild_preflight_cli(
                project_id=project_id,
                is_reference_project=is_reference_project,
            ),
        )

    def _build_processor_run_metric(
        self,
        *,
        project_id: int,
        processor_run_rows: int,
        processed_docs: int,
        status_rows: list[dict[str, Any]],
    ) -> DerivedArtifactMetricDTO:
        detail_lines = [
            "Exact project row count via `processor_run.project_id`.",
            "Operational telemetry is project-owned today; retention policy is still a future follow-up.",
        ]
        ratio = self._format_ratio(processor_run_rows, processed_docs)
        if ratio is not None:
            detail_lines.append(f"Approx. {ratio} run rows per processed document.")
        if status_rows:
            detail_lines.append(
                "Status mix: " + ", ".join(f"{row['status']}={int(row['n']):,}" for row in status_rows)
            )
        return DerivedArtifactMetricDTO(
            artifact_key="processor_run",
            display_name="processor_run",
            ownership="project-owned telemetry",
            quantity_value=int(processor_run_rows),
            quantity_unit="rows",
            quantity_basis="exact project count",
            status="retention_watch",
            summary=(
                "Useful operational history, but growth must stay visible because it can outlive the original "
                "operator intent."
            ),
            detail_lines=detail_lines,
            maintenance_mode="retention_available",
            maintenance_note=(
                "Safe dry-run/apply retention is available. Old successful rows with empty note metadata "
                "can be pruned while preserving recent successful rows, all non-ok rows, and noted evidence rows."
            ),
            maintenance_cli_hint=(
                f"python scripts\\prune_project_telemetry.py --db-path <db-path> --project-id {int(project_id)} --keep-latest-ok 200"
            ),
        )

    def _build_run_error_metric(
        self,
        *,
        run_error_rows: int,
        processor_run_rows: int,
        error_stage_rows: list[dict[str, Any]],
    ) -> DerivedArtifactMetricDTO:
        detail_lines = [
            "Exact project count through `processor_run -> run_error`.",
            "These rows are operational diagnostics, not business content.",
        ]
        if processor_run_rows > 0:
            error_rate = float(run_error_rows) / float(processor_run_rows) * 100.0
            detail_lines.append(f"Approx. error row rate: {error_rate:.4f}% of run rows.")
        if error_stage_rows:
            detail_lines.append(
                "Stage mix: " + ", ".join(f"{row['stage']}={int(row['n']):,}" for row in error_stage_rows)
            )
        return DerivedArtifactMetricDTO(
            artifact_key="run_error",
            display_name="run_error",
            ownership="project-owned telemetry",
            quantity_value=int(run_error_rows),
            quantity_unit="rows",
            quantity_basis="exact project count",
            status="low_volume" if int(run_error_rows) <= 100 else "retention_watch",
            summary=(
                "Error telemetry is usually low-volume. If it starts growing materially, retention and failure "
                "classification become the next follow-up."
            ),
            detail_lines=detail_lines,
            maintenance_mode="retention_with_parent_runs",
            maintenance_note=(
                "Do not prune run_error independently. Cleanup should happen through the parent processor_run "
                "retention path so evidence relationships stay intact."
            ),
        )

    @staticmethod
    def _build_reference_rebuild_cli(*, project_id: int, is_reference_project: bool) -> Optional[str]:
        if not is_reference_project:
            return None
        return (
            "python scripts\\process_reference_corpus.py "
            f"--db-path <db-path> --project-id {int(project_id)} --reprocess-all --dry-run"
        )

    @staticmethod
    def _build_reference_rebuild_preflight_cli(
        *,
        project_id: int,
        is_reference_project: bool,
    ) -> Optional[str]:
        if not is_reference_project:
            return None
        return (
            "python scripts\\process_reference_corpus.py "
            f"--db-path <db-path> --project-id {int(project_id)} --reprocess-all "
            "--backup-db-path <healthy-backup.db> --preflight-only"
        )

    @staticmethod
    def _format_pct(value: Optional[float]) -> str:
        if value is None:
            return "n/a"
        return f"{float(value):.2f}%"
