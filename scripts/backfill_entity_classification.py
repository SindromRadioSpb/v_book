#!/usr/bin/env python
"""Backfill entity classification for existing lemmas and term clusters.

Task 11: Entity Classification & Noise Filtering (PATCH-05)

Usage:
    python scripts/backfill_entity_classification.py --db-path "J:\\Project_Vibe\\V_book\\hdle_premium.db"
    python scripts/backfill_entity_classification.py --db-path "M:\\V_book\\HDLE\\hdle.db"
    python scripts/backfill_entity_classification.py --db-path "path/to/db.db" --dry-run
    python scripts/backfill_entity_classification.py --db-path "path/to/db.db" --batch-size 1000

This script:
- Finds all lemma/term_cluster rows where entity_class IS NULL
- Classifies each row using entity_classifier
- Updates classification fields (entity_class, is_noise, noise_reason, norm_text)
- Processes in batches with progress logging
- Is idempotent (safe to re-run)
"""

import argparse
import logging
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, select, update, func
from sqlalchemy.orm import Session

from app.infra.sa_models import Lemma, TermCluster
from app.services.entity_classifier import classify_text, classify_phrase


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


def backfill_lemmas(session: Session, batch_size: int, dry_run: bool, logger: logging.Logger) -> dict:
    """Backfill classification for lemmas.

    Args:
        session: Database session
        batch_size: Number of rows to process per commit
        dry_run: If True, don't commit changes
        logger: Logger instance

    Returns:
        Statistics dictionary
    """
    # Count unclassified lemmas
    stmt = select(func.count(Lemma.lemma_id)).where(Lemma.entity_class.is_(None))
    total_count = session.execute(stmt).scalar_one()

    logger.info(f"Found {total_count} lemmas to classify")

    if total_count == 0:
        return {'processed': 0, 'noise': 0, 'classes': Counter()}

    stats = {'processed': 0, 'noise': 0, 'classes': Counter()}
    batch_count = 0

    while True:
        # Fetch a batch of unclassified lemmas
        stmt = select(Lemma).where(Lemma.entity_class.is_(None)).limit(batch_size)
        lemmas = list(session.execute(stmt).scalars())

        if not lemmas:
            break

        # Classify each lemma
        for lemma in lemmas:
            classification = classify_text(lemma.lemma_text)

            # Update fields
            lemma.entity_class = classification.entity_class
            lemma.is_noise = 1 if classification.is_noise else 0
            lemma.noise_reason = classification.noise_reason
            lemma.norm_text = classification.norm_text

            # Track stats
            stats['processed'] += 1
            stats['classes'][classification.entity_class] += 1
            if classification.is_noise:
                stats['noise'] += 1

            if stats['processed'] % 100 == 0:
                logger.debug(
                    f"  Classified {stats['processed']}/{total_count} lemmas "
                    f"({stats['noise']} noise)"
                )

        # Commit batch
        batch_count += 1
        if not dry_run:
            session.commit()
            logger.info(
                f"  Batch {batch_count}: Committed {len(lemmas)} lemmas "
                f"({stats['processed']}/{total_count} total)"
            )
        else:
            session.rollback()
            logger.info(f"  [DRY RUN] Would commit batch {batch_count} with {len(lemmas)} lemmas")

    return stats


def backfill_clusters(session: Session, batch_size: int, dry_run: bool, logger: logging.Logger) -> dict:
    """Backfill classification for term clusters.

    Args:
        session: Database session
        batch_size: Number of rows to process per commit
        dry_run: If True, don't commit changes
        logger: Logger instance

    Returns:
        Statistics dictionary
    """
    # Count unclassified clusters
    stmt = select(func.count(TermCluster.cluster_id)).where(TermCluster.entity_class.is_(None))
    total_count = session.execute(stmt).scalar_one()

    logger.info(f"Found {total_count} term clusters to classify")

    if total_count == 0:
        return {'processed': 0, 'noise': 0, 'classes': Counter()}

    stats = {'processed': 0, 'noise': 0, 'classes': Counter()}
    batch_count = 0

    while True:
        # Fetch a batch of unclassified clusters
        stmt = select(TermCluster).where(TermCluster.entity_class.is_(None)).limit(batch_size)
        clusters = list(session.execute(stmt).scalars())

        if not clusters:
            break

        # Classify each cluster
        for cluster in clusters:
            classification = classify_phrase(cluster.representative_he)

            # Update fields
            cluster.entity_class = classification.entity_class
            cluster.is_noise = 1 if classification.is_noise else 0
            cluster.noise_reason = classification.noise_reason
            cluster.norm_text = classification.norm_text

            # Track stats
            stats['processed'] += 1
            stats['classes'][classification.entity_class] += 1
            if classification.is_noise:
                stats['noise'] += 1

            if stats['processed'] % 100 == 0:
                logger.debug(
                    f"  Classified {stats['processed']}/{total_count} clusters "
                    f"({stats['noise']} noise)"
                )

        # Commit batch
        batch_count += 1
        if not dry_run:
            session.commit()
            logger.info(
                f"  Batch {batch_count}: Committed {len(clusters)} clusters "
                f"({stats['processed']}/{total_count} total)"
            )
        else:
            session.rollback()
            logger.info(f"  [DRY RUN] Would commit batch {batch_count} with {len(clusters)} clusters")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Backfill entity classification for existing lemmas and term clusters'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        required=True,
        help='Path to SQLite database file'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=500,
        help='Number of rows to process per commit (default: 500)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without committing'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.verbose)

    # Validate database path
    db_path = Path(args.db_path)
    if not db_path.exists():
        logger.error(f"Database file not found: {db_path}")
        sys.exit(1)

    logger.info(f"Starting backfill for database: {db_path}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Dry run: {args.dry_run}")

    start_time = datetime.now()

    # Connect to database
    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)

    try:
        # Backfill lemmas
        logger.info("=" * 60)
        logger.info("BACKFILLING LEMMAS")
        logger.info("=" * 60)
        lemma_stats = backfill_lemmas(session, args.batch_size, args.dry_run, logger)

        logger.info("")
        logger.info("Lemma Statistics:")
        logger.info(f"  Processed: {lemma_stats['processed']}")
        logger.info(f"  Noise: {lemma_stats['noise']}")
        logger.info(f"  Valid: {lemma_stats['processed'] - lemma_stats['noise']}")
        logger.info(f"  Classes: {dict(lemma_stats['classes'])}")

        # Backfill term clusters
        logger.info("")
        logger.info("=" * 60)
        logger.info("BACKFILLING TERM CLUSTERS")
        logger.info("=" * 60)
        cluster_stats = backfill_clusters(session, args.batch_size, args.dry_run, logger)

        logger.info("")
        logger.info("Term Cluster Statistics:")
        logger.info(f"  Processed: {cluster_stats['processed']}")
        logger.info(f"  Noise: {cluster_stats['noise']}")
        logger.info(f"  Valid: {cluster_stats['processed'] - cluster_stats['noise']}")
        logger.info(f"  Classes: {dict(cluster_stats['classes'])}")

        # Summary
        elapsed = datetime.now() - start_time
        total_processed = lemma_stats['processed'] + cluster_stats['processed']

        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total items processed: {total_processed}")
        logger.info(f"  Lemmas: {lemma_stats['processed']}")
        logger.info(f"  Clusters: {cluster_stats['processed']}")
        logger.info(f"Elapsed time: {elapsed}")

        if total_processed > 0:
            items_per_sec = total_processed / elapsed.total_seconds()
            logger.info(f"Performance: {items_per_sec:.1f} items/second")

        if args.dry_run:
            logger.info("")
            logger.info("[DRY RUN] No changes were committed to the database")
        else:
            logger.info("")
            logger.info("Backfill completed successfully!")

    except Exception as e:
        logger.error(f"Error during backfill: {e}")
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == '__main__':
    main()
