"""FTS5 table management and self-healing.

Ensures FTS5 virtual tables and triggers exist and are consistent.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# FTS5 table DDL from 001_init.sql
SENTENCE_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS sentence_fts USING fts5(
  text,
  doc_id UNINDEXED,
  sentence_id UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 1'
);
"""

TERM_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS term_fts USING fts5(
  he_term,
  ru_translation,
  notes,
  project_id UNINDEXED,
  kind UNINDEXED,
  lemma_id UNINDEXED,
  ngram_id UNINDEXED,
  term_rowid UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 1'
);
"""

# Trigger DDL for sentence_fts
SENTENCE_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_sentence_ai
    AFTER INSERT ON document_sentence
    BEGIN
      INSERT INTO sentence_fts(rowid, text, doc_id, sentence_id)
      VALUES (NEW.sentence_id, NEW.text, NEW.doc_id, NEW.sentence_id);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_sentence_ad
    AFTER DELETE ON document_sentence
    BEGIN
      DELETE FROM sentence_fts WHERE rowid = OLD.sentence_id;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_sentence_au
    AFTER UPDATE OF text ON document_sentence
    BEGIN
      DELETE FROM sentence_fts WHERE rowid = OLD.sentence_id;
      INSERT INTO sentence_fts(rowid, text, doc_id, sentence_id)
      VALUES (NEW.sentence_id, NEW.text, NEW.doc_id, NEW.sentence_id);
    END;
    """,
]

# Trigger DDL for term_fts
TERM_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_term_search_ai
    AFTER INSERT ON term_search
    BEGIN
      INSERT INTO term_fts(he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id, term_rowid)
      VALUES (NEW.he_term, NEW.ru_translation, NEW.notes, NEW.project_id, NEW.kind, NEW.lemma_id, NEW.ngram_id, NEW.term_rowid);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_term_search_ad
    AFTER DELETE ON term_search
    BEGIN
      DELETE FROM term_fts WHERE term_rowid = OLD.term_rowid;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_term_search_au
    AFTER UPDATE ON term_search
    BEGIN
      UPDATE term_fts
      SET he_term = NEW.he_term,
          ru_translation = NEW.ru_translation,
          notes = NEW.notes,
          project_id = NEW.project_id,
          kind = NEW.kind,
          lemma_id = NEW.lemma_id,
          ngram_id = NEW.ngram_id
      WHERE term_rowid = NEW.term_rowid;
    END;
    """,
]


# FTS5 DDL for document_name_fts (PERF-SCALE PATCH-D, migration 027)
DOCUMENT_NAME_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS document_name_fts USING fts5(
    file_name,
    content=source_document,
    content_rowid=doc_id,
    tokenize='unicode61 remove_diacritics 1'
);
"""

DOCUMENT_NAME_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_doc_name_fts_ai
    AFTER INSERT ON source_document BEGIN
        INSERT INTO document_name_fts(rowid, file_name)
            VALUES (new.doc_id, new.file_name);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_doc_name_fts_au
    AFTER UPDATE OF file_name ON source_document BEGIN
        INSERT INTO document_name_fts(document_name_fts, rowid, file_name)
            VALUES ('delete', old.doc_id, old.file_name);
        INSERT INTO document_name_fts(rowid, file_name)
            VALUES (new.doc_id, new.file_name);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_doc_name_fts_ad
    AFTER DELETE ON source_document BEGIN
        INSERT INTO document_name_fts(document_name_fts, rowid, file_name)
            VALUES ('delete', old.doc_id, old.file_name);
    END;
    """,
]


def ensure_document_name_fts_health(
    conn: sqlite3.Connection, schema: str = "main", rebuild: bool = False
) -> dict[str, bool]:
    """Ensure document_name_fts FTS5 table and its sync triggers exist.

    Creates the virtual table and triggers if missing.
    If rebuild=True (or table just created) and source_document has rows,
    repopulates the FTS index from source_document.file_name.

    Returns:
        {"document_name_fts": True}  — if table was created/rebuilt
        {"document_name_fts": False} — if table already existed and was not rebuilt
    """
    prefix = f"{schema}." if schema != "main" else ""
    created = False

    try:
        cursor = conn.execute(
            f"SELECT name FROM {schema}.sqlite_master"
            " WHERE type='table' AND name='document_name_fts'"
        )
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            logger.warning("document_name_fts missing in schema '%s', creating...", schema)
            conn.execute(
                DOCUMENT_NAME_FTS_DDL.replace(
                    "document_name_fts", f"{prefix}document_name_fts"
                ).replace("source_document", f"{prefix}source_document")
            )
            for trigger_ddl in DOCUMENT_NAME_FTS_TRIGGERS:
                conn.execute(trigger_ddl)
            logger.info("Created document_name_fts and triggers in schema '%s'", schema)
            created = True
            rebuild = True  # always rebuild after creation

        if rebuild:
            row_count = conn.execute(f"SELECT COUNT(*) FROM {prefix}source_document").fetchone()[0]
            if row_count > 0:
                # Check if FTS index is already populated to avoid redundant rebuild.
                fts_count = conn.execute(
                    f"SELECT COUNT(*) FROM {prefix}document_name_fts"
                ).fetchone()[0]
                if fts_count == 0:
                    logger.info(
                        "Rebuilding document_name_fts for %d rows in schema '%s'...",
                        row_count,
                        schema,
                    )
                    conn.execute(
                        f"INSERT INTO {prefix}document_name_fts"
                        f"({prefix}document_name_fts) VALUES('rebuild')"
                    )
                    logger.info("Rebuilt document_name_fts in schema '%s'", schema)
                else:
                    logger.debug(
                        "document_name_fts already populated (%d entries), skipping rebuild",
                        fts_count,
                    )
            else:
                logger.debug(
                    "source_document is empty in schema '%s', skipping FTS rebuild", schema
                )

        conn.commit()
        return {"document_name_fts": created}

    except Exception as e:
        logger.error("Failed to ensure document_name_fts in schema '%s': %s", schema, e)
        conn.rollback()
        raise


# FTS5 DDL for lemma_fts (PERF-SCALE PATCH-E, migration 029)
LEMMA_FTS_DDL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS lemma_fts USING fts5(
    lemma_text,
    content=lemma,
    content_rowid=lemma_id,
    tokenize='unicode61 remove_diacritics 1'
);
"""

LEMMA_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_lemma_fts_ai
    AFTER INSERT ON lemma BEGIN
        INSERT INTO lemma_fts(rowid, lemma_text)
            VALUES (new.lemma_id, new.lemma_text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_lemma_fts_au
    AFTER UPDATE OF lemma_text ON lemma BEGIN
        INSERT INTO lemma_fts(lemma_fts, rowid, lemma_text)
            VALUES ('delete', old.lemma_id, old.lemma_text);
        INSERT INTO lemma_fts(rowid, lemma_text)
            VALUES (new.lemma_id, new.lemma_text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_lemma_fts_ad
    AFTER DELETE ON lemma BEGIN
        INSERT INTO lemma_fts(lemma_fts, rowid, lemma_text)
            VALUES ('delete', old.lemma_id, old.lemma_text);
    END;
    """,
]

LEMMA_FTS_TRIGGER_NAMES = (
    "trg_lemma_fts_ai",
    "trg_lemma_fts_au",
    "trg_lemma_fts_ad",
)


def _quote_fts5_prefix_term(term: str) -> str:
    """Return a quoted FTS5 prefix query for a raw term."""
    escaped = str(term or "").replace('"', '""')
    return f'"{escaped}"*'


def inspect_lemma_fts_parity(
    conn: sqlite3.Connection,
    schema: str = "main",
    sample_limit: int = 5,
) -> dict[str, Any]:
    """Inspect lemma_fts rowid/search parity against lemma.lemma_id.

    This is intentionally a bounded, explicit health probe for the Dictionary
    search contract. It is not used on the hot search path.
    """
    prefix = f"{schema}." if schema != "main" else ""
    issues: list[str] = []

    table_exists = (
        conn.execute(
            f"SELECT name FROM {schema}.sqlite_master" " WHERE type='table' AND name='lemma_fts'"
        ).fetchone()
        is not None
    )

    trigger_rows = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master" " WHERE type='trigger' AND name IN (?, ?, ?)",
        LEMMA_FTS_TRIGGER_NAMES,
    ).fetchall()
    trigger_names = sorted(str(row[0]) for row in trigger_rows)
    missing_triggers = sorted(set(LEMMA_FTS_TRIGGER_NAMES) - set(trigger_names))

    lemma_count = int(conn.execute(f"SELECT COUNT(*) FROM {prefix}lemma").fetchone()[0])

    lemma_fts_count: int | None
    missing_in_fts_count: int | None
    extra_in_fts_count: int | None
    sample_missing_ids: list[int] = []
    sample_extra_rowids: list[int] = []
    semantic_sample_ids: list[int] = []
    unsearchable_sample_ids: list[int] = []

    if table_exists:
        lemma_fts_count = int(conn.execute(f"SELECT COUNT(*) FROM {prefix}lemma_fts").fetchone()[0])
        missing_in_fts_count = int(
            conn.execute(
                f"""
            SELECT COUNT(*)
            FROM {prefix}lemma AS l
            WHERE NOT EXISTS (
                SELECT 1
                FROM {prefix}lemma_fts AS f
                WHERE f.rowid = l.lemma_id
            )
            """
            ).fetchone()[0]
        )
        extra_in_fts_count = int(
            conn.execute(
                f"""
            SELECT COUNT(*)
            FROM {prefix}lemma_fts AS f
            WHERE NOT EXISTS (
                SELECT 1
                FROM {prefix}lemma AS l
                WHERE l.lemma_id = f.rowid
            )
            """
            ).fetchone()[0]
        )
        sample_missing_ids = [
            int(row[0])
            for row in conn.execute(
                f"""
                SELECT l.lemma_id
                FROM {prefix}lemma AS l
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM {prefix}lemma_fts AS f
                    WHERE f.rowid = l.lemma_id
                )
                ORDER BY l.lemma_id
                LIMIT ?
                """,
                (sample_limit,),
            ).fetchall()
        ]
        sample_extra_rowids = [
            int(row[0])
            for row in conn.execute(
                f"""
                SELECT f.rowid
                FROM {prefix}lemma_fts AS f
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM {prefix}lemma AS l
                    WHERE l.lemma_id = f.rowid
                )
                ORDER BY f.rowid
                LIMIT ?
                """,
                (sample_limit,),
            ).fetchall()
        ]
        semantic_rows = conn.execute(
            f"""
            SELECT l.lemma_id, l.lemma_text
            FROM {prefix}lemma AS l
            WHERE COALESCE(l.is_noise, 0) = 0
              AND LENGTH(TRIM(COALESCE(l.lemma_text, ''))) >= 2
            ORDER BY l.lemma_id ASC
            LIMIT ?
            """,
            (sample_limit,),
        ).fetchall()
        semantic_sample_ids = [int(row[0]) for row in semantic_rows]
        for lemma_id, lemma_text in semantic_rows:
            match_row = conn.execute(
                f"""
                SELECT 1
                FROM {prefix}lemma_fts
                WHERE rowid = ?
                  AND {prefix}lemma_fts MATCH ?
                LIMIT 1
                """,
                (int(lemma_id), _quote_fts5_prefix_term(str(lemma_text))),
            ).fetchone()
            if match_row is None:
                unsearchable_sample_ids.append(int(lemma_id))
    else:
        lemma_fts_count = None
        missing_in_fts_count = None
        extra_in_fts_count = None

    if not table_exists:
        issues.append("missing_lemma_fts")
    if missing_triggers:
        issues.append(f"missing_triggers:{missing_triggers}")
    if lemma_fts_count is not None and lemma_fts_count != lemma_count:
        issues.append(f"row_count_mismatch:lemma={lemma_count},lemma_fts={lemma_fts_count}")
    if missing_in_fts_count:
        issues.append(f"missing_rowids_in_fts:{missing_in_fts_count}")
    if extra_in_fts_count:
        issues.append(f"extra_rowids_in_fts:{extra_in_fts_count}")
    if unsearchable_sample_ids:
        issues.append(f"unsearchable_sample_rowids:{unsearchable_sample_ids}")

    healthy = (
        table_exists
        and not missing_triggers
        and missing_in_fts_count == 0
        and extra_in_fts_count == 0
        and lemma_fts_count == lemma_count
        and not unsearchable_sample_ids
    )

    return {
        "healthy": healthy,
        "table_exists": table_exists,
        "trigger_names": trigger_names,
        "missing_triggers": missing_triggers,
        "lemma_count": lemma_count,
        "lemma_fts_count": lemma_fts_count,
        "missing_in_fts_count": missing_in_fts_count,
        "extra_in_fts_count": extra_in_fts_count,
        "sample_missing_ids": sample_missing_ids,
        "sample_extra_rowids": sample_extra_rowids,
        "semantic_sample_ids": semantic_sample_ids,
        "unsearchable_sample_ids": unsearchable_sample_ids,
        "issues": issues,
    }


def rebuild_lemma_fts(
    conn: sqlite3.Connection,
    schema: str = "main",
) -> dict[str, Any]:
    """Drop, recreate, and rebuild lemma_fts with post-check verification."""
    prefix = f"{schema}." if schema != "main" else ""
    before = inspect_lemma_fts_parity(conn, schema=schema)

    try:
        for trigger_name in LEMMA_FTS_TRIGGER_NAMES:
            qualified_trigger = f"{schema}.{trigger_name}" if schema != "main" else trigger_name
            conn.execute(f"DROP TRIGGER IF EXISTS {qualified_trigger}")

        conn.execute(f"DROP TABLE IF EXISTS {prefix}lemma_fts")
        conn.execute(
            LEMMA_FTS_DDL.replace("lemma_fts", f"{prefix}lemma_fts").replace(
                "content=lemma", f"content={prefix}lemma"
            )
        )
        for trigger_ddl in LEMMA_FTS_TRIGGERS:
            conn.execute(trigger_ddl)

        row_count = int(conn.execute(f"SELECT COUNT(*) FROM {prefix}lemma").fetchone()[0])
        if row_count > 0:
            conn.execute(f"INSERT INTO {prefix}lemma_fts(lemma_fts) VALUES('rebuild')")

        after = inspect_lemma_fts_parity(conn, schema=schema)
        if not after["healthy"]:
            raise RuntimeError(
                "lemma_fts post-rebuild parity check failed: " + ", ".join(after["issues"])
            )

        conn.commit()
        return {
            "action": "drop_recreate_rebuild",
            "row_count_rebuilt": row_count,
            "before": before,
            "after": after,
        }
    except Exception:
        conn.rollback()
        raise


def ensure_lemma_fts_health(
    conn: sqlite3.Connection, schema: str = "main", rebuild: bool = False
) -> dict[str, bool]:
    """Ensure lemma_fts FTS5 table and its sync triggers exist.

    Creates the virtual table and triggers if missing.
    If rebuild=True (or table just created) and lemma has rows,
    repopulates the FTS index.

    Returns:
        {"lemma_fts": True}  — if table was created/rebuilt
        {"lemma_fts": False} — if table already existed and was not rebuilt
    """
    prefix = f"{schema}." if schema != "main" else ""
    created = False

    try:
        cursor = conn.execute(
            f"SELECT name FROM {schema}.sqlite_master" " WHERE type='table' AND name='lemma_fts'"
        )
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            logger.warning("lemma_fts missing in schema '%s', creating...", schema)
            conn.execute(
                LEMMA_FTS_DDL.replace("lemma_fts", f"{prefix}lemma_fts").replace(
                    "content=lemma", f"content={prefix}lemma"
                )
            )
            for trigger_ddl in LEMMA_FTS_TRIGGERS:
                conn.execute(trigger_ddl)
            logger.info("Created lemma_fts and triggers in schema '%s'", schema)
            created = True
            rebuild = True

        if rebuild:
            row_count = conn.execute(f"SELECT COUNT(*) FROM {prefix}lemma").fetchone()[0]
            if row_count > 0:
                fts_count = conn.execute(f"SELECT COUNT(*) FROM {prefix}lemma_fts").fetchone()[0]
                if fts_count == 0:
                    logger.info(
                        "Rebuilding lemma_fts for %d rows in schema '%s'...",
                        row_count,
                        schema,
                    )
                    conn.execute(
                        f"INSERT INTO {prefix}lemma_fts" f"({prefix}lemma_fts) VALUES('rebuild')"
                    )
                    logger.info("Rebuilt lemma_fts in schema '%s'", schema)
                else:
                    logger.debug(
                        "lemma_fts already populated (%d entries), skipping rebuild",
                        fts_count,
                    )
            else:
                logger.debug("lemma table is empty in schema '%s', skipping FTS rebuild", schema)

        conn.commit()
        return {"lemma_fts": created}

    except Exception as e:
        logger.error("Failed to ensure lemma_fts in schema '%s': %s", schema, e)
        conn.rollback()
        raise


def check_fts_exists(conn: sqlite3.Connection, schema: str = "main") -> tuple[bool, bool]:
    """Check if FTS tables exist.

    Args:
        conn: SQLite connection
        schema: Schema name (main/host)

    Returns:
        Tuple of (sentence_fts_exists, term_fts_exists)
    """
    cursor = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name IN ('sentence_fts', 'term_fts')"
    )
    fts_tables = {row[0] for row in cursor.fetchall()}
    return ("sentence_fts" in fts_tables, "term_fts" in fts_tables)


def ensure_fts_tables(
    conn: sqlite3.Connection, schema: str = "main", rebuild: bool = False
) -> dict[str, bool]:
    """Ensure FTS5 tables and triggers exist, create if missing.

    Args:
        conn: SQLite connection
        schema: Schema name (main/host)
        rebuild: If True, rebuild FTS data from base tables

    Returns:
        Dict with {table_name: created} status
    """
    prefix = f"{schema}." if schema != "main" else ""
    results = {}

    try:
        # Check current state
        sentence_fts_exists, term_fts_exists = check_fts_exists(conn, schema)

        # Create sentence_fts if missing
        if not sentence_fts_exists:
            logger.warning(f"sentence_fts missing in schema '{schema}', creating...")
            conn.execute(SENTENCE_FTS_DDL.replace("sentence_fts", f"{prefix}sentence_fts"))
            for trigger_ddl in SENTENCE_FTS_TRIGGERS:
                # Triggers reference tables without schema prefix (same schema assumed)
                conn.execute(trigger_ddl)
            logger.info(f"Created sentence_fts and triggers in schema '{schema}'")
            results["sentence_fts"] = True

            # Rebuild data if requested and base table has data
            if rebuild:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {prefix}document_sentence")
                row_count = cursor.fetchone()[0]
                if row_count > 0:
                    logger.info(f"Rebuilding sentence_fts with {row_count} rows...")
                    conn.execute(
                        f"""
                        INSERT INTO {prefix}sentence_fts(text, doc_id, sentence_id)
                        SELECT text, doc_id, sentence_id FROM {prefix}document_sentence
                        """
                    )
                    logger.info(f"Rebuilt sentence_fts in schema '{schema}'")
        else:
            logger.debug(f"sentence_fts exists in schema '{schema}'")
            results["sentence_fts"] = False

        # Create term_fts if missing
        if not term_fts_exists:
            logger.warning(f"term_fts missing in schema '{schema}', creating...")
            conn.execute(TERM_FTS_DDL.replace("term_fts", f"{prefix}term_fts"))
            for trigger_ddl in TERM_FTS_TRIGGERS:
                conn.execute(trigger_ddl)
            logger.info(f"Created term_fts and triggers in schema '{schema}'")
            results["term_fts"] = True

            # Rebuild data if requested and base table has data
            if rebuild:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {prefix}term_search")
                row_count = cursor.fetchone()[0]
                if row_count > 0:
                    logger.info(f"Rebuilding term_fts with {row_count} rows...")
                    conn.execute(
                        f"""
                        INSERT INTO {prefix}term_fts(he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id, term_rowid)
                        SELECT he_term, ru_translation, notes, project_id, kind, lemma_id, ngram_id, term_rowid FROM {prefix}term_search
                        """
                    )
                    logger.info(f"Rebuilt term_fts in schema '{schema}'")
        else:
            logger.debug(f"term_fts exists in schema '{schema}'")
            results["term_fts"] = False

        # PERF-SCALE PATCH-D: also ensure document_name_fts health on every startup.
        try:
            doc_fts_result = ensure_document_name_fts_health(conn, schema, rebuild=rebuild)
            results.update(doc_fts_result)
        except Exception as doc_fts_err:
            # Non-fatal: log and continue; picker will fall back to LIKE search.
            logger.warning("document_name_fts health check failed (non-fatal): %s", doc_fts_err)

        # PERF-SCALE PATCH-E: ensure lemma_fts health on every startup.
        try:
            lemma_fts_result = ensure_lemma_fts_health(conn, schema, rebuild=rebuild)
            results.update(lemma_fts_result)
        except Exception as lemma_fts_err:
            # Non-fatal: dictionary search falls back to LIKE.
            logger.warning("lemma_fts health check failed (non-fatal): %s", lemma_fts_err)

        conn.commit()
        return results

    except Exception as e:
        logger.error(f"Failed to ensure FTS tables in schema '{schema}': {e}")
        conn.rollback()
        raise


def ensure_fts_for_db_path(
    db_path: str, schema: str = "main", rebuild: bool = False
) -> dict[str, bool]:
    """Ensure FTS tables for a database file path.

    Args:
        db_path: Path to SQLite database
        schema: Schema name (main/host)
        rebuild: If True, rebuild FTS data from base tables

    Returns:
        Dict with {table_name: created} status
    """
    conn = sqlite3.connect(db_path)
    try:
        return ensure_fts_tables(conn, schema, rebuild)
    finally:
        conn.close()


if __name__ == "__main__":
    # CLI usage for manual repair
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Ensure FTS5 tables exist and are consistent")
    parser.add_argument(
        "--db-path",
        default=r"J:\Project_Vibe\V_book\hdle_premium.db",
        help="Path to database (default: dev DB)",
    )
    parser.add_argument(
        "--schema",
        default="main",
        help="Schema name (default: main)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild FTS data from base tables",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        results = ensure_fts_for_db_path(str(db_path), args.schema, args.rebuild)
        print(f"\nFTS tables ensured in schema '{args.schema}':")
        for table, created in results.items():
            status = "CREATED" if created else "Already existed"
            print(f"  {table}: {status}")
        print("\n[OK] FTS tables ready")
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
