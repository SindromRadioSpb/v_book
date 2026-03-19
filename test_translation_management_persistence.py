"""Regression tests for Translation Management persistence.

Tests that:
1. Inline edits in Translation Management save to DB
2. Approve Selected doesn't reset translation
3. View History shows correct changes
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.services.db_service import DBService


class TestTranslationManagementPersistence(unittest.TestCase):
    """Test Translation Management inline edit persistence."""

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
                name="TM Test Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

        # Create fixture TM entries
        cls._create_tm_entries()

        # Create QApplication for headless testing
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @classmethod
    def _create_tm_entries(cls):
        """Create fixture TM entries."""
        from app.infra.sa_models import TMEntry

        with cls.db_service.get_session() as session:
            # Lemma entry
            lemma_entry = TMEntry(
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="ספר",
                src_norm="ספר",
                translation="книга",
                status="draft",
                origin="import",
            )
            session.add(lemma_entry)

            # Term cluster entry
            term_entry = TMEntry(
                project_id=1,
                kind="term_cluster",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית ספר",
                src_norm="בית_ספר",
                translation="школа",
                status="draft",
                origin="import",
            )
            session.add(term_entry)

            session.commit()

            cls.lemma_tm_id = lemma_entry.tm_id
            cls.term_tm_id = term_entry.tm_id

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def test_inline_edit_persists(self):
        """Test that inline translation edit saves to DB and persists after reload.

        Regression test for bug where inline edits disappeared.
        """
        from sqlalchemy import select

        from app.infra.sa_models import TMEntry
        from app.ui.translation_management_panel import TranslationManagementPanel

        # Create panel
        panel = TranslationManagementPanel(project_id=1)

        # Load entries synchronously (avoid async worker issues in tests)
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        with self.db_service.get_session() as session:
            entries = service.search_tm_entries(
                session, filters={"scope": "project", "project_id": 1}, limit=100, offset=0
            )

        panel.model.update_entries(entries, len(entries))
        QApplication.processEvents()

        # Find lemma entry in model
        lemma_row = None
        for row in range(panel.model.rowCount()):
            entry = panel.model.get_entry(row)
            if entry.tm_id == self.lemma_tm_id:
                lemma_row = row
                break

        self.assertIsNotNone(lemma_row, "Lemma entry should be in model")

        # Edit translation inline
        new_translation = "новая книга"
        model_index = panel.model.index(lemma_row, 3)  # Translation column

        success = panel.model.setData(model_index, new_translation, Qt.ItemDataRole.EditRole)
        self.assertTrue(success, "setData should succeed")

        # Process events to ensure on_translation_edited executes
        QApplication.processEvents()

        # Verify saved in DB
        with self.db_service.get_session() as session:
            stmt = select(TMEntry).where(TMEntry.tm_id == self.lemma_tm_id)
            entry = session.execute(stmt).scalar()

            self.assertIsNotNone(entry)
            self.assertEqual(
                entry.translation, new_translation, "Translation should be saved in DB"
            )

        # Reload panel (simulate closing and reopening)
        panel.close()
        panel.deleteLater()

        panel2 = TranslationManagementPanel(project_id=1)

        # Load entries again
        with self.db_service.get_session() as session:
            entries = service.search_tm_entries(
                session, filters={"scope": "project", "project_id": 1}, limit=100, offset=0
            )

        panel2.model.update_entries(entries, len(entries))
        QApplication.processEvents()

        # Find entry again
        lemma_row2 = None
        for row in range(panel2.model.rowCount()):
            entry = panel2.model.get_entry(row)
            if entry.tm_id == self.lemma_tm_id:
                lemma_row2 = row
                break

        self.assertIsNotNone(lemma_row2, "Entry should still be in model")
        entry2 = panel2.model.get_entry(lemma_row2)

        # CRITICAL: Translation should persist
        self.assertEqual(
            entry2.translation, new_translation, "Translation should persist after reload"
        )

        panel2.close()
        panel2.deleteLater()

    def test_approve_selected_does_not_reset_translation(self):
        """Test that Approve Selected doesn't reset edited translation.

        Regression test for bug where approving reset translation to old value.
        """
        from sqlalchemy import select

        from app.infra.sa_models import TMEntry
        from app.ui.translation_management_panel import TranslationManagementPanel

        # Create panel
        panel = TranslationManagementPanel(project_id=1)

        # Load entries
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        with self.db_service.get_session() as session:
            entries = service.search_tm_entries(
                session, filters={"scope": "project", "project_id": 1}, limit=100, offset=0
            )

        panel.model.update_entries(entries, len(entries))
        QApplication.processEvents()

        # Find term entry
        term_row = None
        for row in range(panel.model.rowCount()):
            entry = panel.model.get_entry(row)
            if entry.tm_id == self.term_tm_id:
                term_row = row
                break

        self.assertIsNotNone(term_row, "Term entry should be in model")

        # Edit translation
        new_translation = "большая школа"
        model_index = panel.model.index(term_row, 3)

        panel.model.setData(model_index, new_translation, Qt.ItemDataRole.EditRole)
        QApplication.processEvents()

        # Select row
        panel.table_view.selectRow(term_row)

        # Approve selected (should NOT reset translation)
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        with self.db_service.get_session() as session:
            service.bulk_set_status(session, [self.term_tm_id], "approved", approved_by="test_user")

        # Verify in DB
        with self.db_service.get_session() as session:
            stmt = select(TMEntry).where(TMEntry.tm_id == self.term_tm_id)
            entry = session.execute(stmt).scalar()

            # CRITICAL: Translation should NOT be reset
            self.assertEqual(
                entry.translation, new_translation, "Translation should not be reset by approve"
            )
            self.assertEqual(entry.status, "approved", "Status should be approved")

        panel.close()
        panel.deleteLater()

    def test_view_history_records_changes(self):
        """Test that View History shows translation edits and status changes.

        Regression test for history not recording inline edits.
        """

        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Edit translation (creates history)
        with self.db_service.get_session() as session:
            service.update_translation(session, self.lemma_tm_id, "измененная книга")

        # Approve (creates history)
        with self.db_service.get_session() as session:
            service.set_status(session, self.lemma_tm_id, "approved", approved_by="test_user")

        # Get history
        with self.db_service.get_session() as session:
            history = service.get_history(session, self.lemma_tm_id)

        # Should have at least 2 entries (edit + approve)
        self.assertGreaterEqual(len(history), 2, "History should record both edit and approve")

        # Check that history contains correct change kinds
        change_kinds = [h.change_kind for h in history]
        self.assertIn("edit", change_kinds, "History should record edit")
        self.assertIn("approve", change_kinds, "History should record approve")

        # Check that latest entry has correct translation
        latest = history[0]  # Assuming newest first
        self.assertEqual(
            latest.translation, "измененная книга", "History should record correct translation"
        )


if __name__ == "__main__":
    unittest.main()
