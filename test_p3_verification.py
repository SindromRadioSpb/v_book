"""P3 Verification Tests.

Tests the P3 verification service itself.
"""

import unittest
import tempfile
import sqlite3
import os
from pathlib import Path

from app.services.p3_verification_service import P3VerificationService
from app.services.db_service import DBService


class TestP3Verification(unittest.TestCase):
    """Test P3 verification service."""

    @classmethod
    def setUpClass(cls):
        """Create test database with full schema."""
        cls.test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        cls.test_db.close()

        # Apply full schema
        DBService.initialize(cls.test_db.name)

        # Apply all migrations
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
                name="Verification Test Project",
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

    def setUp(self):
        """Clean tables before each test to ensure isolation."""
        # P3.1.5: Clean tables to avoid test pollution
        from app.infra.sa_models import DictSource, DictEntry, TMEntry
        from sqlalchemy import delete

        with self.db_service.get_session() as session:
            session.execute(delete(TMEntry))
            session.execute(delete(DictEntry))
            session.execute(delete(DictSource))
            session.commit()

    def test_snapshot_creation(self):
        """Test snapshot creation and SHA256 computation."""
        service = P3VerificationService()

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path, sha256_hex = service.create_snapshot(self.test_db.name, tmpdir)

            # Verify snapshot exists
            self.assertTrue(Path(snapshot_path).exists(), "Snapshot file should exist")

            # Verify SHA256 format
            self.assertEqual(len(sha256_hex), 64, "SHA256 should be 64 hex chars")

            # Recompute SHA256 - should be stable
            snapshot_path2, sha256_hex2 = service.create_snapshot(self.test_db.name, tmpdir + "_2")
            self.assertEqual(sha256_hex, sha256_hex2, "SHA256 should be stable for same DB")

    def test_csv_import_2col(self):
        """Test 2-column CSV import verification step."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_csv_import_2col(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"CSV import should pass: {step.error}")
            self.assertEqual(step.details["total"], 3)
            self.assertEqual(step.details["added"], 3)

    def test_csv_import_full(self):
        """Test full-format CSV import verification step."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_csv_import_full(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"Full CSV import should pass: {step.error}")
            self.assertEqual(step.details["total"], 2)
            # Allow 2-4 entries (aliases may create additional entries)
            self.assertGreaterEqual(step.details["added"], 2)
            self.assertLessEqual(step.details["added"], 4)

    def test_conflict_policies(self):
        """Test conflict policies (skip, overwrite)."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_conflict_policies(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"Conflict policies should pass: {step.error}")
            self.assertIn("skip", step.details)
            self.assertIn("overwrite", step.details)
            self.assertEqual(step.details["skip"]["added"], 1)
            self.assertEqual(step.details["skip"]["skipped"], 1)
            self.assertEqual(step.details["overwrite"]["added"], 1)
            self.assertEqual(step.details["overwrite"]["updated"], 1)

    def test_cancel_behavior(self):
        """Test chunk commit + cancel flag."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_cancel_behavior(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"Cancel behavior should pass: {step.error}")
            self.assertEqual(step.details["added"], 500, "Should import all 500 rows")
            self.assertGreater(step.details["progress_callbacks"], 0, "Progress callbacks should be called")
            self.assertTrue(step.details["chunk_commit"], "Chunk commit should be tested")

    def test_sha256_dedup(self):
        """Test SHA256 deduplication of dict_source."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_sha256_dedup(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"SHA256 dedup should pass: {step.error}")
            self.assertTrue(step.details["dedup_working"])

    def test_csv_injection_protection(self):
        """Test CSV injection protection."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_csv_injection(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"CSV injection protection should pass: {step.error}")
            self.assertTrue(step.details["sanitized"])
            self.assertEqual(step.details["example_input"], "=2+2")
            self.assertEqual(step.details["example_output"], "'=2+2")

    def test_resolve_sanity(self):
        """Test resolve sanity (dict → TM override)."""
        service = P3VerificationService()

        with self.db_service.get_session() as session:
            step = service._verify_resolve_sanity(session, project_id=1, options={})

            self.assertEqual(step.status, "PASS", f"Resolve sanity should pass: {step.error}")
            self.assertEqual(step.details["dict_source"], "dict")
            self.assertEqual(step.details["tm_source"], "tm")
            self.assertIn("TM > dict", step.details["precedence"])

    def test_full_verification_run(self):
        """Test full verification run with all steps."""
        service = P3VerificationService()

        # P3.1.5: For testing, use test DB directly (no snapshot needed)
        # Snapshot is only for production CLI tool
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = self.test_db.name  # Use test DB directly
            sha256_hex = "test_db_fake_sha256"  # Placeholder

            with self.db_service.get_session() as session:
                report = service.run(
                    session,
                    project_id=1,
                    snapshot_path=snapshot_path,
                    snapshot_sha256=sha256_hex,
                )

            # Verify report structure
            self.assertEqual(report.snapshot_path, snapshot_path)
            self.assertEqual(report.snapshot_sha256, sha256_hex)
            self.assertEqual(len(report.steps), 8, "Should have 8 verification steps")

            # Verify overall status
            failed_steps = [s for s in report.steps if s.status == "FAIL"]
            if failed_steps:
                for step in failed_steps:
                    print(f"FAILED: {step.name} - {step.error}")

            self.assertEqual(report.overall_status, "PASS", "Full verification should pass")

            # Test JSON export
            report_dict = report.to_dict()
            self.assertIn("snapshot_path", report_dict)
            self.assertIn("steps", report_dict)

            # Test Markdown export
            md = report.to_markdown()
            self.assertIn("# P3 Verification Report", md)
            self.assertIn("PASS", md)


if __name__ == "__main__":
    unittest.main()
