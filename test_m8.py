"""M8: Term Curation - Comprehensive Tests

Full test suite for M8 term curation functionality.
Tests TermCardService, TermCardDTO, migration 005, and edge cases.

Run: python test_m8.py
Run with anti-flake: python test_m8.py --repeat 20
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.db_service import DBService
from app.services.term_card_service import TermCardService
from app.infra.sa_models import TermCluster, TermAlias, StopwordSet, StopwordItem, DocumentSentence, SourceDocument


class TestM8TermCuration(unittest.TestCase):
    """Comprehensive M8 term curation tests."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        cls.temp_db.close()
        cls.db_path = cls.temp_db.name

        # Initialize with migrations
        DBService.initialize(cls.db_path)
        cls.db_service = DBService.get_instance()

        # Create test project
        with cls.db_service.get_session() as session:
            from app.services.project_service import ProjectService
            project_service = ProjectService()
            project = project_service.create_project(
                session,
                name="test_m8_comprehensive",
                description="M8 comprehensive test project",
            )
            session.commit()
            cls.project_id = project.project_id

            # Create test document for sentence references
            # Note: SourceDocument requires corpus_id, so we need to create a corpus first
            from app.infra.sa_models import SourceCorpus
            corpus = SourceCorpus(
                project_id=cls.project_id,
                name="test_corpus",
                description="Test corpus for M8"
            )
            session.add(corpus)
            session.flush()

            doc = SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path="test_doc.txt",
                file_name="test_doc.txt",
                file_ext=".txt",
                sha256="test_hash_m8_sha256",
            )
            session.add(doc)
            session.commit()
            cls.doc_id = doc.doc_id

            # Create test sentence
            sent = DocumentSentence(
                doc_id=cls.doc_id,
                text="זה משפט דוגמה לבדיקה",
                sent_index=0,
            )
            session.add(sent)
            session.commit()
            cls.sent_id = sent.sentence_id

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        DBService.shutdown()
        if os.path.exists(cls.db_path):
            os.unlink(cls.db_path)

    def setUp(self):
        """Set up each test."""
        self.service = TermCardService()

    # ========================================================================
    # Test 1: Migration Verification
    # ========================================================================

    def test_01_migration_005_applied(self):
        """Test that M8 migration (005) schema changes are present."""
        from sqlalchemy import text

        with self.db_service.get_session() as session:
            # Check schema version
            result = session.execute(text("SELECT value FROM schema_meta WHERE key='schema_version'"))
            version = result.scalar()
            self.assertIsNotNone(version)
            version_int = int(version)
            self.assertGreaterEqual(version_int, 5, "Schema version should be >= 5 (M8)")

            # Check curation columns exist
            result = session.execute(text("PRAGMA table_info(term_cluster)"))
            columns = {row[1] for row in result.fetchall()}

            required_columns = {
                'curation_status',
                'pinned_translation',
                'pinned_translation_lang',
                'pinned_example_sent_id',
                'curation_notes',
                'curated_at',
                'curated_by',
            }

            missing = required_columns - columns
            self.assertEqual(len(missing), 0, f"Missing columns: {missing}")

            print("[OK] Migration 005 applied - all curation columns present")

    # ========================================================================
    # Test 2-3: Basic CRUD Operations
    # ========================================================================

    def test_02_create_and_get_card(self):
        """Test creating term cluster and retrieving as TermCardDTO."""
        canonical = "בדיקה_01"

        with self.db_service.get_session() as session:
            # Create term
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="בדיקה 01",
                freq_abs=15,
                doc_freq=5,
                members_count=3,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Get card
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)

            self.assertIsNotNone(card)
            self.assertEqual(card.cluster_id, cluster_id)
            self.assertEqual(card.canonical_key, canonical)
            self.assertEqual(card.representative_he, "בדיקה 01")
            self.assertEqual(card.freq_abs, 15)
            self.assertEqual(card.doc_freq, 5)
            self.assertEqual(card.curation_status, "auto")
            self.assertEqual(card.aliases, [])
            self.assertFalse(card.is_stopword)
            self.assertIsNone(card.pinned_translation)

            print("[OK] create_and_get_card")

    def test_03_get_card_by_canonical_key(self):
        """Test retrieving card by canonical_key (alternative lookup)."""
        canonical = "בדיקה_02"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="בדיקה 02",
                freq_abs=10,
                doc_freq=3,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()

        # Get by canonical_key
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, canonical_key=canonical)

            self.assertIsNotNone(card)
            self.assertEqual(card.canonical_key, canonical)
            self.assertEqual(card.representative_he, "בדיקה 02")

            print("[OK] get_card_by_canonical_key")

    # ========================================================================
    # Test 4-5: Status Workflow
    # ========================================================================

    def test_04_set_status_workflow(self):
        """Test full status workflow: auto -> needs_review -> approved."""
        canonical = "בדיקה_03"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="בדיקה 03",
                freq_abs=20,
                doc_freq=8,
                members_count=2,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # auto -> needs_review
        with self.db_service.get_session() as session:
            result = self.service.set_status(
                session, cluster_id, "needs_review", "test_curator", "Needs verification"
            )
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.curation_status, "needs_review")
            self.assertEqual(card.curated_by, "test_curator")
            self.assertEqual(card.curation_notes, "Needs verification")
            self.assertIsNotNone(card.curated_at)

        # needs_review -> approved
        with self.db_service.get_session() as session:
            result = self.service.set_status(
                session, cluster_id, "approved", "test_curator", "Verified correct"
            )
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.curation_status, "approved")
            self.assertEqual(card.curation_notes, "Verified correct")

            print("[OK] set_status_workflow")

    def test_05_set_status_rejected(self):
        """Test setting status to 'rejected' (mark as noise)."""
        canonical = "רעש_01"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="רעש",
                freq_abs=2,
                doc_freq=1,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Reject as noise
        with self.db_service.get_session() as session:
            result = self.service.set_status(
                session, cluster_id, "rejected", "test_curator", "Not a real term"
            )
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.curation_status, "rejected")

            print("[OK] set_status_rejected")

    # ========================================================================
    # Test 6: Bulk Status Operations
    # ========================================================================

    def test_06_bulk_set_status(self):
        """Test bulk status update for multiple terms."""
        cluster_ids = []

        with self.db_service.get_session() as session:
            for i in range(5):
                cluster = TermCluster(
                    project_id=self.project_id,
                    canonical_key=f"bulk_term_{i}",
                    representative_he=f"טרם {i}",
                    freq_abs=10 + i,
                    doc_freq=3,
                    members_count=1,
                    curation_status="auto",
                )
                session.add(cluster)
                session.flush()
                cluster_ids.append(cluster.cluster_id)
            session.commit()

        # Bulk approve
        with self.db_service.get_session() as session:
            count = self.service.bulk_set_status(
                session, cluster_ids, "approved", "bulk_curator"
            )
            self.assertEqual(count, 5)
            session.commit()

        # Verify all updated
        with self.db_service.get_session() as session:
            for cid in cluster_ids:
                card = self.service.get_card(session, self.project_id, cluster_id=cid)
                self.assertEqual(card.curation_status, "approved")
                self.assertEqual(card.curated_by, "bulk_curator")

            print("[OK] bulk_set_status")

    # ========================================================================
    # Test 7-8: Alias Management
    # ========================================================================

    def test_07_alias_management_full_cycle(self):
        """Test add/list/remove alias operations."""
        canonical = "בדיקה_alias"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="בדיקה",
                freq_abs=10,
                doc_freq=3,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()

        # Add aliases
        with self.db_service.get_session() as session:
            result1 = self.service.add_alias(session, self.project_id, canonical, "בְּדִיקָה", "With nikud")
            result2 = self.service.add_alias(session, self.project_id, canonical, "בדיקות", "Plural")
            self.assertTrue(result1)
            self.assertTrue(result2)
            session.commit()

        # List aliases
        with self.db_service.get_session() as session:
            aliases = self.service.list_aliases(session, self.project_id, canonical)
            self.assertEqual(len(aliases), 2)
            variants = {a["variant"] for a in aliases}
            self.assertEqual(variants, {"בְּדִיקָה", "בדיקות"})

        # Get card - aliases included in DTO
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, canonical_key=canonical)
            self.assertEqual(set(card.aliases), {"בְּדִיקָה", "בדיקות"})

        # Remove one alias
        with self.db_service.get_session() as session:
            result = self.service.remove_alias(session, self.project_id, canonical, "בדיקות")
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            aliases = self.service.list_aliases(session, self.project_id, canonical)
            self.assertEqual(len(aliases), 1)
            self.assertEqual(aliases[0]["variant"], "בְּדִיקָה")

            print("[OK] alias_management_full_cycle")

    def test_08_alias_duplicate_prevention(self):
        """Test that duplicate aliases are prevented."""
        canonical = "בדיקה_dup"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="בדיקה",
                freq_abs=5,
                doc_freq=2,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()

        # Add alias
        with self.db_service.get_session() as session:
            result1 = self.service.add_alias(session, self.project_id, canonical, "וריאנט", "First")
            self.assertTrue(result1)
            session.commit()

        # Try to add same alias again
        with self.db_service.get_session() as session:
            result2 = self.service.add_alias(session, self.project_id, canonical, "וריאנט", "Duplicate")
            self.assertFalse(result2, "Duplicate alias should be rejected")
            session.commit()

        with self.db_service.get_session() as session:
            aliases = self.service.list_aliases(session, self.project_id, canonical)
            self.assertEqual(len(aliases), 1, "Should only have one alias")

            print("[OK] alias_duplicate_prevention")

    # ========================================================================
    # Test 9-10: Stopword Management
    # ========================================================================

    def test_09_stopword_full_cycle(self):
        """Test set/check/unset stopword operations."""
        canonical = "רעש_stopword"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="רעש",
                freq_abs=100,
                doc_freq=50,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Initially not stopword
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertFalse(card.is_stopword)

        # Set stopword
        with self.db_service.get_session() as session:
            result = self.service.set_stopword(session, self.project_id, canonical, "Too common")
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertTrue(card.is_stopword)

        # Unset stopword
        with self.db_service.get_session() as session:
            result = self.service.unset_stopword(session, self.project_id, canonical)
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertFalse(card.is_stopword)

            print("[OK] stopword_full_cycle")

    def test_10_stopword_duplicate_prevention(self):
        """Test that setting stopword twice returns False."""
        canonical = "רעש_dup"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="רעש",
                freq_abs=50,
                doc_freq=20,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()

        # First set
        with self.db_service.get_session() as session:
            result1 = self.service.set_stopword(session, self.project_id, canonical, "Common")
            self.assertTrue(result1)
            session.commit()

        # Second set (duplicate)
        with self.db_service.get_session() as session:
            result2 = self.service.set_stopword(session, self.project_id, canonical, "Duplicate")
            self.assertFalse(result2, "Duplicate stopword should return False")

            print("[OK] stopword_duplicate_prevention")

    # ========================================================================
    # Test 11-12: Pin Translation
    # ========================================================================

    def test_11_pin_translation_full_cycle(self):
        """Test pin/unpin translation operations."""
        canonical = "מתורגם"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="מתורגם",
                freq_abs=30,
                doc_freq=10,
                members_count=2,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Pin translation
        with self.db_service.get_session() as session:
            result = self.service.pin_translation(session, cluster_id, "переведённый", "ru")
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.pinned_translation, "переведённый")
            self.assertEqual(card.pinned_translation_lang, "ru")

        # Unpin
        with self.db_service.get_session() as session:
            result = self.service.unpin_translation(session, cluster_id)
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertIsNone(card.pinned_translation)
            self.assertIsNone(card.pinned_translation_lang)

            print("[OK] pin_translation_full_cycle")

    def test_12_pin_example_sentence(self):
        """Test pinning example sentence."""
        canonical = "דוגמה_sent"

        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key=canonical,
                representative_he="דוגמה",
                freq_abs=10,
                doc_freq=4,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        # Pin example
        with self.db_service.get_session() as session:
            result = self.service.pin_example(session, cluster_id, self.sent_id)
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertEqual(card.pinned_example_sent_id, self.sent_id)
            self.assertEqual(card.pinned_example_text, "זה משפט דוגמה לבדיקה")

        # Unpin
        with self.db_service.get_session() as session:
            result = self.service.unpin_example(session, cluster_id)
            self.assertTrue(result)
            session.commit()

        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=cluster_id)
            self.assertIsNone(card.pinned_example_sent_id)
            self.assertIsNone(card.pinned_example_text)

            print("[OK] pin_example_sentence")

    # ========================================================================
    # Test 13-14: Review Queue
    # ========================================================================

    def test_13_review_queue_filtering(self):
        """Test review queue filtering by status."""
        # Create terms with different statuses
        cluster_ids = {}

        with self.db_service.get_session() as session:
            for status in ["auto", "needs_review", "approved", "rejected"]:
                for i in range(3):
                    cluster = TermCluster(
                        project_id=self.project_id,
                        canonical_key=f"queue_{status}_{i}",
                        representative_he=f"טרם {status} {i}",
                        freq_abs=20 - i,
                        doc_freq=5,
                        members_count=1,
                        curation_status=status,
                    )
                    session.add(cluster)
                    session.flush()
                    cluster_ids.setdefault(status, []).append(cluster.cluster_id)
            session.commit()

        # Filter by needs_review
        with self.db_service.get_session() as session:
            cards = self.service.list_review_queue(
                session,
                self.project_id,
                status_filter="needs_review",
                limit=100,
            )
            statuses = {card.curation_status for card in cards}
            self.assertEqual(statuses, {"needs_review"})
            self.assertGreaterEqual(len(cards), 3)

        # Filter by approved
        with self.db_service.get_session() as session:
            cards = self.service.list_review_queue(
                session,
                self.project_id,
                status_filter="approved",
                limit=100,
            )
            statuses = {card.curation_status for card in cards}
            self.assertEqual(statuses, {"approved"})

            print("[OK] review_queue_filtering")

    def test_14_review_queue_ordering_and_limits(self):
        """Test review queue ordering and pagination."""
        # Create terms with varying frequencies
        with self.db_service.get_session() as session:
            for freq in [5, 15, 25, 35, 45]:
                cluster = TermCluster(
                    project_id=self.project_id,
                    canonical_key=f"order_test_{freq}",
                    representative_he=f"טרם {freq}",
                    freq_abs=freq,
                    doc_freq=3,
                    members_count=1,
                    curation_status="auto",
                )
                session.add(cluster)
            session.commit()

        # Order by frequency (descending)
        with self.db_service.get_session() as session:
            cards = self.service.list_review_queue(
                session,
                self.project_id,
                order_by="freq",
                limit=3,
            )
            # Should get highest frequencies first
            freqs = [card.freq_abs for card in cards[:3]]
            self.assertEqual(freqs, sorted(freqs, reverse=True), "Should be descending")

        # Min frequency filter
        with self.db_service.get_session() as session:
            cards = self.service.list_review_queue(
                session,
                self.project_id,
                min_freq=30,
                limit=100,
            )
            all_above_30 = all(card.freq_abs >= 30 for card in cards)
            self.assertTrue(all_above_30, "All results should have freq >= 30")

        # Count
        with self.db_service.get_session() as session:
            total = self.service.count_review_queue(session, self.project_id)
            self.assertGreater(total, 0)

            print("[OK] review_queue_ordering_and_limits")

    # ========================================================================
    # Test 15: Edge Cases
    # ========================================================================

    def test_15_edge_cases(self):
        """Test edge cases and error conditions."""
        # Get non-existent card
        with self.db_service.get_session() as session:
            card = self.service.get_card(session, self.project_id, cluster_id=99999)
            self.assertIsNone(card)

        # Set status for non-existent cluster
        with self.db_service.get_session() as session:
            result = self.service.set_status(session, 99999, "approved", "user", "note")
            self.assertFalse(result)

        # Invalid status
        with self.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=self.project_id,
                canonical_key="edge_test",
                representative_he="קצה",
                freq_abs=5,
                doc_freq=2,
                members_count=1,
                curation_status="auto",
            )
            session.add(cluster)
            session.commit()
            cluster_id = cluster.cluster_id

        with self.db_service.get_session() as session:
            with self.assertRaises(ValueError):
                self.service.set_status(session, cluster_id, "invalid_status", "user", "note")

        # Remove non-existent alias
        with self.db_service.get_session() as session:
            result = self.service.remove_alias(session, self.project_id, "edge_test", "nonexistent")
            self.assertFalse(result)

        # Unset stopword that doesn't exist
        with self.db_service.get_session() as session:
            result = self.service.unset_stopword(session, self.project_id, "nonexistent_term")
            self.assertFalse(result)

        print("[OK] edge_cases")


def run_anti_flake_verification(repeat_count=20):
    """Run tests multiple times to verify stability."""
    print("=" * 70)
    print(f"Running anti-flake verification ({repeat_count} iterations)")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestM8TermCuration)

    failures = []
    for i in range(1, repeat_count + 1):
        runner = unittest.TextTestRunner(verbosity=0)
        result = runner.run(suite)

        if not result.wasSuccessful():
            failures.append(i)
            print(f"[FAIL] Iteration {i}/{repeat_count}")
        else:
            print(f"[OK] Iteration {i}/{repeat_count}")

    print("=" * 70)
    if not failures:
        print(f"[SUCCESS] All {repeat_count} iterations passed - NO FLAKES DETECTED")
    else:
        print(f"[FAILURE] {len(failures)} iterations failed: {failures}")
        print("FLAKES DETECTED - tests are not stable")
    print("=" * 70)

    return len(failures) == 0


if __name__ == "__main__":
    # Check for --repeat flag
    if len(sys.argv) > 1 and sys.argv[1] == "--repeat":
        repeat_count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        success = run_anti_flake_verification(repeat_count)
        sys.exit(0 if success else 1)
    else:
        print("=" * 70)
        print("M8: Term Curation - Comprehensive Tests")
        print("=" * 70)
        unittest.main(verbosity=2)
