"""P3 Verification CLI Tool.

Usage:
    python -m app.tools.p3_verify [OPTIONS]

Creates snapshot of production DB and runs comprehensive P3 verification suite.
Never touches production DB directly.
"""

import argparse
import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.p3_verification_service import P3VerificationService
from app.services.db_service import DBService


def get_default_db_path() -> str:
    """Get default HDLE database path.

    Returns:
        Default DB path: %USERPROFILE%\AppData\Local\HDLE\hdle.db
    """
    user_profile = os.environ.get('USERPROFILE')
    if not user_profile:
        return ""

    db_path = Path(user_profile) / "AppData" / "Local" / "HDLE" / "hdle.db"
    return str(db_path)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="P3 Verification Gate - Production-safe verification of import/export/conflicts"
    )

    parser.add_argument(
        "--db",
        type=str,
        default=get_default_db_path(),
        help="Source database path (default: %%USERPROFILE%%\\AppData\\Local\\HDLE\\hdle.db)"
    )

    parser.add_argument(
        "--project-id",
        type=int,
        default=1,
        help="Project ID for testing (default: 1)"
    )

    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory for snapshot and reports (default: runtime/verifications/p3/<timestamp>)"
    )

    args = parser.parse_args()

    # Check if source DB exists
    if not Path(args.db).exists():
        print(f"❌ Database not found: {args.db}")
        print("")
        print("💡 Hint: Specify database path with --db option")
        print(f"   Example: python -m app.tools.p3_verify --db path/to/your.db")
        print("")
        print("Exit code: 2 (SKIPPED)")
        return 2

    # Determine output directory
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("runtime") / "verifications" / "p3" / timestamp

    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("P3 VERIFICATION GATE")
    print("=" * 80)
    print(f"Source DB: {args.db}")
    print(f"Project ID: {args.project_id}")
    print(f"Output Dir: {out_dir}")
    print("")

    # Create snapshot
    print("📸 Creating snapshot...")
    service = P3VerificationService()

    try:
        snapshot_path, snapshot_sha256 = service.create_snapshot(args.db, str(out_dir))
        print(f"✅ Snapshot created: {snapshot_path}")
        print(f"   SHA256: {snapshot_sha256}")
        print("")
    except Exception as e:
        print(f"❌ Failed to create snapshot: {e}")
        return 1

    # Initialize DBService with snapshot
    DBService.initialize(snapshot_path)

    try:
        db_service = DBService.get_instance()

        # Run verification
        print("🔍 Running verification suite...")
        print("")

        with db_service.get_session() as session:
            report = service.run(
                session,
                project_id=args.project_id,
                snapshot_path=snapshot_path,
                snapshot_sha256=snapshot_sha256,
            )

        # Print step results
        for step in report.steps:
            status_icon = "✅" if step.status == "PASS" else "❌" if step.status == "FAIL" else "⏭️"
            print(f"{status_icon} {step.name}: {step.status} ({step.elapsed_ms:.2f}ms)")
            if step.error:
                print(f"   Error: {step.error}")

        print("")
        print("=" * 80)
        print(f"OVERALL STATUS: {report.overall_status}")
        print(f"Total Time: {report.total_elapsed_ms:.2f}ms")
        print("=" * 80)
        print("")

        # Write reports
        json_path = out_dir / "P3_VERIFICATION_REPORT.json"
        md_path = out_dir / "P3_VERIFICATION_REPORT.md"

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(report.to_markdown())

        print(f"📄 Reports written:")
        print(f"   JSON: {json_path}")
        print(f"   MD:   {md_path}")
        print("")

        # Return exit code
        if report.overall_status == "PASS":
            print("✅ Verification PASSED")
            return 0
        else:
            print("❌ Verification FAILED")
            return 1

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    sys.exit(main())
