"""Unit tests for StatsService.

Tests precise metric computation with various data scenarios.
"""

import os
import tempfile
import unittest
from pathlib import Path

from app.infra.sa_models import Lemma, TermCluster, TMEntry
from app.services.db_service import DBService
from app.services.stats_service import StatsService


class TestStatsService(unittest.TestCase):
    """Test StatsService metric computation."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.temp_db.close()
        cls.db_path = cls.temp_db.name

        # Initialize database
        DBService.initialize(cls.db_path)
        cls.db_service = DBService.get_instance()

        # Apply M7 TM migration (required for tm_entry table)
        import sqlite3

        migration_path = Path("schema/004_m7_translation_memory.sql")
        if migration_path.exists():
            migration_sql = migration_path.read_text(encoding="utf-8")
            con = sqlite3.connect(cls.db_path)
            con.executescript(migration_sql)
            con.close()

        # Create test project
        with cls.db_service.get_session() as session:
            from app.services.project_service import ProjectService

            project_service = ProjectService()
            project = project_service.create_project(
                session,
                name="test_stats",
                description="StatsService test project",
            )
            session.commit()
            cls.project_id = project.project_id

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        DBService.shutdown()
        if os.path.exists(cls.db_path):
            os.unlink(cls.db_path)

    def setUp(self):
        """Clear data before each test."""
        with self.db_service.get_session() as session:
            # Clear test data
            session.query(TMEntry).filter(TMEntry.project_id == self.project_id).delete()
            session.query(Lemma).filter(Lemma.project_id == self.project_id).delete()
            session.query(TermCluster).filter(TermCluster.project_id == self.project_id).delete()
            session.commit()

    def test_01_empty_project(self):
        """Test metrics for empty project (all zeros)."""
        stats_service = StatsService()

        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.project_id)

        # All counts should be zero
        self.assertEqual(stats.lemma_count, 0)
        self.assertEqual(stats.tm_entry_count, 0)
        self.assertEqual(stats.term_cluster_count, 0)
        self.assertEqual(stats.lemmas_with_translation_count, 0)

        # Coverage/rate metrics should be 0.0
        self.assertEqual(stats.lemma_coverage_pct, 0.0)
        self.assertEqual(stats.tm_approval_rate_pct, 0.0)
        self.assertEqual(stats.term_approval_rate_pct, 0.0)
        self.assertEqual(stats.tm_entries_per_lemma_pct, 0.0)

        print("[OK] Empty project: all metrics are 0")

    def test_02_basic_coverage_100_percent(self):
        """Test 100% lemma coverage (all lemmas have translations)."""
        with self.db_service.get_session() as session:
            # Create 5 lemmas
            for i in range(5):
                lemma = Lemma(
                    project_id=self.project_id,
                    lemma_text=f"word{i}",
                    pos="NOUN",
                )
                session.add(lemma)

            session.flush()

            # Create approved TM entry for each lemma
            for i in range(5):
                tm_entry = TMEntry(
                    project_id=self.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"слово{i}",
                    status="approved",
                    origin="user_edit",
                )
                session.add(tm_entry)

            session.commit()

        stats_service = StatsService()
        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.project_id)

        # Verify counts
        self.assertEqual(stats.lemma_count, 5)
        self.assertEqual(stats.tm_entry_count, 5)
        self.assertEqual(stats.tm_approved_count, 5)
        self.assertEqual(stats.lemmas_with_translation_count, 5)

        # Verify coverage = 100%
        self.assertEqual(stats.lemma_coverage_pct, 100.0)

        # Verify TM approval rate = 100%
        self.assertEqual(stats.tm_approval_rate_pct, 100.0)

        # Verify density = 100% (1 TM per lemma)
        self.assertAlmostEqual(stats.tm_entries_per_lemma_pct, 100.0, places=1)

        print("[OK] 100% coverage: 5/5 lemmas have translations")

    def test_03_partial_coverage_50_percent(self):
        """Test 50% lemma coverage (half lemmas have translations)."""
        with self.db_service.get_session() as session:
            # Create 8 lemmas
            for i in range(8):
                lemma = Lemma(
                    project_id=self.project_id,
                    lemma_text=f"word{i}",
                    pos="NOUN",
                )
                session.add(lemma)

            session.flush()

            # Create approved TM entries for only 4 lemmas (50%)
            for i in range(4):
                tm_entry = TMEntry(
                    project_id=self.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"слово{i}",
                    status="approved",
                    origin="user_edit",
                )
                session.add(tm_entry)

            session.commit()

        stats_service = StatsService()
        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.project_id)

        # Verify counts
        self.assertEqual(stats.lemma_count, 8)
        self.assertEqual(stats.tm_entry_count, 4)
        self.assertEqual(stats.tm_approved_count, 4)
        self.assertEqual(stats.lemmas_with_translation_count, 4)

        # Verify coverage = 50%
        self.assertAlmostEqual(stats.lemma_coverage_pct, 50.0, places=1)

        # Verify density = 50% (4 TM / 8 lemmas)
        self.assertAlmostEqual(stats.tm_entries_per_lemma_pct, 50.0, places=1)

        print("[OK] 50% coverage: 4/8 lemmas have translations")

    def test_04_density_exceeds_100_percent(self):
        """Test density > 100% (multiple translations per lemma)."""
        with self.db_service.get_session() as session:
            # Create 8 lemmas
            for i in range(8):
                lemma = Lemma(
                    project_id=self.project_id,
                    lemma_text=f"word{i}",
                    pos="NOUN",
                )
                session.add(lemma)

            session.flush()

            # Create 9 approved TM entries (some lemmas have multiple)
            # word0: 2 translations
            # word1-7: 1 translation each
            for i in range(8):
                tm_entry = TMEntry(
                    project_id=self.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"слово{i}_v1",
                    status="approved",
                    origin="user_edit",
                )
                session.add(tm_entry)

            # Add second translation for word0 (different src_norm to avoid unique constraint)
            tm_entry2 = TMEntry(
                project_id=self.project_id,
                kind="term_cluster",  # Different kind to avoid constraint
                src_lang="he",
                tgt_lang="ru",
                src_text="word0",
                src_norm="word0_variant",
                translation="слово0_v2",
                status="approved",
                origin="user_edit",
            )
            session.add(tm_entry2)

            session.commit()

        stats_service = StatsService()
        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.project_id)

        # Verify counts
        self.assertEqual(stats.lemma_count, 8)
        self.assertEqual(stats.tm_entry_count, 9)
        self.assertEqual(stats.tm_approved_count, 9)

        # Coverage is still 100% (all 8 lemmas have ≥1 translation)
        self.assertEqual(stats.lemma_coverage_pct, 100.0)

        # Density exceeds 100% (9 TM entries / 8 lemmas = 112.5%)
        self.assertAlmostEqual(stats.tm_entries_per_lemma_pct, 112.5, places=1)

        print(f"[OK] Density > 100%: 9 TM / 8 lemmas = {stats.tm_entries_per_lemma_pct:.1f}%")

    def test_05_draft_vs_approved_filtering(self):
        """Test that draft TM entries are excluded from coverage (default)."""
        with self.db_service.get_session() as session:
            # Create 5 lemmas
            for i in range(5):
                lemma = Lemma(
                    project_id=self.project_id,
                    lemma_text=f"word{i}",
                    pos="NOUN",
                )
                session.add(lemma)

            session.flush()

            # Create 3 approved TM entries
            for i in range(3):
                tm_entry = TMEntry(
                    project_id=self.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"слово{i}",
                    status="approved",
                    origin="user_edit",
                )
                session.add(tm_entry)

            # Create 2 draft TM entries (should NOT count for coverage)
            for i in range(3, 5):
                tm_entry = TMEntry(
                    project_id=self.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"слово{i}",
                    status="draft",
                    origin="user_edit",
                )
                session.add(tm_entry)

            session.commit()

        stats_service = StatsService()
        with self.db_service.get_session() as session:
            # Default: translation_status_filter="approved"
            stats = stats_service.compute_project_stats(session, self.project_id)

        # Verify counts
        self.assertEqual(stats.lemma_count, 5)
        self.assertEqual(stats.tm_entry_count, 5)
        self.assertEqual(stats.tm_approved_count, 3)

        # Coverage should only count approved (3/5 = 60%)
        self.assertEqual(stats.lemmas_with_translation_count, 3)
        self.assertAlmostEqual(stats.lemma_coverage_pct, 60.0, places=1)

        # TM approval rate = 3/5 = 60%
        self.assertAlmostEqual(stats.tm_approval_rate_pct, 60.0, places=1)

        print("[OK] Draft filtering: only 3/5 approved count for coverage")

    def test_06_term_approval_rate(self):
        """Test term approval rate metric."""
        with self.db_service.get_session() as session:
            # Create 5 term clusters
            for i in range(5):
                cluster = TermCluster(
                    project_id=self.project_id,
                    canonical_key=f"term{i}",
                    representative_he=f"term{i}",
                    curation_status="needs_review" if i < 3 else "approved",
                )
                session.add(cluster)

            session.commit()

        stats_service = StatsService()
        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.project_id)

        # Verify counts
        self.assertEqual(stats.term_cluster_count, 5)
        self.assertEqual(stats.term_approved_count, 2)

        # Term approval rate = 2/5 = 40%
        self.assertAlmostEqual(stats.term_approval_rate_pct, 40.0, places=1)

        print("[OK] Term approval rate: 2/5 = 40%")

    def test_07_all_metrics_bounded(self):
        """Test that coverage metrics stay in [0, 100] range."""
        # Create scenario with various data
        with self.db_service.get_session() as session:
            for i in range(10):
                lemma = Lemma(
                    project_id=self.project_id,
                    lemma_text=f"word{i}",
                    pos="NOUN",
                )
                session.add(lemma)

            session.flush()

            for i in range(7):
                tm_entry = TMEntry(
                    project_id=self.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"слово{i}",
                    status="approved",
                    origin="user_edit",
                )
                session.add(tm_entry)

            for i in range(3):
                cluster = TermCluster(
                    project_id=self.project_id,
                    canonical_key=f"term{i}",
                    representative_he=f"term{i}",
                    curation_status="approved" if i == 0 else "needs_review",
                )
                session.add(cluster)

            session.commit()

        stats_service = StatsService()
        with self.db_service.get_session() as session:
            stats = stats_service.compute_project_stats(session, self.project_id)

        # All coverage/rate metrics must be in [0, 100]
        self.assertGreaterEqual(stats.lemma_coverage_pct, 0.0)
        self.assertLessEqual(stats.lemma_coverage_pct, 100.0)

        self.assertGreaterEqual(stats.tm_approval_rate_pct, 0.0)
        self.assertLessEqual(stats.tm_approval_rate_pct, 100.0)

        self.assertGreaterEqual(stats.term_approval_rate_pct, 0.0)
        self.assertLessEqual(stats.term_approval_rate_pct, 100.0)

        # Density metric CAN exceed 100% (that's OK)
        self.assertGreaterEqual(stats.tm_entries_per_lemma_pct, 0.0)
        # (no upper bound for density)

        print("[OK] All coverage metrics bounded in [0, 100]")


if __name__ == "__main__":
    unittest.main()
