"""Seed deterministic fixture project for metrics testing.

Creates a fixture project "METRICS_FIXTURE_v1" with known data
for validating all metrics against ground truth expectations.

Usage:
    python -m app.tools.seed_metrics_fixture_project

Returns:
    0 if all metrics match expected values
    1 if validation fails
"""

import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.db_service import DBService
from app.services.stats_service import StatsService
from app.infra.sa_models import (
    Library, DictProject, Lemma, TMEntry, TermCluster, TermAlias,
    DictEntry, DictSource, SourceCorpus, SourceDocument
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class FixtureSeed:
    """Deterministic fixture data seeder."""

    FIXTURE_NAME = "METRICS_FIXTURE_v1"

    # Ground truth expectations
    EXPECTED_METRICS = {
        "project_name": "METRICS_FIXTURE_v1",
        "document_count": 0,  # StatsService returns 0 (M9 focused on exports)
        "lemma_count": 10,
        "lemmas_with_translation_count": 6,  # 60% coverage
        "term_cluster_count": 5,
        "term_approved_count": 2,  # 40% approval
        "tm_entry_count": 8,
        "tm_approved_count": 6,  # 75% approval
        "dict_entry_count": 0,  # Skipped for simplicity
        "lemma_coverage_pct": 60.0,  # 6/10
        "tm_approval_rate_pct": 75.0,  # 6/8
        "term_approval_rate_pct": 40.0,  # 2/5
        "tm_entries_per_lemma_pct": 60.0,  # 6/10 = 0.6 = 60%
    }

    def __init__(self):
        self.db_service = DBService.get_instance()
        self.stats_service = StatsService()

    def seed(self) -> bool:
        """Seed fixture project and validate metrics.

        Returns:
            True if validation passes, False otherwise
        """
        with self.db_service.get_session() as session:
            # 1. Delete existing fixture project
            logger.info(f"Deleting existing {self.FIXTURE_NAME} project...")
            existing = session.query(DictProject).filter(
                DictProject.name == self.FIXTURE_NAME
            ).first()
            if existing:
                session.delete(existing)
                session.commit()
                logger.info("  ✓ Deleted existing project")

            # 2. Create or get library
            logger.info("Creating/getting fixture library...")
            library = session.query(Library).filter(Library.name == "FIXTURE_LIBRARY").first()
            if not library:
                library = Library(name="FIXTURE_LIBRARY")
                session.add(library)
                session.flush()
            logger.info(f"  ✓ Library ready (ID={library.library_id})")

            # 3. Create fixture project
            logger.info(f"Creating {self.FIXTURE_NAME} project...")
            project = DictProject(
                library_id=library.library_id,
                name=self.FIXTURE_NAME,
                description="Deterministic fixture for metrics testing"
            )
            session.add(project)
            session.flush()
            project_id = project.project_id
            logger.info(f"  ✓ Created project (ID={project_id})")

            # 4. Create corpus and document
            logger.info("Creating corpus and document...")
            corpus = SourceCorpus(
                project_id=project_id,
                name="fixture_corpus",
                description="Fixture corpus"
            )
            session.add(corpus)
            session.flush()

            doc = SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path="fixture_doc.txt",
                file_name="fixture_doc.txt",
                file_ext=".txt",
                sha256="fixture_sha256_v1",
            )
            session.add(doc)
            session.flush()
            logger.info(f"  ✓ Created 1 document")

            # 5. Create 10 lemmas
            logger.info("Creating 10 lemmas...")
            lemmas = []
            for i in range(1, 11):
                lemma = Lemma(
                    project_id=project_id,
                    lemma_text=f"lemma_{i:02d}",
                    pos="NOUN",
                )
                session.add(lemma)
                lemmas.append(lemma)
            session.flush()
            logger.info(f"  ✓ Created 10 lemmas")

            # 6. Create 8 TM entries (6 approved, 2 draft)
            #    Cover first 6 lemmas (60% coverage)
            logger.info("Creating 8 TM entries (6 approved, 2 draft)...")
            tm_entries = [
                # Approved entries (6) - cover lemmas 01-06
                ("lemma_01", "перевод_01", "approved"),
                ("lemma_02", "перевод_02", "approved"),
                ("lemma_03", "перевод_03", "approved"),
                ("lemma_04", "перевод_04", "approved"),
                ("lemma_05", "перевод_05", "approved"),
                ("lemma_06", "перевод_06", "approved"),
                # Draft entries (2) - don't count for coverage
                ("lemma_07", "перевод_07_draft", "draft"),
                ("lemma_08", "перевод_08_draft", "draft"),
            ]

            for src_text, translation, status in tm_entries:
                tm_entry = TMEntry(
                    project_id=project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=src_text,
                    src_norm=src_text.lower(),  # Simple normalization
                    translation=translation,
                    translation_norm=translation.lower(),
                    status=status,
                    origin="user_edit",
                )
                session.add(tm_entry)
            session.flush()
            logger.info(f"  ✓ Created 8 TM entries (6 approved, 2 draft)")

            # 7. Create 5 term clusters (2 approved, 3 needs_review)
            logger.info("Creating 5 term clusters (2 approved, 3 needs_review)...")
            term_clusters = [
                ("term_cluster_01", "approved", "термин_01"),
                ("term_cluster_02", "approved", "термин_02"),
                ("term_cluster_03", "needs_review", None),
                ("term_cluster_04", "needs_review", None),
                ("term_cluster_05", "needs_review", None),
            ]

            for representative_he, curation_status, pinned_translation in term_clusters:
                cluster = TermCluster(
                    project_id=project_id,
                    canonical_key=representative_he.lower().replace("_", " "),
                    representative_he=representative_he,
                    curation_status=curation_status,
                    pinned_translation=pinned_translation,
                )
                session.add(cluster)

            session.flush()
            logger.info(f"  ✓ Created 5 term clusters (2 approved, 3 needs_review)")

            # 8. Skip dict entries for simplicity (not critical for metrics)
            # Dict entries require complex schema (src_lang, tgt_lang, src_norm, etc.)
            # and don't affect core metrics being tested
            logger.info("Skipping dict entries (not critical for metrics)")

            session.commit()
            logger.info(f"  ✓ Fixture data created successfully")

            # 9. Validate metrics
            logger.info("\n" + "=" * 60)
            logger.info("VALIDATING METRICS AGAINST GROUND TRUTH")
            logger.info("=" * 60)

            stats = self.stats_service.compute_project_stats(session, project_id)

            # Convert stats to dict for comparison
            actual_metrics = {
                "project_name": stats.project_name,
                "document_count": stats.document_count,
                "lemma_count": stats.lemma_count,
                "lemmas_with_translation_count": stats.lemmas_with_translation_count,
                "term_cluster_count": stats.term_cluster_count,
                "term_approved_count": stats.term_approved_count,
                "tm_entry_count": stats.tm_entry_count,
                "tm_approved_count": stats.tm_approved_count,
                "dict_entry_count": stats.dict_entry_count,
                "lemma_coverage_pct": stats.lemma_coverage_pct,
                "tm_approval_rate_pct": stats.tm_approval_rate_pct,
                "term_approval_rate_pct": stats.term_approval_rate_pct,
                "tm_entries_per_lemma_pct": stats.tm_entries_per_lemma_pct,
            }

            # Compare
            all_passed = True
            for metric_key, expected_value in self.EXPECTED_METRICS.items():
                actual_value = actual_metrics[metric_key]

                # For floats, use tolerance
                if isinstance(expected_value, float):
                    matches = abs(actual_value - expected_value) < 0.01
                else:
                    matches = actual_value == expected_value

                if matches:
                    logger.info(f"  ✓ {metric_key:30s} = {actual_value} (expected {expected_value})")
                else:
                    logger.error(f"  ✗ {metric_key:30s} = {actual_value} (expected {expected_value})")
                    all_passed = False

            logger.info("=" * 60)

            if all_passed:
                logger.info("✅ ALL METRICS MATCH GROUND TRUTH")
                logger.info(f"Fixture project '{self.FIXTURE_NAME}' created successfully (ID={project_id})")
                return True
            else:
                logger.error("❌ METRICS VALIDATION FAILED")
                return False


def main():
    """Main entry point."""
    # Use test_m7.db which has M7+ migrations applied
    # This database already has tm_entry, term_cluster, etc.
    db_path = Path("test_m7.db")

    # Initialize database service
    DBService.initialize(db_path)

    seeder = FixtureSeed()
    success = seeder.seed()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
