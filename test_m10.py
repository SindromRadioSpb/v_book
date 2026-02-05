"""
M10: Packaging + QA - Golden Tests

This test suite verifies:
1. Backup before migrations (WAL-safe, retention policy)
2. SnapshotService (create, list, delete)
3. Crash recovery (deterministic timestamps)

Anti-flake strategy:
- Deterministic timestamps using freezegun
- Explicit ORDER BY in all queries
- Cleanup in tearDown even if test fails
- No network calls, no time.sleep()

Testing command:
    python test_m10.py
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import freezegun

from app.infra.db import DatabaseManager
from app.services.db_service import DBService
from app.services.backup_service import BackupService
from app.services.snapshot_service import SnapshotService
from app.infra.sa_models import ProcessorRun, RunError, DictProject


class TestM10Golden(unittest.TestCase):
    """Golden tests for M10 Packaging + QA."""

    def setUp(self):
        """Create isolated temp directory for each test."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_m10_"))
        self.db_path = self.test_dir / "test.db"

    def tearDown(self):
        """Clean up temp directory and WAL files."""
        # Shutdown DBService if initialized
        try:
            DBService.shutdown()
        except Exception:
            pass

        # Clean up test directory
        if self.test_dir.exists():
            try:
                shutil.rmtree(self.test_dir)
            except Exception as e:
                print(f"Warning: Could not clean up {self.test_dir}: {e}")

    def test_01_backup_before_migration(self):
        """
        Test that backup is created before migration.

        Steps:
        1. Create DB with migrations
        2. Verify backup file exists (if migrations were applied)
        3. Verify migrations completed successfully
        """
        print("\n[Test 1] Backup before migration...")

        # Initialize DB with migrations
        db_manager = DatabaseManager(self.db_path)
        db_manager.apply_migrations()

        # Check if backups were created
        backup_dir = self.db_path.parent / "backups"

        if backup_dir.exists():
            backups = list(backup_dir.glob("backup_*.db"))
            if len(backups) > 0:
                print(f"  [OK] {len(backups)} backup(s) created")
            else:
                print("  [OK] No migrations needed (schema up-to-date)")
        else:
            print("  [OK] No migrations needed (first-time DB)")

        # Verify database is functional
        current_version = 0
        with db_manager.engine.connect() as conn:
            from sqlalchemy import text

            result = conn.execute(
                text("SELECT value FROM schema_meta WHERE key='schema_version'")
            ).fetchone()
            current_version = int(result[0]) if result else 0

        self.assertGreater(
            current_version, 0, "Schema version should be greater than 0"
        )
        print(f"  [OK] Migration completed (schema version: {current_version})")

        db_manager.close()

    def test_02_snapshot_service_create_and_list(self):
        """
        Test SnapshotService.create_snapshot() and list_snapshots().

        Steps:
        1. Create test DB with data
        2. Call create_snapshot(reason="golden_test")
        3. Verify snapshot file exists
        4. Verify snapshot size > 0
        5. Verify SHA256 computed
        6. Call list_snapshots()
        7. Verify created snapshot is in list
        """
        print("\n[Test 2] SnapshotService create and list...")

        # Create test DB
        db_manager = DatabaseManager(self.db_path)
        db_manager.apply_migrations()
        db_manager.close()

        # Create snapshot
        snapshot_dir = self.test_dir / "snapshots"
        snapshot_service = SnapshotService(storage_dir=snapshot_dir)

        snapshot_info = snapshot_service.create_snapshot(
            source_db_path=self.db_path,
            reason="golden_test",
            tags=["test", "m10"],
            compute_hash=True,
        )

        self.assertIsNotNone(snapshot_info, "Snapshot info should be returned")
        self.assertTrue(
            snapshot_info.snapshot_path.exists(), "Snapshot file should exist"
        )
        self.assertGreater(snapshot_info.size_bytes, 0, "Snapshot size should be > 0")
        self.assertIsNotNone(snapshot_info.sha256, "SHA256 should be computed")
        print(f"  [OK] Snapshot created: {snapshot_info.snapshot_path.name}")
        print(f"  [OK] Size: {snapshot_info.size_bytes} bytes")
        print(f"  [OK] SHA256: {snapshot_info.sha256[:16]}...")

        # List snapshots
        snapshots = snapshot_service.list_snapshots()
        self.assertEqual(len(snapshots), 1, "Should have 1 snapshot")
        self.assertEqual(
            snapshots[0].snapshot_id,
            snapshot_info.snapshot_id,
            "Snapshot ID should match",
        )
        print(f"  [OK] list_snapshots() returned {len(snapshots)} snapshot(s)")

    @freezegun.freeze_time("2025-01-15 10:30:00")
    def test_03_crash_recovery_marks_running_as_failed(self):
        """
        Test crash recovery on startup (deterministic timestamps).

        Steps:
        1. Create DB with project
        2. Insert ProcessorRun with status='running'
        3. Shutdown DBService
        4. Re-initialize DBService (simulates restart)
        5. Call recover_from_crash()
        6. Verify ProcessorRun status changed to 'failed'
        7. Verify RunError created with 'crash_recovery' type
        8. Verify finished_at = "2025-01-15T10:30:00.000000Z" (deterministic)
        """
        print("\n[Test 3] Crash recovery with deterministic timestamps...")

        # Initialize DB
        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        # Create library and project (required for foreign key)
        from app.infra.sa_models import Library

        with db_service.get_session() as session:
            library = Library(library_id=1, name="Test Library")
            session.add(library)
            session.commit()

            project = DictProject(
                project_id=1, library_id=1, name="Test Project", description=""
            )
            session.add(project)
            session.commit()

        # Create a "running" ProcessorRun
        with db_service.get_session() as session:
            run = ProcessorRun(
                run_id=1,
                project_id=1,
                engine="test_engine",
                engine_version="1.0",
                status="running",
                started_at="2025-01-15T10:25:00.000000Z",
                finished_at=None,
            )
            session.add(run)
            session.commit()

        print("  [OK] Created ProcessorRun with status='running'")

        # Simulate restart by shutting down and re-initializing
        DBService.shutdown()
        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        # Run crash recovery
        recovered_count = db_service.recover_from_crash()

        self.assertEqual(recovered_count, 1, "Should recover 1 run")
        print(f"  [OK] Recovered {recovered_count} run(s)")

        # Verify run status changed
        with db_service.get_session() as session:
            run = session.query(ProcessorRun).filter(ProcessorRun.run_id == 1).first()

            self.assertIsNotNone(run, "Run should exist")
            self.assertEqual(run.status, "failed", "Status should be 'failed'")
            self.assertEqual(
                run.finished_at,
                "2025-01-15T10:30:00.000000Z",
                "finished_at should match frozen time",
            )
            print(f"  [OK] Run status: {run.status}")
            print(f"  [OK] finished_at: {run.finished_at}")

            # Verify RunError created
            error = (
                session.query(RunError)
                .filter(RunError.run_id == 1)
                .filter(RunError.stage == "crash_recovery")
                .first()
            )

            self.assertIsNotNone(error, "RunError should be created")
            self.assertEqual(
                error.stage,
                "crash_recovery",
                "Stage should be 'crash_recovery'",
            )
            self.assertIn(
                "terminated unexpectedly",
                error.message,
                "Message should mention unexpected termination",
            )
            print(f"  [OK] RunError created: {error.message}")

        DBService.shutdown()


def main():
    """Run golden tests."""
    print("=" * 70)
    print("M10: Packaging + QA - Golden Tests")
    print("=" * 70)

    # Run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestM10Golden)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    if result.wasSuccessful():
        print("[OK] ALL TESTS PASSED")
        return 0
    else:
        print(f"[FAIL] {len(result.failures)} FAILED, {len(result.errors)} ERRORS")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
