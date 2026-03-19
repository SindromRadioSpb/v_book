#!/usr/bin/env python3
"""Repair FTS5 index for sentence_fts table."""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import sqlite3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def repair_fts_index(db_path: str) -> bool:
    """
    Repair FTS5 index by rebuilding it.

    Args:
        db_path: Path to SQLite database

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Opening database: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if sentence_fts exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sentence_fts'")
        if not cursor.fetchone():
            logger.error("sentence_fts table does not exist!")
            return False

        logger.info("✓ sentence_fts table exists")

        # Check row count
        cursor.execute("SELECT COUNT(*) FROM sentence_fts")
        fts_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM document_sentence")
        sentence_count = cursor.fetchone()[0]

        logger.info(f"sentence_fts rows: {fts_count}")
        logger.info(f"document_sentence rows: {sentence_count}")

        if fts_count != sentence_count:
            logger.warning(f"Row count mismatch: {fts_count} vs {sentence_count}")
            logger.info("Performing full resync...")

            # Delete all from FTS5
            cursor.execute("DELETE FROM sentence_fts")
            logger.info("Cleared sentence_fts table")

            # Repopulate from document_sentence
            cursor.execute(
                """
                INSERT INTO sentence_fts(text, doc_id, sentence_id)
                SELECT text, doc_id, sentence_id
                FROM document_sentence
                ORDER BY sentence_id
            """
            )
            conn.commit()
            logger.info(f"✓ Repopulated sentence_fts with {sentence_count} rows")

        # Rebuild FTS5 index
        logger.info("Rebuilding FTS5 index...")
        cursor.execute("INSERT INTO sentence_fts(sentence_fts) VALUES('rebuild')")
        conn.commit()
        logger.info("✓ FTS5 index rebuilt successfully")

        # Verify rebuild
        cursor.execute("SELECT COUNT(*) FROM sentence_fts")
        new_count = cursor.fetchone()[0]
        logger.info(f"After rebuild: {new_count} rows")

        if new_count != sentence_count:
            logger.error(f"✗ Row count still mismatched: {new_count} vs {sentence_count}")
            return False

        # Optimize FTS5 index
        logger.info("Optimizing FTS5 index...")
        cursor.execute("INSERT INTO sentence_fts(sentence_fts) VALUES('optimize')")
        conn.commit()
        logger.info("✓ FTS5 index optimized")

        conn.close()
        logger.info("✓ FTS5 index repair complete")
        return True

    except Exception as e:
        logger.error(f"✗ Failed to repair FTS5 index: {e}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Repair FTS5 index for sentence search")
    parser.add_argument(
        "--db-path", default=str(project_root / "hdle_premium.db"), help="Path to database file"
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("FTS5 Index Repair Utility")
    logger.info("=" * 80)

    success = repair_fts_index(args.db_path)

    if success:
        logger.info("\n✓ Repair completed successfully")
        return 0
    else:
        logger.error("\n✗ Repair failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
