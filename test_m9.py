"""M9: Export Center - Comprehensive Tests

Full test suite for M9 export functionality (XLSX, TBX, TMX).
Tests ExportService export methods, file formats, and data integrity.

Run: python test_m9.py
Run with anti-flake: python test_m9.py --repeat 20
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.db_service import DBService
from app.services.export_service import ExportService
from app.infra.sa_models import DictProject, TMEntry, TermCluster


class TestM9ExportCenter(unittest.TestCase):
    """Comprehensive M9 export tests."""

    @classmethod
    def setUpClass(cls):
        """Set up test database."""
        cls.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        cls.temp_db.close()
        cls.db_path = cls.temp_db.name

        # Initialize with migrations
        DBService.initialize(cls.db_path)
        cls.db_service = DBService.get_instance()

        # Apply M7 TM migration (required for tm_entry table)
        import sqlite3
        migration_path = Path("schema/004_m7_translation_memory.sql")
        if migration_path.exists():
            migration_sql = migration_path.read_text(encoding='utf-8')
            con = sqlite3.connect(cls.db_path)
            con.executescript(migration_sql)
            con.close()

        # Create test project
        with cls.db_service.get_session() as session:
            from app.services.project_service import ProjectService
            project_service = ProjectService()
            project = project_service.create_project(
                session,
                name="test_m9_export",
                description="M9 export test project",
            )
            session.commit()
            cls.project_id = project.project_id

            # Create TM entries
            for i in range(15):
                tm_entry = TMEntry(
                    project_id=cls.project_id,
                    kind="lemma",
                    src_lang="he",
                    tgt_lang="ru",
                    src_text=f"מילה_{i}",
                    src_norm=f"מילה_{i}",
                    translation=f"слово_{i}",
                    status="approved" if i < 10 else "draft",
                    origin="import",  # Valid origin per schema CHECK constraint
                )
                session.add(tm_entry)

            # Create term clusters
            for i in range(5):
                cluster = TermCluster(
                    project_id=cls.project_id,
                    canonical_key=f"term_{i}",
                    representative_he=f"טרם {i}",
                    freq_abs=20 - i,
                    doc_freq=5,
                    members_count=1,
                    curation_status="approved" if i < 2 else "auto",
                )
                session.add(cluster)

            session.commit()

        # Temp directory for test exports
        cls.temp_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database and files."""
        DBService.shutdown()
        if os.path.exists(cls.db_path):
            os.unlink(cls.db_path)

        # Clean up temp exports
        import shutil
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir)

    def setUp(self):
        """Set up each test."""
        self.service = ExportService()

    # ========================================================================
    # Test 1-3: XLSX Export
    # ========================================================================

    def test_01_xlsx_export_creates_file(self):
        """Test that XLSX export creates a valid file."""
        output_path = os.path.join(self.temp_dir, "test_export.xlsx")

        with self.db_service.get_session() as session:
            count = self.service.export_xlsx(session, output_path, project_id=self.project_id)

        # File should exist
        self.assertTrue(os.path.exists(output_path), "XLSX file should be created")
        self.assertGreater(os.path.getsize(output_path), 0, "XLSX file should not be empty")
        self.assertGreater(count, 0, "Should export at least some entries")

        print(f"[OK] XLSX created: {output_path}, {count} entries")

    def test_02_xlsx_has_two_sheets(self):
        """Test that XLSX has Dictionary and Statistics sheets."""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not available")

        output_path = os.path.join(self.temp_dir, "test_sheets.xlsx")

        with self.db_service.get_session() as session:
            self.service.export_xlsx(session, output_path, project_id=self.project_id)

        # Load workbook
        wb = openpyxl.load_workbook(output_path)

        # Check sheets
        self.assertIn("Dictionary", wb.sheetnames, "Should have Dictionary sheet")
        self.assertIn("Statistics", wb.sheetnames, "Should have Statistics sheet")

        print(f"[OK] XLSX sheets: {wb.sheetnames}")

    def test_03_xlsx_dictionary_sheet_structure(self):
        """Test Dictionary sheet has correct structure."""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not available")

        output_path = os.path.join(self.temp_dir, "test_structure.xlsx")

        with self.db_service.get_session() as session:
            self.service.export_xlsx(session, output_path, project_id=self.project_id)

        wb = openpyxl.load_workbook(output_path)
        ws = wb["Dictionary"]

        # Check headers (row 1)
        headers = [cell.value for cell in ws[1]]
        expected_headers = [
            "Source (Hebrew)", "Translation (Russian)", "Status",
            "Origin", "Kind", "Frequency", "Notes"
        ]

        for expected in expected_headers:
            self.assertIn(expected, headers, f"Missing header: {expected}")

        # Check we have data rows (more than just header)
        self.assertGreater(ws.max_row, 1, "Should have data rows beyond header")

        print(f"[OK] Dictionary sheet: {ws.max_row} rows (including header)")

    def test_04_xlsx_statistics_sheet_content(self):
        """Test Statistics sheet has project stats."""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not available")

        output_path = os.path.join(self.temp_dir, "test_stats.xlsx")

        with self.db_service.get_session() as session:
            self.service.export_xlsx(session, output_path, project_id=self.project_id)

        wb = openpyxl.load_workbook(output_path)
        ws = wb["Statistics"]

        # Check headers
        headers = [cell.value for cell in ws[1]]
        self.assertEqual(headers[0], "Metric")
        self.assertEqual(headers[1], "Value")

        # Should have at least 8 metric rows (excluding header)
        self.assertGreaterEqual(ws.max_row, 9, "Should have at least 8 metrics + header")

        # Check some expected metrics exist
        metrics = {ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)}
        expected_metrics = {"Project Name", "Project ID", "Documents", "Lemmas (Unique Words)"}

        for expected in expected_metrics:
            self.assertIn(expected, metrics, f"Missing metric: {expected}")

        print(f"[OK] Statistics sheet: {ws.max_row - 1} metrics")

    def test_05_xlsx_atomic_write(self):
        """Test that XLSX uses atomic file writing."""
        output_path = os.path.join(self.temp_dir, "test_atomic.xlsx")

        # Remove if exists
        if os.path.exists(output_path):
            os.unlink(output_path)

        with self.db_service.get_session() as session:
            self.service.export_xlsx(session, output_path, project_id=self.project_id)

        # File should exist and be complete
        self.assertTrue(os.path.exists(output_path))

        # No temp files should remain
        temp_files = [f for f in os.listdir(self.temp_dir) if f.endswith('.tmp')]
        self.assertEqual(len(temp_files), 0, "No temp files should remain after export")

        print("[OK] Atomic write verified - no temp files left")

    # ========================================================================
    # Test 6: CSV Regression
    # ========================================================================

    def test_06_csv_injection_protection_maintained(self):
        """Test that CSV injection protection still works (regression)."""
        output_path = os.path.join(self.temp_dir, "test_csv_inject.csv")

        # Create TM entry with dangerous characters
        with self.db_service.get_session() as session:
            dangerous_entry = TMEntry(
                project_id=self.project_id,
                kind="lemma",  # Valid kind per schema CHECK constraint
                src_lang="he",
                tgt_lang="ru",
                src_text="=SUM(A1:A10)",  # Formula injection attempt
                src_norm="dangerous",
                translation="+DANGEROUS",
                status="approved",
                origin="import",
            )
            session.add(dangerous_entry)
            session.commit()

        # Export to CSV
        with self.db_service.get_session() as session:
            self.service.export_tm_csv(session, output_path, project_id=self.project_id)

        # Read and verify escaping
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()

            # Should have prefixed with single quote
            self.assertIn("'=SUM(A1:A10)", content, "Formula should be escaped with '")
            self.assertIn("'+DANGEROUS", content, "Plus sign should be escaped with '")

        print("[OK] CSV injection protection verified")

    # ========================================================================
    # Test 7: Export Service API
    # ========================================================================

    def test_07_export_service_existing_methods_still_work(self):
        """Test that existing CSV/JSON export methods still function."""
        csv_path = os.path.join(self.temp_dir, "test_tm.csv")
        json_path = os.path.join(self.temp_dir, "test_tm.json")

        # CSV export
        with self.db_service.get_session() as session:
            csv_count = self.service.export_tm_csv(
                session, csv_path, project_id=self.project_id
            )

        self.assertTrue(os.path.exists(csv_path))
        self.assertGreater(csv_count, 0)

        # JSON export
        with self.db_service.get_session() as session:
            json_count = self.service.export_tm_json(
                session, json_path, project_id=self.project_id
            )

        self.assertTrue(os.path.exists(json_path))
        self.assertGreater(json_count, 0)

        print(f"[OK] CSV: {csv_count} entries, JSON: {json_count} entries")

    # ========================================================================
    # Test 8: Edge Cases
    # ========================================================================

    def test_08_xlsx_empty_project(self):
        """Test XLSX export with empty project."""
        # Create empty project
        with self.db_service.get_session() as session:
            from app.services.project_service import ProjectService
            project_service = ProjectService()
            empty_project = project_service.create_project(
                session,
                name="test_empty",
                description="Empty project",
            )
            session.commit()
            empty_project_id = empty_project.project_id

        output_path = os.path.join(self.temp_dir, "test_empty.xlsx")

        # Should not crash on empty project
        with self.db_service.get_session() as session:
            count = self.service.export_xlsx(
                session, output_path, project_id=empty_project_id
            )

        # File should still be created with sheets
        self.assertTrue(os.path.exists(output_path))

        try:
            import openpyxl
            wb = openpyxl.load_workbook(output_path)
            self.assertIn("Dictionary", wb.sheetnames)
            self.assertIn("Statistics", wb.sheetnames)
        except ImportError:
            pass  # Skip sheet check if openpyxl not available

        print("[OK] Empty project export handled gracefully")


def run_anti_flake_verification(repeat_count=20):
    """Run tests multiple times to verify stability."""
    print("=" * 70)
    print(f"Running anti-flake verification ({repeat_count} iterations)")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestM9ExportCenter)

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
        print("M9: Export Center - Comprehensive Tests (PATCH 5)")
        print("=" * 70)
        unittest.main(verbosity=2)
