#!/usr/bin/env python3
"""Database health diagnostic tool.

Checks:
- Schema version
- FTS tables existence
- Triggers existence
- Stuck 'running' processor runs
- FTS row counts vs base tables
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class DBHealthChecker:
    """Database health diagnostic checker."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.issues = []
        self.warnings = []

    def close(self):
        """Close database connection."""
        self.conn.close()

    def check_all(self) -> bool:
        """Run all health checks.

        Returns:
            True if all checks passed, False if any issues found
        """
        print("=" * 80)
        print(f"Database Health Check: {self.db_path}")
        print("=" * 80)
        print()

        self.check_schema_version()
        self.check_fts_tables()
        self.check_fts_triggers()
        self.check_stuck_runs()
        self.check_fts_row_counts()

        print()
        print("=" * 80)
        print("Summary")
        print("=" * 80)

        if self.issues:
            print(f"\n[FAIL] {len(self.issues)} issue(s) found:\n")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("\n[OK] No issues found")

        if self.warnings:
            print(f"\n[WARN] {len(self.warnings)} warning(s):\n")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")

        print()
        return len(self.issues) == 0

    def check_schema_version(self):
        """Check schema version from schema_meta table."""
        print("1. Schema Version Check")
        print("-" * 40)

        try:
            cursor = self.conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            )
            row = cursor.fetchone()
            if row:
                version = int(row[0])
                print(f"   Schema version: {version}")

                # Expected version (update this when adding new migrations)
                expected_max = 10  # Update when new migrations added
                if version < expected_max:
                    self.warnings.append(
                        f"Schema version ({version}) is lower than expected ({expected_max})"
                    )
            else:
                self.issues.append("schema_meta table exists but no version found")
        except sqlite3.Error as e:
            self.issues.append(f"Failed to read schema_version: {e}")

        print()

    def check_fts_tables(self):
        """Check FTS5 virtual tables exist."""
        print("2. FTS Tables Check")
        print("-" * 40)

        expected_fts = ['sentence_fts', 'term_fts']

        for table_name in expected_fts:
            try:
                cursor = self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,)
                )
                if cursor.fetchone():
                    print(f"   {table_name}: EXISTS")
                else:
                    self.issues.append(f"FTS table missing: {table_name}")
                    print(f"   {table_name}: MISSING")
            except sqlite3.Error as e:
                self.issues.append(f"Failed to check {table_name}: {e}")

        print()

    def check_fts_triggers(self):
        """Check FTS trigger existence."""
        print("3. FTS Triggers Check")
        print("-" * 40)

        expected_triggers = [
            'trg_sentence_ai',  # INSERT on document_sentence
            'trg_sentence_ad',  # DELETE on document_sentence
            'trg_sentence_au',  # UPDATE on document_sentence
            'trg_term_search_ai',  # INSERT on term_search
            'trg_term_search_ad',  # DELETE on term_search
            'trg_term_search_au',  # UPDATE on term_search
        ]

        for trigger_name in expected_triggers:
            try:
                cursor = self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?",
                    (trigger_name,)
                )
                if cursor.fetchone():
                    print(f"   {trigger_name}: EXISTS")
                else:
                    self.issues.append(f"Trigger missing: {trigger_name}")
                    print(f"   {trigger_name}: MISSING")
            except sqlite3.Error as e:
                self.issues.append(f"Failed to check trigger {trigger_name}: {e}")

        print()

    def check_stuck_runs(self):
        """Check for stuck processor runs (status='running')."""
        print("4. Stuck Processor Runs Check")
        print("-" * 40)

        try:
            # Check if table exists first
            cursor = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='processor_run'"
            )
            if not cursor.fetchone():
                print("   processor_run table not found (skipped)")
                print()
                return

            cursor = self.conn.execute(
                "SELECT run_id, started_at, engine FROM processor_run WHERE status='running'"
            )
            stuck_runs = cursor.fetchall()

            if stuck_runs:
                self.warnings.append(
                    f"Found {len(stuck_runs)} stuck runs (status='running')"
                )
                print(f"   Found {len(stuck_runs)} stuck run(s):")
                for run_id, started_at, engine in stuck_runs:
                    print(f"     - run_id={run_id}, started={started_at}, engine={engine}")
            else:
                print("   No stuck runs found (OK)")

        except sqlite3.Error as e:
            self.issues.append(f"Failed to check stuck runs: {e}")

        print()

    def check_fts_row_counts(self):
        """Check FTS row counts match base tables."""
        print("5. FTS Row Count Consistency")
        print("-" * 40)

        # Check sentence_fts vs document_sentence
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM document_sentence")
            sentence_count = cursor.fetchone()[0]

            cursor = self.conn.execute("SELECT COUNT(*) FROM sentence_fts")
            fts_count = cursor.fetchone()[0]

            print(f"   document_sentence: {sentence_count} rows")
            print(f"   sentence_fts:      {fts_count} rows")

            if sentence_count != fts_count:
                self.warnings.append(
                    f"Row count mismatch: document_sentence ({sentence_count}) "
                    f"vs sentence_fts ({fts_count})"
                )
                print("   Status: MISMATCH (run repair_fts_index.py)")
            else:
                print("   Status: MATCH (OK)")

        except sqlite3.Error as e:
            self.issues.append(f"Failed to check sentence FTS counts: {e}")

        print()

        # Check term_fts vs term_search
        try:
            # Check if term_search exists first
            cursor = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='term_search'"
            )
            if not cursor.fetchone():
                print("   term_search table not found (skipped)")
                print()
                return

            cursor = self.conn.execute("SELECT COUNT(*) FROM term_search")
            term_count = cursor.fetchone()[0]

            cursor = self.conn.execute("SELECT COUNT(*) FROM term_fts")
            term_fts_count = cursor.fetchone()[0]

            print(f"   term_search: {term_count} rows")
            print(f"   term_fts:    {term_fts_count} rows")

            if term_count != term_fts_count:
                self.warnings.append(
                    f"Row count mismatch: term_search ({term_count}) "
                    f"vs term_fts ({term_fts_count})"
                )
                print("   Status: MISMATCH (run repair_fts_index.py)")
            else:
                print("   Status: MATCH (OK)")

        except sqlite3.Error as e:
            self.issues.append(f"Failed to check term FTS counts: {e}")

        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Database health diagnostic tool"
    )
    parser.add_argument(
        "--db-path",
        default=str(project_root / "hdle_premium.db"),
        help="Path to database file (default: dev DB)"
    )

    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    checker = DBHealthChecker(str(db_path))
    try:
        all_passed = checker.check_all()
        return 0 if all_passed else 1
    finally:
        checker.close()


if __name__ == "__main__":
    sys.exit(main())
