"""
Re-propagate all tm_global translations to linked tm_entries.

PROBLEM: Some tm_entry rows have empty translations even though tm_global has valid translation.
         This happened because old code didn't call propagate_to_entries after upsert.

SOLUTION: Iterate through all tm_global rows and propagate to linked tm_entries.

SAFE:
- Read-only on tm_global
- Only updates tm_entry rows where translation differs from tm_global
- Dry-run mode available (--dry-run)
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
from app.infra.sa_models import TMGlobal
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Re-propagate tm_global to all linked tm_entries")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (no changes)")
    parser.add_argument("--db-path", help="Path to database file (default: production DB)")
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
    logger.info("TM Global Re-Propagation Script")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE (will modify DB)'}")
    logger.info("")

    session = db_service.get_session()
    service = TMGlobalService()

    # Get all tm_global rows
    logger.info("Fetching all tm_global rows...")
    all_global = session.execute(select(TMGlobal)).scalars().all()
    logger.info(f"Found {len(all_global)} tm_global rows")
    logger.info("")

    if args.dry_run:
        logger.info("DRY RUN: Simulating propagation...")
    else:
        logger.info("LIVE MODE: Propagating changes...")

    total_updated = 0
    chunk_size = 100

    for i, g in enumerate(all_global, 1):
        if not args.dry_run:
            # Propagate to all linked tm_entries
            count = service.propagate_to_entries(
                session=session,
                tm_global_id=g.tm_global_id,
                fields=[
                    "translation",
                    "status",
                    "origin",
                    "confidence",
                    "is_noise",
                    "noise_reason",
                ],
            )
            total_updated += count

            if count > 0:
                logger.info(
                    f"[{i}/{len(all_global)}] tm_global_id={g.tm_global_id}: {count} entries updated"
                )
        else:
            # Dry run: just count without updating
            from app.infra.sa_models import TMEntry

            entries = (
                session.execute(select(TMEntry).where(TMEntry.tm_global_id == g.tm_global_id))
                .scalars()
                .all()
            )

            count = sum(1 for e in entries if e.translation != g.translation)
            total_updated += count

            if count > 0:
                logger.info(
                    f"[{i}/{len(all_global)}] tm_global_id={g.tm_global_id}: {count} entries would be updated"
                )

        # Commit in chunks
        if not args.dry_run and i % chunk_size == 0:
            session.commit()
            logger.info(f"  Committed chunk {i // chunk_size}")

    # Final commit
    if not args.dry_run:
        session.commit()
        logger.info("  Final commit complete")

    logger.info("")
    logger.info("=" * 60)
    logger.info("Re-Propagation Complete")
    logger.info("=" * 60)
    logger.info(f"Total tm_entries updated: {total_updated}")
    logger.info("")

    session.close()


if __name__ == "__main__":
    main()
