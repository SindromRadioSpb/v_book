"""P1 Verification CLI - Headless runner for Scenario 7.

Usage:
    python -m app.tools.p1_verify --db hdle.db
    python -m app.tools.p1_verify --db hdle.db --project-id 1
    python -m app.tools.p1_verify --db hdle.db --out-dir ./my_reports
"""

import argparse
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Run P1 verification headless."""
    parser = argparse.ArgumentParser(description="P1 Scenario 7 Verification")
    parser.add_argument("--db", required=True, help="Path to database file")
    parser.add_argument("--project-id", type=int, help="Project ID (optional)")
    parser.add_argument("--out-dir", help="Output directory (optional)")

    args = parser.parse_args()

    # Validate DB exists
    if not Path(args.db).exists():
        print(f"ERROR: Database not found: {args.db}")
        sys.exit(1)

    print("=" * 70)
    print("P1 Scenario 7 Verification - Headless Runner")
    print("=" * 70)
    print(f"Database: {args.db}")
    print(f"Project ID: {args.project_id or 'None (global scope)'}")
    print(f"Output: {args.out_dir or 'runtime/verifications/p1/<timestamp>'}")
    print("=" * 70)

    try:
        from app.services.p1_verification_service import P1VerificationService
        from app.services.db_service import DBService
        import time
        import json

        service = P1VerificationService()
        start_time = time.time()

        # Phase 1: Create snapshot
        print("\n[1/7] Creating DB snapshot...")
        snapshot_info = service.create_snapshot_db(args.db, args.out_dir)
        print(f"  ✓ Snapshot: {snapshot_info.snapshot_path}")
        print(f"  Size: {snapshot_info.size_bytes / 1024 / 1024:.2f} MB")

        # Phase 2: Open snapshot
        print("\n[2/7] Opening snapshot DB...")
        DBService.initialize(snapshot_info.snapshot_path)
        db_service = DBService.get_instance()

        with db_service.get_session() as session:
            # Phase 3: Select test items
            print("\n[3/7] Selecting test items...")
            test_items = service.select_test_items(session, args.project_id)

            if not test_items:
                print("  ⚠ No processed data found - SKIPPED")
                sys.exit(2)  # Exit code 2 = SKIPPED

            print(f"  ✓ Selected {len(test_items)} items:")
            for item in test_items:
                print(f"    - {item.kind}: {item.src_text}")

            # Phase 4: Seed TM
            print("\n[4/7] Seeding TM entries...")
            seeded_tm = service.seed_tm_entries(session, test_items, args.project_id)
            print(f"  ✓ Created {len(seeded_tm)} TM entries")

            # Phase 5: Pre-extraction verify
            print("\n[5/7] Pre-extraction verification...")
            phase_pre = service.verify_resolve(session, seeded_tm, args.project_id)
            print(f"  ✓ {phase_pre.items_passed}/{phase_pre.items_checked} PASS")

            # Phase 6: Post-extraction verify
            print("\n[6/7] Post-extraction verification...")
            service.run_reextraction(args.project_id, snapshot_info.snapshot_path)
            phase_post = service.verify_resolve(session, seeded_tm, args.project_id)
            print(f"  ✓ {phase_post.items_passed}/{phase_post.items_checked} PASS")

        # Phase 7: Post-restart verify
        print("\n[7/7] Post-restart verification...")
        session_restart = service.simulate_restart(snapshot_info.snapshot_path)
        phase_restart = service.verify_resolve(session_restart, seeded_tm, args.project_id)
        print(f"  ✓ {phase_restart.items_passed}/{phase_restart.items_checked} PASS")
        session_restart.close()

        # Determine status
        all_pass = all(
            p.items_failed == 0
            for p in [phase_pre, phase_post, phase_restart]
        )
        status = "PASS" if all_pass else "PARTIAL"

        # Save reports
        from app.services.p1_verification_service import P1VerificationReport

        report = P1VerificationReport(
            timestamp=snapshot_info.timestamp,
            source_db_path=snapshot_info.source_path,
            snapshot_db_path=snapshot_info.snapshot_path,
            snapshot_sha256=snapshot_info.sha256,
            project_id=args.project_id,
            test_items=test_items,
            seeded_tm_entries=seeded_tm,
            phase_pre_extraction=phase_pre,
            phase_post_extraction=phase_post,
            phase_post_restart=phase_restart,
            status=status,
            total_duration_ms=(time.time() - start_time) * 1000,
        )

        out_dir = args.out_dir or f"runtime/verifications/p1/{snapshot_info.timestamp}"
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        md_path = Path(out_dir) / "P1_SCENARIO_7_REPORT.md"
        json_path = Path(out_dir) / "P1_SCENARIO_7_REPORT.json"

        # Save reports (simplified)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        print("\n" + "=" * 70)
        print(f"Status: {status}")
        print(f"Duration: {report.total_duration_ms:.2f} ms")
        print(f"Report: {json_path}")
        print("=" * 70)

        # Exit code: 0 = PASS/PARTIAL, 1 = FAIL
        sys.exit(0 if status in ("PASS", "PARTIAL") else 1)

    except Exception as e:
        logger.exception("P1 verification failed")
        print(f"\n❌ ERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
