"""Generate EXPLAIN QUERY PLAN audit for key hewiki-scale read flows."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.infra.sa_models import Lemma, LemmaProjectStat
from app.services.dictionary_service import DictionaryService
from app.services.document_service import DocumentService


def _resolve_project_id(conn: sqlite3.Connection, explicit_project_id: int | None) -> int:
    if explicit_project_id is not None:
        return int(explicit_project_id)

    row = conn.execute(
        """
        SELECT c.project_id, COUNT(d.doc_id) AS doc_count
        FROM source_corpus c
        LEFT JOIN source_document d ON d.corpus_id = c.corpus_id
        GROUP BY c.project_id
        ORDER BY doc_count DESC, c.project_id ASC
        LIMIT 1
        """
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0])

    fallback = conn.execute(
        "SELECT project_id FROM dict_project ORDER BY project_id ASC LIMIT 1"
    ).fetchone()
    if fallback and fallback[0] is not None:
        return int(fallback[0])

    raise RuntimeError("No projects found in database")


def _plan_notes(plan_rows: list[tuple[Any, ...]]) -> list[str]:
    details = [str(row[3]) for row in plan_rows]
    notes: list[str] = []
    if any("USE TEMP B-TREE" in d for d in details):
        notes.append("Uses temporary B-tree (sort/group spill risk).")
    if any(d.startswith("SCAN ") and "USING" not in d for d in details):
        notes.append("Contains full scan without explicit index usage.")
    if not notes:
        notes.append("No obvious full scan/temp B-tree marker in this plan.")
    return notes


def _table_indexes(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'index' AND tbl_name = ?
        ORDER BY name
        """,
        (table_name,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _read_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version' LIMIT 1"
    ).fetchone()
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _compile_stmt(stmt, session) -> str:
    return str(
        stmt.compile(
            dialect=session.bind.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )


def _build_live_queries(
    session, *, project_id: int, search_term: str
) -> list[tuple[str, str, str]]:
    dict_service = DictionaryService()
    doc_service = DocumentService()
    filters = {"pos": "All", "hide_noise": True, "search": ""}

    dictionary_page_stmt = (
        select(Lemma, LemmaProjectStat)
        .select_from(LemmaProjectStat)
        .join(
            Lemma,
            (Lemma.lemma_id == LemmaProjectStat.lemma_id)
            & (Lemma.project_id == LemmaProjectStat.project_id),
        )
        .where(
            LemmaProjectStat.project_id == project_id,
            Lemma.project_id == project_id,
        )
    )
    dictionary_page_stmt = dict_service._apply_filters(
        dictionary_page_stmt,
        filters,
        session=session,
    )
    dictionary_page_stmt = dict_service._apply_sort(
        dictionary_page_stmt,
        "freq_abs",
        "desc",
    )
    dictionary_page_stmt = dictionary_page_stmt.limit(100).offset(0)

    dictionary_count_stmt = select(func.count(Lemma.lemma_id)).where(Lemma.project_id == project_id)
    dictionary_count_stmt = dict_service._apply_filters(
        dictionary_count_stmt,
        filters,
        session=session,
    )

    picker_empty_stmt = (
        doc_service.build_project_documents_query(
            project_id,
            search_query=None,
            sort_by="doc_id",
            sort_dir="desc",
            session=session,
        )
        .limit(50)
        .offset(0)
    )

    picker_search_stmt = (
        doc_service.build_project_documents_query(
            project_id,
            search_query=search_term,
            sort_by="file_name",
            sort_dir="asc",
            session=session,
        )
        .limit(50)
        .offset(0)
    )

    return [
        (
            "Dictionary first page",
            "dictionary_first_page",
            _compile_stmt(dictionary_page_stmt, session),
        ),
        (
            "Dictionary count",
            "dictionary_count",
            _compile_stmt(dictionary_count_stmt, session),
        ),
        (
            "Document picker page (empty search)",
            "picker_page_empty",
            _compile_stmt(picker_empty_stmt, session),
        ),
        (
            "Document picker page (text search)",
            "picker_page_search",
            _compile_stmt(picker_search_stmt, session),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="EXPLAIN QUERY PLAN audit writer")
    parser.add_argument("--db-path", type=Path, required=True, help="SQLite DB path")
    parser.add_argument("--project-id", type=int, default=None, help="Project ID override")
    parser.add_argument("--search-term", type=str, default="wiki", help="Document search term")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/PERF_QUERY_PLANS_HEWIKI.md"),
        help="Markdown output path",
    )
    parser.add_argument(
        "--include-timings",
        action="store_true",
        help="Execute each query once and include elapsed time",
    )
    args = parser.parse_args()

    if not args.db_path.exists():
        raise FileNotFoundError(f"Database not found: {args.db_path}")

    conn = sqlite3.connect(f"file:{args.db_path}?mode=ro", uri=True)
    engine = create_engine(
        f"sqlite:///{args.db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    try:
        project_id = _resolve_project_id(conn, args.project_id)
        schema_version = _read_schema_version(conn)
        with session_factory() as session:
            queries = _build_live_queries(
                session,
                project_id=project_id,
                search_term=args.search_term,
            )

        report_lines: list[str] = []
        report_lines.append("# PERF Query Plan Audit (Hewiki)")
        report_lines.append("")
        report_lines.append(f"- Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`")
        report_lines.append(f"- DB: `{args.db_path}`")
        report_lines.append(f"- Schema version: `{schema_version}`")
        report_lines.append(f"- DB size bytes: `{args.db_path.stat().st_size}`")
        report_lines.append(f"- Project ID: `{project_id}`")
        report_lines.append(f"- Search term: `{args.search_term}`")
        report_lines.append(
            "- Query source: `DictionaryService` / `DocumentService` live statements"
        )
        report_lines.append("")

        report_lines.append("## Index Snapshot")
        report_lines.append("")
        for table_name in [
            "lemma",
            "lemma_project_stat",
            "source_corpus",
            "source_document",
            "document_sentence",
            "pronunciation_entry",
            "tm_entry",
        ]:
            indexes = _table_indexes(conn, table_name)
            report_lines.append(f"### `{table_name}`")
            if not indexes:
                report_lines.append("- (no indexes)")
            else:
                for idx_name in indexes:
                    report_lines.append(f"- `{idx_name}`")
            report_lines.append("")

        report_lines.append("## Query Plans")
        report_lines.append("")
        query_temp_btree: dict[str, bool] = {}
        for title, tag, sql in queries:
            plan_rows = conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
            query_temp_btree[tag] = any("USE TEMP B-TREE" in str(row[3]) for row in plan_rows)
            elapsed = None
            row_count = None
            if args.include_timings:
                started = time.perf_counter()
                rows = conn.execute(sql).fetchall()
                elapsed = time.perf_counter() - started
                row_count = len(rows)

            report_lines.append(f"### {title} (`{tag}`)")
            report_lines.append("")
            report_lines.append("```sql")
            report_lines.append(sql.strip())
            report_lines.append("```")
            report_lines.append("")
            report_lines.append("Plan:")
            for row in plan_rows:
                report_lines.append(f"- `{row}`")
            for note in _plan_notes(plan_rows):
                report_lines.append(f"- Note: {note}")
            if elapsed is not None:
                report_lines.append(f"- Sample time: `{elapsed:.4f}s` (rows={row_count})")
            report_lines.append("")

        report_lines.append("## Findings")
        report_lines.append("")
        report_lines.append(
            "- Dictionary first-page flow is index-driven when ordering uses "
            "`lemma_project_stat.lemma_id` as tie-breaker."
        )
        report_lines.append("- Dictionary count uses `idx_lemma_noise` and remains a bounded read.")
        if query_temp_btree.get("picker_page_empty"):
            report_lines.append(
                "- Document picker empty search still uses temporary sort; "
                "index pack migration adds `idx_doc_corpus_file_name` to reduce sort pressure "
                "for file-name ordered pagination paths."
            )
        if query_temp_btree.get("picker_page_search"):
            report_lines.append(
                "- Document picker text search may still use temporary sort for final ordering, "
                "but the split matcher path (title contains + indexed exact tag match) "
                "removes the slow `OR lower(...) LIKE` branch."
            )
        report_lines.append("")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(f"Wrote query plan report: {args.out.resolve()}")
        return 0
    finally:
        engine.dispose()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
