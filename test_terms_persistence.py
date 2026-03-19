"""Regression test for Terms tab translation persistence after Refresh.

Reproduces bug:
1. User enters translation inline in Terms tab
2. Status changes to "approved"
3. User clicks Refresh
4. Translation disappears, status returns to None

This test verifies that inline TM overrides persist after refresh.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.services.db_service import DBService


class TestTermsTranslationPersistence(unittest.TestCase):
    """Test that Terms tab inline translations persist after refresh."""

    @classmethod
    def setUpClass(cls):
        """Create test database and QApplication."""
        # Create test DB
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        DBService.initialize(cls.test_db.name)

        # Apply migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(
            encoding="utf-8"
        )
        migration_p2 = Path("schema/006_p2_add_revert_origin.sql").read_text(encoding="utf-8")
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.executescript(migration_p2)
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
                name="Terms Persistence Test",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

        # Create fixture term cluster
        cls._create_term_cluster()

        # Create QApplication for headless testing
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @classmethod
    def _create_term_cluster(cls):
        """Create a test term cluster."""
        from app.infra.sa_models import TermCluster

        with cls.db_service.get_session() as session:
            cluster = TermCluster(
                project_id=1,
                canonical_key="ספר_גדול",  # Normalized key
                representative_he="ספר גדול",  # Surface form
                representative_lemma="ספר גדול",
                freq_abs=10,
                doc_freq=2,
            )
            session.add(cluster)
            session.commit()

            cls.cluster_id = cluster.cluster_id

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def test_inline_translation_persists_after_refresh(self):
        """Test that inline translation edit persists after Refresh button click.

        This is the core regression test for the bug where:
        - User enters translation in Terms tab
        - Status shows "approved"
        - User clicks Refresh
        - Translation disappears (BUG!)
        """
        from sqlalchemy import select

        from app.infra.sa_models import TMEntry
        from app.ui.terms_view import TermsView

        # Create TermsView for project 1
        terms_view = TermsView(project_id=1)

        # Simulate loading clusters (as Extract Terms does)
        from app.domain.dto import ClusterStats
        from app.infra.sa_models import TermCluster

        with self.db_service.get_session() as session:
            stmt = select(TermCluster).where(TermCluster.project_id == 1)
            db_cluster = session.execute(stmt).scalar()
            self.assertIsNotNone(db_cluster, "Fixture cluster should exist")

            # Build ClusterStats DTO (what the UI model uses)
            cluster_stats = ClusterStats(
                cluster_id=db_cluster.cluster_id,
                canonical_key=db_cluster.canonical_key,
                representative_he=db_cluster.representative_he,
                representative_lemma=db_cluster.representative_lemma,
                freq_abs=db_cluster.freq_abs,
                doc_freq=db_cluster.doc_freq,
                members_count=1,
                best_pmi=None,
                best_llr=None,
                best_dice=None,
                best_tscore=None,
                translation=None,
                translation_status=None,
            )

        # Load cluster into UI model
        terms_view.terms_model._clusters = [cluster_stats]
        terms_view.terms_model.layoutChanged.emit()

        # STEP 1: Simulate user inline edit of Translation column
        # Find the translation column index
        translation_col = 11  # Translation column (from model definition)

        # Get model index for first row, translation column
        model_index = terms_view.terms_model.index(0, translation_col)

        # Set translation value (simulates user typing "Книга большая")
        translation_value = "Книга большая"
        success = terms_view.terms_model.setData(
            model_index, translation_value, Qt.ItemDataRole.EditRole
        )
        self.assertTrue(success, "setData should succeed")

        # CRITICAL: Process Qt events to ensure signal handlers execute
        from PyQt6.QtWidgets import QApplication

        QApplication.processEvents()

        # STEP 2: Verify TM entry was created in DB with correct project_id
        with self.db_service.get_session() as session:
            stmt = select(TMEntry).where(
                TMEntry.project_id == 1,
                TMEntry.kind == "term_cluster",
                TMEntry.translation == translation_value,
            )
            tm_entry = session.execute(stmt).scalar()

            # This is the KEY assertion - TM entry must exist after inline edit
            self.assertIsNotNone(tm_entry, "TM entry should be created after inline edit")

            # Verify fields are correct
            self.assertEqual(tm_entry.project_id, 1, "TM entry should be project-scoped")
            self.assertEqual(tm_entry.src_lang, "he")
            self.assertEqual(tm_entry.tgt_lang, "ru")
            self.assertEqual(tm_entry.status, "approved", "User edit should be approved")
            self.assertEqual(tm_entry.origin, "user_edit")

            # Verify src_norm matches what load will use
            from app.domain.normalization.normalizer import normalize_for_tm

            expected_norm = normalize_for_tm("he", cluster_stats.representative_he, "term_cluster")

            # DEBUG: Write to file instead of print (encoding issues)
            with open("debug_terms_test.txt", "w", encoding="utf-8") as f:
                f.write("DEBUG after save:\n")
                f.write(f"  representative_he: {cluster_stats.representative_he}\n")
                f.write(f"  canonical_key: {cluster_stats.canonical_key}\n")
                f.write(f"  expected_norm: {expected_norm.norm}\n")
                f.write(f"  tm_entry.src_norm: {tm_entry.src_norm}\n")
                f.write(f"  tm_entry.src_text: {tm_entry.src_text}\n")

            self.assertEqual(
                tm_entry.src_norm, expected_norm.norm, "src_norm should match load normalization"
            )

        # DEBUG: Check TM entry exists before refresh
        with self.db_service.get_session() as session:
            stmt = select(TMEntry).where(
                TMEntry.project_id == 1,
                TMEntry.kind == "term_cluster",
            )
            all_tm_entries = session.execute(stmt).scalars().all()

            with open("debug_terms_test.txt", "a", encoding="utf-8") as f:
                f.write("\nDEBUG TM entries before refresh:\n")
                f.write(f"  count: {len(all_tm_entries)}\n")
                for tm in all_tm_entries:
                    f.write("  TM entry:\n")
                    f.write(f"    src_text: {tm.src_text}\n")
                    f.write(f"    src_norm: {tm.src_norm}\n")
                    f.write(f"    translation: {tm.translation}\n")
                    f.write(f"    status: {tm.status}\n")
                    f.write(f"    project_id: {tm.project_id}\n")

        # STEP 3: Simulate Refresh button click
        # This should reload translations from DB
        # NOTE: Don't save reference to clusters - get from model each time

        # DEBUG: Test bulk_resolve directly
        from app.services.translation_service import TranslationService

        translation_service = TranslationService()

        with self.db_service.get_session() as session:
            items = [(terms_view.terms_model.clusters[0].representative_he, "term_cluster")]
            direct_results = translation_service.bulk_resolve(
                session,
                items,
                src_lang="he",
                tgt_lang="ru",
                project_id=1,
                allow_draft=False,
            )

            with open("debug_terms_test.txt", "a", encoding="utf-8") as f:
                f.write("\nDEBUG bulk_resolve direct call:\n")
                f.write(f"  items: {items}\n")
                f.write(f"  results count: {len(direct_results)}\n")
                for key, value in direct_results.items():
                    f.write(f"  key: {key}\n")
                    f.write(f"  translation: {value.translation}\n")
                    f.write(f"  source: {value.source}\n")

        # DEBUG: Log clusters before worker
        with open("debug_terms_test.txt", "a", encoding="utf-8") as f:
            f.write("\nDEBUG before worker:\n")
            f.write(f"  project_id: {terms_view.project_id}\n")
            f.write(f"  clusters count: {len(terms_view.terms_model.clusters)}\n")
            if terms_view.terms_model.clusters:
                c = terms_view.terms_model.clusters[0]
                f.write(f"  cluster[0].representative_he: {c.representative_he}\n")
                f.write(f"  cluster[0].canonical_key: {c.canonical_key}\n")

        # STEP 3b: Call bulk_resolve directly and update model
        # This tests our fix in models_qt.py without QThread complications
        from app.services.translation_service import TranslationService

        translation_svc = TranslationService()

        with self.db_service.get_session() as session:
            # Build items list (same way worker does) - get clusters from model!
            items = [
                (cluster.representative_he, "term_cluster")
                for cluster in terms_view.terms_model.clusters
            ]

            # Call bulk_resolve
            results = translation_svc.bulk_resolve(
                session,
                items,
                src_lang="he",
                tgt_lang="ru",
                project_id=1,
                allow_draft=False,
            )

            # DEBUG: Log what we're passing to update_translations
            with open("debug_terms_test.txt", "a", encoding="utf-8") as f:
                f.write("\nDEBUG calling update_translations:\n")
                f.write(f"  results keys: {list(results.keys())}\n")
                f.write(
                    f"  model.clusters[0].representative_he: {terms_view.terms_model.clusters[0].representative_he}\n"
                )
                for key, value in results.items():
                    f.write(f"  result key: {key}\n")
                    f.write(f"    translation: {value.translation}\n")

            # Update model with results (THIS TESTS OUR FIX!)
            terms_view.terms_model.update_translations(results)

            # DEBUG: Check if model was updated
            with open("debug_terms_test.txt", "a", encoding="utf-8") as f:
                f.write("\nDEBUG after update_translations:\n")
                f.write(
                    f"  cluster.translation: {terms_view.terms_model.clusters[0].translation}\n"
                )
                f.write(
                    f"  cluster.translation_status: {terms_view.terms_model.clusters[0].translation_status}\n"
                )

        # STEP 4: Verify translation is still present after refresh
        refreshed_cluster = terms_view.terms_model.clusters[0]

        # DEBUG: Append to file
        with open("debug_terms_test.txt", "a", encoding="utf-8") as f:
            f.write("\nDEBUG after refresh:\n")
            f.write(f"  representative_he: {refreshed_cluster.representative_he}\n")
            f.write(f"  canonical_key: {refreshed_cluster.canonical_key}\n")
            f.write(f"  translation: {refreshed_cluster.translation}\n")
            f.write(f"  translation_status: {refreshed_cluster.translation_status}\n")

        # THIS IS THE BUG ASSERTION - translation should NOT disappear
        self.assertEqual(
            refreshed_cluster.translation,
            translation_value,
            "Translation should persist after Refresh (BUG: it disappears!)",
        )

        self.assertEqual(
            refreshed_cluster.translation_status,
            "approved",
            "Status should remain 'approved' after Refresh (BUG: returns to None!)",
        )

        # Clean up
        terms_view.close()
        terms_view.deleteLater()


if __name__ == "__main__":
    unittest.main()
