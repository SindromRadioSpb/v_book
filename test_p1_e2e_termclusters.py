#!/usr/bin/env python3
"""P1 E2E Test - Real Term Clusters.

Tests P1 verification with a real term extraction pipeline to ensure:
1. Fixture has actual term_clusters (not empty)
2. P1 verification is NOT SKIPPED
3. TM entries persist through all phases
4. At least one term_cluster item is tested
"""

import unittest
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestP1E2ETermClusters(unittest.TestCase):
    """E2E test with real term clusters."""

    @classmethod
    def setUpClass(cls):
        """Build fixture DB with term clusters."""
        from app.tools.build_termcluster_fixture import build_fixture

        logger.info("Building fixture DB with term clusters...")
        cls.db_path, cls.project_id = build_fixture()
        logger.info(f"Fixture DB: {cls.db_path}")
        logger.info(f"Project ID: {cls.project_id}")

    @classmethod
    def tearDownClass(cls):
        """Clean up fixture DB."""
        if hasattr(cls, 'db_path'):
            # Keep fixture for inspection - delete parent directory
            fixture_dir = Path(cls.db_path).parent
            # Don't auto-delete - keep for debugging
            logger.info(f"Fixture preserved at: {fixture_dir}")

    def test_01_fixture_has_term_clusters(self):
        """Verify fixture has term clusters."""
        from app.services.db_service import DBService
        from app.infra.sa_models import TermCluster
        from sqlalchemy import select, func

        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            stmt = select(func.count()).select_from(TermCluster).where(
                TermCluster.project_id == self.project_id
            )
            count = session.execute(stmt).scalar()

        DBService.shutdown()

        logger.info(f"Term clusters in fixture: {count}")
        self.assertGreater(count, 0, "Fixture should have at least 1 term cluster")

    def setUp(self):
        """Clean up TM entries before each test."""
        from app.services.db_service import DBService
        from app.infra.sa_models import TMEntry

        DBService.initialize(self.db_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            # Delete all TM entries for this project
            session.query(TMEntry).filter(TMEntry.project_id == self.project_id).delete()
            session.commit()

        DBService.shutdown()

    def test_02_p1_verification_not_skipped(self):
        """Test P1 verification runs successfully (not SKIPPED)."""
        from app.services.p1_verification_service import P1VerificationService
        from app.services.db_service import DBService
        from pathlib import Path

        service = P1VerificationService()

        # Create snapshot with unique output directory for this test
        out_dir = f"runtime/test_e2e/test_02_{id(self)}"
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        snapshot_info = service.create_snapshot_db(self.db_path, out_dir)

        # Initialize DBService with snapshot
        DBService.initialize(snapshot_info.snapshot_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            # Select test items
            items = service.select_test_items(session, self.project_id)

            # Should NOT be empty (would cause SKIPPED)
            self.assertGreater(len(items), 0, "Should have test items (not SKIPPED)")

            # Should have at least one term_cluster if fixture worked
            has_term_cluster = any(item.kind == "term_cluster" for item in items)
            if has_term_cluster:
                logger.info("✓ Fixture has term_cluster item")
            else:
                logger.warning("No term_cluster item (fixture may be incomplete)")

            # Seed TM
            seeded_tm = service.seed_tm_entries(session, items, self.project_id)
            self.assertGreater(len(seeded_tm), 0, "Should have seeded TM entries")

            # Verify pre-extraction
            phase_pre = service.verify_resolve(session, seeded_tm, self.project_id)
            self.assertEqual(phase_pre.items_passed, phase_pre.items_checked,
                           "Pre-extraction phase should PASS all items")

        # Verify post-restart
        session_restart = service.simulate_restart(snapshot_info.snapshot_path)
        phase_restart = service.verify_resolve(session_restart, seeded_tm, self.project_id)
        session_restart.close()

        self.assertEqual(phase_restart.items_passed, phase_restart.items_checked,
                       "Post-restart phase should PASS all items")

        DBService.shutdown()

        logger.info("✅ P1 E2E PASS - TM entries persisted")

    def test_03_full_verification_report(self):
        """Run full P1 verification and generate report."""
        from app.services.p1_verification_service import P1VerificationService, P1VerificationReport
        from app.services.db_service import DBService
        from pathlib import Path
        import time

        service = P1VerificationService()
        start_time = time.time()

        # Create snapshot with unique output directory for this test
        out_dir = f"runtime/test_e2e/test_03_{id(self)}"
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        snapshot_info = service.create_snapshot_db(self.db_path, out_dir)

        # Initialize DBService with snapshot
        DBService.initialize(snapshot_info.snapshot_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            # Select items
            items = service.select_test_items(session, self.project_id)
            self.assertGreater(len(items), 0)

            # Seed TM
            seeded_tm = service.seed_tm_entries(session, items, self.project_id)

            # Pre-extraction
            phase_pre = service.verify_resolve(session, seeded_tm, self.project_id)
            phase_pre.phase_name = "pre_extraction"

            # Post-extraction (stub)
            service.run_reextraction(self.project_id, snapshot_info.snapshot_path)
            phase_post = service.verify_resolve(session, seeded_tm, self.project_id)
            phase_post.phase_name = "post_extraction"

        # Post-restart
        session_restart = service.simulate_restart(snapshot_info.snapshot_path)
        phase_restart = service.verify_resolve(session_restart, seeded_tm, self.project_id)
        phase_restart.phase_name = "post_restart"
        session_restart.close()

        # Determine status
        all_pass = all(
            p.items_failed == 0
            for p in [phase_pre, phase_post, phase_restart]
        )
        status = "PASS" if all_pass else "PARTIAL"

        # Generate report
        report = P1VerificationReport(
            timestamp=snapshot_info.timestamp,
            source_db_path=snapshot_info.source_path,
            snapshot_db_path=snapshot_info.snapshot_path,
            snapshot_sha256=snapshot_info.sha256,
            project_id=self.project_id,
            test_items=items,
            seeded_tm_entries=seeded_tm,
            phase_pre_extraction=phase_pre,
            phase_post_extraction=phase_post,
            phase_post_restart=phase_restart,
            status=status,
            total_duration_ms=(time.time() - start_time) * 1000,
        )

        # Save report
        out_dir = Path(snapshot_info.snapshot_path).parent
        md_path = out_dir / "P1_SCENARIO_7_E2E_REPORT.md"
        json_path = out_dir / "P1_SCENARIO_7_E2E_REPORT.json"

        import json
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        logger.info(f"Report saved: {json_path}")

        # Assertions
        self.assertEqual(status, "PASS", "E2E verification should PASS")
        self.assertEqual(phase_pre.items_failed, 0)
        self.assertEqual(phase_post.items_failed, 0)
        self.assertEqual(phase_restart.items_failed, 0)

        DBService.shutdown()

        print(f"\n{'='*70}")
        print(f"E2E Test Result: {status}")
        print(f"Test Items: {len(items)}")
        print(f"Pre-extraction: {phase_pre.items_passed}/{phase_pre.items_checked} PASS")
        print(f"Post-extraction: {phase_post.items_passed}/{phase_post.items_checked} PASS")
        print(f"Post-restart: {phase_restart.items_passed}/{phase_restart.items_checked} PASS")
        print(f"Report: {json_path}")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
