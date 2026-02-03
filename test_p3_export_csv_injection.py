"""P3 Export CSV Injection Tests.

Tests CSV injection protection:
- Values starting with = + - @ are prefixed with '
- JSON export is NOT sanitized
- All text fields are protected
"""

import unittest
import tempfile
import sqlite3
import os
import csv
import json
from pathlib import Path

from app.services.export_service import ExportService
from app.services.db_service import DBService


class TestExportCSVInjection(unittest.TestCase):
    """Test CSV injection protection."""

    @classmethod
    def setUpClass(cls):
        """Create test database."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        DBService.initialize(cls.test_db.name)

        # Apply M7 migrations
        migration_m7 = Path("schema/004_m7_translation_memory.sql").read_text(encoding='utf-8')
        migration_m7_revert = Path("schema/005_m7_add_revert_origin.sql").read_text(encoding='utf-8')
        migration_p2 = Path("schema/006_p2_add_revert_origin.sql").read_text(encoding='utf-8')
        con = sqlite3.connect(cls.test_db.name)
        con.executescript(migration_m7)
        con.executescript(migration_m7_revert)
        con.executescript(migration_p2)
        con.close()

        cls.db_service = DBService.get_instance()

    @classmethod
    def tearDownClass(cls):
        """Clean up."""
        DBService.shutdown()
        os.unlink(cls.test_db.name)

    def setUp(self):
        """Create test TM entries with dangerous values."""
        from app.infra.sa_models import TMEntry

        with self.db_service.get_session() as session:
            # Clean
            session.query(TMEntry).delete()

            # Create entries with injection patterns
            entries = [
                TMEntry(
                    project_id=None,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="=2+2",  # Formula injection
                    src_norm="=2+2",
                    translation="+危险",  # Plus prefix
                    status="approved",
                    origin="import",
                ),
                TMEntry(
                    project_id=None,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text="test",
                    src_norm="test",
                    translation="-cmd|'/c calc'!A1",  # Command injection
                    pos="@NOUN",  # @ prefix
                    domain="=domain",  # = prefix
                    notes="@note",  # @ prefix
                    status="approved",
                    origin="user_edit",
                    source_ref="+ref",  # + prefix
                ),
            ]

            for entry in entries:
                session.add(entry)

            session.commit()

    def test_csv_export_sanitizes_dangerous_chars(self):
        """Test that CSV export sanitizes = + - @."""
        export_service = ExportService()

        # Export to CSV
        csv_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='w', encoding='utf-8')
        csv_file.close()

        try:
            with self.db_service.get_session() as session:
                count = export_service.export_tm_csv(session, csv_file.name)

            self.assertEqual(count, 2)

            # Read CSV and check sanitization
            with open(csv_file.name, 'r', encoding='utf-8', newline='') as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Header + 2 data rows
            self.assertEqual(len(rows), 3)

            # Check first entry (=2+2 should be '=2+2)
            row1 = rows[1]
            src_text_idx = 5  # src_text column
            translation_idx = 7  # translation column

            self.assertEqual(row1[src_text_idx], "'=2+2")  # Sanitized
            self.assertEqual(row1[translation_idx], "'+危险")  # Sanitized

            # Check second entry
            row2 = rows[2]
            pos_idx = 9  # pos column
            domain_idx = 10  # domain column
            notes_idx = 11  # notes column
            source_ref_idx = 15  # source_ref column

            self.assertEqual(row2[translation_idx], "'-cmd|'/c calc'!A1")  # Sanitized
            self.assertEqual(row2[pos_idx], "'@NOUN")  # Sanitized
            self.assertEqual(row2[domain_idx], "'=domain")  # Sanitized
            self.assertEqual(row2[notes_idx], "'@note")  # Sanitized
            self.assertEqual(row2[source_ref_idx], "'+ref")  # Sanitized

        finally:
            os.unlink(csv_file.name)

    def test_json_export_no_sanitization(self):
        """Test that JSON export does NOT sanitize (not needed for JSON)."""
        export_service = ExportService()

        # Export to JSON
        json_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8')
        json_file.close()

        try:
            with self.db_service.get_session() as session:
                count = export_service.export_tm_json(session, json_file.name)

            self.assertEqual(count, 2)

            # Read JSON
            with open(json_file.name, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.assertEqual(len(data), 2)

            # Check that values are NOT sanitized (original values)
            self.assertEqual(data[0]['src_text'], "=2+2")  # NOT '=2+2
            self.assertEqual(data[0]['translation'], "+危险")  # NOT '+危险

            self.assertEqual(data[1]['translation'], "-cmd|'/c calc'!A1")  # NOT sanitized
            self.assertEqual(data[1]['pos'], "@NOUN")  # NOT sanitized
            self.assertEqual(data[1]['domain'], "=domain")  # NOT sanitized
            self.assertEqual(data[1]['notes'], "@note")  # NOT sanitized
            self.assertEqual(data[1]['source_ref'], "+ref")  # NOT sanitized

        finally:
            os.unlink(json_file.name)

    def test_sanitize_csv_cell_unit(self):
        """Test sanitize_csv_cell function directly."""
        export_service = ExportService()

        # Test dangerous prefixes
        self.assertEqual(export_service.sanitize_csv_cell("=2+2"), "'=2+2")
        self.assertEqual(export_service.sanitize_csv_cell("+危险"), "'+危险")
        self.assertEqual(export_service.sanitize_csv_cell("-cmd"), "'-cmd")
        self.assertEqual(export_service.sanitize_csv_cell("@note"), "'@note")

        # Test safe values (no prefix)
        self.assertEqual(export_service.sanitize_csv_cell("safe"), "safe")
        self.assertEqual(export_service.sanitize_csv_cell("בית"), "בית")
        self.assertEqual(export_service.sanitize_csv_cell("123"), "123")

        # Test empty/None
        self.assertEqual(export_service.sanitize_csv_cell(""), "")
        self.assertEqual(export_service.sanitize_csv_cell(None), "")

        # Test values with dangerous chars in middle (should NOT be prefixed)
        self.assertEqual(export_service.sanitize_csv_cell("a=b"), "a=b")
        self.assertEqual(export_service.sanitize_csv_cell("x+y"), "x+y")


if __name__ == "__main__":
    unittest.main()
