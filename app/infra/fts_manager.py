"""FTS5 table management and self-healing.

Ensures FTS5 virtual tables and triggers exist and are consistent.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

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
      INSERT INTO sentence_fts(text, doc_id, sentence_id)
      VALUES (NEW.text, NEW.doc_id, NEW.sentence_id);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_sentence_ad
    AFTER DELETE ON document_sentence
    BEGIN
      DELETE FROM sentence_fts WHERE sentence_id = OLD.sentence_id;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_sentence_au
    AFTER UPDATE OF text ON document_sentence
    BEGIN
      UPDATE sentence_fts
      SET text = NEW.text, doc_id = NEW.doc_id
      WHERE sentence_id = NEW.sentence_id;
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

        conn.commit()
        return results

    except Exception as e:
        logger.error(f"Failed to ensure FTS tables in schema '{schema}': {e}")
        conn.rollback()
        raise


def ensure_fts_for_db_path(db_path: str, schema: str = "main", rebuild: bool = False) -> dict[str, bool]:
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
