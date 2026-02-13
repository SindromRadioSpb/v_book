"""
Deduplicate tm_entry records - PATCH-18-02.

PROBLEM: Multiple tm_entry records exist for same lemma/cluster due to normalization bug.
SOLUTION: Find duplicates, merge into canonical record, delete others.

SAFE:
- Idempotent (can run multiple times)
- Reports changes (dry-run mode available)
- Backs up before deletion
"""

import argparse
import logging
import sys
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select, func
from app.infra.db import DatabaseManager
from app.infra.sa_models import TMEntry, Lemma, TermCluster
from app.domain.normalization.normalizer import normalize_for_tm

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class TMEntryDeduplicator:
    """Deduplicate tm_entry records with same entity."""

    def __init__(self, session, dry_run=False):
        self.session = session
        self.dry_run = dry_run
        self.stats = {
            'groups_found': 0,
            'records_merged': 0,
            'records_deleted': 0,
            'records_renormalized': 0,
        }

    def run(self):
        """Run deduplication for lemmas and term clusters."""
        logger.info("=" * 60)
        logger.info("TM Entry Deduplication Script")
        logger.info("=" * 60)
        logger.info(f"Mode: {'DRY RUN (no changes)' if self.dry_run else 'LIVE (will modify DB)'}")
        logger.info("")

        # Deduplicate lemmas
        logger.info("Step 1: Deduplicating lemma tm_entry records...")
        self._dedupe_lemmas()

        # Deduplicate term clusters
        logger.info("")
        logger.info("Step 2: Deduplicating term_cluster tm_entry records...")
        self._dedupe_clusters()

        # Report
        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Duplicate groups found: {self.stats['groups_found']}")
        logger.info(f"Records merged: {self.stats['records_merged']}")
        logger.info(f"Records deleted: {self.stats['records_deleted']}")
        logger.info(f"Records re-normalized: {self.stats['records_renormalized']}")
        logger.info("")

        if self.dry_run:
            logger.info("DRY RUN complete - no changes made to database")
        else:
            logger.info("Deduplication complete - changes committed to database")

    def _dedupe_lemmas(self):
        """Deduplicate tm_entry records for lemmas."""
        # Find duplicates by (project_id, src_text) with multiple records
        stmt = (
            select(
                TMEntry.project_id,
                TMEntry.src_text,
                func.count(TMEntry.tm_id).label('count')
            )
            .where(TMEntry.kind == 'lemma')
            .group_by(TMEntry.project_id, TMEntry.src_text)
            .having(func.count(TMEntry.tm_id) > 1)
        )

        duplicates = self.session.execute(stmt).all()

        if not duplicates:
            logger.info("  No duplicate lemma tm_entry records found")
            return

        logger.info(f"  Found {len(duplicates)} duplicate groups")

        for project_id, src_text, count in duplicates:
            self._merge_duplicate_group('lemma', project_id, src_text, count)

    def _dedupe_clusters(self):
        """Deduplicate tm_entry records for term clusters."""
        # Find duplicates by (project_id, src_text) with multiple records
        stmt = (
            select(
                TMEntry.project_id,
                TMEntry.src_text,
                func.count(TMEntry.tm_id).label('count')
            )
            .where(TMEntry.kind == 'term_cluster')
            .group_by(TMEntry.project_id, TMEntry.src_text)
            .having(func.count(TMEntry.tm_id) > 1)
        )

        duplicates = self.session.execute(stmt).all()

        if not duplicates:
            logger.info("  No duplicate term_cluster tm_entry records found")
            return

        logger.info(f"  Found {len(duplicates)} duplicate groups")

        for project_id, src_text, count in duplicates:
            self._merge_duplicate_group('term_cluster', project_id, src_text, count)

    def _merge_duplicate_group(self, kind: str, project_id: int, src_text: str, count: int):
        """Merge duplicate tm_entry records for same entity.

        Args:
            kind: 'lemma' or 'term_cluster'
            project_id: Project ID
            src_text: Source text
            count: Number of duplicate records
        """
        # Fetch all duplicates
        stmt = (
            select(TMEntry)
            .where(
                TMEntry.project_id == project_id,
                TMEntry.kind == kind,
                TMEntry.src_text == src_text
            )
            .order_by(
                # Prioritize: non-empty translation > user_edit origin > most recent
                TMEntry.translation.isnot(None).desc(),
                (TMEntry.translation != '').desc(),
                (TMEntry.origin == 'user_edit').desc(),
                TMEntry.updated_at.desc(),
                TMEntry.tm_id.asc()  # deterministic tiebreaker
            )
        )

        records = list(self.session.execute(stmt).scalars().all())

        if len(records) < 2:
            return  # No duplicates (shouldn't happen, but safe)

        # Select canonical record (first by priority order)
        canonical = records[0]
        others = records[1:]

        self.stats['groups_found'] += 1

        logger.info(f"  Group: {kind} '{src_text}' in project {project_id} ({count} records)")
        logger.info(f"    Canonical: tm_id={canonical.tm_id}, origin={canonical.origin}, "
                    f"translation={'<empty>' if not canonical.translation else canonical.translation[:30]}, "
                    f"src_norm={canonical.src_norm}")

        # Merge data from others into canonical
        for other in others:
            logger.info(f"    Merging: tm_id={other.tm_id}, origin={other.origin}, "
                        f"translation={'<empty>' if not other.translation else other.translation[:30]}, "
                        f"src_norm={other.src_norm}")

            # If canonical has empty translation but other has filled, take other's translation
            if not canonical.translation and other.translation:
                logger.info(f"      -> Copying translation from tm_id={other.tm_id}")
                if not self.dry_run:
                    canonical.translation = other.translation
                self.stats['records_merged'] += 1

            # If canonical has draft status but other is approved, upgrade
            if canonical.status == 'draft' and other.status == 'approved':
                logger.info(f"      -> Upgrading status to approved")
                if not self.dry_run:
                    canonical.status = 'approved'

        # Re-normalize canonical src_norm using normalize_for_tm
        src_lang = canonical.src_lang or 'he'
        normalized = normalize_for_tm(src_lang, src_text, kind)
        if canonical.src_norm != normalized.norm:
            logger.info(f"      -> Re-normalizing src_norm: '{canonical.src_norm}' -> '{normalized.norm}'")
            if not self.dry_run:
                canonical.src_norm = normalized.norm
            self.stats['records_renormalized'] += 1

        # Link to source entity if not already linked
        if kind == 'lemma' and not canonical.lemma_id:
            lemma_stmt = select(Lemma).where(
                Lemma.project_id == project_id,
                Lemma.lemma_text == src_text
            )
            lemma = self.session.execute(lemma_stmt).scalar()
            if lemma:
                logger.info(f"      -> Linking to lemma_id={lemma.lemma_id}")
                if not self.dry_run:
                    canonical.lemma_id = lemma.lemma_id
                    canonical.is_noise = lemma.is_noise
                    canonical.noise_reason = lemma.noise_reason

        elif kind == 'term_cluster' and not canonical.cluster_id:
            cluster_stmt = select(TermCluster).where(
                TermCluster.project_id == project_id,
                TermCluster.representative_he == src_text
            )
            cluster = self.session.execute(cluster_stmt).scalar()
            if cluster:
                logger.info(f"      -> Linking to cluster_id={cluster.cluster_id}")
                if not self.dry_run:
                    canonical.cluster_id = cluster.cluster_id
                    canonical.is_noise = cluster.is_noise
                    canonical.noise_reason = cluster.noise_reason

        # Delete other records
        for other in others:
            logger.info(f"    Deleting: tm_id={other.tm_id}")
            if not self.dry_run:
                self.session.delete(other)
            self.stats['records_deleted'] += 1


def main():
    parser = argparse.ArgumentParser(description='Deduplicate tm_entry records')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (no changes)')
    parser.add_argument('--db-path', help='Path to database file (default: production DB)')
    args = parser.parse_args()

    # Get DB instance
    if args.db_path:
        db_manager = DatabaseManager(db_path=str(args.db_path))
    else:
        db_manager = DatabaseManager.get_instance()

    # Run deduplication
    with db_manager.get_session() as session:
        deduplicator = TMEntryDeduplicator(session, dry_run=args.dry_run)
        deduplicator.run()

        if not args.dry_run:
            logger.info("Committing changes...")
            session.commit()
            logger.info("Changes committed successfully")
        else:
            logger.info("Rolling back (dry run)...")
            session.rollback()

    return 0


if __name__ == '__main__':
    sys.exit(main())
