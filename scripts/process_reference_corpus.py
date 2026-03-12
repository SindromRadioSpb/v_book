#!/usr/bin/env python3
"""PERF-SCALE PATCH-J: CLI-only NLP processing for reference corpus projects.

This script is the ONLY supported way to run NLP processing on a reference
corpus project (is_reference=1 or is_general_corpus=1).  The UI blocks these
operations to prevent accidental multi-hour write sessions that would hold the
SQLite write-lock and block all other users.

Key fixes vs. original script:
- Per-document sessions (not one mega-session) → short write transactions.
- Inter-chunk sleep → other writers can interleave between chunks.
- --dry-run, --max-docs, --chunk-sleep, --project-id, --no-mock flags.
- Uses stdlib logging (no dependency on app.infra.util.logging).
- Exits with code 2 if any errors occurred.

Usage examples
--------------
Process all unprocessed docs in project 1 (mock engine, default):
    python scripts/process_reference_corpus.py --db-path hdle_premium.db --project-id 1

Process with Stanza + GPU, chunk 25, max 500:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --no-mock --use-gpu --chunk-size 25 --max-docs 500

Probe a deterministic late-scale processed-doc slice:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --backfill-snapshots --doc-offset 60000 --max-docs 60000 \\
        --probe-out build\\logs\\snapshot_probe.jsonl --probe-every-chunks 1

Dry run:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 --dry-run

Coverage-only snapshot audit:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --backfill-snapshots --coverage-only

Verify persisted snapshot doc stats:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --verify-snapshot-stats --max-docs 5000

Rebuild persisted snapshot doc stats:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --rebuild-snapshot-stats --backup-db-path healthy_backup.db --preflight-only

Backfill snapshots for already processed docs:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --backfill-snapshots --chunk-size 5000 --merge-batch-size 1000

Re-process all currently processed docs:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --reprocess-all --resume-latest

Repeat the same late-scale probe but skip the final WAL checkpoint flush:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --backfill-snapshots --doc-offset 60000 --max-docs 60000 \\
        --integrity-checkpoint-mode none
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("process_reference_corpus")

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _get_doc_counts(session, project_id: int) -> tuple[int, int]:
    """Return (total_all, already_processed) for the project."""
    from sqlalchemy import text

    total_all = session.execute(
        text(
            "SELECT COUNT(sd.doc_id) FROM source_document sd"
            " JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
            " WHERE sc.project_id = :pid"
        ),
        {"pid": project_id},
    ).scalar() or 0

    already_processed = session.execute(
        text(
            "SELECT COUNT(sd.doc_id) FROM source_document sd"
            " JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
            " WHERE sc.project_id = :pid AND sd.status = 'processed'"
        ),
        {"pid": project_id},
    ).scalar() or 0

    return total_all, already_processed


def _get_unprocessed_doc_ids(session, project_id: int) -> list[int]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT sd.doc_id FROM source_document sd"
            " JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
            " WHERE sc.project_id = :pid"
            "   AND (sd.status IS NULL OR sd.status NOT IN ('processed', 'processing'))"
            " ORDER BY sd.doc_id"
        ),
        {"pid": project_id},
    ).fetchall()
    return [r[0] for r in rows]


def _get_project_doc_ids(session, project_id: int) -> list[int]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT sd.doc_id FROM source_document sd"
            " JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
            " WHERE sc.project_id = :pid"
            " ORDER BY sd.doc_id"
        ),
        {"pid": project_id},
    ).fetchall()
    return [r[0] for r in rows]


def _get_processed_doc_ids(session, project_id: int) -> list[int]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT sd.doc_id FROM source_document sd"
            " JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
            " WHERE sc.project_id = :pid"
            "   AND sd.status = 'processed'"
            " ORDER BY sd.doc_id"
        ),
        {"pid": project_id},
    ).fetchall()
    return [r[0] for r in rows]


def _get_missing_snapshot_doc_ids(session, project_id: int) -> list[int]:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "WITH snapshot_counts AS ("
            "  SELECT ds.doc_id, COUNT(*) AS snapshot_count"
            "  FROM sentence_nlp_snapshot sns"
            "  JOIN document_sentence ds ON ds.sentence_id = sns.sentence_id"
            "  GROUP BY ds.doc_id"
            ") "
            "SELECT sd.doc_id FROM source_document sd"
            " JOIN source_corpus sc ON sc.corpus_id = sd.corpus_id"
            " LEFT JOIN snapshot_counts snap ON snap.doc_id = sd.doc_id"
            " WHERE sc.project_id = :pid"
            "   AND sd.status = 'processed'"
            "   AND COALESCE(sd.sentence_count, 0) > 0"
            "   AND COALESCE(snap.snapshot_count, 0) < COALESCE(sd.sentence_count, 0)"
            " ORDER BY sd.doc_id"
        ),
        {"pid": project_id},
    ).fetchall()
    return [r[0] for r in rows]


def _get_snapshot_coverage(session, project_id: int) -> dict[str, Any]:
    from sqlalchemy import text

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
        {"pid": project_id},
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
            if sentence_count_total else None
        ),
        "doc_full_coverage_pct": (
            round(fully_covered_docs / processed_docs * 100.0, 4)
            if processed_docs else None
        ),
    }


def _process_chunk(
    db_service,
    process_service,
    doc_ids: list[int],
    use_mock: bool,
    use_gpu: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """Process one chunk with per-document sessions. Returns (success, error)."""
    if dry_run:
        logger.info("[DRY-RUN] Would process %d docs: %s...", len(doc_ids), doc_ids[:3])
        return len(doc_ids), 0

    success = 0
    error = 0
    for doc_id in doc_ids:
        # Each document gets a fresh session → short write transaction per doc.
        with db_service.get_session() as session:
            try:
                ok = process_service.process_document(
                    session, doc_id, use_gpu=use_gpu, use_mock=use_mock
                )
                success += 1 if ok else 0
                error += 0 if ok else 1
            except Exception as exc:
                logger.error("Failed to process doc %d: %s", doc_id, exc)
                try:
                    session.rollback()
                except Exception:
                    pass
                error += 1
    return success, error


def _log_batch_state(state: dict[str, Any], tracker: dict[str, Any]) -> None:
    phase = str(state.get("phase") or "")
    run_id = state.get("run_id")
    docs_processed = int(state.get("docs_processed") or 0)
    docs_failed = int(state.get("docs_failed") or 0)
    docs_total = int(state.get("docs_total") or 0)
    chunks_completed = int(state.get("chunks_completed") or 0)
    chunks_total = int(state.get("chunks_total") or 0)
    last_doc_id = state.get("last_doc_id")
    status = str(state.get("status") or "")
    stage = str(state.get("stage") or "")
    message = str(state.get("message") or "")

    should_log = False
    if tracker.get("run_id") != run_id:
        should_log = True
    elif phase in {
        "started",
        "resumed",
        "paused",
        "cancelled",
        "completed",
        "verifying_integrity",
        "failed",
    }:
        should_log = True
    elif tracker.get("chunks_completed") != chunks_completed:
        should_log = True

    if not should_log:
        return

    logger.info(
        "Run %s | phase=%s status=%s stage=%s | docs=%d/%d failed=%d | chunks=%d/%d | last_doc_id=%s | %s",
        run_id,
        phase,
        status,
        stage,
        docs_processed + docs_failed,
        docs_total,
        docs_failed,
        chunks_completed,
        chunks_total,
        last_doc_id if last_doc_id is not None else "-",
        message,
    )
    tracker["run_id"] = run_id
    tracker["chunks_completed"] = chunks_completed


def _log_batch_verification(report: dict[str, Any]) -> None:
    if not report.get("ok"):
        logger.error(
            "Verification failed | mode=%s run_id=%s docs=%s remaining=%s | %s",
            report.get("mode"),
            report.get("run_id") if report.get("run_id") is not None else "-",
            report.get("doc_count"),
            report.get("remaining_docs"),
            report.get("reason") or "Unknown verification failure",
        )
        return

    logger.info(
        "Verification ok | mode=%s run_id=%s status=%s stage=%s | docs=%s remaining=%s chunk_size=%s",
        report.get("mode"),
        report.get("run_id") if report.get("run_id") is not None else "-",
        report.get("status") or "fresh",
        report.get("stage") or "queued",
        report.get("doc_count"),
        report.get("remaining_docs"),
        report.get("chunk_size") if report.get("chunk_size") is not None else "-",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_quick_check_probe(
    conn: sqlite3.Connection,
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    probe = {
        "ok": True,
        "rows": [],
        "error": None,
        "timed_out": False,
        "timeout_sec": float(timeout_sec),
    }
    quick_started = time.perf_counter()

    def _progress_handler() -> int:
        if timeout_sec <= 0:
            return 0
        elapsed = time.perf_counter() - quick_started
        return 1 if elapsed >= timeout_sec else 0

    conn.set_progress_handler(_progress_handler, 10_000)
    try:
        rows: list[str] = []
        try:
            rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check(10)").fetchall()]
        except sqlite3.OperationalError as exc:
            lowered = str(exc).lower()
            if "interrupted" in lowered and timeout_sec > 0:
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


def _collect_snapshot_backfill_probe(
    *,
    db_path: Path,
    project_id: int,
    state: dict[str, Any],
    quick_check_timeout_sec: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp_utc": _utc_now(),
        "db_path": str(db_path),
        "project_id": int(project_id),
        "run_id": state.get("run_id"),
        "phase": str(state.get("phase") or ""),
        "status": str(state.get("status") or ""),
        "stage": str(state.get("stage") or ""),
        "docs_total": int(state.get("docs_total") or 0),
        "docs_processed": int(state.get("docs_processed") or 0),
        "docs_failed": int(state.get("docs_failed") or 0),
        "chunks_total": int(state.get("chunks_total") or 0),
        "chunks_completed": int(state.get("chunks_completed") or 0),
        "last_doc_id": state.get("last_doc_id"),
        "message": str(state.get("message") or ""),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else None,
        "wal_size_bytes": None,
        "shm_size_bytes": None,
        "page_size": None,
        "page_count": None,
        "freelist_count": None,
        "snapshot_max_rowid": None,
        "snapshot_probe_error": None,
        "quick_check": None,
        "checkpoint_passive": None,
        "probe_error": None,
    }
    wal_path = Path(f"{db_path}-wal")
    shm_path = Path(f"{db_path}-shm")
    payload["wal_size_bytes"] = wal_path.stat().st_size if wal_path.exists() else None
    payload["shm_size_bytes"] = shm_path.stat().st_size if shm_path.exists() else None

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.execute("PRAGMA busy_timeout=15000")
        payload["page_size"] = int(conn.execute("PRAGMA page_size").fetchone()[0])
        payload["page_count"] = int(conn.execute("PRAGMA page_count").fetchone()[0])
        payload["freelist_count"] = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        checkpoint_row = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        if checkpoint_row is not None:
            payload["checkpoint_passive"] = [int(value) for value in checkpoint_row]
        try:
            snapshot_row = conn.execute(
                "SELECT MAX(rowid) FROM sentence_nlp_snapshot"
            ).fetchone()
            payload["snapshot_max_rowid"] = int(snapshot_row[0]) if snapshot_row and snapshot_row[0] is not None else None
        except sqlite3.Error as exc:
            payload["snapshot_probe_error"] = str(exc)
        payload["quick_check"] = _run_quick_check_probe(
            conn,
            timeout_sec=float(quick_check_timeout_sec),
        )
    except sqlite3.Error as exc:
        payload["probe_error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()

    return payload


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _build_snapshot_probe_callback(
    *,
    db_path: Path,
    project_id: int,
    probe_out: Path | None,
    probe_every_chunks: int,
    quick_check_timeout_sec: float,
    state_tracker: dict[str, Any],
):
    if probe_out is None:
        return lambda state: _log_batch_state(state, state_tracker)

    def _callback(state: dict[str, Any]) -> None:
        _log_batch_state(state, state_tracker)
        phase = str(state.get("phase") or "")
        chunks_completed = int(state.get("chunks_completed") or 0)
        should_probe = phase in {"started", "verifying_integrity", "completed", "failed", "cancelled"}
        if not should_probe and probe_every_chunks > 0 and phase == "chunk_complete":
            should_probe = chunks_completed > 0 and chunks_completed % probe_every_chunks == 0
        if not should_probe:
            return
        payload = _collect_snapshot_backfill_probe(
            db_path=db_path,
            project_id=project_id,
            state=state,
            quick_check_timeout_sec=quick_check_timeout_sec,
        )
        _append_jsonl(probe_out, payload)

    return _callback


def _is_snapshot_backfill_write(args: argparse.Namespace) -> bool:
    return bool(
        args.backfill_snapshots
        and not args.coverage_only
        and not args.verify_only
        and not args.dry_run
    )


def _is_reference_reprocess_write(args: argparse.Namespace) -> bool:
    return bool(
        args.reprocess_all
        and not args.verify_only
        and not args.dry_run
    )


def _is_snapshot_stats_rebuild_write(args: argparse.Namespace) -> bool:
    return bool(
        args.rebuild_snapshot_stats
        and not args.dry_run
    )


def _is_reference_heavy_write(args: argparse.Namespace) -> bool:
    return bool(
        _is_snapshot_backfill_write(args)
        or _is_reference_reprocess_write(args)
        or _is_snapshot_stats_rebuild_write(args)
    )


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
        conn.execute("SELECT 1 FROM source_document LIMIT 1").fetchone()
        conn.execute("SELECT 1 FROM document_sentence LIMIT 1").fetchone()
        try:
            conn.execute("SELECT sentence_id FROM sentence_nlp_snapshot ORDER BY sentence_id DESC LIMIT 1").fetchone()
        except sqlite3.Error:
            # A bounded probe should not fail solely because the snapshot table is empty.
            pass

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


def _run_reference_heavy_write_preflight(
    *,
    db_path: Path,
    backup_db_path: Path | None,
    project_id: int,
    selected_doc_count: int,
    allow_protected_db_heavy_write: bool,
    operation_label: str,
) -> dict[str, Any]:
    from app.infra.db_path_resolver import classify_db_profile, is_protected_reference_db_path

    db_profile = classify_db_profile(db_path)
    protected_target = is_protected_reference_db_path(db_path)
    report: dict[str, Any] = {
        "ok": False,
        "project_id": int(project_id),
        "selected_doc_count": int(selected_doc_count),
        "db_path": str(db_path),
        "db_profile": db_profile,
        "protected_target": bool(protected_target),
        "backup_db_path": str(backup_db_path) if backup_db_path is not None else None,
        "operation_label": str(operation_label),
        "target_probe": {},
        "backup_probe": {},
        "error": None,
    }

    if protected_target and not allow_protected_db_heavy_write:
        report["error"] = (
            f"Heavy {operation_label} is blocked on the protected baseline/main reference DB. "
            "Use a working test DB or disposable clone, or cross the explicit decision gate "
            "with --allow-protected-db-heavy-write."
        )
        return report

    if backup_db_path is None:
        report["error"] = (
            f"Heavy {operation_label} requires --backup-db-path so the target DB can be restored "
            "if durability verification fails."
        )
        return report

    backup_db_path = backup_db_path.resolve()
    if not backup_db_path.exists():
        report["error"] = f"Backup DB not found: {backup_db_path}"
        return report

    if backup_db_path == db_path.resolve():
        report["error"] = "--backup-db-path must point to a different DB file"
        return report

    target_probe = _sqlite_health_probe(db_path.resolve())
    backup_probe = _sqlite_health_probe(backup_db_path)
    report["target_probe"] = target_probe
    report["backup_probe"] = backup_probe

    if not target_probe.get("ok"):
        report["error"] = (
            "Target DB failed preflight health probe: "
            + str(target_probe.get("error") or "unknown error")
        )
        return report
    if not backup_probe.get("ok"):
        report["error"] = (
            "Backup DB failed preflight health probe: "
            + str(backup_probe.get("error") or "unknown error")
        )
        return report

    report["ok"] = True
    return report


def _log_reference_heavy_write_preflight(report: dict[str, Any]) -> None:
    operation_label = str(report.get("operation_label") or "reference write")
    if not report.get("ok"):
        logger.error(
            "%s preflight failed | project_id=%s profile=%s protected=%s docs=%s | %s",
            operation_label,
            report.get("project_id"),
            report.get("db_profile"),
            report.get("protected_target"),
            report.get("selected_doc_count"),
            report.get("error") or "unknown error",
        )
        return

    logger.info(
        "%s preflight ok | project_id=%s profile=%s protected=%s docs=%s target_schema=%s backup_schema=%s",
        operation_label,
        report.get("project_id"),
        report.get("db_profile"),
        report.get("protected_target"),
        report.get("selected_doc_count"),
        report.get("target_probe", {}).get("schema_version"),
        report.get("backup_probe", {}).get("schema_version"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CLI-only NLP processing for reference corpus (PERF-SCALE PATCH-J)"
    )
    parser.add_argument("--db-path", required=True, help="Path to main HDLE Premium DB")
    parser.add_argument(
        "--project-id", type=int, help="Project ID (preferred)"
    )
    parser.add_argument(
        "--project-name", type=str, help="Project name (fallback if --project-id not given)"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=50,
        help="Documents per chunk; for snapshot backfill this is the super-chunk boundary (default: 50)",
    )
    parser.add_argument(
        "--chunk-sleep", type=float, default=0.5,
        help="Sleep seconds between chunks for WAL interleave (default: 0.5)",
    )
    parser.add_argument(
        "--max-docs", type=int, default=0,
        help="Stop after N documents; 0 = no limit",
    )
    parser.add_argument(
        "--doc-offset",
        type=int,
        default=0,
        help="Skip the first N candidate docs before applying --max-docs (for deterministic bounded probes).",
    )
    parser.add_argument(
        "--no-mock", action="store_true",
        help="Use Stanza NLP engine instead of Mock (rule-based)",
    )
    parser.add_argument(
        "--use-gpu", action="store_true",
        help="Enable GPU for Stanza (requires CUDA)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be processed without writing",
    )
    parser.add_argument(
        "--resume-latest",
        action="store_true",
        help="Resume the latest matching incomplete batch run when possible",
    )
    parser.add_argument(
        "--resume-run-id",
        type=int,
        help="Resume this exact incomplete batch run ID instead of auto-selecting the latest match",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate the deterministic batch contract without writing to the DB",
    )
    parser.add_argument(
        "--backfill-snapshots",
        action="store_true",
        help="Backfill sentence_nlp_snapshot rows for already processed docs",
    )
    parser.add_argument(
        "--reprocess-all",
        action="store_true",
        help="Re-process all currently processed docs instead of processing only unprocessed docs.",
    )
    parser.add_argument(
        "--rebuild-snapshot-stats",
        action="store_true",
        help="Rebuild persisted per-document snapshot coverage stats for processed docs.",
    )
    parser.add_argument(
        "--verify-snapshot-stats",
        action="store_true",
        help="Verify persisted per-document snapshot coverage stats against source-of-truth tables.",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="Report sentence snapshot coverage for the selected project and exit",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run heavy snapshot-backfill preflight checks and exit without writing.",
    )
    parser.add_argument(
        "--backup-db-path",
        type=str,
        default=None,
        help="Path to a healthy backup DB required before heavy snapshot backfill writes.",
    )
    parser.add_argument(
        "--allow-protected-db-heavy-write",
        action="store_true",
        help="Explicit decision-gate override for heavy snapshot backfill on the protected baseline/main DB.",
    )
    parser.add_argument(
        "--probe-out",
        type=str,
        default=None,
        help="Optional JSONL path for snapshot backfill forensic probes.",
    )
    parser.add_argument(
        "--probe-every-chunks",
        type=int,
        default=0,
        help="Append an extra forensic probe every N completed chunks during snapshot backfill.",
    )
    parser.add_argument(
        "--probe-quick-check-timeout",
        type=float,
        default=2.0,
        help="Timeout in seconds for per-probe quick_check; timeout is treated as inconclusive.",
    )
    parser.add_argument(
        "--integrity-checkpoint-mode",
        choices=["truncate", "passive", "full", "restart", "none"],
        default=None,
        help="Optional snapshot-backfill post-run WAL checkpoint mode before the final quick_check (default backfill behavior: none).",
    )
    parser.add_argument(
        "--merge-batch-size",
        type=int,
        default=1000,
        help="Snapshot-backfill merge batch size from staging into sentence_nlp_snapshot (default: 1000).",
    )
    parser.add_argument(
        "--segment-quick-check-timeout",
        type=float,
        default=0.5,
        help="Bounded quick_check timeout in seconds after each snapshot backfill super-chunk (default: 0.5).",
    )
    args = parser.parse_args()

    if not args.project_id and not args.project_name:
        parser.error("Provide --project-id or --project-name")
    if args.resume_latest and args.resume_run_id is not None:
        parser.error("--resume-latest and --resume-run-id are mutually exclusive")
    if args.verify_only and args.dry_run:
        parser.error("--verify-only and --dry-run are mutually exclusive")
    if args.coverage_only and args.verify_only:
        parser.error("--coverage-only and --verify-only are mutually exclusive")
    if args.coverage_only and args.dry_run:
        parser.error("--coverage-only and --dry-run are mutually exclusive")
    if args.preflight_only and args.verify_only:
        parser.error("--preflight-only and --verify-only are mutually exclusive")
    if args.preflight_only and args.coverage_only:
        parser.error("--preflight-only and --coverage-only are mutually exclusive")
    if args.preflight_only and args.dry_run:
        parser.error("--preflight-only and --dry-run are mutually exclusive")
    if args.verify_snapshot_stats and args.verify_only:
        parser.error("--verify-snapshot-stats and --verify-only are mutually exclusive")
    if args.verify_snapshot_stats and args.dry_run:
        parser.error("--verify-snapshot-stats and --dry-run are mutually exclusive")
    if args.verify_snapshot_stats and args.preflight_only:
        parser.error("--verify-snapshot-stats and --preflight-only are mutually exclusive")
    if args.reprocess_all and args.backfill_snapshots:
        parser.error("--reprocess-all and --backfill-snapshots are mutually exclusive")
    if args.reprocess_all and args.coverage_only:
        parser.error("--reprocess-all and --coverage-only are mutually exclusive")
    if args.rebuild_snapshot_stats and args.backfill_snapshots:
        parser.error("--rebuild-snapshot-stats and --backfill-snapshots are mutually exclusive")
    if args.rebuild_snapshot_stats and args.reprocess_all:
        parser.error("--rebuild-snapshot-stats and --reprocess-all are mutually exclusive")
    if args.rebuild_snapshot_stats and args.coverage_only:
        parser.error("--rebuild-snapshot-stats and --coverage-only are mutually exclusive")
    if args.rebuild_snapshot_stats and args.verify_only:
        parser.error("--rebuild-snapshot-stats and --verify-only are mutually exclusive")
    if args.verify_snapshot_stats and args.backfill_snapshots:
        parser.error("--verify-snapshot-stats and --backfill-snapshots are mutually exclusive")
    if args.verify_snapshot_stats and args.reprocess_all:
        parser.error("--verify-snapshot-stats and --reprocess-all are mutually exclusive")
    if args.verify_snapshot_stats and args.coverage_only:
        parser.error("--verify-snapshot-stats and --coverage-only are mutually exclusive")
    if args.coverage_only and int(args.doc_offset or 0) > 0:
        parser.error("--doc-offset is not supported with --coverage-only")
    if args.resume_run_id is not None and int(args.resume_run_id) <= 0:
        parser.error("--resume-run-id must be >= 1")
    if int(args.doc_offset or 0) < 0:
        parser.error("--doc-offset must be >= 0")
    if int(args.probe_every_chunks or 0) < 0:
        parser.error("--probe-every-chunks must be >= 0")
    if float(args.probe_quick_check_timeout or 0.0) < 0:
        parser.error("--probe-quick-check-timeout must be >= 0")
    if int(args.merge_batch_size or 0) <= 0:
        parser.error("--merge-batch-size must be >= 1")
    if float(args.segment_quick_check_timeout or 0.0) < 0:
        parser.error("--segment-quick-check-timeout must be >= 0")
    if args.probe_out and not args.backfill_snapshots:
        parser.error("--probe-out requires --backfill-snapshots")
    if int(args.probe_every_chunks or 0) > 0 and not args.backfill_snapshots:
        parser.error("--probe-every-chunks requires --backfill-snapshots")
    if int(args.probe_every_chunks or 0) > 0 and not args.probe_out:
        parser.error("--probe-every-chunks requires --probe-out")
    if args.integrity_checkpoint_mode is not None and not args.backfill_snapshots:
        parser.error("--integrity-checkpoint-mode requires --backfill-snapshots")
    if (args.resume_latest or args.resume_run_id is not None) and (
        args.rebuild_snapshot_stats or args.verify_snapshot_stats
    ):
        parser.error("--resume-latest/--resume-run-id are not supported for snapshot stats rebuild/verify")
    if args.preflight_only and not (args.backfill_snapshots or args.reprocess_all or args.rebuild_snapshot_stats):
        parser.error("--preflight-only requires --backfill-snapshots, --reprocess-all, or --rebuild-snapshot-stats")
    if args.backup_db_path and not (args.backfill_snapshots or args.reprocess_all or args.rebuild_snapshot_stats):
        parser.error("--backup-db-path requires --backfill-snapshots, --reprocess-all, or --rebuild-snapshot-stats")
    if args.allow_protected_db_heavy_write and not (args.backfill_snapshots or args.reprocess_all or args.rebuild_snapshot_stats):
        parser.error("--allow-protected-db-heavy-write requires --backfill-snapshots, --reprocess-all, or --rebuild-snapshot-stats")

    db_path = Path(args.db_path)
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)
    probe_out = Path(args.probe_out).expanduser() if args.probe_out else None
    backup_db_path = Path(args.backup_db_path).expanduser() if args.backup_db_path else None
    integrity_checkpoint_mode = str(args.integrity_checkpoint_mode or "none")

    use_mock = not args.no_mock
    use_gpu = args.use_gpu
    wants_resume = bool(args.resume_latest or args.resume_run_id is not None)
    is_reprocess_mode = bool(args.reprocess_all)
    is_snapshot_stats_rebuild_mode = bool(args.rebuild_snapshot_stats)
    is_snapshot_stats_verify_mode = bool(args.verify_snapshot_stats)
    needs_snapshot_audit = bool(args.backfill_snapshots or args.coverage_only)

    from app.services.db_service import DBService
    from app.services.process_service import ProcessService
    from app.services.project_service import ProjectService
    from sqlalchemy import text as _text

    db_service = DBService.initialize(db_path)

    try:
        # Resolve project_id
        with db_service.get_session() as session:
            if args.project_id:
                project = ProjectService().get_project(session, args.project_id)
                if project is None:
                    logger.error("Project %d not found.", args.project_id)
                    sys.exit(1)
                project_id = args.project_id
            else:
                from sqlalchemy import select
                from app.infra.sa_models import DictProject
                project = session.execute(
                    select(DictProject).where(DictProject.name == args.project_name)
                ).scalar_one_or_none()
                if project is None:
                    logger.error("Project '%s' not found.", args.project_name)
                    sys.exit(1)
                project_id = int(project.project_id)

            is_ref = bool(getattr(project, "is_reference", 0) or project.is_general_corpus)
            logger.info(
                "Project: '%s' (id=%d, is_reference=%s, is_general_corpus=%s)",
                project.name, project_id,
                getattr(project, "is_reference", 0),
                project.is_general_corpus,
            )
            if not is_ref:
                logger.warning(
                    "Project %d is NOT a reference corpus. "
                    "Consider using the UI for regular projects.",
                    project_id,
                )

            total_all, already_processed = _get_doc_counts(session, project_id)
            project_doc_ids: list[int] = []
            remaining_doc_ids: list[int] = []
            processed_doc_ids: list[int] = []
            missing_snapshot_doc_ids: list[int] = []
            snapshot_coverage: dict[str, Any] | None = None

            if args.backfill_snapshots or is_reprocess_mode or is_snapshot_stats_rebuild_mode or is_snapshot_stats_verify_mode:
                processed_doc_ids = _get_processed_doc_ids(session, project_id)
            elif wants_resume:
                project_doc_ids = _get_project_doc_ids(session, project_id)
                remaining_doc_ids = _get_unprocessed_doc_ids(session, project_id)
            else:
                remaining_doc_ids = _get_unprocessed_doc_ids(session, project_id)

            if needs_snapshot_audit:
                missing_snapshot_doc_ids = _get_missing_snapshot_doc_ids(session, project_id)
                snapshot_coverage = _get_snapshot_coverage(session, project_id)

        pct_done = already_processed / total_all * 100 if total_all else 0
        logger.info(
            "Total docs: %d | Already processed: %d (%.1f%%) | To process: %d",
            total_all, already_processed, pct_done, len(remaining_doc_ids),
        )
        if snapshot_coverage is not None:
            logger.info(
                "Sentence snapshot coverage | processed_docs=%d fully_covered_docs=%d zero_snapshot_docs=%d partial_snapshot_docs=%d sentence_coverage=%s%% doc_coverage=%s%%",
                snapshot_coverage["processed_docs"],
                snapshot_coverage["fully_covered_docs"],
                snapshot_coverage["zero_snapshot_docs"],
                snapshot_coverage["partial_snapshot_docs"],
                snapshot_coverage["sentence_snapshot_coverage_pct"]
                if snapshot_coverage["sentence_snapshot_coverage_pct"] is not None
                else "-",
                snapshot_coverage["doc_full_coverage_pct"]
                if snapshot_coverage["doc_full_coverage_pct"] is not None
                else "-",
            )

        if args.coverage_only:
            logger.info(
                "Coverage-only mode complete | project_id=%d missing_snapshot_docs=%d",
                project_id,
                len(missing_snapshot_doc_ids),
            )
            return
        mode_label = "reference_processing"
        source_label = "reference_cli"
        if args.backfill_snapshots:
            mode_label = "snapshot_backfill"
            source_label = "snapshot_backfill_cli"
            doc_ids_all = processed_doc_ids
        elif is_reprocess_mode:
            mode_label = "reference_reprocess"
            source_label = "reference_cli_reprocess"
            doc_ids_all = processed_doc_ids
        elif is_snapshot_stats_rebuild_mode or is_snapshot_stats_verify_mode:
            mode_label = "snapshot_stats"
            source_label = "snapshot_stats"
            doc_ids_all = processed_doc_ids
        else:
            doc_ids_all = project_doc_ids if wants_resume else remaining_doc_ids
        if args.doc_offset > 0:
            doc_ids_all = doc_ids_all[args.doc_offset :]
        if args.max_docs > 0:
            doc_ids_all = doc_ids_all[: args.max_docs]
        doc_ids_to_process = doc_ids_all

        if args.backfill_snapshots and not wants_resume and not missing_snapshot_doc_ids:
            logger.info("No sentence snapshot backfill needed. Exiting.")
            return

        if not doc_ids_to_process:
            logger.info("Nothing to process. Exiting.")
            return

        if wants_resume:
            if args.backfill_snapshots:
                logger.info(
                    "Resume contract slice: %d processed docs (currently missing snapshots: %d)",
                    len(doc_ids_to_process),
                    len(missing_snapshot_doc_ids),
                )
            elif is_reprocess_mode:
                logger.info(
                    "Resume contract slice: %d processed docs (currently processed: %d)",
                    len(doc_ids_to_process),
                    len(processed_doc_ids),
                )
            else:
                logger.info(
                    "Resume contract slice: %d docs (remaining currently unprocessed: %d)",
                    len(doc_ids_to_process),
                    len(remaining_doc_ids),
                )
        elif args.backfill_snapshots:
            selected_doc_ids = set(doc_ids_to_process)
            logger.info(
                "Snapshot backfill candidate docs in current slice: %d of %d processed docs",
                len([doc_id for doc_id in missing_snapshot_doc_ids if doc_id in selected_doc_ids]),
                len(doc_ids_to_process),
            )
        elif is_reprocess_mode:
            logger.info(
                "Re-process candidate docs in current slice: %d processed docs",
                len(doc_ids_to_process),
            )
        elif is_snapshot_stats_rebuild_mode or is_snapshot_stats_verify_mode:
            logger.info(
                "Snapshot stats candidate docs in current slice: %d processed docs",
                len(doc_ids_to_process),
            )

        if doc_ids_to_process:
            logger.info(
                "Selected doc slice | offset=%d max_docs=%d first_doc_id=%d last_doc_id=%d selected=%d",
                int(args.doc_offset or 0),
                int(args.max_docs or 0),
                int(doc_ids_to_process[0]),
                int(doc_ids_to_process[-1]),
                len(doc_ids_to_process),
            )

        if args.preflight_only or _is_reference_heavy_write(args):
            operation_label = (
                "snapshot backfill"
                if args.backfill_snapshots
                else "reference reprocess"
                if is_reprocess_mode
                else "snapshot stats rebuild"
                if is_snapshot_stats_rebuild_mode
                else "reference write"
            )
            preflight = _run_reference_heavy_write_preflight(
                db_path=db_path,
                backup_db_path=backup_db_path,
                project_id=project_id,
                selected_doc_count=len(doc_ids_to_process),
                allow_protected_db_heavy_write=bool(args.allow_protected_db_heavy_write),
                operation_label=operation_label,
            )
            _log_reference_heavy_write_preflight(preflight)
            if not preflight.get("ok"):
                sys.exit(2)
            if args.preflight_only:
                return

        action_label = "Processing"
        if args.verify_only:
            action_label = "Verifying"
        elif args.dry_run:
            action_label = "Planning"
        if args.backfill_snapshots:
            action_label = {
                "Verifying": "Verifying snapshot backfill",
                "Planning": "Planning snapshot backfill",
                "Processing": "Backfilling snapshots",
            }[action_label]
        elif is_reprocess_mode:
            action_label = {
                "Verifying": "Verifying reprocess batch",
                "Planning": "Planning reprocess batch",
                "Processing": "Reprocessing",
            }[action_label]
        elif is_snapshot_stats_rebuild_mode:
            action_label = {
                "Planning": "Planning snapshot stats rebuild",
                "Processing": "Rebuilding snapshot stats",
            }[action_label]
        elif is_snapshot_stats_verify_mode:
            action_label = "Verifying snapshot stats"

        logger.info(
            "%s %d docs | chunk=%d sleep=%.1fs mock=%s gpu=%s%s",
            action_label,
            len(doc_ids_to_process),
            args.chunk_size,
            args.chunk_sleep,
            use_mock,
            use_gpu,
            " DRY-RUN" if args.dry_run else "",
        )
        if args.backfill_snapshots:
            logger.info(
                "Snapshot backfill settings | integrity_checkpoint_mode=%s merge_batch_size=%d segment_quick_check_timeout=%.2fs",
                integrity_checkpoint_mode,
                int(args.merge_batch_size),
                float(args.segment_quick_check_timeout),
            )

        if args.dry_run:
            total_success = len(doc_ids_to_process)
            total_error = 0
            chunks = [
                doc_ids_to_process[i : i + args.chunk_size]
                for i in range(0, len(doc_ids_to_process), args.chunk_size)
            ]
            for chunk_idx, chunk in enumerate(chunks, 1):
                logger.info("[DRY-RUN] Chunk %d/%d | docs=%d | sample=%s", chunk_idx, len(chunks), len(chunk), chunk[:3])
            logger.info("Finished. success=%d error=%d time=0.0s", total_success, total_error)
            return

        process_service = ProcessService()
        from app.services.snapshot_doc_stats_service import SnapshotDocStatsService

        snapshot_doc_stats_service = SnapshotDocStatsService()
        start = time.monotonic()
        state_tracker = {"run_id": None, "chunks_completed": None}
        state_callback = lambda state: _log_batch_state(state, state_tracker)
        if args.backfill_snapshots:
            state_callback = _build_snapshot_probe_callback(
                db_path=db_path,
                project_id=project_id,
                probe_out=probe_out,
                probe_every_chunks=int(args.probe_every_chunks or 0),
                quick_check_timeout_sec=float(args.probe_quick_check_timeout or 0.0),
                state_tracker=state_tracker,
            )

        if args.verify_only:
            with db_service.get_session() as session:
                report = process_service.verify_batch_run_contract(
                    session,
                    doc_ids_to_process,
                    use_gpu=use_gpu,
                    use_mock=use_mock,
                    is_reprocess=is_reprocess_mode,
                    source_label=source_label,
                    resume_latest=bool(args.resume_latest),
                    resume_run_id=args.resume_run_id,
                    contract="snapshot_backfill_v1" if args.backfill_snapshots else "process_document_v2",
                )
            _log_batch_verification(report)
            if not report.get("ok"):
                sys.exit(3)
            return

        if is_snapshot_stats_verify_mode:
            with db_service.get_read_session() as session:
                verification = snapshot_doc_stats_service.verify_document_stats(
                    session,
                    doc_ids_to_process,
                )
            logger.info(
                "Snapshot stats verify | docs_checked=%d docs_ok=%d docs_with_drift=%d sentence_count_mismatches=%d snapshot_count_mismatches=%d state_mismatches=%d sample_doc_ids=%s",
                verification.docs_checked,
                verification.docs_ok,
                verification.docs_with_drift,
                verification.sentence_count_mismatches,
                verification.snapshot_count_mismatches,
                verification.state_mismatches,
                verification.sample_doc_ids[:10],
            )
            if verification.docs_with_drift > 0:
                sys.exit(3)
            return

        if is_snapshot_stats_rebuild_mode:
            total_success = 0
            total_invalid = 0
            chunks = [
                doc_ids_to_process[i : i + args.chunk_size]
                for i in range(0, len(doc_ids_to_process), args.chunk_size)
            ]
            for chunk_idx, chunk in enumerate(chunks, 1):
                with db_service.get_session() as session:
                    refresh_result = snapshot_doc_stats_service.refresh_document_stats(
                        session,
                        chunk,
                    )
                    session.commit()
                total_success += int(refresh_result.docs_valid)
                total_invalid += int(refresh_result.docs_invalid)
                logger.info(
                    "Snapshot stats rebuild chunk %d/%d | docs=%d valid=%d invalid=%d snapshot_sentence_total=%d",
                    chunk_idx,
                    len(chunks),
                    len(chunk),
                    refresh_result.docs_valid,
                    refresh_result.docs_invalid,
                    refresh_result.snapshot_sentence_total,
                )
                if args.chunk_sleep > 0 and chunk_idx < len(chunks):
                    time.sleep(args.chunk_sleep)

            with db_service.get_read_session() as session:
                verification = snapshot_doc_stats_service.verify_document_stats(
                    session,
                    doc_ids_to_process,
                )
            logger.info(
                "Snapshot stats rebuild finished | docs=%d valid=%d invalid=%d verify_drift=%d time=%.1fs",
                len(doc_ids_to_process),
                total_success,
                total_invalid,
                verification.docs_with_drift,
                time.monotonic() - start,
            )
            if verification.docs_with_drift > 0:
                logger.error(
                    "Snapshot stats rebuild verify failed | sample_doc_ids=%s",
                    verification.sample_doc_ids[:10],
                )
                sys.exit(2)
            return

        try:
            with db_service.get_session() as session:
                if args.backfill_snapshots:
                    total_success, total_error = process_service.backfill_sentence_snapshots_batch(
                        session,
                        doc_ids_to_process,
                        use_gpu=use_gpu,
                        use_mock=use_mock,
                        chunk_size=args.chunk_size,
                        chunk_sleep=args.chunk_sleep,
                        state_callback=state_callback,
                        resume_latest=bool(args.resume_latest),
                        resume_run_id=args.resume_run_id,
                        source_label=source_label,
                        integrity_checkpoint_mode=integrity_checkpoint_mode,
                        merge_batch_size=int(args.merge_batch_size),
                        segment_quick_check_timeout=float(args.segment_quick_check_timeout),
                    )
                else:
                    total_success, total_error = process_service.process_documents_batch(
                        session,
                        doc_ids_to_process,
                        use_gpu=use_gpu,
                        use_mock=use_mock,
                        is_reprocess=is_reprocess_mode,
                        chunk_size=args.chunk_size,
                        chunk_sleep=args.chunk_sleep,
                        state_callback=state_callback,
                        resume_latest=bool(args.resume_latest),
                        resume_run_id=args.resume_run_id,
                        source_label=source_label,
                    )
        except Exception as exc:
            logger.error(
                "%s failed after %.1fs: %s",
                "Snapshot backfill"
                if args.backfill_snapshots
                else "Reference re-processing"
                if is_reprocess_mode
                else "Reference processing",
                time.monotonic() - start,
                exc,
            )
            sys.exit(2)

        logger.info(
            "Finished. success=%d error=%d time=%.1fs",
            total_success, total_error, time.monotonic() - start,
        )
        if total_error > 0:
            sys.exit(2)

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
