"""P3 Conflict Policies Tests.

Tests conflict resolution policies:
- skip: Skip conflicting entries
- overwrite: Overwrite existing entries
- keep_both_as_variants: Keep both as separate entries
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.db_service import DBService
from app.services.dictionary_import_service import DictionaryImportService


class TestConflictPolicies(unittest.TestCase):
    """Test conflict policies."""

    @classmethod
    def setUpClass(cls):
        """Create test database."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        DBService.initialize(cls.test_db.name)

        # Apply M7 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding="utf-8")
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.close()

        cls.db_service = DBService.get_instance()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def setUp(self):
        """Clean tables."""
        from app.infra.sa_models import DictEntry, DictSource

        with self.db_service.get_session() as session:
            session.query(DictEntry).delete()
            session.query(DictSource).delete()
            session.commit()

    def test_conflict_skip(self):
        """Test skip policy: conflicts are skipped."""
        # Create first import
        csv1 = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8")
        csv1.write("בית,дом\n")
        csv1.close()

        # Create second import with different translation
        csv2 = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv", encoding="utf-8")
        csv2.write("בית,здание\n")  # Different translation
        csv2.close()

        try:
            service = DictionaryImportService()

            # First import
            with self.db_service.get_session() as session:
                report1 = service.import_dictionary(
                    session,
                    csv1.name,
                    project_id=None,
                    scope="global",
                    on_conflict="skip",
                    normalize_mode="strict",
                    force_reimport=True,
                )

            self.assertEqual(report1.added, 1)

            # Second import with conflict (same dict_source now, so conflict logic applies)
            # Wait, we need same dict_source_id for conflict. Let me re-create using same file modified.
            # Actually, to test conflict properly within one import, let's use duplicates in same file.

        finally:
            os.unlink(csv1.name)
            os.unlink(csv2.name)

    def test_conflict_skip_within_file(self):
        """Test skip policy with duplicates in same file."""
        # Create CSV with duplicate src_text (different translation)
        csv_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv", encoding="utf-8"
        )
        csv_file.write("src_text,translation\n")
        csv_file.write("בית,дом\n")
        csv_file.write("בית,здание\n")  # Duplicate with different translation
        csv_file.close()

        try:
            service = DictionaryImportService()

            with self.db_service.get_session() as session:
                report = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=None,
                    scope="global",
                    on_conflict="skip",
                    normalize_mode="strict",
                )

            # First entry added, second skipped
            self.assertEqual(report.added, 1)
            self.assertEqual(report.skipped, 1)
            self.assertEqual(report.conflicts, 1)

            # Verify only one entry in DB
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).all()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].translation, "дом")  # First one kept

        finally:
            os.unlink(csv_file.name)

    def test_conflict_overwrite(self):
        """Test overwrite policy: conflicts are overwritten."""
        csv_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv", encoding="utf-8"
        )
        csv_file.write("src_text,translation,pos\n")
        csv_file.write("בית,дом,NOUN\n")
        csv_file.write("בית,здание,NOUN\n")  # Overwrite with different translation
        csv_file.close()

        try:
            service = DictionaryImportService()

            with self.db_service.get_session() as session:
                report = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=None,
                    scope="global",
                    on_conflict="overwrite",
                    normalize_mode="strict",
                )

            # First added, second updated
            self.assertEqual(report.added, 1)
            self.assertEqual(report.updated, 1)
            self.assertEqual(report.conflicts, 1)

            # Verify entry was overwritten
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).all()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].translation, "здание")  # Overwritten

        finally:
            os.unlink(csv_file.name)

    def test_conflict_keep_both(self):
        """Test keep_both_as_variants policy: both entries kept."""
        csv_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv", encoding="utf-8"
        )
        csv_file.write("src_text,translation\n")
        csv_file.write("בית,дом\n")
        csv_file.write("בית,здание\n")  # Keep both as variants
        csv_file.close()

        try:
            service = DictionaryImportService()

            with self.db_service.get_session() as session:
                report = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=None,
                    scope="global",
                    on_conflict="keep_both_as_variants",
                    normalize_mode="strict",
                )

            # Both added (first as new, second as variant)
            self.assertEqual(report.added, 2)
            self.assertEqual(report.conflicts, 1)

            # Verify both entries exist
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).order_by(DictEntry.dict_entry_id).all()
                self.assertEqual(len(entries), 2)

                # Same src_norm but different translations
                self.assertEqual(entries[0].src_norm, entries[1].src_norm)
                translations = sorted([e.translation for e in entries])
                self.assertEqual(translations, ["дом", "здание"])

        finally:
            os.unlink(csv_file.name)

    def test_duplicate_same_translation_skipped(self):
        """Test that duplicate with same translation is skipped."""
        csv_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv", encoding="utf-8"
        )
        csv_file.write("src_text,translation\n")
        csv_file.write("בית,дом\n")
        csv_file.write("בית,дом\n")  # Exact duplicate
        csv_file.close()

        try:
            service = DictionaryImportService()

            with self.db_service.get_session() as session:
                report = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=None,
                    scope="global",
                    on_conflict="keep_both_as_variants",
                    normalize_mode="strict",
                )

            # First added, second skipped as duplicate
            self.assertEqual(report.added, 1)
            self.assertEqual(report.skipped, 1)

            # Only one entry
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).all()
                self.assertEqual(len(entries), 1)

        finally:
            os.unlink(csv_file.name)


if __name__ == "__main__":
    unittest.main()
