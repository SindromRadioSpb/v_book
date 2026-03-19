"""Persisted per-document snapshot coverage stats and rebuild/verify helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

SNAPSHOT_STATS_STATE_UNKNOWN = "unknown"
SNAPSHOT_STATS_STATE_VALID = "valid"
SNAPSHOT_STATS_STATE_INVALID = "invalid"


@dataclass
class SnapshotDocStatsRefreshResult:
    docs_seen: int
    docs_valid: int
    docs_invalid: int
    snapshot_sentence_total: int
    sentence_count_mismatches: int


@dataclass
class SnapshotDocStatsVerifyResult:
    docs_checked: int
    docs_ok: int
    docs_with_drift: int
    sentence_count_mismatches: int
    snapshot_count_mismatches: int
    state_mismatches: int
    sample_doc_ids: list[int]


class SnapshotDocStatsService:
    """Source-of-truth helper for persisted snapshot coverage on source_document."""

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @staticmethod
    def _chunk_ids(doc_ids: Iterable[int], chunk_size: int = 500) -> list[list[int]]:
        ordered = [int(doc_id) for doc_id in doc_ids]
        size = max(1, int(chunk_size or 500))
        return [ordered[idx : idx + size] for idx in range(0, len(ordered), size)]

    def mark_documents_unknown(
        self,
        session: Session,
        doc_ids: Iterable[int],
    ) -> int:
        doc_chunks = self._chunk_ids(doc_ids)
        if not doc_chunks:
            return 0
        updated_at = self._utc_now()
        updated = 0
        for chunk in doc_chunks:
            params = [
                {
                    "doc_id": int(doc_id),
                    "updated_at": updated_at,
                }
                for doc_id in chunk
            ]
            session.execute(
                text(
                    "UPDATE source_document "
                    "SET snapshot_sentence_count = 0, "
                    "    snapshot_stats_state = :state, "
                    "    snapshot_stats_updated_at = :updated_at "
                    "WHERE doc_id = :doc_id"
                ),
                [
                    {
                        **row,
                        "state": SNAPSHOT_STATS_STATE_UNKNOWN,
                    }
                    for row in params
                ],
            )
            updated += len(chunk)
        return updated

    def set_document_valid(
        self,
        *,
        document,
        snapshot_sentence_count: int,
        updated_at: str | None = None,
    ) -> None:
        document.snapshot_sentence_count = max(int(snapshot_sentence_count or 0), 0)
        document.snapshot_stats_state = SNAPSHOT_STATS_STATE_VALID
        document.snapshot_stats_updated_at = str(updated_at or self._utc_now())

    def refresh_document_stats(
        self,
        session: Session,
        doc_ids: Iterable[int],
    ) -> SnapshotDocStatsRefreshResult:
        doc_ids_list = [int(doc_id) for doc_id in doc_ids]
        if not doc_ids_list:
            return SnapshotDocStatsRefreshResult(0, 0, 0, 0, 0)

        rows_by_doc: dict[int, dict[str, Any]] = {}
        for chunk in self._chunk_ids(doc_ids_list):
            param_names = [f"doc_id_{idx}" for idx in range(len(chunk))]
            params = {name: int(doc_id) for name, doc_id in zip(param_names, chunk)}
            in_clause = ", ".join(f":{name}" for name in param_names)
            rows = (
                session.execute(
                    text(
                        "SELECT "
                        "  sd.doc_id AS doc_id, "
                        "  COALESCE(sd.sentence_count, 0) AS stored_sentence_count, "
                        "  COUNT(ds.sentence_id) AS actual_sentence_count, "
                        "  COUNT(sns.sentence_id) AS actual_snapshot_sentence_count "
                        "FROM source_document sd "
                        "LEFT JOIN document_sentence ds ON ds.doc_id = sd.doc_id "
                        "LEFT JOIN sentence_nlp_snapshot sns ON sns.sentence_id = ds.sentence_id "
                        f"WHERE sd.doc_id IN ({in_clause}) "
                        "GROUP BY sd.doc_id, sd.sentence_count"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            for row in rows:
                rows_by_doc[int(row["doc_id"])] = dict(row)

        now = self._utc_now()
        updates: list[dict[str, Any]] = []
        docs_valid = 0
        docs_invalid = 0
        snapshot_sentence_total = 0
        sentence_count_mismatches = 0
        for doc_id in doc_ids_list:
            row = rows_by_doc.get(int(doc_id))
            if row is None:
                updates.append(
                    {
                        "doc_id": int(doc_id),
                        "snapshot_sentence_count": 0,
                        "snapshot_stats_state": SNAPSHOT_STATS_STATE_INVALID,
                        "snapshot_stats_updated_at": now,
                    }
                )
                docs_invalid += 1
                sentence_count_mismatches += 1
                continue

            stored_sentence_count = int(row["stored_sentence_count"] or 0)
            actual_sentence_count = int(row["actual_sentence_count"] or 0)
            actual_snapshot_sentence_count = int(row["actual_snapshot_sentence_count"] or 0)
            is_valid = stored_sentence_count == actual_sentence_count
            updates.append(
                {
                    "doc_id": int(doc_id),
                    "snapshot_sentence_count": actual_snapshot_sentence_count,
                    "snapshot_stats_state": (
                        SNAPSHOT_STATS_STATE_VALID if is_valid else SNAPSHOT_STATS_STATE_INVALID
                    ),
                    "snapshot_stats_updated_at": now,
                }
            )
            snapshot_sentence_total += actual_snapshot_sentence_count
            if is_valid:
                docs_valid += 1
            else:
                docs_invalid += 1
                sentence_count_mismatches += 1

        session.execute(
            text(
                "UPDATE source_document "
                "SET snapshot_sentence_count = :snapshot_sentence_count, "
                "    snapshot_stats_state = :snapshot_stats_state, "
                "    snapshot_stats_updated_at = :snapshot_stats_updated_at "
                "WHERE doc_id = :doc_id"
            ),
            updates,
        )
        return SnapshotDocStatsRefreshResult(
            docs_seen=len(doc_ids_list),
            docs_valid=docs_valid,
            docs_invalid=docs_invalid,
            snapshot_sentence_total=snapshot_sentence_total,
            sentence_count_mismatches=sentence_count_mismatches,
        )

    def verify_document_stats(
        self,
        session: Session,
        doc_ids: Iterable[int],
        *,
        sample_limit: int = 25,
    ) -> SnapshotDocStatsVerifyResult:
        doc_ids_list = [int(doc_id) for doc_id in doc_ids]
        if not doc_ids_list:
            return SnapshotDocStatsVerifyResult(0, 0, 0, 0, 0, 0, [])

        docs_ok = 0
        docs_with_drift = 0
        sentence_count_mismatches = 0
        snapshot_count_mismatches = 0
        state_mismatches = 0
        sample_doc_ids: list[int] = []

        for chunk in self._chunk_ids(doc_ids_list):
            param_names = [f"doc_id_{idx}" for idx in range(len(chunk))]
            params = {name: int(doc_id) for name, doc_id in zip(param_names, chunk)}
            in_clause = ", ".join(f":{name}" for name in param_names)
            rows = (
                session.execute(
                    text(
                        "SELECT "
                        "  sd.doc_id AS doc_id, "
                        "  COALESCE(sd.sentence_count, 0) AS stored_sentence_count, "
                        "  COALESCE(sd.snapshot_sentence_count, 0) AS stored_snapshot_sentence_count, "
                        "  COALESCE(sd.snapshot_stats_state, 'unknown') AS stored_snapshot_stats_state, "
                        "  COUNT(ds.sentence_id) AS actual_sentence_count, "
                        "  COUNT(sns.sentence_id) AS actual_snapshot_sentence_count "
                        "FROM source_document sd "
                        "LEFT JOIN document_sentence ds ON ds.doc_id = sd.doc_id "
                        "LEFT JOIN sentence_nlp_snapshot sns ON sns.sentence_id = ds.sentence_id "
                        f"WHERE sd.doc_id IN ({in_clause}) "
                        "GROUP BY "
                        "  sd.doc_id, sd.sentence_count, sd.snapshot_sentence_count, sd.snapshot_stats_state"
                    ),
                    params,
                )
                .mappings()
                .all()
            )

            for row in rows:
                doc_id = int(row["doc_id"])
                stored_sentence_count = int(row["stored_sentence_count"] or 0)
                stored_snapshot_sentence_count = int(row["stored_snapshot_sentence_count"] or 0)
                stored_state = str(
                    row["stored_snapshot_stats_state"] or SNAPSHOT_STATS_STATE_UNKNOWN
                )
                actual_sentence_count = int(row["actual_sentence_count"] or 0)
                actual_snapshot_sentence_count = int(row["actual_snapshot_sentence_count"] or 0)

                sentence_mismatch = stored_sentence_count != actual_sentence_count
                snapshot_mismatch = stored_snapshot_sentence_count != actual_snapshot_sentence_count
                expected_state = (
                    SNAPSHOT_STATS_STATE_VALID
                    if not sentence_mismatch
                    else SNAPSHOT_STATS_STATE_INVALID
                )
                state_mismatch = stored_state != expected_state

                if sentence_mismatch:
                    sentence_count_mismatches += 1
                if snapshot_mismatch:
                    snapshot_count_mismatches += 1
                if state_mismatch:
                    state_mismatches += 1

                if sentence_mismatch or snapshot_mismatch or state_mismatch:
                    docs_with_drift += 1
                    if len(sample_doc_ids) < int(sample_limit):
                        sample_doc_ids.append(doc_id)
                else:
                    docs_ok += 1

        return SnapshotDocStatsVerifyResult(
            docs_checked=len(doc_ids_list),
            docs_ok=docs_ok,
            docs_with_drift=docs_with_drift,
            sentence_count_mismatches=sentence_count_mismatches,
            snapshot_count_mismatches=snapshot_count_mismatches,
            state_mismatches=state_mismatches,
            sample_doc_ids=sample_doc_ids,
        )
