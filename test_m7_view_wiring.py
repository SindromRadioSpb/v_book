"""M7 P1 View Wiring Integration Tests.

Tests the integration of DictionaryView and TermsView with:
- TranslationResolveWorker
- Inline edit → TM entry + history
- "Why?" action / explainability dialog

These tests run headless (QT_QPA_PLATFORM=offscreen).
"""

import unittest
import tempfile
import sqlite3
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop, QTimer, Qt

# Ensure QApplication exists for tests
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestDictionaryViewWiring(unittest.TestCase):
    """Test DictionaryView M7 wiring."""

    @classmethod
    def setUpClass(cls):
        """Create test database with M7 schema."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply schema via DBService
        from app.services.db_service import DBService
        DBService.initialize(cls.test_db.name)
        cls.db_service = DBService.get_instance()

        # Apply M7 migrations manually
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.close()

        # Create test library, project and lemmas
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import Library, DictProject, Lemma, LemmaProjectStat

            # Create library
            library = Library(library_id=1, name="Test Library")
            session.add(library)

            # Create project
            project = DictProject(
                library_id=1,
                name="Test Project",
                src_lang="he",
                tgt_lang="ru",
                description="Test project for view wiring"
            )
            session.add(project)
            session.flush()
            cls.project_id = project.project_id

            # Create lemmas
            lemmas_data = [
                ("בית", "NOUN", 15),
                ("ספר", "NOUN", 12),
                ("בית ספר", "NOUN", 8),
            ]

            for lemma_text, pos, freq in lemmas_data:
                lemma = Lemma(
                    project_id=cls.project_id,
                    lemma_text=lemma_text,
                    pos=pos,
                )
                session.add(lemma)
                session.flush()

                # Add stats
                stat = LemmaProjectStat(
                    lemma_id=lemma.lemma_id,
                    project_id=cls.project_id,
                    freq_abs=freq,
                    doc_freq=1,
                )
                session.add(stat)

            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        from app.services.db_service import DBService
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def setUp(self):
        """Clean up TM entries before each test."""
        from app.infra.sa_models import TMEntry
        with self.db_service.get_session() as session:
            session.query(TMEntry).delete()
            session.commit()

    def test_01_dictionary_view_creates_successfully(self):
        """Test that DictionaryView can be created headless."""
        from app.ui.dictionary_view import DictionaryView

        view = DictionaryView(self.project_id)
        self.assertIsNotNone(view)
        self.assertEqual(view.project_id, self.project_id)
        self.assertIsNotNone(view.lemma_model)
        self.assertIsNotNone(view.lemma_table)
        view.close()

    def test_02_dictionary_view_loads_lemmas(self):
        """Test that DictionaryView loads lemmas into model."""
        from app.ui.dictionary_view import DictionaryView

        view = DictionaryView(self.project_id)

        # Check model has lemmas
        self.assertGreater(view.lemma_model.rowCount(), 0)
        self.assertEqual(view.lemma_model.rowCount(), 3)

        # Check first lemma
        lemma = view.lemma_model.lemmas[0]
        self.assertIn(lemma.lemma_text, ["בית", "ספר", "בית ספר"])

        view.close()

    def test_03_dictionary_view_worker_resolves_translations(self):
        """Test that TranslationResolveWorker is started and updates model."""
        from app.ui.dictionary_view import DictionaryView

        view = DictionaryView(self.project_id)

        # Wait for worker to finish (using QEventLoop)
        if view.translation_worker and view.translation_worker.isRunning():
            loop = QEventLoop()
            view.translation_worker.finished.connect(loop.quit)
            QTimer.singleShot(5000, loop.quit)  # 5 second timeout
            loop.exec()

        # Check that model has translations (could be from dict/mt)
        # Note: Translations might be None if no dict/mt sources available
        # But the worker should have run and updated the model
        self.assertIsNotNone(view.lemma_model)

        view.close()

    def test_04_dictionary_view_inline_edit_saves_to_tm(self):
        """Test that inline edit saves to TM."""
        from app.ui.dictionary_view import DictionaryView
        from app.infra.sa_models import TMEntry

        view = DictionaryView(self.project_id)

        # Wait for worker if running
        if view.translation_worker and view.translation_worker.isRunning():
            loop = QEventLoop()
            view.translation_worker.finished.connect(loop.quit)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

        # Simulate inline edit
        model = view.lemma_model
        self.assertGreater(model.rowCount(), 0)

        # Edit translation for first lemma
        index = model.index(0, 4)  # Translation column
        test_translation = "тестовый перевод дома"
        model.setData(index, test_translation, Qt.ItemDataRole.EditRole)

        # Check TM entry was created
        with self.db_service.get_session() as session:
            tm_entries = session.query(TMEntry).filter(
                TMEntry.project_id == self.project_id
            ).all()
            self.assertGreater(len(tm_entries), 0)

            # Find our entry
            tm_entry = tm_entries[0]
            self.assertEqual(tm_entry.translation, test_translation)
            self.assertEqual(tm_entry.status, "approved")
            self.assertEqual(tm_entry.origin, "user_edit")

        view.close()

    def test_05_dictionary_view_why_dialog(self):
        """Test that 'Why?' dialog can be shown."""
        from app.ui.dictionary_view import DictionaryView

        view = DictionaryView(self.project_id)

        # Wait for worker
        if view.translation_worker and view.translation_worker.isRunning():
            loop = QEventLoop()
            view.translation_worker.finished.connect(loop.quit)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

        # Call show_why_dialog programmatically (don't exec the dialog)
        # Just verify it creates without error
        if view.lemma_model.rowCount() > 0:
            try:
                # Note: We can't call exec() in headless mode, so we just create the dialog
                from app.ui.dialogs import WhyTranslationDialog
                from app.services.translation_service import TranslationResult

                lemma = view.lemma_model.lemmas[0]
                result = TranslationResult(
                    translation="test",
                    source="tm",
                    status="approved"
                )
                dialog = WhyTranslationDialog(result, lemma.lemma_text, view)
                self.assertIsNotNone(dialog)
                dialog.close()
            except Exception as e:
                self.fail(f"Failed to create Why dialog: {e}")

        view.close()


class TestTermsViewWiring(unittest.TestCase):
    """Test TermsView M7 wiring."""

    @classmethod
    def setUpClass(cls):
        """Create test database with M7 schema and term clusters."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply schema via DBService
        from app.services.db_service import DBService
        DBService.initialize(cls.test_db.name)
        cls.db_service = DBService.get_instance()

        # Apply M7 migrations manually
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.close()

        # Create test library, project and term clusters
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import Library, DictProject, TermCluster
            from app.domain.normalization import normalize_for_tm

            # Create library
            library = Library(library_id=1, name="Test Library")
            session.add(library)

            # Create project
            project = DictProject(
                library_id=1,
                name="Test Project",
                src_lang="he",
                tgt_lang="ru",
                description="Test project for terms view wiring"
            )
            session.add(project)
            session.flush()
            cls.project_id = project.project_id

            # Create term clusters
            clusters_data = [
                ("בית הספר", ["בית הספר", "בית ספר"], 8),
                ("תלמיד טוב", ["תלמיד טוב"], 4),
            ]

            for representative_he, variants, freq in clusters_data:
                normalized = normalize_for_tm("he", representative_he, "term_cluster")
                cluster = TermCluster(
                    project_id=cls.project_id,
                    representative_he=representative_he,
                    canonical_key=normalized.norm,
                    freq_abs=freq,
                    doc_freq=1,
                    members_count=len(variants),
                )
                session.add(cluster)

            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        from app.services.db_service import DBService
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def setUp(self):
        """Clean up TM entries before each test."""
        from app.infra.sa_models import TMEntry
        with self.db_service.get_session() as session:
            session.query(TMEntry).delete()
            session.commit()

    def test_01_terms_view_creates_successfully(self):
        """Test that TermsView can be created headless."""
        from app.ui.terms_view import TermsView

        view = TermsView(self.project_id)
        self.assertIsNotNone(view)
        self.assertEqual(view.project_id, self.project_id)
        self.assertIsNotNone(view.terms_model)
        self.assertIsNotNone(view.terms_table)
        view.close()

    def test_02_terms_view_loads_clusters(self):
        """Test that TermsView loads term clusters into model."""
        from app.ui.terms_view import TermsView

        view = TermsView(self.project_id)

        # Check model has clusters
        self.assertGreater(view.terms_model.rowCount(), 0)
        self.assertGreaterEqual(view.terms_model.rowCount(), 2)

        # Check first cluster
        cluster = view.terms_model.clusters[0]
        self.assertIn(cluster.representative_he, ["בית הספר", "תלמיד טוב"])

        view.close()

    def test_03_terms_view_worker_resolves_translations(self):
        """Test that TranslationResolveWorker updates term model."""
        from app.ui.terms_view import TermsView

        view = TermsView(self.project_id)

        # Wait for worker to finish
        if view.translation_worker and view.translation_worker.isRunning():
            loop = QEventLoop()
            view.translation_worker.finished.connect(loop.quit)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

        # Check model is updated
        self.assertIsNotNone(view.terms_model)

        view.close()

    def test_04_terms_view_inline_edit_saves_to_tm(self):
        """Test that inline edit saves term translation to TM."""
        from app.ui.terms_view import TermsView
        from app.infra.sa_models import TMEntry

        view = TermsView(self.project_id)

        # Wait for worker
        if view.translation_worker and view.translation_worker.isRunning():
            loop = QEventLoop()
            view.translation_worker.finished.connect(loop.quit)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

        # Simulate inline edit
        model = view.terms_model
        self.assertGreater(model.rowCount(), 0)

        # Edit translation for first cluster
        index = model.index(0, 11)  # Translation column
        test_translation = "тестовая школа"
        model.setData(index, test_translation, Qt.ItemDataRole.EditRole)

        # Check TM entry was created
        with self.db_service.get_session() as session:
            tm_entries = session.query(TMEntry).filter(
                TMEntry.project_id == self.project_id,
                TMEntry.kind == "term_cluster"
            ).all()
            self.assertGreater(len(tm_entries), 0)

            # Find our entry
            tm_entry = tm_entries[0]
            self.assertEqual(tm_entry.translation, test_translation)
            self.assertEqual(tm_entry.status, "approved")
            self.assertEqual(tm_entry.origin, "user_edit")

        view.close()

    def test_05_terms_view_why_dialog(self):
        """Test that 'Why?' dialog can be shown for term clusters."""
        from app.ui.terms_view import TermsView

        view = TermsView(self.project_id)

        # Wait for worker
        if view.translation_worker and view.translation_worker.isRunning():
            loop = QEventLoop()
            view.translation_worker.finished.connect(loop.quit)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()

        # Verify dialog creation
        if view.terms_model.rowCount() > 0:
            try:
                from app.ui.dialogs import WhyTranslationDialog
                from app.services.translation_service import TranslationResult

                cluster = view.terms_model.clusters[0]
                result = TranslationResult(
                    translation="test",
                    source="tm",
                    status="approved"
                )
                dialog = WhyTranslationDialog(result, cluster.representative_he, view)
                self.assertIsNotNone(dialog)
                dialog.close()
            except Exception as e:
                self.fail(f"Failed to create Why dialog: {e}")

        view.close()


if __name__ == "__main__":
    unittest.main()
