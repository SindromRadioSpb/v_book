"""Diagnostic script to check FTS5 table presence and consistency.

Usage:
    python scripts/diag_fts_presence.py [--db-path PATH]

Checks:
    - sentence_fts and term_fts virtual tables exist
    - Corresponding triggers exist
    - FTS tables are consistent with base tables
    - Schema version
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def check_fts_presence(db_path: str, schema: str = "main") -> dict:
    """Check FTS tables, triggers, and consistency.

    Args:
        db_path: Path to SQLite database
        schema: Schema name (main/host)

    Returns:
        Dict with diagnostic results
    """
    conn = sqlite3.connect(db_path)
    results = {
        "db_path": db_path,
        "schema": schema,
        "sentence_fts_exists": False,
        "term_fts_exists": False,
        "sentence_triggers": [],
        "term_triggers": [],
        "schema_version": None,
        "issues": [],
    }

    try:
        # Check schema version
        cursor = conn.execute(f"SELECT value FROM {schema}.schema_meta WHERE key='schema_version'")
        row = cursor.fetchone()
        results["schema_version"] = int(row[0]) if row else None

        # Check FTS tables
        cursor = conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name IN ('sentence_fts', 'term_fts')"
        )
        fts_tables = [row[0] for row in cursor.fetchall()]
        results["sentence_fts_exists"] = "sentence_fts" in fts_tables
        results["term_fts_exists"] = "term_fts" in fts_tables

        # Check triggers
        cursor = conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='trigger' AND name LIKE 'trg_sentence%'"
        )
        results["sentence_triggers"] = [row[0] for row in cursor.fetchall()]

        cursor = conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='trigger' AND name LIKE 'trg_term%'"
        )
        results["term_triggers"] = [row[0] for row in cursor.fetchall()]

        # Check for inconsistencies
        if results["sentence_triggers"] and not results["sentence_fts_exists"]:
            results["issues"].append(
                f"CRITICAL: sentence triggers exist but sentence_fts table is missing! "
                f"This will cause OperationalError on INSERT/DELETE/UPDATE to document_sentence."
            )

        if results["term_triggers"] and not results["term_fts_exists"]:
            results["issues"].append(
                f"CRITICAL: term triggers exist but term_fts table is missing! "
                f"This will cause OperationalError on INSERT/DELETE/UPDATE to term_search."
            )

        # Check row counts if FTS exists
        if results["sentence_fts_exists"]:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {schema}.sentence_fts")
            sentence_fts_count = cursor.fetchone()[0]
            cursor = conn.execute(f"SELECT COUNT(*) FROM {schema}.document_sentence")
            sentence_count = cursor.fetchone()[0]

            if sentence_fts_count != sentence_count:
                results["issues"].append(
                    f"WARNING: sentence_fts has {sentence_fts_count} rows but document_sentence has {sentence_count} rows. "
                    f"FTS index may need rebuild."
                )

        if results["term_fts_exists"]:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {schema}.term_fts")
            term_fts_count = cursor.fetchone()[0]
            cursor = conn.execute(f"SELECT COUNT(*) FROM {schema}.term_search")
            term_count = cursor.fetchone()[0]

            if term_fts_count != term_count:
                results["issues"].append(
                    f"WARNING: term_fts has {term_fts_count} rows but term_search has {term_count} rows. "
                    f"FTS index may need rebuild."
                )

    finally:
        conn.close()

    return results


def print_results(results: dict) -> None:
    """Print diagnostic results."""
    print(f"\n{'='*70}")
    print(f"FTS Diagnostic Report")
    print(f"{'='*70}")
    print(f"Database: {results['db_path']}")
    print(f"Schema: {results['schema']}")
    print(f"Schema Version: {results['schema_version']}")
    print(f"\nFTS Tables:")
    print(f"  sentence_fts: {'[OK] EXISTS' if results['sentence_fts_exists'] else '[!!] MISSING'}")
    print(f"  term_fts:     {'[OK] EXISTS' if results['term_fts_exists'] else '[!!] MISSING'}")
    print(f"\nTriggers:")
    print(
        f"  sentence: {', '.join(results['sentence_triggers']) if results['sentence_triggers'] else 'NONE'}"
    )
    print(
        f"  term:     {', '.join(results['term_triggers']) if results['term_triggers'] else 'NONE'}"
    )

    if results["issues"]:
        print(f"\n{'!'*70}")
        print("ISSUES FOUND:")
        for issue in results["issues"]:
            print(f"  - {issue}")
        print(f"{'!'*70}")
    else:
        print(f"\n{'='*70}")
        print("[OK] No issues found. FTS configuration is healthy.")
        print(f"{'='*70}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Check FTS5 table presence and consistency")
    parser.add_argument(
        "--db-path",
        default=r"J:\Project_Vibe\V_book\hdle_premium.db",
        help="Path to database (default: dev DB)",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    results = check_fts_presence(str(db_path))
    print_results(results)

    # Exit with error code if issues found
    sys.exit(1 if results["issues"] else 0)


if __name__ == "__main__":
    main()
