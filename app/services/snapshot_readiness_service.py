"""Read-only snapshot readiness reporting for operator-facing UI/CLI surfaces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.dto import SnapshotReadinessSummaryDTO
from app.infra.sa_models import DictProject, ProcessorRun

SNAPSHOT_BOUNDED_VALIDATION_MIN_DOCS = 10_000


class SnapshotReadinessService:
    """Read-only service for project snapshot coverage and latest backfill summary."""

    def get_project_summary(self, session: Session, project_id: int) -> SnapshotReadinessSummaryDTO:
        project = session.get(DictProject, int(project_id))
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        coverage = self._get_snapshot_coverage(session, int(project_id))
        backfill_runs = self._find_snapshot_backfill_runs(session, int(project_id))
        latest_run = backfill_runs[0] if backfill_runs else None
        bounded_evidence = self._find_bounded_validation_evidence(backfill_runs)
        contract_state = self._resolve_contract_state(
            project,
            coverage,
            latest_run,
            bounded_evidence,
        )

        summary_note = (
            "Observational only. This panel does not approve production rollout or start backfill."
        )
        contract_note = self._build_contract_note(
            project,
            coverage,
            latest_run,
            contract_state,
            bounded_evidence,
        )

        return SnapshotReadinessSummaryDTO(
            project_id=int(project.project_id),
            project_name=str(project.name or ""),
            is_general_corpus=bool(getattr(project, "is_general_corpus", 0)),
            is_reference_project=bool(getattr(project, "is_reference", 0)),
            processed_docs=int(coverage["processed_docs"]),
            fully_covered_docs=int(coverage["fully_covered_docs"]),
            zero_snapshot_docs=int(coverage["zero_snapshot_docs"]),
            partial_snapshot_docs=int(coverage["partial_snapshot_docs"]),
            remaining_uncovered_docs=max(
                int(coverage["processed_docs"]) - int(coverage["fully_covered_docs"]),
                0,
            ),
            sentence_count_total=int(coverage["sentence_count_total"]),
            snapshot_count_total=int(coverage["snapshot_count_total"]),
            sentence_coverage_pct=coverage["sentence_snapshot_coverage_pct"],
            doc_coverage_pct=coverage["doc_full_coverage_pct"],
            stats_valid_docs=int(coverage["stats_valid_docs"]),
            stats_unknown_docs=int(coverage["stats_unknown_docs"]),
            stats_invalid_docs=int(coverage["stats_invalid_docs"]),
            coverage_is_degraded=bool(coverage["coverage_is_degraded"]),
            coverage_source=str(coverage["coverage_source"]),
            latest_backfill_run_id=(
                int(latest_run.run_id) if latest_run is not None else None
            ),
            latest_backfill_status=(
                str(latest_run.status or "") if latest_run is not None and latest_run.status else None
            ),
            latest_backfill_stage=(
                str(latest_run.stage or "") if latest_run is not None and latest_run.stage else None
            ),
            latest_backfill_last_doc_id=(
                int(latest_run.last_doc_id)
                if latest_run is not None and latest_run.last_doc_id is not None
                else None
            ),
            latest_backfill_finished_at=(
                str(latest_run.finished_at or "")
                if latest_run is not None and latest_run.finished_at
                else None
            ),
            latest_backfill_docs_processed=(
                int(latest_run.docs_processed or 0) if latest_run is not None else 0
            ),
            latest_backfill_docs_total=(
                int(latest_run.docs_total or 0) if latest_run is not None else 0
            ),
            contract_state=contract_state,
            contract_note=contract_note,
            summary_note=summary_note,
            last_refreshed_at=self._utc_now(),
        )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def _parse_note_payload(note: Optional[str]) -> dict[str, Any]:
        if not note:
            return {}
        try:
            payload = json.loads(note)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _find_snapshot_backfill_runs(
        self,
        session: Session,
        project_id: int,
    ) -> list[ProcessorRun]:
        candidates: list[ProcessorRun] = (
            session.query(ProcessorRun)
            .filter(ProcessorRun.project_id == int(project_id))
            .order_by(ProcessorRun.run_id.desc())
            .limit(50)
            .all()
        )
        runs: list[ProcessorRun] = []
        for run in candidates:
            payload = self._parse_note_payload(getattr(run, "note", None))
            source = str(payload.get("source") or "")
            if source.startswith("snapshot_backfill"):
                runs.append(run)
        return runs

    def _build_validation_evidence(self, run: ProcessorRun) -> dict[str, Any]:
        payload = self._parse_note_payload(getattr(run, "note", None))
        validation_scope = str(payload.get("validation_scope") or "").strip().lower()
        validated_doc_count = int(payload.get("validated_doc_count") or 0)
        latest_doc_count = max(
            int(getattr(run, "docs_processed", 0) or 0),
            int(getattr(run, "docs_total", 0) or 0),
        )
        is_success = str(getattr(run, "status", "") or "") == "ok" and str(
            getattr(run, "stage", "") or ""
        ) == "completed"
        if not is_success:
            return {"kind": "none", "validated_doc_count": 0, "run": run}
        if validation_scope == "bounded" and validated_doc_count >= SNAPSHOT_BOUNDED_VALIDATION_MIN_DOCS:
            return {
                "kind": "bounded",
                "validated_doc_count": validated_doc_count,
                "source": "explicit_note",
                "run": run,
            }
        if latest_doc_count >= SNAPSHOT_BOUNDED_VALIDATION_MIN_DOCS:
            return {
                "kind": "bounded",
                "validated_doc_count": latest_doc_count,
                "source": "legacy_large_success",
                "run": run,
            }
        if latest_doc_count > 0:
            return {
                "kind": "limited",
                "validated_doc_count": latest_doc_count,
                "source": "small_success",
                "run": run,
            }
        return {"kind": "none", "validated_doc_count": 0, "run": run}

    def _find_bounded_validation_evidence(
        self,
        runs: list[ProcessorRun],
    ) -> Optional[dict[str, Any]]:
        for run in runs:
            evidence = self._build_validation_evidence(run)
            if evidence.get("kind") == "bounded":
                return evidence
        return None

    def _get_snapshot_coverage(self, session: Session, project_id: int) -> dict[str, Any]:
        row = session.execute(
            text(
                "SELECT "
                "  COUNT(sd.doc_id) AS processed_docs,"
                "  COALESCE(SUM(COALESCE(sd.sentence_count, 0)), 0) AS sentence_count_total,"
                "  COALESCE(SUM(CASE "
                "    WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'valid' "
                "    THEN COALESCE(sd.snapshot_sentence_count, 0) "
                "    ELSE 0 END), 0) AS snapshot_count_total,"
                "  SUM(CASE "
                "    WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'valid' "
                "      AND COALESCE(sd.sentence_count, 0) > 0 "
                "      AND COALESCE(sd.snapshot_sentence_count, 0) >= COALESCE(sd.sentence_count, 0) "
                "    THEN 1 ELSE 0 END) AS fully_covered_docs,"
                "  SUM(CASE "
                "    WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'valid' "
                "      AND COALESCE(sd.snapshot_sentence_count, 0) = 0 "
                "    THEN 1 ELSE 0 END) AS zero_snapshot_docs,"
                "  SUM(CASE "
                "    WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'valid' "
                "      AND COALESCE(sd.snapshot_sentence_count, 0) > 0 "
                "      AND COALESCE(sd.snapshot_sentence_count, 0) < COALESCE(sd.sentence_count, 0) "
                "    THEN 1 ELSE 0 END) AS partial_snapshot_docs,"
                "  SUM(CASE WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'valid' THEN 1 ELSE 0 END) AS stats_valid_docs,"
                "  SUM(CASE WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'unknown' THEN 1 ELSE 0 END) AS stats_unknown_docs,"
                "  SUM(CASE WHEN COALESCE(sd.snapshot_stats_state, 'unknown') = 'invalid' THEN 1 ELSE 0 END) AS stats_invalid_docs "
                "FROM source_document sd "
                "JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id "
                "WHERE sc.project_id = :pid AND sd.status = 'processed'"
            ),
            {"pid": int(project_id)},
        ).mappings().one()

        processed_docs = int(row["processed_docs"] or 0)
        sentence_count_total = int(row["sentence_count_total"] or 0)
        snapshot_count_total = int(row["snapshot_count_total"] or 0)
        fully_covered_docs = int(row["fully_covered_docs"] or 0)
        stats_valid_docs = int(row["stats_valid_docs"] or 0)
        stats_unknown_docs = int(row["stats_unknown_docs"] or 0)
        stats_invalid_docs = int(row["stats_invalid_docs"] or 0)
        coverage_is_degraded = (stats_unknown_docs + stats_invalid_docs) > 0
        if coverage_is_degraded and stats_valid_docs <= 0:
            sentence_coverage_pct = None
            doc_full_coverage_pct = None
        else:
            sentence_coverage_pct = (
                round(snapshot_count_total / sentence_count_total * 100.0, 4)
                if sentence_count_total
                else None
            )
            doc_full_coverage_pct = (
                round(fully_covered_docs / processed_docs * 100.0, 4)
                if processed_docs
                else None
            )
        return {
            "processed_docs": processed_docs,
            "sentence_count_total": sentence_count_total,
            "snapshot_count_total": snapshot_count_total,
            "fully_covered_docs": fully_covered_docs,
            "zero_snapshot_docs": int(row["zero_snapshot_docs"] or 0),
            "partial_snapshot_docs": int(row["partial_snapshot_docs"] or 0),
            "stats_valid_docs": stats_valid_docs,
            "stats_unknown_docs": stats_unknown_docs,
            "stats_invalid_docs": stats_invalid_docs,
            "coverage_is_degraded": coverage_is_degraded,
            "coverage_source": "source_document.snapshot_stats",
            "sentence_snapshot_coverage_pct": sentence_coverage_pct,
            "doc_full_coverage_pct": doc_full_coverage_pct,
        }

    def _resolve_contract_state(
        self,
        project: DictProject,
        coverage: dict[str, Any],
        latest_run: Optional[ProcessorRun],
        bounded_evidence: Optional[dict[str, Any]],
    ) -> str:
        processed_docs = int(coverage["processed_docs"])
        fully_covered_docs = int(coverage["fully_covered_docs"])
        snapshot_count_total = int(coverage["snapshot_count_total"])
        if bool(coverage.get("coverage_is_degraded")):
            return "stats_rebuild_required"

        if processed_docs <= 0:
            return "no_processed_docs"
        if fully_covered_docs >= processed_docs:
            return "fully_covered"
        if bounded_evidence is not None and (
            bool(getattr(project, "is_general_corpus", 0))
            or bool(getattr(project, "is_reference", 0))
        ):
            return "bounded_validated"
        if snapshot_count_total > 0:
            return "partial_coverage"
        return "no_snapshot_coverage"

    def _build_contract_note(
        self,
        project: DictProject,
        coverage: dict[str, Any],
        latest_run: Optional[ProcessorRun],
        contract_state: str,
        bounded_evidence: Optional[dict[str, Any]],
    ) -> str:
        if contract_state == "no_processed_docs":
            return "No processed documents exist for this project yet."
        if contract_state == "stats_rebuild_required":
            valid_docs = int(coverage.get("stats_valid_docs") or 0)
            unknown_docs = int(coverage.get("stats_unknown_docs") or 0)
            invalid_docs = int(coverage.get("stats_invalid_docs") or 0)
            return (
                "Persisted snapshot doc stats require rebuild or verification before this project can be "
                "treated as fully observed. "
                f"Validated docs: {valid_docs:,}; unknown stats: {unknown_docs:,}; invalid stats: {invalid_docs:,}. "
                "Coverage shown here is limited to currently validated document stats."
            )
        if contract_state == "fully_covered":
            return "All processed documents currently have sentence snapshots."
        if contract_state == "bounded_validated":
            evidence_run = bounded_evidence.get("run") if bounded_evidence else None
            evidence_docs = int(bounded_evidence.get("validated_doc_count") or 0) if bounded_evidence else 0
            if evidence_run is not None and evidence_docs > 0:
                return (
                    "Bounded staged validation exists for this workflow. "
                    f"Most recent bounded evidence: run #{int(evidence_run.run_id)} "
                    f"({evidence_docs:,} docs). Full-scale validation remains deferred."
                )
            return (
                "Bounded staged validation exists for this workflow. "
                "Full-scale validation remains deferred."
            )
        if contract_state == "partial_coverage":
            if latest_run is not None:
                return (
                    "Some processed documents already have sentence snapshots. "
                    "Use safe read-only coverage checks before any explicit backfill decision."
                )
            return "Partial snapshot coverage exists, but no recent snapshot backfill run was found."
        if bool(getattr(project, "is_general_corpus", 0)) or bool(getattr(project, "is_reference", 0)):
            return (
                "Reference-scale project. Heavy backfill requires the explicit decision gate "
                "documented in the runbook."
            )
        if int(coverage["processed_docs"]) > 0:
            return "Processed documents currently have no persisted sentence snapshots."
        return "No snapshot readiness data is available yet."
