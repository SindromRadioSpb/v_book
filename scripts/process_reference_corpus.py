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
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

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
    args = parser.parse_args()

    if not args.project_id and not args.project_name:
        parser.error("Provide --project-id or --project-name")

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
            doc_ids_all = _get_unprocessed_doc_ids(session, project_id)

        pct_done = already_processed / total_all * 100 if total_all else 0
        logger.info(
            "Total docs: %d | Already processed: %d (%.1f%%) | To process: %d",
            total_all, already_processed, pct_done, len(doc_ids_all),
        )

        if args.max_docs > 0:
            doc_ids_all = doc_ids_all[: args.max_docs]
        doc_ids_to_process = doc_ids_all

        if not doc_ids_to_process:
            logger.info("Nothing to process. Exiting.")
            return

        logger.info(
            "Processing %d docs | chunk=%d sleep=%.1fs mock=%s gpu=%s%s",
            len(doc_ids_to_process), args.chunk_size, args.chunk_sleep,
            use_mock, use_gpu,
            " DRY-RUN" if args.dry_run else "",
        )

        process_service = ProcessService()
        total_success = 0
        total_error = 0
        chunks = [
            doc_ids_to_process[i : i + args.chunk_size]
            for i in range(0, len(doc_ids_to_process), args.chunk_size)
        ]
        start = time.monotonic()

        for chunk_idx, chunk in enumerate(chunks, 1):
            ok, err = _process_chunk(
                db_service, process_service, chunk, use_mock, use_gpu, args.dry_run
            )
            total_success += ok
            total_error += err
            elapsed = time.monotonic() - start
            docs_done = total_success + total_error
            rate = docs_done / elapsed if elapsed > 0 else 0
            remaining = len(doc_ids_to_process) - docs_done
            eta = remaining / rate if rate > 0 else float("inf")

            logger.info(
                "Chunk %d/%d | +%d ok +%d err | total %d/%d | %.1f doc/s | ETA %.0fs",
                chunk_idx, len(chunks), ok, err,
                docs_done, len(doc_ids_to_process), rate, eta,
            )

            if chunk_idx < len(chunks) and args.chunk_sleep > 0 and not args.dry_run:
                time.sleep(args.chunk_sleep)

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
