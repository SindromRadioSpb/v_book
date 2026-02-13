"""
Backfill tm_global from existing tm_entry records - TASK-19-01.

PROBLEM: tm_global table exists but is empty. Need to populate from existing tm_entry data.
SOLUTION: Group tm_entry by canonical key, pick best by scoring, create tm_global, link all entries.

SAFE:
- Idempotent (can run multiple times)
- Dry-run mode available (--dry-run)
- Reports changes (groups created, entries linked)
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.db_service import DBService
from app.services.tm_global_service import TMGlobalService
from app.main import get_app_dir

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Backfill tm_global from existing tm_entry records')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (no changes)')
    parser.add_argument('--db-path', help='Path to database file (default: production DB)')
    parser.add_argument('--chunk-size', type=int, default=500, help='Commit every N keys (default: 500)')
    args = parser.parse_args()

    # Get DB instance
    if args.db_path:
        db_service = DBService.initialize(Path(args.db_path))
    else:
        # Use default production DB path
        app_dir = get_app_dir()
        db_path = app_dir / "hdle.db"
        db_service = DBService.initialize(db_path)

    logger.info("=" * 60)
    logger.info("TM Global Backfill Script")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE (will modify DB)'}")
    logger.info("")

    # Run backfill
    with db_service.get_session() as session:
        service = TMGlobalService()
        stats = service.backfill(
            session=session,
            chunk_size=args.chunk_size,
            dry_run=args.dry_run,
        )

        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Groups created: {stats['groups_created']}")
        logger.info(f"Entries linked: {stats['entries_linked']}")
        logger.info(f"Entries skipped: {stats['entries_skipped']}")
        logger.info("")

        if args.dry_run:
            logger.info("DRY RUN complete - no changes made to database")
            session.rollback()
        else:
            logger.info("Backfill complete - changes committed to database")

    return 0


if __name__ == '__main__':
    sys.exit(main())
