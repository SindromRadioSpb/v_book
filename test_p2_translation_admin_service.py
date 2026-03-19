"""P2 Translation Admin Service Tests.

Tests all service operations for TM entry management:
- Search with filters
- Status changes (approve/reject/deprecate)
- History and revert
- Bulk operations
"""

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class TestTranslationAdminService(unittest.TestCase):
    """Test Translation Admin Service."""

    @classmethod
    def setUpClass(cls):
        """Create test database with M7 schema."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply schema
        from app.services.db_service import DBService

        DBService.initialize(cls.test_db.name)

        # Apply M7 + P2 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(
            encoding="utf-8"
        )
        migration_p2_revert_origin = Path("schema/006_p2_add_revert_origin.sql").read_text(
            encoding="utf-8"
        )
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.executescript(migration_p2_revert_origin)
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
        """Clean TM entries before each test."""
        from app.infra.sa_models import TMEntry, TMEntryHistory

        with self.db_service.get_session() as session:
            session.query(TMEntryHistory).delete()
            session.query(TMEntry).delete()
            session.commit()

    def test_search_filters_origin_and_source_ref(self):
        """Test search with origin and source_ref filters."""
        from app.infra.sa_models import TMEntry
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create test entries with different origins
        with self.db_service.get_session() as session:
            entries = [
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
                    source_ref="ui_test",
                ),
                TMEntry(
                    project_id=1,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="ספר",
                    src_norm="ספר",
                    translation="книга",
                    status="approved",
                    origin="import",
                    source_ref="dict_import",
                ),
            ]
            for entry in entries:
                session.add(entry)
            session.commit()

        # Test origin filter
        with self.db_service.get_session() as session:
            results = service.search_tm_entries(
                session,
                filters={"origin": "user_edit"},
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].origin, "user_edit")

        # Test source_ref filter
        with self.db_service.get_session() as session:
            results = service.search_tm_entries(
                session,
                filters={"source_ref": "dict_import"},
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].source_ref, "dict_import")

    def test_scope_filter_project_vs_global(self):
        """Test scope filter for project vs global TM entries."""
        from app.infra.sa_models import TMEntry
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create project and global entries
        with self.db_service.get_session() as session:
            entries = [
                TMEntry(
                    project_id=1,  # Project-scoped
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
                    project_id=None,  # Global
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="ספר",
                    src_norm="ספר",
                    translation="книга",
                    status="approved",
                    origin="import",
                ),
            ]
            for entry in entries:
                session.add(entry)
            session.commit()

        # Test global scope
        with self.db_service.get_session() as session:
            results = service.search_tm_entries(
                session,
                filters={"scope": "global"},
            )
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0].project_id)

        # Test project scope
        with self.db_service.get_session() as session:
            results = service.search_tm_entries(
                session,
                filters={"scope": "project", "project_id": 1},
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].project_id, 1)

    def test_set_status_approve_sets_approved_at(self):
        """Test that approve sets approved_at and approved_by."""
        from app.infra.sa_models import TMEntry
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create draft entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом",
                status="draft",
                origin="user_edit",
            )
            session.add(entry)
            session.commit()
            tm_id = entry.tm_id

        # Approve it
        with self.db_service.get_session() as session:
            service.set_status(session, tm_id, "approved", approved_by="test_user")

        # Verify
        with self.db_service.get_session() as session:
            entry = session.query(TMEntry).filter(TMEntry.tm_id == tm_id).one()
            self.assertEqual(entry.status, "approved")
            self.assertIsNotNone(entry.approved_at)
            self.assertEqual(entry.approved_by, "test_user")

    def test_set_status_reject_clears_approved_at(self):
        """Test that reject/deprecate clears approved_at and approved_by."""
        from app.infra.sa_models import TMEntry
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create approved entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом",
                status="approved",
                origin="user_edit",
                approved_at=datetime.now(),
                approved_by="original_user",
            )
            session.add(entry)
            session.commit()
            tm_id = entry.tm_id

        # Reject it
        with self.db_service.get_session() as session:
            service.set_status(session, tm_id, "rejected")

        # Verify approved_at/by cleared
        with self.db_service.get_session() as session:
            entry = session.query(TMEntry).filter(TMEntry.tm_id == tm_id).one()
            self.assertEqual(entry.status, "rejected")
            self.assertIsNone(entry.approved_at)
            self.assertIsNone(entry.approved_by)

    def test_update_translation_creates_history(self):
        """Test that update_translation creates history entry."""
        from app.infra.sa_models import TMEntry, TMEntryHistory
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом",
                status="approved",
                origin="user_edit",
            )
            session.add(entry)
            session.commit()
            tm_id = entry.tm_id

        # Update translation
        with self.db_service.get_session() as session:
            service.update_translation(session, tm_id, "новый дом", notes="Updated translation")

        # Check history created
        with self.db_service.get_session() as session:
            history = session.query(TMEntryHistory).filter(TMEntryHistory.tm_id == tm_id).all()
            self.assertGreater(len(history), 0)
            self.assertEqual(history[0].change_kind, "edit")

        # Check translation updated
        with self.db_service.get_session() as session:
            entry = session.query(TMEntry).filter(TMEntry.tm_id == tm_id).one()
            self.assertEqual(entry.translation, "новый дом")
            self.assertEqual(entry.notes, "Updated translation")

    def test_revert_sets_origin_revert_and_restores_translation(self):
        """Test that revert restores translation and sets origin='revert'."""
        from app.infra.sa_models import TMEntry, TMEntryHistory
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="בית",
                src_norm="בית",
                translation="дом",
                status="approved",
                origin="user_edit",
            )
            session.add(entry)
            session.commit()
            tm_id = entry.tm_id

        # Update it (creates version 1)
        with self.db_service.get_session() as session:
            service.update_translation(session, tm_id, "новый дом")

        # Update again (creates version 2)
        with self.db_service.get_session() as session:
            service.update_translation(session, tm_id, "другой дом")

        # Revert to version 2 (which has "новый дом")
        with self.db_service.get_session() as session:
            service.revert(session, tm_id, version=2, approved_by="test_user")

        # Verify reverted
        with self.db_service.get_session() as session:
            entry = session.query(TMEntry).filter(TMEntry.tm_id == tm_id).one()
            self.assertEqual(entry.translation, "новый дом")  # Version 2 translation
            self.assertEqual(
                entry.origin, "user_edit"
            )  # P2 FIX: origin uses 'user_edit' (history tracks revert)

        # Check history has revert entry
        with self.db_service.get_session() as session:
            history = (
                session.query(TMEntryHistory)
                .filter(TMEntryHistory.tm_id == tm_id, TMEntryHistory.change_kind == "revert")
                .all()
            )
            self.assertGreater(len(history), 0)

    def test_bulk_set_status_transactional(self):
        """Test that bulk_set_status is transactional."""
        from app.infra.sa_models import TMEntry
        from app.services.translation_admin_service import TranslationAdminService

        service = TranslationAdminService()

        # Create multiple entries
        with self.db_service.get_session() as session:
            entries = [
                TMEntry(
                    project_id=1,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"word{i}",
                    src_norm=f"word{i}",
                    translation=f"перевод{i}",
                    status="draft",
                    origin="user_edit",
                )
                for i in range(3)
            ]
            for entry in entries:
                session.add(entry)
            session.commit()
            tm_ids = [e.tm_id for e in entries]

        # Bulk approve
        with self.db_service.get_session() as session:
            count = service.bulk_set_status(session, tm_ids, "approved", approved_by="bulk_test")
            self.assertEqual(count, 3)

        # Verify all approved
        with self.db_service.get_session() as session:
            entries = session.query(TMEntry).filter(TMEntry.tm_id.in_(tm_ids)).all()
            for entry in entries:
                self.assertEqual(entry.status, "approved")
                self.assertIsNotNone(entry.approved_at)
                self.assertEqual(entry.approved_by, "bulk_test")


if __name__ == "__main__":
    unittest.main()
