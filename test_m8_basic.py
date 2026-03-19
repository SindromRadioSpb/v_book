"""M8: Term Curation - Basic Tests

Basic smoke tests for M8 term curation functionality.
Tests TermCardService and migration 005.
"""

import os
import tempfile
import unittest

from app.infra.sa_models import TermCluster
from app.services.db_service import DBService
from app.services.term_card_service import TermCardService


class TestM8BasicCuration(unittest.TestCase):
    """Basic M8 term curation tests."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.temp_db.close()
        cls.db_path = cls.temp_db.name

        # Initialize with migrations
        DBService.initialize(cls.db_path)
        cls.db_service = DBService.get_instance()

        # Create test data
        with cls.db_service.get_session() as session:
            # Create test project
            from app.services.project_service import ProjectService

            project_service = ProjectService()
            project = project_service.create_project(
                session,
                name="test_m8_project",
                description="M8 test project",
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
        """Set up each test."""
        self.service = TermCardService()

    def test_01_migration_applied(self):
        """Test that M8 migration (005) was applied correctly."""
        from sqlalchemy import text

        with self.db_service.get_session() as session:
            # Check schema_meta
            result = session.execute(
                text("SELECT value FROM schema_meta WHERE key='schema_version'")
            )
            version = result.scalar()
            # Should be at least 5 (M8 migration)
            # But might be higher if M7 migrations also ran
            self.assertIsNotNone(version)
            print(f"Schema version: {version}")

            # Check that curation_status column exists
            result = session.execute(text("PRAGMA table_info(term_cluster)"))
            columns = [row[1] for row in result.fetchall()]
            self.assertIn("curation_status", columns)
            self.assertIn("pinned_translation", columns)
            self.assertIn("pinned_example_sent_id", columns)
            self.assertIn("curation_notes", columns)

            print("[OK] M8 migration applied - curation columns exist")

    def test_02_create_term_cluster(self):
        """Test creating a term cluster with curation fields."""
        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key="בית_ספר",
                representative_he="בית ספר",
                representative_lemma="בית_ספר",
                freq_abs=10,
                doc_freq=3,
                members_count=2,
                curation_status="auto",  # Default
            )
            session.add(cluster)
            session.commit()

            # Verify
            retrieved = (
                session.query(TermCluster).filter(TermCluster.canonical_key == "בית_ספר").first()
            )
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.curation_status, "auto")
            self.assertIsNone(retrieved.pinned_translation)
            print("[OK] Term cluster created with curation fields")

    def test_03_get_card(self):
        """Test getting term card."""
        with self.db_service.get_session() as session:
            # Create a term
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key="שלום",
                representative_he="שלום",
                freq_abs=5,
                doc_freq=2,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Get card
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertIsNotNone(card)
            self.assertEqual(card.canonical_key, "שלום")
            self.assertEqual(card.curation_status, "auto")
            self.assertEqual(card.aliases, [])
            self.assertFalse(card.is_stopword)
            print("[OK] get_card() works")

    def test_04_set_status(self):
        """Test setting curation status."""
        with self.db_service.get_session() as session:
            # Create a term
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key="מבחן",
                representative_he="מבחן",
                freq_abs=3,
                doc_freq=1,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Set to needs_review
        with self.db_service.get_session() as session:
            result = self.service.set_status(
                session, cluster_id, "needs_review", "test_user", "Flagged for review"
            )
            self.assertTrue(result)
            session.commit()

        # Verify
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.curation_status, "needs_review")
            self.assertEqual(card.curated_by, "test_user")
            self.assertEqual(card.curation_notes, "Flagged for review")
            self.assertIsNotNone(card.curated_at)
            print("[OK] set_status() works")

    def test_05_add_remove_alias(self):
        """Test adding and removing aliases."""
        canonical = "דוגמה"

        with self.db_service.get_session() as session:
            # Create a term
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="דוגמה",
                freq_abs=2,
                doc_freq=1,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()

        # Add alias
        with self.db_service.get_session() as session:
            result = self.service.add_alias(
                session, self.project_id, canonical, "דֻגְמָה", "With nikud"
            )
            self.assertTrue(result)
            session.commit()

        # Verify alias exists
        with self.db_service.get_session() as session:
            aliases = self.service.list_aliases(session, self.project_id, canonical)
            self.assertEqual(len(aliases), 1)
            self.assertEqual(aliases[0]["variant"], "דֻגְמָה")
            print("[OK] add_alias() works")

        # Remove alias
        with self.db_service.get_session() as session:
            result = self.service.remove_alias(session, self.project_id, canonical, "דֻגְמָה")
            self.assertTrue(result)
            session.commit()

        # Verify removed
        with self.db_service.get_session() as session:
            aliases = self.service.list_aliases(session, self.project_id, canonical)
            self.assertEqual(len(aliases), 0)
            print("[OK] remove_alias() works")

    def test_06_set_unset_stopword(self):
        """Test marking term as stopword."""
        canonical = "רעש"

        with self.db_service.get_session() as session:
            # Create a term
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="רעש",
                freq_abs=1,
                doc_freq=1,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Set stopword
        with self.db_service.get_session() as session:
            result = self.service.set_stopword(session, self.project_id, canonical, "Too common")
            self.assertTrue(result)
            session.commit()

        # Verify
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertTrue(card.is_stopword)
            print("[OK] set_stopword() works")

        # Unset stopword
        with self.db_service.get_session() as session:
            result = self.service.unset_stopword(session, self.project_id, canonical)
            self.assertTrue(result)
            session.commit()

        # Verify
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertFalse(card.is_stopword)
            print("[OK] unset_stopword() works")

    def test_07_pin_unpin_translation(self):
        """Test pinning/unpinning translation."""
        with self.db_service.get_session() as session:
            # Create a term
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key="מתורגם",
                representative_he="מתורגם",
                freq_abs=4,
                doc_freq=2,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Pin translation
        with self.db_service.get_session() as session:
            result = self.service.pin_translation(session, cluster_id, "переведено", "ru")
            self.assertTrue(result)
            session.commit()

        # Verify
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.pinned_translation, "переведено")
            self.assertEqual(card.pinned_translation_lang, "ru")
            print("[OK] pin_translation() works")

        # Unpin
        with self.db_service.get_session() as session:
            result = self.service.unpin_translation(session, cluster_id)
            self.assertTrue(result)
            session.commit()

        # Verify
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertIsNone(card.pinned_translation)
            print("[OK] unpin_translation() works")

    def test_08_review_queue(self):
        """Test review queue listing."""
        with self.db_service.get_session() as session:
            # Create multiple terms with different statuses
            for i, status in enumerate(["auto", "needs_review", "approved", "rejected"]):
                cluster = TermCluster(
                    project_id=self.project_id,
                    canonical_key=f"term_{status}_{i}",
                    representative_he=f"טרם {status}",
                    freq_abs=10 - i,
                    doc_freq=2,
                    members_count=1,
                    curation_status=status,
                )
                session.add(cluster)
            session.commit()

        # List needs_review
        with self.db_service.get_session() as session:
            cards = self.service.list_review_queue(
                session,
                self.project_id,
                status_filter="needs_review",
                order_by="freq",
                limit=10,
            )
            needs_review = [c for c in cards if c.curation_status == "needs_review"]
            self.assertGreater(len(needs_review), 0)
            print(f"[OK] Review queue: {len(needs_review)} needs_review terms")

        # Count all
        with self.db_service.get_session() as session:
            total = self.service.count_review_queue(session, self.project_id)
            self.assertGreater(total, 0)
            print(f"[OK] Total terms in queue: {total}")


if __name__ == "__main__":
    print("=" * 70)
    print("M8: Term Curation - Basic Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
