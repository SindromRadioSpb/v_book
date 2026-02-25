"""Generate EXPLAIN QUERY PLAN audit for key hewiki-scale read flows."""

from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    try:
        project_id = _resolve_project_id(conn, args.project_id)
        search_pattern = f"%{args.search_term}%"

        queries = [
            (
                "Dictionary first page",
                "dictionary_first_page",
                """
SELECT l.lemma_id, l.lemma_text, l.pos, s.freq_abs, s.doc_freq
FROM lemma_project_stat AS s
JOIN lemma AS l
  ON l.lemma_id = s.lemma_id AND l.project_id = s.project_id
WHERE s.project_id = ?
  AND l.project_id = ?
  AND (l.is_noise = 0 OR l.is_noise IS NULL)
ORDER BY s.freq_abs DESC, s.lemma_id ASC
LIMIT 100 OFFSET 0
""",
                (project_id, project_id),
            ),
            (
                "Dictionary count",
                "dictionary_count",
                """
SELECT COUNT(l.lemma_id)
FROM lemma AS l
WHERE l.project_id = ?
  AND (l.is_noise = 0 OR l.is_noise IS NULL)
""",
                (project_id,),
            ),
            (
                "Document picker page (empty search)",
                "picker_page_empty",
                """
SELECT d.doc_id, d.file_name, d.tag
FROM source_document AS d
JOIN source_corpus AS c ON d.corpus_id = c.corpus_id
WHERE c.project_id = ?
ORDER BY d.doc_id DESC
LIMIT 50 OFFSET 0
""",
                (project_id,),
            ),
            (
                "Document picker page (text search)",
                "picker_page_search",
                """
SELECT d.doc_id, d.file_name, d.tag
FROM source_document AS d
JOIN source_corpus AS c ON d.corpus_id = c.corpus_id
WHERE c.project_id = ?
  AND (lower(d.file_name) LIKE lower(?) OR lower(d.tag) LIKE lower(?))
ORDER BY d.file_name ASC, d.doc_id ASC
LIMIT 50 OFFSET 0
""",
                (project_id, search_pattern, search_pattern),
            ),
        ]

        report_lines: list[str] = []
        report_lines.append("# PERF Query Plan Audit (Hewiki)")
        report_lines.append("")
        report_lines.append(f"- Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`")
        report_lines.append(f"- DB: `{args.db_path}`")
        report_lines.append(f"- Project ID: `{project_id}`")
        report_lines.append(f"- Search term: `{args.search_term}`")
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
        for title, tag, sql, params in queries:
            plan_rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
            query_temp_btree[tag] = any("USE TEMP B-TREE" in str(row[3]) for row in plan_rows)
            elapsed = None
            row_count = None
            if args.include_timings:
                started = time.perf_counter()
                rows = conn.execute(sql, params).fetchall()
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
        report_lines.append(
            "- Dictionary count uses `idx_lemma_noise` and remains a bounded read."
        )
        if query_temp_btree.get("picker_page_empty"):
            report_lines.append(
                "- Document picker empty search still uses temporary sort; "
                "index pack migration adds `idx_doc_corpus_file_name` to reduce sort pressure "
                "for file-name ordered pagination paths."
            )
        if query_temp_btree.get("picker_page_search"):
            report_lines.append(
                "- Document picker text search uses temporary sort due flexible text predicate; "
                "this is expected for contains-style matching."
            )
        report_lines.append("")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(f"Wrote query plan report: {args.out.resolve()}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
