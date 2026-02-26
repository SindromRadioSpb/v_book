#!/usr/bin/env python3
"""CLI script to import a .hdleproj bundle."""

import argparse
import logging
import sys
from pathlib import Path

from app.services.db_service import DBService
from app.services.project_exchange.import_engine import ProjectImportEngine
from app.services.project_exchange.dto import ImportOptions


def setup_logging():
    """Setup basic logging to console."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Import HDLE Premium project from .hdleproj bundle"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        required=True,
        help="Path to SQLite database file"
    )
    parser.add_argument(
        "--bundle",
        type=str,
        required=True,
        help="Path to .hdleproj bundle file"
    )
    parser.add_argument(
        "--name",
        type=str,
        help="Override project name (optional)"
    )
    parser.add_argument(
        "--no-auto-rename",
        action="store_true",
        help="Fail if project name conflicts (instead of auto-rename)"
    )

    args = parser.parse_args()

    setup_logging()

    # Initialize DB
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        return 1

    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"Error: Bundle not found: {bundle_path}", file=sys.stderr)
        return 1

    DBService.initialize(str(db_path))

    # Import
    engine = ProjectImportEngine()
    options = ImportOptions(
        rename_if_conflict=not args.no_auto_rename,
        custom_name=args.name if args.name else None,
    )

    print(f"Importing bundle {bundle_path} into {db_path}...")

    report = engine.import_project(
        bundle_path=bundle_path,
        options=options,
        progress_callback=lambda stage, cur, tot: print(f"  {stage} ({cur}/{tot})"),
    )

    if report.success:
        print("\n[OK] Import successful!")
        print(f"  New Project ID: {report.new_project_id}")
        print(f"  Project Name: {report.new_project_name}")
        print(f"  Time: {report.elapsed_seconds:.1f}s")
        print(f"  Total rows: {sum(report.table_counts.values()):,}")

        if report.warnings:
            print("\n  Warnings:")
            for warning in report.warnings:
                print(f"    - {warning}")

        return 0
    else:
        print(f"\n[FAIL] Import failed: {report.error_message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
