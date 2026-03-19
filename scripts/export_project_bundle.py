#!/usr/bin/env python3
"""CLI script to export a project as .hdleproj bundle."""

import argparse
import logging
import sys
from pathlib import Path

from app.services.db_service import DBService
from app.services.project_exchange.export_engine import ProjectExportEngine
from app.services.project_exchange.dto import ExportOptions


def setup_logging():
    """Setup basic logging to console."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Export HDLE Premium project as .hdleproj bundle")
    parser.add_argument("--db-path", type=str, required=True, help="Path to SQLite database file")
    parser.add_argument("--project-id", type=int, required=True, help="Project ID to export")
    parser.add_argument("--out", type=str, required=True, help="Output .hdleproj file path")
    parser.add_argument(
        "--no-snapshots", action="store_true", help="Exclude project snapshots from export"
    )

    args = parser.parse_args()

    setup_logging()

    # Initialize DB
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        return 1

    DBService.initialize(str(db_path))

    # Export
    engine = ProjectExportEngine()
    options = ExportOptions(include_snapshots=not args.no_snapshots)

    print(f"Exporting project {args.project_id} from {db_path}...")

    report = engine.export_project(
        project_id=args.project_id,
        out_path=Path(args.out),
        options=options,
        progress_callback=lambda stage, cur, tot: print(f"  {stage} ({cur}/{tot})"),
    )

    if report.success:
        print("\n[OK] Export successful!")
        print(f"  Bundle: {report.bundle_path}")
        print(f"  Size: {report.bundle_path.stat().st_size / 1024 / 1024:.1f} MB")
        print(f"  Time: {report.elapsed_seconds:.1f}s")
        print(f"  Total rows: {sum(report.manifest.table_counts.values()):,}")
        return 0
    else:
        print(f"\n[FAIL] Export failed: {report.error_message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
