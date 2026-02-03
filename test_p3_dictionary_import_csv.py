"""P3 Dictionary Import CSV Tests.

Tests CSV import functionality:
- 2-column format
- Full format with headers
- Aliases
- SHA256 deduplication
- Chunk commit
- Cancel flag
"""

import unittest
import tempfile
import sqlite3
import os
from pathlib import Path

from app.services.dictionary_import_service import DictionaryImportService
from app.services.db_service import DBService


class TestDictionaryImportCSV(unittest.TestCase):
    """Test CSV import."""

    @classmethod
    def setUpClass(cls):
        """Create test database."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply schema
        DBService.initialize(cls.test_db.name)

        # Apply M7 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
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
                name="Test Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.commit()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def setUp(self):
        """Clean dict tables before each test."""
        from app.infra.sa_models import DictSource, DictEntry

        with self.db_service.get_session() as session:
            session.query(DictEntry).delete()
            session.query(DictSource).delete()
            session.commit()

    def test_import_2column_csv(self):
        """Test importing 2-column CSV (he, ru)."""
        # Create test CSV
        csv_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
        csv_file.write("בית,дом\n")
        csv_file.write("ספר,книга\n")
        csv_file.write("שולחן,стол\n")
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
                    default_kind="lemma",
                    default_status="approved",
                )

            # Verify report
            self.assertEqual(report.total, 3)
            self.assertEqual(report.added, 3)
            self.assertEqual(report.skipped, 0)
            self.assertEqual(report.invalid, 0)

            # Verify DB entries
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).all()
                self.assertEqual(len(entries), 3)

                # Check first entry
                entry = entries[0]
                self.assertEqual(entry.kind, "lemma")
                self.assertEqual(entry.src_lang, "he")
                self.assertEqual(entry.tgt_lang, "ru")
                self.assertEqual(entry.src_text, "בית")
                self.assertEqual(entry.translation, "дом")
                self.assertEqual(entry.status, "approved")

        finally:
            os.unlink(csv_file.name)

    def test_import_full_format_csv(self):
        """Test importing full format CSV with headers."""
        # Create test CSV with headers
        csv_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
        csv_file.write("kind,src_lang,tgt_lang,src_text,translation,pos,domain,status\n")
        csv_file.write("lemma,he,ru,בית,дом,NOUN,general,approved\n")
        csv_file.write("term_cluster,he,ru,בית הספר,школа,,education,approved\n")
        csv_file.close()

        try:
            service = DictionaryImportService()

            with self.db_service.get_session() as session:
                report = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=1,
                    scope="project",
                    on_conflict="skip",
                    normalize_mode="strict",
                    default_kind="lemma",
                    default_status="approved",
                )

            # Verify report
            self.assertEqual(report.total, 2)
            self.assertEqual(report.added, 2)

            # Verify entries
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).order_by(DictEntry.dict_entry_id).all()
                self.assertEqual(len(entries), 2)

                # Check lemma
                self.assertEqual(entries[0].kind, "lemma")
                self.assertEqual(entries[0].pos, "NOUN")
                self.assertEqual(entries[0].domain, "general")

                # Check term cluster
                self.assertEqual(entries[1].kind, "term_cluster")
                self.assertEqual(entries[1].domain, "education")

        finally:
            os.unlink(csv_file.name)

    def test_import_with_aliases(self):
        """Test importing CSV with aliases."""
        # Create test CSV with aliases column
        # Use aliases that normalize differently to avoid UNIQUE constraint violation
        csv_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
        csv_file.write("src_text,translation,aliases\n")
        csv_file.write("בית,дом,ספר;שולחן\n")  # Use different words as aliases for testing
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
                    default_kind="lemma",
                    default_status="approved",
                )

            # Verify: 1 main + 2 aliases = 3 entries
            self.assertEqual(report.added, 3)

            # Verify DB
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).all()
                self.assertEqual(len(entries), 3)

                # All should have same translation
                translations = [e.translation for e in entries]
                self.assertTrue(all(t == "дом" for t in translations))

                # Different src_text
                src_texts = sorted([e.src_text for e in entries])
                self.assertIn("בית", src_texts)
                self.assertIn("ספר", src_texts)
                self.assertIn("שולחן", src_texts)

        finally:
            os.unlink(csv_file.name)

    def test_sha256_dedup(self):
        """Test SHA256 deduplication prevents re-import."""
        # Create test CSV
        csv_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
        csv_file.write("בית,дом\n")
        csv_file.close()

        try:
            service = DictionaryImportService()

            # First import
            with self.db_service.get_session() as session:
                report1 = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=None,
                    scope="global",
                    on_conflict="skip",
                    normalize_mode="strict",
                )

            self.assertEqual(report1.added, 1)

            # Second import (same file, same scope)
            with self.db_service.get_session() as session:
                report2 = service.import_dictionary(
                    session,
                    csv_file.name,
                    project_id=None,
                    scope="global",
                    on_conflict="skip",
                    normalize_mode="strict",
                )

            # Should be skipped due to SHA256 match
            self.assertEqual(report2.total, 0)
            self.assertEqual(report2.added, 0)
            self.assertEqual(report2.sha256, report1.sha256)

        finally:
            os.unlink(csv_file.name)

    def test_cancel_flag(self):
        """Test cancel flag interrupts import."""
        # Create CSV with 300 rows (will commit first 200, then cancel on second chunk)
        csv_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
        for i in range(300):
            csv_file.write(f"word{i},перевод{i}\n")
        csv_file.close()

        try:
            service = DictionaryImportService()

            # Cancel after 250 rows (after first chunk of 200 committed)
            cancel_counter = {"count": 0}

            def progress_cb(cur, tot):
                cancel_counter["count"] = cur

            def cancel_flag():
                return cancel_counter["count"] >= 250

            with self.assertRaises(InterruptedError):
                with self.db_service.get_session() as session:
                    service.import_dictionary(
                        session,
                        csv_file.name,
                        project_id=None,
                        scope="global",
                        on_conflict="skip",
                        normalize_mode="strict",
                        progress_cb=progress_cb,
                        cancel_flag=cancel_flag,
                    )

            # Verify partial commit: first chunk (200) committed, rest rolled back
            from app.infra.sa_models import DictEntry

            with self.db_service.get_session() as session:
                entries = session.query(DictEntry).all()
                # Due to chunk commit (200 rows), first chunk should be committed
                # This is expected behavior - cancel happens between chunks
                self.assertEqual(len(entries), 200)

        finally:
            os.unlink(csv_file.name)


if __name__ == "__main__":
    unittest.main()
