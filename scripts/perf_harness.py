"""Read-path performance harness for hewiki-scale profiling.

Usage:
    python scripts/perf_harness.py --db-path <path> --runs 5 --warmup 1 --out perf.json
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.dictionary_service import DictionaryService
from app.services.document_service import DocumentService


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _select_project_id(session_factory: sessionmaker, explicit_project_id: int | None) -> int:
    if explicit_project_id is not None:
        return int(explicit_project_id)

    with session_factory() as session:
        row = session.execute(
            text(
                """
                SELECT c.project_id, COUNT(d.doc_id) AS doc_count
                FROM source_corpus c
                LEFT JOIN source_document d ON d.corpus_id = c.corpus_id
                GROUP BY c.project_id
                ORDER BY doc_count DESC, c.project_id ASC
                LIMIT 1
                """
            )
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])

        fallback = session.execute(
            text("SELECT project_id FROM dict_project ORDER BY project_id ASC LIMIT 1")
        ).fetchone()
        if fallback and fallback[0] is not None:
            return int(fallback[0])

    raise RuntimeError("No projects found in database")


def _read_schema_version(session_factory: sessionmaker) -> int | None:
    with session_factory() as session:
        row = session.execute(
            text("SELECT value FROM schema_meta WHERE key = 'schema_version' LIMIT 1")
        ).fetchone()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _run_timed_operation(
    *,
    warmup: int,
    runs: int,
    operation: Callable[[], int],
) -> dict[str, Any]:
    samples: list[float] = []
    row_counts: list[int] = []

    total = warmup + runs
    for i in range(total):
        start = time.perf_counter()
        count = int(operation())
        elapsed = time.perf_counter() - start
        if i >= warmup:
            samples.append(elapsed)
            row_counts.append(count)

    return {
        "runs": samples,
        "rows": row_counts,
        "mean": float(statistics.fmean(samples)) if samples else 0.0,
        "p50": _percentile(samples, 50.0),
        "p95": _percentile(samples, 95.0),
        "min": min(samples) if samples else 0.0,
        "max": max(samples) if samples else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-path performance harness")
    parser.add_argument("--db-path", type=Path, required=True, help="SQLite DB path")
    parser.add_argument("--project-id", type=int, default=None, help="Project ID override")
    parser.add_argument("--runs", type=int, default=5, help="Measured runs")
    parser.add_argument("--warmup", type=int, default=1, help="Warm-up runs")
    parser.add_argument("--search-term", type=str, default="wiki", help="Picker search term")
    parser.add_argument("--out", type=Path, default=Path("perf_results.json"), help="JSON output path")
    args = parser.parse_args()

    if args.runs <= 0:
        raise ValueError("--runs must be > 0")
    if args.warmup < 0:
        raise ValueError("--warmup must be >= 0")
    if not args.db_path.exists():
        raise FileNotFoundError(f"Database not found: {args.db_path}")

    engine = create_engine(
        f"sqlite:///{args.db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    try:
        project_id = _select_project_id(session_factory, args.project_id)
        schema_version = _read_schema_version(session_factory)
        dict_service = DictionaryService()
        doc_service = DocumentService()
        filters = {"pos": "All", "hide_noise": True, "search": ""}

        def _dictionary_first_page() -> int:
            with session_factory() as session:
                rows = dict_service.search_lemmas(
                    session,
                    project_id=project_id,
                    filters=filters,
                    limit=100,
                    offset=0,
                    sort_column="freq_abs",
                    sort_direction="desc",
                )
                return len(rows)

        def _dictionary_count() -> int:
            with session_factory() as session:
                return int(
                    dict_service.count_lemmas(
                        session,
                        project_id=project_id,
                        filters=filters,
                    )
                )

        def _picker_page_empty() -> int:
            with session_factory() as session:
                rows = doc_service.fetch_project_documents_page(
                    session,
                    project_id=project_id,
                    search_query=None,
                    sort_by="doc_id",
                    sort_dir="desc",
                    limit=50,
                    offset=0,
                )
                return len(rows)

        def _picker_page_search() -> int:
            with session_factory() as session:
                rows = doc_service.fetch_project_documents_page(
                    session,
                    project_id=project_id,
                    search_query=args.search_term,
                    sort_by="file_name",
                    sort_dir="asc",
                    limit=50,
                    offset=0,
                )
                return len(rows)

        operations: dict[str, dict[str, Any]] = {
            "dictionary_first_page": _run_timed_operation(
                warmup=args.warmup, runs=args.runs, operation=_dictionary_first_page
            ),
            "dictionary_count": _run_timed_operation(
                warmup=args.warmup, runs=args.runs, operation=_dictionary_count
            ),
            "picker_page_empty": _run_timed_operation(
                warmup=args.warmup, runs=args.runs, operation=_picker_page_empty
            ),
            "picker_page_search": _run_timed_operation(
                warmup=args.warmup, runs=args.runs, operation=_picker_page_search
            ),
        }

        payload = {
            "schema": "hdle_perf_v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "db_path": str(args.db_path),
            "schema_version": schema_version,
            "db_size_bytes": int(args.db_path.stat().st_size),
            "project_id": int(project_id),
            "runs": int(args.runs),
            "warmup": int(args.warmup),
            "search_term": str(args.search_term),
            "env": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "sqlite3": sqlite3.sqlite_version,
            },
            "operations": operations,
        }

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        print(f"DB: {args.db_path}")
        print(f"Project ID: {project_id}")
        print(f"Output: {args.out.resolve()}")
        for name, stats in operations.items():
            print(
                f"{name}: p50={stats['p50']:.3f}s p95={stats['p95']:.3f}s "
                f"mean={stats['mean']:.3f}s rows(last)={stats['rows'][-1] if stats['rows'] else 0}"
            )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
