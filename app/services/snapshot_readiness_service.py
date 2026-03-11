"""Read-only snapshot readiness reporting for operator-facing UI/CLI surfaces."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.dto import SnapshotReadinessSummaryDTO
from app.infra.sa_models import DictProject, ProcessorRun


class SnapshotReadinessService:
    """Read-only service for project snapshot coverage and latest backfill summary."""

    def get_project_summary(self, session: Session, project_id: int) -> SnapshotReadinessSummaryDTO:
        project = session.get(DictProject, int(project_id))
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        coverage = self._get_snapshot_coverage(session, int(project_id))
        latest_run = self._find_latest_snapshot_backfill_run(session, int(project_id))
        contract_state = self._resolve_contract_state(project, coverage, latest_run)

        summary_note = (
            "Observational only. This panel does not approve production rollout or start backfill."
        )
        contract_note = self._build_contract_note(project, coverage, latest_run, contract_state)

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

    def _find_latest_snapshot_backfill_run(
        self,
        session: Session,
        project_id: int,
    ) -> Optional[ProcessorRun]:
        candidates = (
            session.query(ProcessorRun)
            .filter(ProcessorRun.project_id == int(project_id))
            .order_by(ProcessorRun.run_id.desc())
            .limit(50)
            .all()
        )
        for run in candidates:
            payload = self._parse_note_payload(getattr(run, "note", None))
            source = str(payload.get("source") or "")
            if source.startswith("snapshot_backfill"):
                return run
        return None

    def _get_snapshot_coverage(self, session: Session, project_id: int) -> dict[str, Any]:
        row = session.execute(
            text(
                "WITH processed_docs AS ("
                "  SELECT sd.doc_id, COALESCE(sd.sentence_count, 0) AS sentence_count"
                "  FROM source_document sd"
                "  JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
                "  WHERE sc.project_id = :pid AND sd.status = 'processed'"
                "), snapshot_counts AS ("
                "  SELECT ds.doc_id, COUNT(*) AS snapshot_count"
                "  FROM sentence_nlp_snapshot sns"
                "  JOIN document_sentence ds ON ds.sentence_id = sns.sentence_id"
                "  GROUP BY ds.doc_id"
                ") "
                "SELECT "
                "  COUNT(pd.doc_id) AS processed_docs,"
                "  COALESCE(SUM(pd.sentence_count), 0) AS sentence_count_total,"
                "  COALESCE(SUM(COALESCE(snap.snapshot_count, 0)), 0) AS snapshot_count_total,"
                "  SUM(CASE WHEN pd.sentence_count > 0 AND COALESCE(snap.snapshot_count, 0) >= pd.sentence_count THEN 1 ELSE 0 END) AS fully_covered_docs,"
                "  SUM(CASE WHEN COALESCE(snap.snapshot_count, 0) = 0 THEN 1 ELSE 0 END) AS zero_snapshot_docs,"
                "  SUM(CASE WHEN COALESCE(snap.snapshot_count, 0) > 0 AND COALESCE(snap.snapshot_count, 0) < pd.sentence_count THEN 1 ELSE 0 END) AS partial_snapshot_docs "
                "FROM processed_docs pd "
                "LEFT JOIN snapshot_counts snap ON snap.doc_id = pd.doc_id"
            ),
            {"pid": int(project_id)},
        ).mappings().one()

        processed_docs = int(row["processed_docs"] or 0)
        sentence_count_total = int(row["sentence_count_total"] or 0)
        snapshot_count_total = int(row["snapshot_count_total"] or 0)
        fully_covered_docs = int(row["fully_covered_docs"] or 0)
        return {
            "processed_docs": processed_docs,
            "sentence_count_total": sentence_count_total,
            "snapshot_count_total": snapshot_count_total,
            "fully_covered_docs": fully_covered_docs,
            "zero_snapshot_docs": int(row["zero_snapshot_docs"] or 0),
            "partial_snapshot_docs": int(row["partial_snapshot_docs"] or 0),
            "sentence_snapshot_coverage_pct": (
                round(snapshot_count_total / sentence_count_total * 100.0, 4)
                if sentence_count_total
                else None
            ),
            "doc_full_coverage_pct": (
                round(fully_covered_docs / processed_docs * 100.0, 4)
                if processed_docs
                else None
            ),
        }

    def _resolve_contract_state(
        self,
        project: DictProject,
        coverage: dict[str, Any],
        latest_run: Optional[ProcessorRun],
    ) -> str:
        processed_docs = int(coverage["processed_docs"])
        fully_covered_docs = int(coverage["fully_covered_docs"])
        snapshot_count_total = int(coverage["snapshot_count_total"])

        if processed_docs <= 0:
            return "no_processed_docs"
        if fully_covered_docs >= processed_docs:
            return "fully_covered"
        if latest_run is not None and (
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
    ) -> str:
        if contract_state == "no_processed_docs":
            return "No processed documents exist for this project yet."
        if contract_state == "fully_covered":
            return "All processed documents currently have sentence snapshots."
        if contract_state == "bounded_validated":
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
