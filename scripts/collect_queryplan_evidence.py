#!/usr/bin/env python3
"""Collect deterministic EXPLAIN QUERY PLAN evidence for perf hot paths (PATCH-07)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


def _is_forbidden_m_path(path: Path) -> bool:
    normalized = str(path.resolve()).replace("/", "\\").upper()
    return normalized.startswith("M:\\")


def _is_expected_j_path(path: Path) -> bool:
    normalized = str(path.resolve()).replace("/", "\\").upper()
    return normalized.startswith("J:\\")


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

    fallback = conn.execute("SELECT project_id FROM dict_project ORDER BY project_id ASC LIMIT 1").fetchone()
    if fallback and fallback[0] is not None:
        return int(fallback[0])

    raise RuntimeError("No projects found in database.")


def _resolve_project_langs(conn: sqlite3.Connection, project_id: int) -> tuple[str, str]:
    row = conn.execute(
        "SELECT src_lang, tgt_lang FROM dict_project WHERE project_id = ? LIMIT 1",
        (project_id,),
    ).fetchone()
    if row:
        return str(row[0] or "he"), str(row[1] or "ru")
    return "he", "ru"


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


def _collect_one(
    conn: sqlite3.Connection,
    *,
    query_id: str,
    area: str,
    title: str,
    sql: str,
    params: tuple[Any, ...],
) -> dict[str, Any]:
    plan_rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    started = time.perf_counter()
    sample_rows = conn.execute(sql, params).fetchall()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "query_id": query_id,
        "area": area,
        "title": title,
        "sql": sql.strip(),
        "params": [str(x) for x in params],
        "plan_rows": [list(row) for row in plan_rows],
        "plan_notes": _plan_notes(plan_rows),
        "sample_elapsed_ms": elapsed_ms,
        "sample_row_count": len(sample_rows),
    }


def _write_markdown(out_path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Query Plan Evidence Pack")
    lines.append("")
    lines.append(f"- Generated UTC: `{payload['generated_utc']}`")
    lines.append(f"- DB Path: `{payload['db_path']}`")
    lines.append(f"- Schema Version: `{payload['schema_version']}`")
    lines.append(f"- DB Size Bytes: `{payload['db_size_bytes']}`")
    lines.append(f"- Project ID: `{payload['project_id']}`")
    lines.append(f"- Search term: `{payload['search_term']}`")
    lines.append("")
    lines.append("## Index Snapshot")
    lines.append("")
    for table_name, indexes in payload["index_snapshot"].items():
        lines.append(f"### `{table_name}`")
        if not indexes:
            lines.append("- (no indexes)")
        else:
            for idx in indexes:
                lines.append(f"- `{idx}`")
        lines.append("")
    lines.append("## Query Plans")
    lines.append("")
    for item in payload["queries"]:
        lines.append(f"### {item['title']} (`{item['query_id']}`)")
        lines.append("")
        lines.append(f"- Area: `{item['area']}`")
        lines.append(f"- Sample elapsed: `{item['sample_elapsed_ms']:.3f} ms`")
        lines.append(f"- Sample row count: `{item['sample_row_count']}`")
        lines.append("")
        lines.append("```sql")
        lines.append(item["sql"])
        lines.append("```")
        lines.append("")
        lines.append("Plan rows:")
        for row in item["plan_rows"]:
            lines.append(f"- `{tuple(row)}`")
        for note in item["plan_notes"]:
            lines.append(f"- Note: {note}")
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, required=True, help="SQLite DB path on J:\\.")
    parser.add_argument("--project-id", type=int, default=None, help="Project ID override.")
    parser.add_argument("--search-term", type=str, default="wiki", help="Search token for LIKE queries.")
    parser.add_argument("--out-dir", type=Path, default=Path("build/logs"), help="Output directory for JSON/MD artifacts.")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    db_path = args.db_path.expanduser().resolve()

    if _is_forbidden_m_path(db_path):
        raise RuntimeError(f"Forbidden db-path on M:\\ for query plan evidence: {db_path}")
    if not _is_expected_j_path(db_path):
        raise RuntimeError(f"Query plan evidence db-path must be on J:\\: {db_path}")
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"queryplan_evidence_{ts}.json"
    md_path = out_dir / f"queryplan_evidence_{ts}.md"

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        project_id = _resolve_project_id(conn, args.project_id)
        src_lang, tgt_lang = _resolve_project_langs(conn, project_id)
        like_term = f"%{args.search_term}%"
        schema_version = _read_schema_version(conn)

        queries = [
            {
                "query_id": "extract_terms_lemma_rollup",
                "area": "extract_terms",
                "title": "Extract Terms: lemma_doc_stat rollup",
                "sql": """
SELECT lds.lemma_id, SUM(lds.freq_abs) AS freq_abs, COUNT(DISTINCT lds.doc_id) AS doc_freq
FROM lemma_doc_stat AS lds
WHERE lds.project_id = ?
GROUP BY lds.lemma_id
ORDER BY freq_abs DESC, lds.lemma_id ASC
LIMIT 100
""",
                "params": (project_id,),
            },
            {
                "query_id": "dictionary_first_page",
                "area": "dictionary",
                "title": "Dictionary listing first page",
                "sql": """
SELECT l.lemma_id, l.lemma_text, l.pos, s.freq_abs, s.doc_freq
FROM lemma_project_stat AS s
JOIN lemma AS l ON l.lemma_id = s.lemma_id AND l.project_id = s.project_id
WHERE s.project_id = ?
  AND l.project_id = ?
  AND (l.is_noise = 0 OR l.is_noise IS NULL)
ORDER BY s.freq_abs DESC, s.lemma_id ASC
LIMIT 100
""",
                "params": (project_id, project_id),
            },
            {
                "query_id": "terms_listing",
                "area": "terms",
                "title": "Terms listing by frequency",
                "sql": """
SELECT tc.cluster_id, tc.representative_he, tc.freq_abs, tc.doc_freq
FROM term_cluster AS tc
WHERE tc.project_id = ?
ORDER BY tc.freq_abs DESC, tc.cluster_id ASC
LIMIT 100
""",
                "params": (project_id,),
            },
            {
                "query_id": "terms_search_like",
                "area": "terms",
                "title": "Terms search LIKE",
                "sql": """
SELECT ts.term_rowid, ts.he_term, ts.kind
FROM term_search AS ts
WHERE ts.project_id = ?
  AND ts.he_term LIKE ?
ORDER BY ts.term_rowid ASC
LIMIT 100
""",
                "params": (project_id, like_term),
            },
            {
                "query_id": "tm_entry_listing",
                "area": "translation_management",
                "title": "Translation management entry listing",
                "sql": """
SELECT tm.tm_id, tm.src_text, tm.translation, tm.status, tm.updated_at
FROM tm_entry AS tm
WHERE tm.project_id = ?
ORDER BY tm.updated_at DESC, tm.tm_id DESC
LIMIT 100
""",
                "params": (project_id,),
            },
            {
                "query_id": "tm_global_lookup",
                "area": "translation_management",
                "title": "TM Global lookup by normalized source",
                "sql": """
SELECT tg.tm_global_id, tg.src_text, tg.translation, tg.status
FROM tm_global AS tg
WHERE tg.src_lang = ?
  AND tg.tgt_lang = ?
  AND tg.src_norm LIKE ?
ORDER BY tg.tm_global_id DESC
LIMIT 100
""",
                "params": (src_lang, tgt_lang, like_term),
            },
        ]

        query_results = [
            _collect_one(
                conn,
                query_id=item["query_id"],
                area=item["area"],
                title=item["title"],
                sql=item["sql"],
                params=item["params"],
            )
            for item in queries
        ]

        payload = {
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "db_path": str(db_path),
            "schema_version": schema_version,
            "db_size_bytes": int(db_path.stat().st_size),
            "project_id": int(project_id),
            "search_term": str(args.search_term),
            "index_snapshot": {
                table: _table_indexes(conn, table)
                for table in [
                    "lemma",
                    "lemma_doc_stat",
                    "lemma_project_stat",
                    "term_cluster",
                    "term_search",
                    "tm_entry",
                    "tm_global",
                    "source_document",
                    "source_corpus",
                    "document_sentence",
                ]
            },
            "queries": query_results,
            "artifacts": {
                "json": str(json_path),
                "markdown": str(md_path),
            },
        }

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_markdown(md_path, payload)
        print(f"Query plan JSON: {json_path}")
        print(f"Query plan Markdown: {md_path}")
        return 0
    finally:
        conn.close()


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
