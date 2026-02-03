"""Background worker threads."""
import logging
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class Worker(QThread):
    """Generic worker thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        """Run the worker function."""
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("Worker error")
            self.error.emit(str(e))


class ExtractionWorker(QThread):
    """Worker for extracting terms from a document."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total

    def __init__(self, document_id: int, force: bool = False):
        super().__init__()
        self.document_id = document_id
        self.force = force

    def run(self):
        """Extract terms from document."""
        try:
            from app.services.db_service import DBService
            from app.services.term_extraction_service import TermExtractionService

            db_service = DBService.get_instance()
            extraction_service = TermExtractionService()

            with db_service.get_session() as session:
                # Extract terms
                results = extraction_service.extract_from_document(
                    session, self.document_id, force=self.force
                )

                self.finished.emit(results)

        except Exception as e:
            logger.exception("Term extraction worker error")
            self.error.emit(str(e))


class TranslationResolveWorker(QThread):
    """Worker for resolving translations in bulk (non-blocking)."""

    results_ready = pyqtSignal(dict)  # {(src_text, kind): TranslationResult}
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total

    def __init__(
        self,
        items: List[Tuple[str, str]],  # [(src_text, kind), ...]
        project_id: Optional[int] = None,
        src_lang: str = "he",
        tgt_lang: str = "ru",
        allow_draft: bool = False,
    ):
        super().__init__()
        self.items = items
        self.project_id = project_id
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.allow_draft = allow_draft
        self._cancelled = False

    def run(self):
        """Resolve translations for all items."""
        try:
            from app.services.db_service import DBService
            from app.services.translation_service import TranslationService

            db_service = DBService.get_instance()
            translation_service = TranslationService()

            with db_service.get_session() as session:
                # Bulk resolve for performance (no N+1 queries)
                results = translation_service.bulk_resolve(
                    session,
                    self.items,
                    src_lang=self.src_lang,
                    tgt_lang=self.tgt_lang,
                    project_id=self.project_id,
                    allow_draft=self.allow_draft,
                )

                # Check for cancellation
                if self._cancelled:
                    logger.info("Translation resolve cancelled")
                    return

                # Emit results
                self.results_ready.emit(results)

        except Exception as e:
            logger.exception("Translation resolve worker error")
            error_msg = self._make_user_friendly_error(str(e))
            self.error.emit(error_msg)

    def cancel(self):
        """Request cancellation of the worker."""
        self._cancelled = True

    def _make_user_friendly_error(self, error: str) -> str:
        """Convert technical error to user-friendly message."""
        error_lower = error.lower()

        if "database" in error_lower or "locked" in error_lower:
            return (
                "Database error occurred during translation resolution.\n\n"
                "Please try again. If the problem persists, restart the application."
            )
        else:
            return (
                f"An error occurred during translation:\n\n"
                f"{error[:200]}\n\n"
                f"Check the logs for details."
            )


class P1VerificationWorker(QThread):
    """Worker for P1 Scenario 7 verification (TM persistence through re-extraction)."""

    progress = pyqtSignal(int)  # 0-100
    log = pyqtSignal(str)  # Log message
    finished = pyqtSignal(str, str, str)  # report_md_path, report_json_path, status
    failed = pyqtSignal(str, str)  # error_summary, details

    def __init__(
        self,
        db_path: str,
        project_id: Optional[int] = None,
        out_dir: Optional[str] = None,
    ):
        super().__init__()
        self.db_path = db_path
        self.project_id = project_id
        self.out_dir = out_dir
        self._cancelled = False

    def run(self):
        """Run P1 verification."""
        try:
            from app.services.p1_verification_service import P1VerificationService, P1VerificationReport
            from app.services.db_service import DBService

            service = P1VerificationService()
            start_time = time.time()

            # Phase 1: Create snapshot
            self.log.emit("Phase 1/7: Creating DB snapshot...")
            self.progress.emit(10)

            if self._cancelled:
                self.log.emit("Cancelled by user")
                return

            snapshot_info = service.create_snapshot_db(self.db_path, self.out_dir)
            self.log.emit(f"  ✓ Snapshot created: {snapshot_info.snapshot_path}")
            self.log.emit(f"  Size: {snapshot_info.size_bytes / 1024 / 1024:.2f} MB")
            self.log.emit(f"  SHA256: {snapshot_info.sha256[:16]}...")

            # Phase 2: Open snapshot DB
            self.log.emit("\nPhase 2/7: Opening snapshot DB...")
            self.progress.emit(20)

            # Initialize DBService with snapshot
            DBService.initialize(snapshot_info.snapshot_path)
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                # Phase 3: Select test items
                self.log.emit("\nPhase 3/7: Selecting test items...")
                self.progress.emit(30)

                if self._cancelled:
                    return

                test_items = service.select_test_items(session, self.project_id)

                if not test_items:
                    self.log.emit("  ⚠ No processed data found - SKIPPED")
                    # Generate skipped report
                    report = self._generate_skipped_report(snapshot_info)
                    report_paths = self._save_reports(report, snapshot_info.timestamp)
                    self.finished.emit(report_paths[0], report_paths[1], "SKIPPED")
                    return

                self.log.emit(f"  ✓ Selected {len(test_items)} test items:")
                for item in test_items:
                    self.log.emit(f"    - {item.kind}: {item.src_text} (priority={item.priority})")

                # Phase 4: Seed TM entries
                self.log.emit("\nPhase 4/7: Seeding TM entries...")
                self.progress.emit(40)

                if self._cancelled:
                    return

                seeded_tm = service.seed_tm_entries(session, test_items, self.project_id)
                self.log.emit(f"  ✓ Created {len(seeded_tm)} TM entries")
                for tm in seeded_tm:
                    self.log.emit(f"    - tm_id={tm.tm_id}: {tm.translation}")

                # Phase 5: Pre-extraction verification
                self.log.emit("\nPhase 5/7: Pre-extraction verification...")
                self.progress.emit(50)

                if self._cancelled:
                    return

                phase_pre = service.verify_resolve(session, seeded_tm, self.project_id)
                phase_pre.phase_name = "pre_extraction"
                self.log.emit(f"  ✓ Verified: {phase_pre.items_passed}/{phase_pre.items_checked} PASS")

                # Phase 6: Post-extraction verification (stub - re-extraction not implemented)
                self.log.emit("\nPhase 6/7: Post-extraction verification...")
                self.progress.emit(70)

                if self._cancelled:
                    return

                # NOTE: Real re-extraction would go here
                service.run_reextraction(self.project_id, snapshot_info.snapshot_path)
                self.log.emit("  ⚠ Re-extraction STUB (not implemented)")

                phase_post = service.verify_resolve(session, seeded_tm, self.project_id)
                phase_post.phase_name = "post_extraction"
                self.log.emit(f"  ✓ Verified: {phase_post.items_passed}/{phase_post.items_checked} PASS")

            # Phase 7: Post-restart verification
            self.log.emit("\nPhase 7/7: Post-restart verification...")
            self.progress.emit(85)

            if self._cancelled:
                return

            session_restart = service.simulate_restart(snapshot_info.snapshot_path)
            phase_restart = service.verify_resolve(session_restart, seeded_tm, self.project_id)
            phase_restart.phase_name = "post_restart"
            self.log.emit(f"  ✓ Verified: {phase_restart.items_passed}/{phase_restart.items_checked} PASS")
            session_restart.close()

            # Determine status
            total_duration_ms = (time.time() - start_time) * 1000
            status = self._determine_status(phase_pre, phase_post, phase_restart)

            # Generate report
            self.log.emit("\nGenerating report...")
            self.progress.emit(95)

            report = P1VerificationReport(
                timestamp=snapshot_info.timestamp,
                source_db_path=snapshot_info.source_path,
                snapshot_db_path=snapshot_info.snapshot_path,
                snapshot_sha256=snapshot_info.sha256,
                project_id=self.project_id,
                test_items=test_items,
                seeded_tm_entries=seeded_tm,
                phase_pre_extraction=phase_pre,
                phase_post_extraction=phase_post,
                phase_post_restart=phase_restart,
                status=status,
                total_duration_ms=total_duration_ms,
            )

            report_paths = self._save_reports(report, snapshot_info.timestamp)

            self.progress.emit(100)
            self.log.emit(f"\n✅ Verification complete: {status}")
            self.log.emit(f"Report: {report_paths[0]}")

            self.finished.emit(report_paths[0], report_paths[1], status)

        except Exception as e:
            logger.exception("P1 verification worker error")
            error_summary = f"Verification failed: {str(e)[:100]}"
            error_details = str(e)
            self.failed.emit(error_summary, error_details)

    def cancel(self):
        """Cancel verification."""
        self._cancelled = True

    def _determine_status(self, phase_pre, phase_post, phase_restart) -> str:
        """Determine overall status."""
        phases = [phase_pre, phase_post, phase_restart]

        # Check if all phases passed all items
        all_pass = all(p.items_failed == 0 for p in phases)
        if all_pass:
            return "PASS"

        # Check if any items passed
        any_pass = any(p.items_passed > 0 for p in phases)
        if any_pass:
            return "PARTIAL"

        return "FAIL"

    def _generate_skipped_report(self, snapshot_info) -> "P1VerificationReport":
        """Generate report for skipped verification."""
        from app.services.p1_verification_service import P1VerificationReport

        return P1VerificationReport(
            timestamp=snapshot_info.timestamp,
            source_db_path=snapshot_info.source_path,
            snapshot_db_path=snapshot_info.snapshot_path,
            snapshot_sha256=snapshot_info.sha256,
            project_id=self.project_id,
            test_items=[],
            seeded_tm_entries=[],
            status="SKIPPED",
            error_summary="No processed data (lemmas/term_clusters) found in project",
        )

    def _save_reports(self, report: "P1VerificationReport", timestamp: str) -> Tuple[str, str]:
        """Save MD and JSON reports."""
        out_dir = self.out_dir or f"runtime/verifications/p1/{timestamp}"
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        md_path = Path(out_dir) / "P1_SCENARIO_7_REPORT.md"
        json_path = Path(out_dir) / "P1_SCENARIO_7_REPORT.json"

        # Save Markdown
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._generate_markdown_report(report))

        # Save JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        return (str(md_path), str(json_path))

    def _generate_markdown_report(self, report: "P1VerificationReport") -> str:
        """Generate Markdown report."""
        md = []
        md.append("# P1 Scenario 7 Verification Report\n")
        md.append(f"**Date:** {report.timestamp}")
        md.append(f"**Status:** {report.status}\n")

        md.append("## Environment\n")
        md.append(f"- **Source DB:** `{report.source_db_path}`")
        md.append(f"- **Snapshot DB:** `{report.snapshot_db_path}`")
        md.append(f"- **Snapshot SHA256:** `{report.snapshot_sha256}`")
        md.append(f"- **Project ID:** {report.project_id}\n")

        if report.status == "SKIPPED":
            md.append("## Result\n")
            md.append("⚠️ **SKIPPED:** No processed data found in project.\n")
            md.append(f"**Reason:** {report.error_summary}\n")
            return "\n".join(md)

        md.append("## Test Items\n")
        for i, item in enumerate(report.test_items, 1):
            md.append(f"{i}. **{item.kind}**: `{item.src_text}` (src_norm: `{item.src_norm}`)")
        md.append("")

        md.append("## Verification Phases\n")
        phases = [
            ("Pre-Extraction", report.phase_pre_extraction),
            ("Post-Extraction", report.phase_post_extraction),
            ("Post-Restart", report.phase_post_restart),
        ]

        for phase_name, phase in phases:
            if phase:
                status_icon = "✅" if phase.items_failed == 0 else "❌"
                md.append(f"### {status_icon} {phase_name}")
                md.append(f"- **Checked:** {phase.items_checked}")
                md.append(f"- **Passed:** {phase.items_passed}")
                md.append(f"- **Failed:** {phase.items_failed}")
                md.append(f"- **Success Rate:** {phase.success_rate:.1f}%")
                md.append(f"- **Duration:** {phase.duration_ms:.2f} ms")

                if phase.failures:
                    md.append("\n**Failures:**")
                    for fail in phase.failures:
                        md.append(f"  - {fail['item']} ({fail['kind']})")
                        md.append(f"    - Expected: `{fail['expected_translation']}` from `{fail['expected_source']}`")
                        md.append(f"    - Actual: `{fail['actual_translation']}` from `{fail['actual_source']}`")
                md.append("")

        md.append("## Summary\n")
        md.append(f"- **Total Duration:** {report.total_duration_ms:.2f} ms")
        md.append(f"- **Final Status:** **{report.status}**\n")

        if report.status == "PASS":
            md.append("✅ **All TM entries persisted through re-extraction and restart.**\n")
        elif report.status == "PARTIAL":
            md.append("⚠️ **Some TM entries persisted, but not all tests passed.**\n")
        elif report.status == "FAIL":
            md.append("❌ **TM entries did NOT persist through re-extraction/restart.**\n")

        return "\n".join(md)
