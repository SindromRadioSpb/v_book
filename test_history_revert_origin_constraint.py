"""Regression test for History Revert origin constraint fix.

Tests that:
1. Revert operation doesn't crash with IntegrityError
2. Reverted entry has valid origin ('user_edit')
3. History correctly records revert action (change_kind='revert')

Bug: Code was setting origin='revert' which violates CHECK constraint.
Fix: Use origin='user_edit' instead (history still tracks revert via change_kind).
"""

import unittest
import tempfile
import sqlite3
import os
from pathlib import Path
from datetime import datetime

from app.services.db_service import DBService


class TestHistoryRevertOriginConstraint(unittest.TestCase):
    """Test that History Revert doesn't violate origin constraint."""

    @classmethod
    def setUpClass(cls):
        """Create test database."""
        # Create test DB
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        DBService.initialize(cls.test_db.name)

        # Apply migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')
        migration_p2 = Path("schema/006_p2_add_revert_origin.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.executescript(migration_p2)
        con.close()

        cls.db_service = DBService.get_instance()

        # Create test project
        with cls.db_service.get_session() as session:
            from app.infra.sa_models import Library, DictProject

            library = Library(library_id=1, name="Test Library")
            session.add(library)

            project = DictProject(
                project_id=1,
                library_id=1,
                name="Revert Test Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def test_revert_uses_valid_origin(self):
        """Test that revert operation uses 'user_edit' origin, not 'revert'.

        Regression test for IntegrityError bug where code tried to set
        origin='revert' which violates CHECK constraint.
        """
        from app.services.translation_admin_service import TranslationAdminService
        from app.infra.sa_models import TMEntry, TMEntryHistory
        from sqlalchemy import select

        service = TranslationAdminService()

        # Create TM entry with initial translation
        with self.db_service.get_session() as session:
            entry = TMEntry(
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="ספר",
                src_norm="ספר",
                translation="книга",
                status="approved",
                origin="import",
            )
            session.add(entry)
            session.commit()
            tm_id = entry.tm_id

        # Edit translation (creates history)
        with self.db_service.get_session() as session:
            service.update_translation(
                session,
                tm_id,
                "новая книга"
            )

        # Edit again (creates second version)
        with self.db_service.get_session() as session:
            service.update_translation(
                session,
                tm_id,
                "другая книга"
            )

        # Get history to find version to revert to
        with self.db_service.get_session() as session:
            history = service.get_history(session, tm_id)
            # Should have at least 2 versions
            self.assertGreaterEqual(len(history), 2, "Should have multiple versions")

            # Find version with "новая книга"
            target_version = None
            for h in history:
                if h.translation == "новая книга":
                    target_version = h.version
                    break

            self.assertIsNotNone(target_version, "Should find version to revert to")

        # CRITICAL TEST: Revert should NOT crash with IntegrityError
        try:
            with self.db_service.get_session() as session:
                service.revert(
                    session,
                    tm_id=tm_id,
                    version=target_version,
                    approved_by="test_user"
                )
        except sqlite3.IntegrityError as e:
            self.fail(f"Revert crashed with IntegrityError: {e}")

        # Verify entry has valid origin
        with self.db_service.get_session() as session:
            stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
            entry = session.execute(stmt).scalar()

            self.assertIsNotNone(entry)
            # P2 FIX: Should be 'user_edit', not 'revert'
            self.assertEqual(
                entry.origin,
                "user_edit",
                "Reverted entry should have valid origin 'user_edit'"
            )

            # Verify translation was reverted
            self.assertEqual(
                entry.translation,
                "новая книга",
                "Translation should be reverted to target version"
            )

        # Verify history correctly records revert action
        with self.db_service.get_session() as session:
            history = service.get_history(session, tm_id)

            # Find revert entry in history
            revert_entries = [h for h in history if h.change_kind == "revert"]
            self.assertGreater(
                len(revert_entries),
                0,
                "History should contain revert action"
            )

            # Latest entry should be the revert
            latest = history[0]  # Assuming newest first
            self.assertEqual(
                latest.change_kind,
                "revert",
                "Latest history entry should be revert action"
            )

    def test_revert_tm_entry_uses_valid_origin(self):
        """Test TranslationService.revert_tm_entry also uses valid origin.

        Tests the second revert method location.
        """
        from app.services.translation_service import TranslationService
        from app.infra.sa_models import TMEntry, TMEntryHistory
        from sqlalchemy import select

        service = TranslationService()

        # Create TM entry
        with self.db_service.get_session() as session:
            entry = TMEntry(
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
            session.add(entry)
            session.commit()
            tm_id = entry.tm_id

        # Create history by updating entry
        with self.db_service.get_session() as session:
            entry = session.get(TMEntry, tm_id)
            entry.translation = "большая школа"
            entry.status = "approved"

            # Create history entry manually
            history = TMEntryHistory(
                tm_id=tm_id,
                version=1,
                translation="школа",
                notes=None,
                status="draft",
                origin="import",
                change_kind="edit",
            )
            session.add(history)
            session.commit()

        # Revert to version 1
        try:
            with self.db_service.get_session() as session:
                success = service.revert_tm_entry(
                    session,
                    tm_id=tm_id,
                    target_version=1,
                    actor="test_user"
                )
                self.assertTrue(success, "Revert should succeed")
        except sqlite3.IntegrityError as e:
            self.fail(f"revert_tm_entry crashed with IntegrityError: {e}")

        # Verify entry has valid origin
        with self.db_service.get_session() as session:
            stmt = select(TMEntry).where(TMEntry.tm_id == tm_id)
            entry = session.execute(stmt).scalar()

            self.assertIsNotNone(entry)
            self.assertEqual(
                entry.origin,
                "user_edit",
                "Reverted entry should have valid origin 'user_edit'"
            )

            # Verify translation was reverted
            self.assertEqual(
                entry.translation,
                "школа",
                "Translation should be reverted to version 1"
            )

        # Verify history contains revert action
        with self.db_service.get_session() as session:
            stmt = select(TMEntryHistory).where(
                TMEntryHistory.tm_id == tm_id,
                TMEntryHistory.change_kind == "revert"
            )
            revert_history = session.execute(stmt).scalars().all()

            self.assertGreater(
                len(revert_history),
                0,
                "History should contain revert action"
            )


if __name__ == "__main__":
    unittest.main()
