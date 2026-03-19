#!/usr/bin/env python3
"""P1 Verification Service - Automated Tests.

Tests P1 Scenario 7 verification without manual UI interaction.
"""

import os
import tempfile
import unittest
from pathlib import Path

from app.services.db_service import DBService
from app.services.p1_verification_service import P1VerificationService


class TestP1VerificationService(unittest.TestCase):
    """Test P1 verification service."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        # Create temp test DB
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Initialize DB with schema (DBService.initialize applies migrations automatically)
        DBService.initialize(cls.test_db.name)
        cls.db_service = DBService.get_instance()

        # Apply M7 migrations for TM support
        import sqlite3

        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(
            encoding="utf-8"
        )

        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.close()

        # Create minimal test data
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import DictProject, Lemma, LemmaProjectStat, Library

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
            session.flush()

            # Add test lemmas
            for i, lemma_text in enumerate(["בית", "ספר", "בית ספר"], start=1):
                lemma = Lemma(
                    lemma_id=i,
                    project_id=1,
                    lemma_text=lemma_text,
                    pos="NOUN",
                )
                session.add(lemma)

                stat = LemmaProjectStat(
                    lemma_id=i,
                    project_id=1,
                    freq_abs=10,
                    doc_freq=1,
                )
                session.add(stat)

            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        if hasattr(cls, "test_db"):
            try:
                os.unlink(cls.test_db.name)
            except:
                pass

    def test_01_snapshot_safe(self):
        """Test that snapshot doesn't modify original DB."""
        service = P1VerificationService()

        # Get original size/mtime
        original_size = os.path.getsize(self.test_db.name)
        original_mtime = os.path.getmtime(self.test_db.name)

        # Create snapshot
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_info = service.create_snapshot_db(self.test_db.name, tmpdir)

            # Verify snapshot created
            self.assertTrue(os.path.exists(snapshot_info.snapshot_path))

            # Verify original unchanged
            self.assertEqual(os.path.getsize(self.test_db.name), original_size)
            self.assertEqual(os.path.getmtime(self.test_db.name), original_mtime)

            # Verify snapshot is copy
            self.assertGreater(os.path.getsize(snapshot_info.snapshot_path), 0)

    def test_02_select_test_items(self):
        """Test selection of test items."""
        service = P1VerificationService()

        with self.db_service.get_session() as session:
            items = service.select_test_items(session, project_id=1)

            # Should select up to 3 items
            self.assertGreater(len(items), 0)
            self.assertLessEqual(len(items), 3)

            # Items should have required fields
            for item in items:
                self.assertIsNotNone(item.kind)
                self.assertIsNotNone(item.src_text)
                self.assertIsNotNone(item.src_norm)

    def test_03_seed_strict(self):
        """Test that TM entries are seeded with strict normalization."""
        from app.domain.normalization import normalize_for_tm
        from app.infra.sa_models import TMEntry

        service = P1VerificationService()

        with self.db_service.get_session() as session:
            # Clear existing TM entries for clean test
            session.query(TMEntry).filter(TMEntry.project_id == 1).delete()
            session.commit()

            items = service.select_test_items(session, project_id=1)
            seeded_tm = service.seed_tm_entries(session, items, project_id=1)

            # Verify seeded TM uses strict normalization
            for tm in seeded_tm:
                # Compute what strict normalization should be
                expected_norm = normalize_for_tm("he", tm.item.src_text, tm.item.kind).norm

                # Verify TM entry uses strict norm
                self.assertEqual(tm.src_norm, expected_norm)

    def test_04_verify_resolve(self):
        """Test verification of TM entry resolution."""
        from app.infra.sa_models import TMEntry

        service = P1VerificationService()

        with self.db_service.get_session() as session:
            # Clear existing TM entries for clean test
            session.query(TMEntry).filter(TMEntry.project_id == 1).delete()
            session.commit()

            items = service.select_test_items(session, project_id=1)
            seeded_tm = service.seed_tm_entries(session, items, project_id=1)

            # Verify resolution
            result = service.verify_resolve(session, seeded_tm, project_id=1)

            # All items should resolve successfully
            self.assertEqual(result.items_passed, result.items_checked)
            self.assertEqual(result.items_failed, 0)

    def test_05_restart_simulation(self):
        """Test that TM entries persist after restart simulation."""
        from app.infra.sa_models import TMEntry

        service = P1VerificationService()

        # Seed TM entries
        with self.db_service.get_session() as session:
            # Clear existing TM entries for clean test
            session.query(TMEntry).filter(TMEntry.project_id == 1).delete()
            session.commit()

            items = service.select_test_items(session, project_id=1)
            seeded_tm = service.seed_tm_entries(session, items, project_id=1)

        # Simulate restart
        session_restart = service.simulate_restart(self.test_db.name)

        # Verify TM entries still resolve
        result = service.verify_resolve(session_restart, seeded_tm, project_id=1)

        self.assertEqual(result.items_passed, result.items_checked)
        self.assertEqual(result.items_failed, 0)

        session_restart.close()

    def test_06_skip_gracefully(self):
        """Test that empty project SKIPs gracefully without exceptions."""
        service = P1VerificationService()

        # Create empty project
        with self.db_service.get_session() as session:
            from app.infra.sa_models import DictProject

            empty_project = DictProject(
                project_id=999,
                library_id=1,
                name="Empty Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(empty_project)
            session.commit()

            # Select items should return empty list
            items = service.select_test_items(session, project_id=999)
            self.assertEqual(len(items), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
