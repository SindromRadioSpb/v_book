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

Dry run:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 --dry-run

Coverage-only snapshot audit:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --backfill-snapshots --coverage-only

Backfill snapshots for already processed docs:
    python scripts/process_reference_corpus.py \\
        --db-path hdle_premium.db --project-id 1 \\
        --backfill-snapshots --chunk-size 50
"""
from __future__ import annotations

import argparse
import logging
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
        help="Documents per chunk / WAL commit boundary (default: 50)",
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
        "--coverage-only",
        action="store_true",
        help="Report sentence snapshot coverage for the selected project and exit",
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
    if args.resume_run_id is not None and int(args.resume_run_id) <= 0:
        parser.error("--resume-run-id must be >= 1")

    db_path = Path(args.db_path)
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    use_mock = not args.no_mock
    use_gpu = args.use_gpu

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
            project_doc_ids = _get_project_doc_ids(session, project_id)
            remaining_doc_ids = _get_unprocessed_doc_ids(session, project_id)
            processed_doc_ids = _get_processed_doc_ids(session, project_id)
            missing_snapshot_doc_ids = _get_missing_snapshot_doc_ids(session, project_id)
            snapshot_coverage = _get_snapshot_coverage(session, project_id)

        pct_done = already_processed / total_all * 100 if total_all else 0
        logger.info(
            "Total docs: %d | Already processed: %d (%.1f%%) | To process: %d",
            total_all, already_processed, pct_done, len(remaining_doc_ids),
        )
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

        wants_resume = bool(args.resume_latest or args.resume_run_id is not None)
        mode_label = "reference_processing"
        source_label = "reference_cli"
        if args.backfill_snapshots:
            mode_label = "snapshot_backfill"
            source_label = "snapshot_backfill_cli"
            doc_ids_all = processed_doc_ids
        else:
            doc_ids_all = project_doc_ids if wants_resume else remaining_doc_ids
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
        start = time.monotonic()
        state_tracker = {"run_id": None, "chunks_completed": None}

        if args.verify_only:
            with db_service.get_session() as session:
                report = process_service.verify_batch_run_contract(
                    session,
                    doc_ids_to_process,
                    use_gpu=use_gpu,
                    use_mock=use_mock,
                    source_label=source_label,
                    resume_latest=bool(args.resume_latest),
                    resume_run_id=args.resume_run_id,
                    contract="snapshot_backfill_v1" if args.backfill_snapshots else "process_document_v2",
                )
            _log_batch_verification(report)
            if not report.get("ok"):
                sys.exit(3)
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
                        state_callback=lambda state: _log_batch_state(state, state_tracker),
                        resume_latest=bool(args.resume_latest),
                        resume_run_id=args.resume_run_id,
                        source_label=source_label,
                    )
                else:
                    total_success, total_error = process_service.process_documents_batch(
                        session,
                        doc_ids_to_process,
                        use_gpu=use_gpu,
                        use_mock=use_mock,
                        chunk_size=args.chunk_size,
                        chunk_sleep=args.chunk_sleep,
                        state_callback=lambda state: _log_batch_state(state, state_tracker),
                        resume_latest=bool(args.resume_latest),
                        resume_run_id=args.resume_run_id,
                        source_label=source_label,
                    )
        except Exception as exc:
            logger.error(
                "%s failed after %.1fs: %s",
                "Snapshot backfill" if args.backfill_snapshots else "Reference processing",
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
