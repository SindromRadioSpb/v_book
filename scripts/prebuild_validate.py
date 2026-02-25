"""Prebuild validation script for HDLE Premium.

Runs comprehensive checks before building installer:
- FTS table presence and consistency
- Project lifecycle (create/delete)
- Export/import bundle roundtrip
- Database integrity

Usage:
    python scripts/prebuild_validate.py [--db-path PATH]

Exit codes:
    0 - PASS or PASS_WITH_SKIPS
    1 - FAIL
"""

import argparse
from datetime import datetime, timezone
from dataclasses import dataclass
import importlib
import logging
import sqlite3
import sys
import tempfile
from uuid import uuid4
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROFILE_DEFAULT = "default"
PROFILE_REFERENCE_RO = "reference-ro"

CHECK_PASSED = "PASSED"
CHECK_FAILED = "FAILED"
CHECK_SKIPPED = "SKIPPED"

FINAL_PASS = "PASS"
FINAL_PASS_WITH_SKIPS = "PASS_WITH_SKIPS"
FINAL_FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    details: str = ""


def _unique_export_project_name() -> str:
    """Generate collision-proof project name for export/import validation."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid4().hex[:8]
    return f"__EXPORT_TEST__{ts}_{suffix}"


def check_required_local_modules() -> bool:
    """Check that required local runtime modules are importable."""
    logger.info("=" * 70)
    logger.info("CHECK 0: Required Local Modules")
    logger.info("=" * 70)

    required_modules = ["phonikud"]
    all_ok = True

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    for module_name in required_modules:
        try:
            importlib.import_module(module_name)
            logger.info(f"  {module_name}: IMPORT OK")
        except Exception as exc:
            all_ok = False
            logger.error(f"  {module_name}: IMPORT FAILED ({exc})")

    if all_ok:
        logger.info("[OK] Required local modules import successfully")
    else:
        logger.error("[!!] Required local module import checks failed")

    return all_ok


def check_fts_presence(db_path: Path) -> bool:
    """Check that FTS tables exist and are consistent."""
    logger.info("=" * 70)
    logger.info("CHECK 1: FTS Table Presence")
    logger.info("=" * 70)

    from app.infra.fts_manager import check_fts_exists

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            sentence_fts_exists, term_fts_exists = check_fts_exists(conn)

            # Check for issues
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_sentence%'"
            )
            sentence_triggers = [row[0] for row in cursor.fetchall()]

            issues = []
            if sentence_triggers and not sentence_fts_exists:
                issues.append(
                    "CRITICAL: sentence triggers exist but sentence_fts table is missing!"
                )

            results = {
                "sentence_fts_exists": sentence_fts_exists,
                "term_fts_exists": term_fts_exists,
                "issues": issues,
            }
        finally:
            conn.close()

        if results["issues"]:
            logger.error("FTS issues found:")
            for issue in results["issues"]:
                logger.error(f"  - {issue}")
            return False

        logger.info(f"  sentence_fts: {'EXISTS' if results['sentence_fts_exists'] else 'MISSING'}")
        logger.info(f"  term_fts:     {'EXISTS' if results['term_fts_exists'] else 'MISSING'}")
        logger.info("[OK] FTS tables present and consistent")
        return True

    except Exception as e:
        logger.exception(f"FTS check failed: {e}")
        return False


def check_project_lifecycle(db_path: Path) -> bool:
    """Test project creation and deletion."""
    logger.info("\n" + "=" * 70)
    logger.info("CHECK 2: Project Lifecycle (Create/Delete)")
    logger.info("=" * 70)

    from app.services.db_service import DBService
    from app.services.project_service import ProjectService

    try:
        # Reset singleton
        DBService._instance = None
        DBService._db_manager = None

        # Initialize DB service
        db_service = DBService.initialize(db_path)
        project_service = ProjectService()

        # Create project
        logger.info("  Creating test project...")
        with db_service.get_session() as session:
            library = project_service.get_or_create_default_library(session)
            project = project_service.create_project(
                session,
                name="__PREBUILD_TEST_PROJECT__",
                description="Temporary project for prebuild validation",
                library=library,
            )
            project_id = project.project_id
            session.commit()

        logger.info(f"  Project created: ID={project_id}")

        # Verify project exists
        with db_service.get_session() as session:
            project = project_service.get_project(session, project_id)
            if not project:
                logger.error("  Project not found after creation!")
                return False

        # Delete project
        logger.info("  Deleting test project...")
        with db_service.get_session() as session:
            report = project_service.delete_project(session, project_id)
            if not report.success:
                logger.error(f"  Delete failed: {report.error_message}")
                return False

        # Verify project is gone
        with db_service.get_session() as session:
            project = project_service.get_project(session, project_id)
            if project:
                logger.error("  Project still exists after deletion!")
                return False

        logger.info("[OK] Project lifecycle working correctly")
        return True

    except Exception as e:
        logger.exception(f"Project lifecycle check failed: {e}")
        return False

    finally:
        # Cleanup
        if DBService._instance:
            DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None


def check_export_import(db_path: Path) -> bool:
    """Test export/import bundle roundtrip."""
    logger.info("\n" + "=" * 70)
    logger.info("CHECK 3: Export/Import Bundle Roundtrip")
    logger.info("=" * 70)

    from app.services.db_service import DBService
    from app.services.project_service import ProjectService
    from app.services.project_exchange.export_engine import ProjectExportEngine
    from app.services.project_exchange.import_engine import ProjectImportEngine
    from app.services.project_exchange.dto import ExportOptions, ImportOptions

    temp_bundle = None
    project_id = None
    import_project_id = None
    project_name = _unique_export_project_name()
    library_id = None
    db_service = None
    project_service = None

    try:
        # Reset singleton
        DBService._instance = None
        DBService._db_manager = None

        # Initialize DB service
        db_service = DBService.initialize(db_path)
        project_service = ProjectService()
        export_engine = ProjectExportEngine()
        import_engine = ProjectImportEngine()

        # Create a test project
        logger.info("  Creating test project for export...")
        logger.info(f"  Attempting project create: name={project_name}")
        with db_service.get_session() as session:
            try:
                library = project_service.get_or_create_default_library(session)
                library_id = int(getattr(library, "library_id", 0) or 0)
                logger.info(f"  Using library_id={library_id}")
                project = project_service.create_project(
                    session,
                    name=project_name,
                    description="Test project for export",
                    library=library,
                )
                project_id = project.project_id
                session.commit()
            except Exception:
                session.rollback()
                raise

        logger.info(f"  Project created: ID={project_id}")

        # Export bundle
        logger.info("  Exporting project bundle...")
        with tempfile.NamedTemporaryFile(suffix=".hdleproj", delete=False) as f:
            temp_bundle = Path(f.name)

        export_report = export_engine.export_project(
            project_id=project_id,
            out_path=temp_bundle,
            options=ExportOptions(),
        )

        if not export_report.success:
            logger.error(f"  Export failed: {export_report.error_message}")
            return False

        logger.info(f"  Export successful: {temp_bundle.stat().st_size} bytes")

        # Import bundle
        logger.info("  Importing project bundle...")
        import_report = import_engine.import_project(
            bundle_path=temp_bundle,
            options=ImportOptions(rename_if_conflict=True),
        )

        if not import_report.success:
            logger.error(f"  Import failed: {import_report.error_message}")
            return False

        import_project_id = int(getattr(import_report, "new_project_id", 0) or 0)
        logger.info(f"  Import successful: project ID={import_project_id or 'N/A'}")

        logger.info("[OK] Export/import roundtrip successful")
        return True

    except Exception as e:
        logger.exception(f"Export/import check failed: {e}")
        logger.error(
            "  Context: attempted project_name=%s, library_id=%s",
            project_name,
            library_id if library_id is not None else "unknown",
        )
        return False

    finally:
        # Cleanup test projects, even on failure.
        if db_service and project_service and (project_id or import_project_id):
            try:
                logger.info("  Cleaning up test projects...")
                with db_service.get_session() as session:
                    try:
                        if project_id:
                            project_service.delete_project(session, int(project_id))
                        if import_project_id and import_project_id != project_id:
                            project_service.delete_project(session, int(import_project_id))
                        session.commit()
                    except Exception:
                        session.rollback()
                        raise
            except Exception as cleanup_exc:
                logger.warning(f"  Cleanup warning: {cleanup_exc}")

        # Cleanup temp bundle
        if temp_bundle and temp_bundle.exists():
            try:
                temp_bundle.unlink()
            except Exception:
                pass

        # Cleanup DB service
        if DBService._instance:
            DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None


def check_database_integrity(db_path: Path) -> bool:
    """Check database integrity."""
    logger.info("\n" + "=" * 70)
    logger.info("CHECK 4: Database Integrity")
    logger.info("=" * 70)

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Quick check (faster than full integrity_check on large DB)
        logger.info("  Running PRAGMA quick_check...")
        cursor.execute("PRAGMA quick_check(10)")  # Check first 10 pages
        results = cursor.fetchall()

        if results and results[0][0] == "ok":
            logger.info("[OK] Database quick check passed")
            conn.close()
            return True
        else:
            logger.error(f"  Quick check found issues:")
            for row in results:
                logger.error(f"    {row[0]}")
            conn.close()
            return False

    except Exception as e:
        logger.exception(f"Database integrity check failed: {e}")
        return False


def _status_from_bool(ok: bool) -> str:
    return CHECK_PASSED if ok else CHECK_FAILED


def _compute_final_status(results: list[CheckResult]) -> str:
    if any(r.status == CHECK_FAILED for r in results):
        return FINAL_FAIL
    if any(r.status == CHECK_SKIPPED for r in results):
        return FINAL_PASS_WITH_SKIPS
    return FINAL_PASS


def run_prebuild_validation(
    db_path: Path,
    *,
    profile: str = PROFILE_DEFAULT,
    skip_export_import: bool = False,
    skip_quick_check: bool = False,
) -> tuple[str, list[CheckResult]]:
    """Run validation checks and return final status + per-check results."""
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            name="Required Local Modules",
            status=_status_from_bool(check_required_local_modules()),
        )
    )
    results.append(
        CheckResult(
            name="FTS Presence",
            status=_status_from_bool(check_fts_presence(db_path)),
        )
    )

    if profile == PROFILE_REFERENCE_RO:
        results.append(
            CheckResult(
                name="Project Lifecycle",
                status=CHECK_SKIPPED,
                details="Skipped in reference-ro profile (write check).",
            )
        )
        if not skip_export_import:
            results.append(
                CheckResult(
                    name="Export/Import",
                    status=CHECK_SKIPPED,
                    details="Skipped in reference-ro profile (write check).",
                )
            )
    else:
        results.append(
            CheckResult(
                name="Project Lifecycle",
                status=_status_from_bool(check_project_lifecycle(db_path)),
            )
        )
        if not skip_export_import:
            results.append(
                CheckResult(
                    name="Export/Import",
                    status=_status_from_bool(check_export_import(db_path)),
                )
            )

    if skip_quick_check:
        results.append(
            CheckResult(
                name="Database Integrity",
                status=CHECK_SKIPPED,
                details="Skipped by --skip-quick-check.",
            )
        )
    else:
        results.append(
            CheckResult(
                name="Database Integrity",
                status=_status_from_bool(check_database_integrity(db_path)),
            )
        )

    final_status = _compute_final_status(results)
    return final_status, results


def main():
    parser = argparse.ArgumentParser(
        description="Prebuild validation for HDLE Premium"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(r"J:\Project_Vibe\V_book\hdle_premium.db"),
        help="Path to database (default: dev DB)",
    )
    parser.add_argument(
        "--skip-export-import",
        action="store_true",
        help="Skip export/import check (faster)",
    )
    parser.add_argument(
        "--profile",
        choices=[PROFILE_DEFAULT, PROFILE_REFERENCE_RO],
        default=PROFILE_DEFAULT,
        help="Validation profile: default or reference-ro (readonly huge DB)",
    )
    parser.add_argument(
        "--skip-quick-check",
        action="store_true",
        help="Skip PRAGMA quick_check (useful for very large DB pipelines)",
    )
    args = parser.parse_args()

    db_path = args.db_path
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        sys.exit(1)

    logger.info("\n" + "=" * 70)
    logger.info("HDLE Premium - Prebuild Validation")
    logger.info("=" * 70)
    logger.info(f"Database: {db_path}")
    logger.info(f"Size: {db_path.stat().st_size / 1024 / 1024:.1f} MB")
    logger.info(f"Profile: {args.profile}")
    logger.info("")

    final_status, results = run_prebuild_validation(
        db_path,
        profile=args.profile,
        skip_export_import=bool(args.skip_export_import),
        skip_quick_check=bool(args.skip_quick_check),
    )

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)

    for result in results:
        if result.status == CHECK_PASSED:
            prefix = "[OK]"
        elif result.status == CHECK_SKIPPED:
            prefix = "[--]"
        else:
            prefix = "[!!]"

        line = f"  {result.name:.<40} {prefix} {result.status}"
        if result.details:
            line = f"{line} ({result.details})"
        logger.info(line)

    logger.info("=" * 70)

    if final_status == FINAL_PASS:
        logger.info("\n[OK] ALL CHECKS PASSED - Ready for build")
        sys.exit(0)
    if final_status == FINAL_PASS_WITH_SKIPS:
        logger.info("\n[OK] PASS_WITH_SKIPS - Read-only profile checks completed")
        sys.exit(0)

    if final_status == FINAL_FAIL:
        logger.error("\n[!!] SOME CHECKS FAILED - Fix issues before build")
        sys.exit(1)

    logger.error(f"\n[!!] Unknown final status: {final_status}")
    sys.exit(1)


if __name__ == "__main__":
    main()
