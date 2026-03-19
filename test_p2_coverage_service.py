"""P2 Coverage Service Tests.

Tests coverage calculations and untranslated lists:
- Lemma coverage metrics
- Term cluster coverage metrics
- Untranslated filtering
- Ordering by freq/termhood
- Query count guards (no N+1)
"""

import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event


# Query counter context manager
@contextmanager
def count_sql_queries(db_service):
    """Context manager to count SQL queries executed.

    Args:
        db_service: DBService instance

    Yields:
        dict with 'count' key that increments
    """
    counter = {"count": 0}

    # Get engine from DBService
    engine = db_service.db_manager.engine

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    # Register listener
    event.listen(engine, "before_cursor_execute", before_cursor_execute)

    try:
        yield counter
    finally:
        # Remove listener
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


class TestCoverageService(unittest.TestCase):
    """Test Coverage Service."""

    @classmethod
    def setUpClass(cls):
        """Create test database with M7 schema."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply schema
        from app.services.db_service import DBService

        DBService.initialize(cls.test_db.name)

        # Apply M7 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(
            encoding="utf-8"
        )
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.close()

        cls.db_service = DBService.get_instance()

        # Create test project
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import DictProject, Library

            library = Library(library_id=1, name="Test Library")
            session.add(library)

            project = DictProject(
                project_id=1,
                library_id=1,
                name="Test Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        from app.services.db_service import DBService

        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def setUp(self):
        """Clean and seed test data."""
        from app.infra.sa_models import (
            DictEntry,
            DictSource,
            Lemma,
            LemmaProjectStat,
            TermCluster,
            TMEntry,
        )

        with self.db_service.get_session() as session:
            # Clean tables
            session.query(TMEntry).delete()
            session.query(DictEntry).delete()
            session.query(DictSource).delete()
            session.query(TermCluster).delete()
            session.query(LemmaProjectStat).delete()
            session.query(Lemma).delete()
            session.commit()

            # Seed lemmas
            lemmas_data = [
                ("בית", "NOUN", 100),  # Will be translated via TM
                ("ספר", "NOUN", 80),  # Will be translated via Dict
                ("שולחן", "NOUN", 60),  # Untranslated
                ("כסא", "NOUN", 40),  # Untranslated
            ]

            for lemma_text, pos, freq in lemmas_data:
                lemma = Lemma(
                    project_id=1,
                    lemma_text=lemma_text,
                    pos=pos,
                )
                session.add(lemma)
                session.flush()

                stat = LemmaProjectStat(
                    lemma_id=lemma.lemma_id,
                    project_id=1,
                    freq_abs=freq,
                    doc_freq=1,
                )
                session.add(stat)

            # Seed term clusters
            clusters_data = [
                ("בית הספר", 50, 0.8),  # Translated via TM, high weirdness
                ("שולחן עגול", 30, 0.6),  # Untranslated, medium weirdness
                ("כסא נוח", 20, 0.4),  # Untranslated, low weirdness
            ]

            for representative, freq, weirdness in clusters_data:
                cluster = TermCluster(
                    project_id=1,
                    representative_he=representative,
                    canonical_key=representative.replace(" ", "_"),
                    freq_abs=freq,
                    doc_freq=1,
                    members_count=1,
                    weirdness=weirdness,  # Use weirdness instead of termhood_score
                )
                session.add(cluster)

            # Add TM entries (approved)
            tm_entries = [
                TMEntry(
                    project_id=1,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="בית",
                    src_norm="בית",
                    translation="дом",
                    status="approved",
                    origin="user_edit",
                ),
                TMEntry(
                    project_id=1,
                    kind="term_cluster",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="בית הספר",
                    src_norm="בית_הספר",
                    translation="школа",
                    status="approved",
                    origin="user_edit",
                ),
            ]
            for entry in tm_entries:
                session.add(entry)

            # Add dict source and entry
            dict_source = DictSource(
                project_id=1,
                name="Test Dict",
                format="csv",
                sha256="test_hash",
                row_count=1,
            )
            session.add(dict_source)
            session.flush()

            dict_entry = DictEntry(
                dict_source_id=dict_source.dict_source_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="ספר",
                src_norm="ספר",
                translation="книга",
                status="approved",
            )
            session.add(dict_entry)

            session.commit()

    def test_compute_lemma_coverage_basic(self):
        """Test basic lemma coverage calculation."""
        from app.services.coverage_service import CoverageService

        service = CoverageService()

        with self.db_service.get_session() as session:
            metrics = service.compute_lemma_coverage(session, project_id=1)

        # 4 lemmas total, 2 covered (1 via TM, 1 via Dict)
        self.assertEqual(metrics.total, 4)
        self.assertEqual(metrics.covered, 2)
        self.assertEqual(metrics.uncovered, 2)
        self.assertEqual(metrics.coverage_pct, 50.0)

    def test_compute_termcluster_coverage_basic(self):
        """Test basic term cluster coverage calculation."""
        from app.services.coverage_service import CoverageService

        service = CoverageService()

        with self.db_service.get_session() as session:
            metrics = service.compute_termcluster_coverage(session, project_id=1)

        # 3 clusters total, 1 covered via TM
        self.assertEqual(metrics.total, 3)
        self.assertEqual(metrics.covered, 1)
        self.assertEqual(metrics.uncovered, 2)
        self.assertAlmostEqual(metrics.coverage_pct, 33.3, places=1)

    def test_list_untranslated_lemmas_excludes_translated(self):
        """Test that untranslated lemmas excludes those with TM/Dict."""
        from app.services.coverage_service import CoverageService

        service = CoverageService()

        with self.db_service.get_session() as session:
            untranslated = service.list_untranslated_lemmas(
                session,
                project_id=1,
                limit=100,
                order_by="freq",
            )

        # Should only return שולחן and כסא (not בית or ספר)
        self.assertEqual(len(untranslated), 2)
        lemma_texts = [row.lemma_text for row in untranslated]
        self.assertIn("שולחן", lemma_texts)
        self.assertIn("כסא", lemma_texts)
        self.assertNotIn("בית", lemma_texts)
        self.assertNotIn("ספר", lemma_texts)

    def test_list_untranslated_termclusters_excludes_translated(self):
        """Test that untranslated clusters excludes those with TM."""
        from app.services.coverage_service import CoverageService

        service = CoverageService()

        with self.db_service.get_session() as session:
            untranslated = service.list_untranslated_termclusters(
                session,
                project_id=1,
                limit=100,
                order_by="termhood",
            )

        # Should only return שולחן עגול and כסא נוח (not בית הספר)
        self.assertEqual(len(untranslated), 2)
        cluster_texts = [row.representative_he for row in untranslated]
        self.assertIn("שולחן עגול", cluster_texts)
        self.assertIn("כסא נוח", cluster_texts)
        self.assertNotIn("בית הספר", cluster_texts)

    def test_ordering_untranslated_lemmas_by_freq(self):
        """Test untranslated lemmas ordered by frequency."""
        from app.services.coverage_service import CoverageService

        service = CoverageService()

        with self.db_service.get_session() as session:
            untranslated = service.list_untranslated_lemmas(
                session,
                project_id=1,
                limit=100,
                order_by="freq",
            )

        # Should be ordered freq desc: שולחן (60) before כסא (40)
        self.assertEqual(untranslated[0].lemma_text, "שולחן")
        self.assertEqual(untranslated[0].freq_abs, 60)
        self.assertEqual(untranslated[1].lemma_text, "כסא")
        self.assertEqual(untranslated[1].freq_abs, 40)

    def test_query_count_guard_no_n_plus_one(self):
        """Test that coverage operations don't exceed query count ceilings."""
        from app.services.coverage_service import CoverageService

        service = CoverageService()

        # Test compute_lemma_coverage
        with self.db_service.get_session() as session:
            with count_sql_queries(self.db_service) as counter:
                service.compute_lemma_coverage(session, project_id=1)

            # Ceiling: <= 3 queries (total count + covered count subquery)
            # Actual: 2 queries (count total, count covered)
            self.assertLessEqual(
                counter["count"],
                3,
                f"compute_lemma_coverage exceeded query ceiling: {counter['count']} > 3",
            )

        # Test compute_termcluster_coverage
        with self.db_service.get_session() as session:
            with count_sql_queries(self.db_service) as counter:
                service.compute_termcluster_coverage(session, project_id=1)

            self.assertLessEqual(
                counter["count"],
                3,
                f"compute_termcluster_coverage exceeded query ceiling: {counter['count']} > 3",
            )

        # Test list_untranslated_lemmas
        with self.db_service.get_session() as session:
            with count_sql_queries(self.db_service) as counter:
                service.list_untranslated_lemmas(session, project_id=1, limit=100)

            # Ceiling: <= 5 queries (join with stats, TM, dict)
            # Actual: 1 query with joins
            self.assertLessEqual(
                counter["count"],
                5,
                f"list_untranslated_lemmas exceeded query ceiling: {counter['count']} > 5",
            )

        # Test list_untranslated_termclusters
        with self.db_service.get_session() as session:
            with count_sql_queries(self.db_service) as counter:
                service.list_untranslated_termclusters(session, project_id=1, limit=100)

            self.assertLessEqual(
                counter["count"],
                5,
                f"list_untranslated_termclusters exceeded query ceiling: {counter['count']} > 5",
            )


if __name__ == "__main__":
    unittest.main()
