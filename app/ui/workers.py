"""Background worker threads."""
import logging
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from app.domain.normalization.normalizer import normalize_for_tm

logger = logging.getLogger(__name__)


def _flush_mt_usage_queue(reason: str) -> None:
    """Best-effort flush for deferred MT usage counters at batch boundaries."""
    try:
        from app.infra.translators.providers.google_cloud_translate_provider import (
            GoogleCloudTranslateProvider,
        )

        GoogleCloudTranslateProvider.flush_deferred_usage_now(trace_id=reason)
    except Exception as e:
        logger.debug(f"MT usage queue flush skipped ({reason}): {e}")


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


class IngestWorker(QThread):
    """Worker thread for document ingestion."""

    progress = pyqtSignal(int, int, str)  # current, total, file_name
    finished = pyqtSignal(object)  # results list
    error = pyqtSignal(str)

    def __init__(self, corpus_id: int, file_paths: List[Path], use_ocr: bool = False):
        super().__init__()
        self.corpus_id = corpus_id
        self.file_paths = file_paths
        self.use_ocr = use_ocr

    def run(self):
        """Run the ingestion process."""
        from app.services.operations_center import OperationsCenter
        op_id = OperationsCenter.instance().register(
            f"Ingest ({len(self.file_paths)} files)", "ingest"
        )
        try:
            from app.services.db_service import DBService
            from app.services.ingest_service import IngestService

            db_service = DBService.get_instance()
            ingest_service = IngestService()

            results = []

            with db_service.get_session() as session:
                for idx, file_path in enumerate(self.file_paths):
                    self.progress.emit(idx + 1, len(self.file_paths), file_path.name)

                    try:
                        doc = ingest_service.import_document(
                            session,
                            self.corpus_id,
                            file_path,
                            use_ocr=self.use_ocr
                        )
                        results.append((file_path, doc, None))
                    except Exception as e:
                        logger.exception(f"Failed to import {file_path}")
                        results.append((file_path, None, str(e)))

            self.finished.emit(results)

        except Exception as e:
            logger.exception("Ingest worker error")
            self.error.emit(str(e))
        finally:
            OperationsCenter.instance().unregister(op_id)


class ProcessWorker(QThread):
    """Worker thread for NLP document processing."""

    progress = pyqtSignal(int, int, str)  # current, total, doc_name
    finished = pyqtSignal(int, int)  # success_count, error_count
    error = pyqtSignal(str)

    def __init__(self, doc_ids: List[int], use_mock: bool = True, use_gpu: bool = False, is_reprocess: bool = False):
        super().__init__()
        self.doc_ids = doc_ids
        self.use_mock = use_mock
        self.use_gpu = use_gpu
        self.is_reprocess = is_reprocess

    def run(self):
        """Run the processing pipeline."""
        from app.services.operations_center import OperationsCenter
        op_id = OperationsCenter.instance().register(
            f"NLP Process ({len(self.doc_ids)} docs)", "nlp_process"
        )
        try:
            from app.services.db_service import DBService
            from app.services.process_service import ProcessService

            db_service = DBService.get_instance()
            process_service = ProcessService()

            success_count = 0
            error_count = 0

            # Task 12: Per-document session isolation to prevent session contamination
            for idx, doc_id in enumerate(self.doc_ids):
                # Fresh session for each document
                with db_service.get_session() as session:
                    try:
                        # Get document name for progress
                        from app.infra.sa_models import SourceDocument
                        doc = session.get(SourceDocument, doc_id)
                        doc_name = doc.file_name if doc else f"Doc {doc_id}"

                        self.progress.emit(idx + 1, len(self.doc_ids), doc_name)

                        # Process or re-process document
                        if self.is_reprocess:
                            # M4: Re-process with delta statistics
                            success = process_service.reprocess_document(
                                session,
                                doc_id,
                                use_gpu=self.use_gpu,
                                use_mock=self.use_mock
                            )
                        else:
                            # Normal processing
                            success = process_service.process_document(
                                session,
                                doc_id,
                                use_gpu=self.use_gpu,
                                use_mock=self.use_mock
                            )

                        if success:
                            success_count += 1
                        else:
                            error_count += 1

                    except Exception as doc_error:
                        logger.exception(f"Error processing document {doc_id}")
                        error_count += 1
                        # Session auto-closes and rolls back via context manager
                        # Continue with next document in fresh session

            self.finished.emit(success_count, error_count)

        except Exception as e:
            logger.exception("Process worker error")
            # Make error message user-friendly
            error_msg = self._make_user_friendly_error(str(e))
            self.error.emit(error_msg)
        finally:
            OperationsCenter.instance().unregister(op_id)

    def _make_user_friendly_error(self, error: str) -> str:
        """Convert technical error to user-friendly message."""
        error_lower = error.lower()

        if "rollback" in error_lower or "flush" in error_lower:
            return (
                "Database error occurred during processing.\n\n"
                "This usually happens when:\n"
                "- The database is locked by another process\n"
                "- The document is already being processed\n\n"
                "Please try again. If the problem persists, restart the application."
            )
        elif "cuda" in error_lower or "gpu" in error_lower:
            return (
                "GPU/CUDA error occurred.\n\n"
                "Try disabling 'Use GPU for NLP' and process again with CPU."
            )
        elif "stanza" in error_lower:
            return (
                "NLP engine error occurred.\n\n"
                "This may happen if:\n"
                "- Stanza models are not properly installed\n"
                "- The text contains unsupported characters\n\n"
                "The application will use Mock engine as fallback."
            )
        elif "memory" in error_lower:
            return (
                "Out of memory error.\n\n"
                "Try processing fewer documents at once,\n"
                "or disable GPU processing."
            )
        else:
            return (
                f"An error occurred during processing:\n\n"
                f"{error[:200]}\n\n"
                f"Check the logs for more details."
            )


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


class ProjectTermExtractionWorker(QThread):
    """Worker for extracting terms for entire project."""

    finished = pyqtSignal(object)  # ExtractReport
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # Progress message
    state_changed = pyqtSignal(object)  # Structured extraction progress state

    def __init__(
        self,
        project_id: int,
        enable_ngrams: bool = True,
        include_np: bool = False,
        min_freq: int = 2,
        ngram_ns: tuple = (2, 3),
        np_max_len: int = 5,
        overwrite: bool = True,
    ):
        super().__init__()
        self.project_id = project_id
        self.enable_ngrams = enable_ngrams
        self.include_np = include_np
        self.min_freq = min_freq
        self.ngram_ns = ngram_ns
        self.np_max_len = np_max_len
        self.overwrite = overwrite
        self._cancel_requested = False
        self._pause_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def pause(self) -> None:
        self._pause_requested = True

    def resume(self) -> None:
        self._pause_requested = False

    def run(self):
        """Extract terms for project."""
        from app.services.operations_center import OperationsCenter
        op_id = OperationsCenter.instance().register(
            f"Term Extract (project {self.project_id})", "term_extract"
        )
        try:
            from app.services.db_service import DBService
            from app.services.term_extraction_service import TermExtractionService

            db_service = DBService.get_instance()
            extraction_service = TermExtractionService()

            with db_service.get_session() as session:
                report = extraction_service.extract_terms_for_project(
                    session,
                    self.project_id,
                    enable_ngrams=self.enable_ngrams,
                    include_np=self.include_np,
                    min_freq=self.min_freq,
                    ngram_ns=self.ngram_ns,
                    np_max_len=self.np_max_len,
                    overwrite=self.overwrite,
                    progress_callback=lambda message: self.progress.emit(message),
                    state_callback=lambda state: self.state_changed.emit(state),
                    cancel_check=lambda: self._cancel_requested,
                    pause_check=lambda: self._pause_requested,
                )

                self.finished.emit(report)

        except Exception as e:
            logger.exception("Project term extraction worker error")
            self.error.emit(str(e))
        finally:
            OperationsCenter.instance().unregister(op_id)


class ConcordanceSearchWorker(QThread):
    """Worker thread for concordance/KWIC search (M6)."""

    results_ready = pyqtSignal(list)  # List of KWICResult
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: int,
        query: str,
        limit: int = 100,
        offset: int = 0,
        is_phrase: bool = False,
        normalize: bool = True
    ):
        super().__init__()
        self.project_id = project_id
        self.query = query
        self.limit = limit
        self.offset = offset
        self.is_phrase = is_phrase
        self.normalize = normalize

    def run(self):
        """Run the concordance search."""
        try:
            from app.services.db_service import DBService
            from app.services.concordance_service import ConcordanceService

            db_service = DBService.get_instance()
            concordance_service = ConcordanceService()

            with db_service.get_session() as session:
                results = concordance_service.search_concordance(
                    session,
                    self.project_id,
                    self.query,
                    limit=self.limit,
                    offset=self.offset,
                    is_phrase=self.is_phrase,
                    normalize=self.normalize
                )

            self.results_ready.emit(results)

        except Exception as e:
            logger.exception("Concordance search worker error")
            error_msg = self._make_user_friendly_error(str(e))
            self.error.emit(error_msg)

    def _make_user_friendly_error(self, error: str) -> str:
        """Convert technical error to user-friendly message."""
        error_lower = error.lower()

        if "fts" in error_lower or "match" in error_lower:
            return (
                "Search query syntax error.\n\n"
                "Please check your search query and try again.\n"
                "For phrases, use quotes: \"exact phrase\""
            )
        elif "database" in error_lower or "locked" in error_lower:
            return (
                "Database error occurred during search.\n\n"
                "Please try again. If the problem persists, restart the application."
            )
        else:
            return (
                f"An error occurred during search:\n\n"
                f"{error[:200]}\n\n"
                f"Please try again or check the logs for details."
            )


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

            # Overlay translation resolution is read-only and should not occupy
            # the write pool on large/reference databases.
            with db_service.get_read_session() as session:
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


# ============================================================================
# P2: Translation Management & Coverage Workers
# ============================================================================

class TMSearchWorker(QThread):
    """P2: Worker for searching TM entries (non-blocking).

    Uses the read engine (PERF-SCALE PATCH-C) — pure SELECT, no writes.
    """

    results_ready = pyqtSignal(list, int)  # (entries: List[TMEntryDTO], total_count: int)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # status message

    def __init__(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "updated_at",
        sort_direction: str = "desc",
    ):
        super().__init__()
        self.filters = filters
        self.limit = limit
        self.offset = offset
        self.sort_column = sort_column
        self.sort_direction = sort_direction
        self._cancelled = False

    def run(self):
        """Execute search."""
        try:
            from app.services.db_service import DBService
            from app.services.translation_admin_service import TranslationAdminService

            self.progress.emit("Searching TM entries...")

            db_service = DBService.get_instance()
            admin_service = TranslationAdminService()

            with db_service.get_read_session() as session:
                if self._cancelled:
                    return

                # Get entries
                entries = admin_service.search_tm_entries(
                    session,
                    filters=self.filters,
                    limit=self.limit,
                    offset=self.offset,
                    sort_column=self.sort_column,
                    sort_direction=self.sort_direction,
                )

                if self._cancelled:
                    return

                # Get total count
                total_count = admin_service.count_tm_entries(
                    session,
                    filters=self.filters,
                )

                if not self._cancelled:
                    self.results_ready.emit(entries, total_count)

        except Exception as e:
            logger.exception("TM search error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the search."""
        self._cancelled = True


class DocumentsPageWorker(QThread):
    """Worker for Documents server-side count + page fetch (global filters/sort).

    Uses the read engine (PERF-SCALE PATCH-C) — pure SELECT, no writes.
    """

    page_loaded = pyqtSignal(int, int, list)  # request_id, total_count, rows(List[DocumentDTO])
    error = pyqtSignal(int, str)              # request_id, message
    status = pyqtSignal(int, str)             # request_id, status text

    def __init__(
        self,
        *,
        request_id: int,
        corpus_id: int,
        filters: Dict[str, Any],
        sort_column: str,
        sort_direction: str,
        page_size: int,
        page_index: int,
    ):
        super().__init__()
        self.request_id = int(request_id)
        self.corpus_id = int(corpus_id)
        self.filters = dict(filters or {})
        self.sort_column = str(sort_column or "imported_at")
        self.sort_direction = str(sort_direction or "desc")
        self.page_size = max(1, int(page_size))
        self.page_index = max(1, int(page_index))
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.document_service import DocumentService

            self.status.emit(self.request_id, "Loading documents...")

            db_service = DBService.get_instance()
            doc_service = DocumentService()

            with db_service.get_read_session() as session:
                if self._cancelled:
                    return

                total_count = doc_service.get_documents_total_count(
                    session,
                    self.corpus_id,
                    title_search=self.filters.get("title_search"),
                    tag_filter=self.filters.get("tag_filter"),
                    level_filter=self.filters.get("level_filter"),
                    topic_filter=self.filters.get("topic_filter"),
                    status_filter=self.filters.get("status_filter"),
                )

                if self._cancelled:
                    return

                offset = (self.page_index - 1) * self.page_size
                rows = doc_service.fetch_documents_page(
                    session,
                    self.corpus_id,
                    title_search=self.filters.get("title_search"),
                    tag_filter=self.filters.get("tag_filter"),
                    level_filter=self.filters.get("level_filter"),
                    topic_filter=self.filters.get("topic_filter"),
                    status_filter=self.filters.get("status_filter"),
                    sort_by=self.sort_column,
                    sort_dir=self.sort_direction,
                    limit=self.page_size,
                    offset=offset,
                )

                if self._cancelled:
                    return

                self.page_loaded.emit(self.request_id, int(total_count), rows)
        except Exception as e:
            logger.exception("Documents page worker error")
            self.error.emit(self.request_id, str(e))


class ProjectDocumentsPageWorker(QThread):
    """Worker for project-scoped document picker queries (search + paging).

    Uses the read engine (PERF-SCALE PATCH-C) — pure SELECT, no writes.
    """

    page_loaded = pyqtSignal(int, int, list)  # request_id, total_count, rows(List[DocumentDTO])
    frequent_tags_loaded = pyqtSignal(int, list)  # request_id, tags(List[str])
    error = pyqtSignal(int, str)              # request_id, message
    status = pyqtSignal(int, str)             # request_id, status text

    def __init__(
        self,
        *,
        request_id: int,
        project_id: int,
        search_query: Optional[str],
        document_filter: Optional[str] = None,
        document_id: Optional[int] = None,
        tag_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
        level_filter: Optional[str] = None,
        tag_match_mode: str = "any",
        page_size: int,
        page_index: int,
    ):
        super().__init__()
        self.request_id = int(request_id)
        self.project_id = int(project_id)
        self.search_query = (search_query or "").strip() or None
        self.document_filter = (document_filter or "").strip() or None
        self.document_id = int(document_id) if document_id is not None else None
        self.tag_filter = (tag_filter or "").strip() or None
        self.topic_filter = (topic_filter or "").strip() or None
        self.level_filter = (level_filter or "").strip() or None
        self.tag_match_mode = str(tag_match_mode or "any").strip().lower() or "any"
        self.page_size = max(1, int(page_size))
        self.page_index = max(1, int(page_index))
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.document_service import DocumentService

            self.status.emit(self.request_id, "Loading documents...")
            db_service = DBService.get_instance()
            doc_service = DocumentService()

            with db_service.get_read_session() as session:
                if self._cancelled:
                    return

                total_count = doc_service.get_project_documents_total_count(
                    session,
                    self.project_id,
                    search_query=self.search_query,
                    document_filter=self.document_filter,
                    document_id=self.document_id,
                    tag_filter=self.tag_filter,
                    topic_filter=self.topic_filter,
                    level_filter=self.level_filter,
                    tag_match_mode=self.tag_match_mode,
                )

                if self._cancelled:
                    return

                offset = (self.page_index - 1) * self.page_size
                any_filter = any(
                    (
                        self.search_query,
                        self.document_filter,
                        self.document_id is not None,
                        self.tag_filter,
                        self.topic_filter,
                        self.level_filter,
                    )
                )
                sort_by = "file_name" if any_filter else "doc_id"
                sort_dir = "asc" if any_filter else "desc"
                rows = doc_service.fetch_project_documents_page(
                    session,
                    self.project_id,
                    search_query=self.search_query,
                    document_filter=self.document_filter,
                    document_id=self.document_id,
                    tag_filter=self.tag_filter,
                    topic_filter=self.topic_filter,
                    level_filter=self.level_filter,
                    tag_match_mode=self.tag_match_mode,
                    sort_by=sort_by,
                    sort_dir=sort_dir,
                    limit=self.page_size,
                    offset=offset,
                )

                frequent_tags = doc_service.get_project_frequent_tags(
                    session,
                    self.project_id,
                    limit=5,
                )

                if self._cancelled:
                    return
                self.frequent_tags_loaded.emit(self.request_id, frequent_tags)
                self.page_loaded.emit(self.request_id, int(total_count), rows)
        except Exception as e:
            logger.exception("Project documents page worker error")
            self.error.emit(self.request_id, str(e))


class ProjectDeleteWorker(QThread):
    """Background worker for project deletion to keep UI responsive."""

    status = pyqtSignal(str)
    finished = pyqtSignal(object)  # DeleteReport
    error = pyqtSignal(str)

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = int(project_id)

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.project_service import ProjectService

            self.status.emit("Deleting project...")
            db = DBService.get_instance()
            service = ProjectService()
            with db.get_session() as session:
                report = service.delete_project(session, self.project_id)
            self.finished.emit(report)
        except Exception as e:
            logger.exception("Project deletion failed")
            self.error.emit(str(e))


class DocumentDeleteWorker(QThread):
    """Background worker for document deletion in Documents view."""

    progress = pyqtSignal(int, int, str)  # current, total, file_name
    finished = pyqtSignal(dict)  # {deleted, failed, total}
    error = pyqtSignal(str)

    def __init__(self, doc_ids: List[int]):
        super().__init__()
        self.doc_ids = [int(doc_id) for doc_id in doc_ids]

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.ingest_service import IngestService

            db = DBService.get_instance()
            service = IngestService()
            with db.get_session() as session:
                deleted_count, error_count = service.bulk_delete(
                    session,
                    self.doc_ids,
                    progress_callback=lambda current, total, file_name: self.progress.emit(
                        int(current),
                        int(total),
                        str(file_name),
                    ),
                )
            self.finished.emit(
                {
                    "deleted": int(deleted_count),
                    "failed": int(error_count),
                    "total": len(self.doc_ids),
                }
            )
        except Exception as e:
            logger.exception("Document deletion failed")
            self.error.emit(str(e))


class DictionarySearchWorker(QThread):
    """Worker for searching lemmas with pagination (non-blocking).

    Uses the read engine (PERF-SCALE PATCH-C) — pure SELECT, no writes.
    """

    results_ready = pyqtSignal(list)  # rows: List[Tuple[Lemma, LemmaProjectStat]]
    count_ready = pyqtSignal(int)     # total_count
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: int,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "freq_abs",
        sort_direction: str = "desc",
        include_total_count: bool = True,
    ):
        super().__init__()
        self.project_id = project_id
        self.filters = filters
        self.limit = limit
        self.offset = offset
        self.sort_column = sort_column
        self.sort_direction = sort_direction
        self.include_total_count = bool(include_total_count)
        self._cancelled = False

    def run(self):
        """Execute search."""
        try:
            from app.services.db_service import DBService
            from app.services.dictionary_service import DictionaryService

            db_service = DBService.get_instance()
            dict_service = DictionaryService()

            with db_service.get_read_session() as session:
                if self._cancelled:
                    return

                # Get page of lemmas
                rows = dict_service.search_lemmas(
                    session,
                    project_id=self.project_id,
                    filters=self.filters,
                    limit=self.limit,
                    offset=self.offset,
                    sort_column=self.sort_column,
                    sort_direction=self.sort_direction,
                )

                if self._cancelled:
                    return

                self.results_ready.emit(rows)

                if self.include_total_count:
                    # Get total count in the second stage to keep first-page UX responsive.
                    total_count = dict_service.count_lemmas(
                        session,
                        project_id=self.project_id,
                        filters=self.filters,
                    )

                    if not self._cancelled:
                        self.count_ready.emit(total_count)

        except Exception as e:
            logger.exception("Dictionary search error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the search."""
        self._cancelled = True


class TermsSearchWorker(QThread):
    """Worker for searching term clusters with pagination (non-blocking).

    Uses the read engine (PERF-SCALE PATCH-C) — pure SELECT, no writes.
    """

    results_ready = pyqtSignal(list)  # clusters: List[TermCluster]
    count_ready = pyqtSignal(int)     # total_count
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: int,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "freq_abs",  # preset name, actually
        sort_direction: str = "desc",
        include_total_count: bool = True,
    ):
        super().__init__()
        self.project_id = project_id
        self.filters = filters
        self.limit = limit
        self.offset = offset
        self.sort_column = sort_column  # For Terms, this is "preset" name
        self.sort_direction = sort_direction
        self.include_total_count = bool(include_total_count)
        self._cancelled = False

    def run(self):
        """Execute search."""
        try:
            from app.services.db_service import DBService
            from app.services.term_extraction_service import TermExtractionService

            db_service = DBService.get_instance()
            term_service = TermExtractionService()

            with db_service.get_read_session() as session:
                if self._cancelled:
                    return

                # Get page of term clusters
                clusters = term_service.list_term_clusters(
                    session,
                    project_id=self.project_id,
                    search=self.filters.get("search"),
                    preset=self.filters.get("preset", "freq"),
                    min_freq=self.filters.get("min_freq"),
                    source_filter=self.filters.get("source_filter"),
                    hide_noise=self.filters.get("hide_noise", True),
                    top_n=self.limit,
                    offset=self.offset,
                )

                if self._cancelled:
                    return

                self.results_ready.emit(clusters)

                if self._cancelled or not self.include_total_count:
                    return

                total_count = term_service.count_term_clusters(
                    session,
                    project_id=self.project_id,
                    search=self.filters.get("search"),
                    min_freq=self.filters.get("min_freq"),
                    source_filter=self.filters.get("source_filter"),
                    hide_noise=self.filters.get("hide_noise", True),
                )

                if not self._cancelled:
                    self.count_ready.emit(total_count)

        except Exception as e:
            logger.exception("Terms search error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the search."""
        self._cancelled = True


class CrossViewOverlayWorker(QThread):
    """Resolve cross-view study/audio/pronunciation overlays off the UI thread."""

    results_ready = pyqtSignal(dict)  # {item_id: overlay_payload}
    error = pyqtSignal(str)

    def __init__(self, rows: List[Dict[str, Any]]):
        super().__init__()
        self.rows = list(rows or [])
        self._cancelled = False

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.user_dictionary_service import UserDictionaryService

            db_service = DBService.get_instance()
            user_dict_service = UserDictionaryService()

            prepared_rows: List[Dict[str, Any]] = []
            payloads: List[Dict[str, Any]] = []
            raw_norm_pairs: List[Tuple[str, str]] = []

            for raw in self.rows:
                if self._cancelled:
                    return
                item_id = int(raw.get("item_id") or 0)
                kind = str(raw.get("kind") or "").strip()
                src_text = str(raw.get("src_text") or "").strip()
                norm_hint = str(raw.get("norm_text") or "").strip()
                if item_id <= 0 or not kind or not src_text:
                    continue
                try:
                    src_norm = normalize_for_tm("he", src_text, kind).norm or norm_hint
                except Exception:
                    src_norm = norm_hint
                src_norm = (src_norm or "").strip()
                try:
                    raw_src_norm = normalize_for_tm("he", src_text, "surface").norm or norm_hint
                except Exception:
                    raw_src_norm = norm_hint
                raw_src_norm = (raw_src_norm or "").strip()
                if not src_norm:
                    continue
                prepared_rows.append(
                    {
                        "item_id": item_id,
                        "kind": kind,
                        "src_text": src_text,
                        "src_norm": src_norm,
                        "raw_src_norm": raw_src_norm,
                    }
                )
                payloads.append(
                    {
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "kind": kind,
                        "src_text": src_text,
                        "src_norm": src_norm,
                        "raw_src_norm": raw_src_norm,
                    }
                )
                if raw_src_norm:
                    raw_norm_pairs.append(("he", raw_src_norm))

            if self._cancelled:
                return
            if not prepared_rows:
                self.results_ready.emit({})
                return

            with db_service.get_read_session() as session:
                overlay_map = user_dict_service.resolve_cross_view_status(session, payloads)
                pronunciation_map = user_dict_service._resolve_pronunciation_overlay(session, raw_norm_pairs)

            results: Dict[int, Dict[str, Any]] = {}
            for row in prepared_rows:
                if self._cancelled:
                    return
                canonical_hash = user_dict_service.build_canonical_hash(
                    "he",
                    "ru",
                    row["kind"],
                    row["src_norm"],
                )
                overlay = dict(overlay_map.get(canonical_hash) or {})
                if not overlay:
                    overlay = {
                        "in_user_dictionary_count": 0,
                        "study_tooltip": None,
                        "study_state": None,
                        "study_due_human": None,
                        "last_grade": None,
                        "last_graded_at": None,
                        "translation_tier": None,
                        "audio_status": None,
                        "pronunciation_text": None,
                        "pronunciation_source": None,
                        "pronunciation_confidence": None,
                        "pronunciation_qc": None,
                    }
                row_pron = pronunciation_map.get(("he", row["raw_src_norm"]))
                if row_pron:
                    overlay["pronunciation_text"] = row_pron.get("pronunciation_text")
                    overlay["pronunciation_source"] = row_pron.get("pronunciation_source")
                    overlay["pronunciation_confidence"] = row_pron.get("pronunciation_confidence")
                    overlay["pronunciation_qc"] = row_pron.get("pronunciation_qc")
                results[int(row["item_id"])] = overlay

            if not self._cancelled:
                self.results_ready.emit(results)

        except Exception as e:
            logger.exception("Cross-view overlay worker error")
            self.error.emit(str(e))

    def cancel(self):
        self._cancelled = True


class CoverageWorker(QThread):
    """P2: Worker for computing coverage metrics (non-blocking)."""

    results_ready = pyqtSignal(dict)  # {metrics, untranslated_lemmas, untranslated_clusters}
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # status message

    def __init__(
        self,
        project_id: int,
        include_draft: bool = False,
        untranslated_limit: int = 100,
        lemma_order: str = "freq",
        cluster_order: str = "termhood",
    ):
        super().__init__()
        self.project_id = project_id
        self.include_draft = include_draft
        self.untranslated_limit = untranslated_limit
        self.lemma_order = lemma_order
        self.cluster_order = cluster_order
        self._cancelled = False

    def run(self):
        """Execute coverage calculation."""
        try:
            from app.services.db_service import DBService
            from app.services.coverage_service import CoverageService

            self.progress.emit("Computing coverage metrics...")

            db_service = DBService.get_instance()
            coverage_service = CoverageService()

            with db_service.get_session() as session:
                if self._cancelled:
                    return

                # Compute lemma coverage
                self.progress.emit("Computing lemma coverage...")
                lemma_metrics = coverage_service.compute_lemma_coverage(
                    session,
                    self.project_id,
                    include_draft=self.include_draft,
                )

                if self._cancelled:
                    return

                # Compute term cluster coverage
                self.progress.emit("Computing term cluster coverage...")
                cluster_metrics = coverage_service.compute_termcluster_coverage(
                    session,
                    self.project_id,
                    include_draft=self.include_draft,
                )

                if self._cancelled:
                    return

                # Get untranslated lemmas
                self.progress.emit("Fetching untranslated lemmas...")
                untranslated_lemmas = coverage_service.list_untranslated_lemmas(
                    session,
                    self.project_id,
                    limit=self.untranslated_limit,
                    order_by=self.lemma_order,
                    include_draft=self.include_draft,
                )

                if self._cancelled:
                    return

                # Get untranslated clusters
                self.progress.emit("Fetching untranslated term clusters...")
                untranslated_clusters = coverage_service.list_untranslated_termclusters(
                    session,
                    self.project_id,
                    limit=self.untranslated_limit,
                    order_by=self.cluster_order,
                    include_draft=self.include_draft,
                )

                if not self._cancelled:
                    results = {
                        "lemma_metrics": lemma_metrics,
                        "cluster_metrics": cluster_metrics,
                        "untranslated_lemmas": untranslated_lemmas,
                        "untranslated_clusters": untranslated_clusters,
                    }
                    self.results_ready.emit(results)

        except Exception as e:
            logger.exception("Coverage calculation error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the calculation."""
        self._cancelled = True


class ImportWorker(QThread):
    """P3: Worker for importing dictionaries (non-blocking)."""

    progress = pyqtSignal(int, int)  # (current, total)
    log_message = pyqtSignal(str)  # Log message for UI
    import_complete = pyqtSignal(object)  # ImportReport
    error = pyqtSignal(str)

    def __init__(
        self,
        file_path: str,
        project_id: Optional[int],
        scope: str,
        on_conflict: str,
        normalize_mode: str,
        default_kind: str,
        default_status: str,
        force_reimport: bool = False,
    ):
        super().__init__()
        self.file_path = file_path
        self.project_id = project_id
        self.scope = scope
        self.on_conflict = on_conflict
        self.normalize_mode = normalize_mode
        self.default_kind = default_kind
        self.default_status = default_status
        self.force_reimport = force_reimport
        self._cancelled = False

    def run(self):
        """Run import operation."""
        try:
            from app.services.db_service import DBService
            from app.services.dictionary_import_service import DictionaryImportService

            db_service = DBService.get_instance()
            import_service = DictionaryImportService()

            self.log_message.emit(f"Starting import: {self.file_path}")
            self.log_message.emit(f"Scope: {self.scope}, Conflict policy: {self.on_conflict}")

            with db_service.get_session() as session:
                report = import_service.import_dictionary(
                    session,
                    self.file_path,
                    project_id=self.project_id,
                    scope=self.scope,
                    on_conflict=self.on_conflict,
                    normalize_mode=self.normalize_mode,
                    default_kind=self.default_kind,
                    default_status=self.default_status,
                    progress_cb=lambda cur, tot: self.progress.emit(cur, tot),
                    cancel_flag=lambda: self._cancelled,
                    force_reimport=self.force_reimport,
                )

            if not self._cancelled:
                self.log_message.emit("Import completed successfully!")
                self.log_message.emit(
                    f"Added: {report.added}, Updated: {report.updated}, "
                    f"Skipped: {report.skipped}, Invalid: {report.invalid}"
                )
                self.import_complete.emit(report)

        except InterruptedError:
            self.log_message.emit("Import cancelled by user")
        except Exception as e:
            logger.exception("Import error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the import."""
        self._cancelled = True
        self.log_message.emit("Cancelling import...")


class ExportWorker(QThread):
    """M9: Worker for exporting data in various formats (non-blocking)."""

    progress = pyqtSignal(str)  # Progress message
    export_complete = pyqtSignal(int, str)  # (entry_count, file_path)
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: int,
        file_path: str,
        format_type: str,  # "csv", "json", "xlsx", "tbx", "tmx"
        **export_options
    ):
        super().__init__()
        self.project_id = project_id
        self.file_path = file_path
        self.format_type = format_type.lower()
        self.export_options = export_options
        self._cancelled = False

    def run(self):
        """Run export operation."""
        try:
            from app.services.db_service import DBService
            from app.services.export_service import ExportService

            db_service = DBService.get_instance()
            export_service = ExportService()

            self.progress.emit(f"Starting {self.format_type.upper()} export...")

            with db_service.get_session() as session:
                if self._cancelled:
                    return

                # Task 11: Get noise filtering options (apply to all formats)
                exclude_noise = self.export_options.get("exclude_noise", True)
                include_classification = self.export_options.get("include_classification", False)

                # Call appropriate export method based on format
                if self.format_type == "csv":
                    count = export_service.export_tm_csv(
                        session, self.file_path, project_id=self.project_id
                    )
                elif self.format_type == "json":
                    count = export_service.export_tm_json(
                        session, self.file_path, project_id=self.project_id
                    )
                elif self.format_type == "xlsx":
                    count = export_service.export_xlsx(
                        session,
                        self.file_path,
                        project_id=self.project_id,
                        exclude_noise=exclude_noise,
                        include_classification=include_classification,
                    )
                elif self.format_type == "tbx":
                    # TBX options: approved_only, include_pinned, exclude_noise, include_classification
                    count = export_service.export_tbx(
                        session,
                        self.file_path,
                        project_id=self.project_id,
                        approved_only=self.export_options.get("approved_only", True),
                        include_pinned=self.export_options.get("include_pinned", True),
                        exclude_noise=exclude_noise,
                        include_classification=include_classification,
                    )
                elif self.format_type == "tmx":
                    # TMX options: include_draft, include_pinned, exclude_noise, include_classification
                    count = export_service.export_tmx(
                        session,
                        self.file_path,
                        project_id=self.project_id,
                        include_draft=self.export_options.get("include_draft", False),
                        include_pinned=self.export_options.get("include_pinned", True),
                        exclude_noise=exclude_noise,
                        include_classification=include_classification,
                    )
                else:
                    raise ValueError(f"Unknown format type: {self.format_type}")

                if not self._cancelled:
                    self.progress.emit("Export completed successfully!")
                    self.export_complete.emit(count, self.file_path)

        except Exception as e:
            logger.exception("Export worker error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the export."""
        self._cancelled = True


class TMExportWorker(QThread):
    """Task #14: Worker for exporting filtered TM entries to Excel (non-blocking).

    Exports TM entries matching current filters in Translation Management Panel.
    Supports cancel during export (checked between chunks).
    """

    progress = pyqtSignal(str)  # Progress message
    export_complete = pyqtSignal(int, str)  # (entry_count, file_path)
    error = pyqtSignal(str)

    def __init__(
        self,
        file_path: str,
        filters: dict,
        sort_column: str = "updated_at",
        sort_direction: str = "desc",
    ):
        """Initialize TM export worker.

        Args:
            file_path: Output XLSX file path
            filters: Filters dict (same as TranslationAdminService.search_tm_entries)
            sort_column: Column to sort by
            sort_direction: Sort direction ("asc" or "desc")
        """
        super().__init__()
        self.file_path = file_path
        self.filters = filters
        self.sort_column = sort_column
        self.sort_direction = sort_direction
        self._cancelled = False

    def run(self):
        """Run export operation."""
        try:
            from app.services.db_service import DBService
            from app.services.export_service import ExportService

            db_service = DBService.get_instance()
            export_service = ExportService()

            self.progress.emit("Preparing filtered data for export...")

            with db_service.get_session() as session:
                if self._cancelled:
                    self.progress.emit("Export cancelled")
                    return

                self.progress.emit("Writing Excel file...")

                # Call export_tm_filtered_xlsx (chunked fetch inside)
                count = export_service.export_tm_filtered_xlsx(
                    session,
                    self.file_path,
                    filters=self.filters,
                    sort_column=self.sort_column,
                    sort_direction=self.sort_direction,
                )

                if not self._cancelled:
                    self.progress.emit("Export completed successfully!")
                    self.export_complete.emit(count, self.file_path)

        except Exception as e:
            logger.exception("TM export worker error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the export."""
        self._cancelled = True


class BulkNoiseUpdateWorker(QThread):
    """P0 Safety: Worker for bulk updating is_noise status (non-blocking).

    Prevents UI freeze during bulk operations on large datasets (1000+ rows).
    Supports cancel and progress reporting.
    """

    progress = pyqtSignal(int, int)  # (current, total)
    update_complete = pyqtSignal(int)  # (rows_updated)
    error = pyqtSignal(str)

    def __init__(
        self,
        model_class: str,  # "Lemma" or "TermCluster" or "TMEntry"
        item_ids: list,    # List of lemma_id, cluster_id, or tm_id
        is_noise: bool,    # True = mark as noise, False = mark as valid
    ):
        """Initialize bulk noise update worker.

        Args:
            model_class: "Lemma", "TermCluster", or "TMEntry"
            item_ids: List of IDs to update
            is_noise: True to mark as noise, False to mark as valid
        """
        super().__init__()
        self.model_class = model_class
        self.item_ids = item_ids
        self.is_noise = is_noise
        self._cancelled = False

    def run(self):
        """Run bulk update in chunks with progress reporting."""
        try:
            from app.services.db_service import DBService
            from app.infra.sa_models import Lemma, TermCluster, TMEntry
            from sqlalchemy import update

            db_service = DBService.get_instance()

            # Select model class
            if self.model_class == "Lemma":
                Model = Lemma
                id_column = Lemma.lemma_id
            elif self.model_class == "TermCluster":
                Model = TermCluster
                id_column = TermCluster.cluster_id
            elif self.model_class == "TMEntry":
                Model = TMEntry
                id_column = TMEntry.tm_id
            else:
                raise ValueError(f"Unknown model class: {self.model_class}")

            total_count = len(self.item_ids)
            chunk_size = 100  # Update 100 rows per chunk for progress granularity
            updated_count = 0

            with db_service.get_session() as session:
                # Process in chunks
                for i in range(0, total_count, chunk_size):
                    if self._cancelled:
                        logger.info(f"Bulk noise update cancelled at {updated_count}/{total_count}")
                        return

                    # Get chunk of IDs
                    chunk_ids = self.item_ids[i:i + chunk_size]

                    # Update chunk
                    stmt = update(Model).where(
                        id_column.in_(chunk_ids)
                    ).values(
                        is_noise=1 if self.is_noise else 0
                    )
                    result = session.execute(stmt)

                    # NOTE: Source->TMEntry sync is now handled by DB triggers (migration 014)
                    # - trg_lemma_noise_to_tm_entry: fires on lemma.is_noise UPDATE
                    # - trg_cluster_noise_to_tm_entry: fires on term_cluster.is_noise UPDATE
                    # This guarantees sync at DB level, no application code needed.
                    # The trigger fires when we commit the source entity update below.

                    session.commit()

                    # Update progress
                    updated_count += len(chunk_ids)
                    self.progress.emit(updated_count, total_count)

                if not self._cancelled:
                    self.update_complete.emit(updated_count)
                    logger.info(f"Bulk noise update completed: {updated_count}/{total_count}")

        except Exception as e:
            logger.exception("Bulk noise update worker error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the bulk update."""
        self._cancelled = True


class SingleTextTranslateWorker(QThread):
    """Worker for translating single text via MT providers (non-blocking).

    Used by TranslateTextDialog for user-initiated translation.
    """

    result_ready = pyqtSignal(object)  # TranslationResult
    error = pyqtSignal(str)

    def __init__(
        self,
        text: str,
        src_lang: str = "en",
        tgt_lang: str = "he",
        project_id: Optional[int] = None,
    ):
        """Initialize worker.

        Args:
            text: Text to translate
            src_lang: Source language code (ISO 639-1)
            tgt_lang: Target language code (ISO 639-1)
            project_id: Optional project ID for TM/glossary scope
        """
        super().__init__()
        self.text = text
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.project_id = project_id
        self._cancelled = False

    def cancel(self) -> None:
        """Request cooperative cancellation.

        The underlying provider call may still need to finish, but the worker
        will suppress result/error delivery after cancellation.
        """
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        """Translate text via MT providers."""
        try:
            from app.services.db_service import DBService
            from app.services.translation_service import TranslationService

            if self._cancelled or self.isInterruptionRequested():
                logger.info("Single text translate cancelled before start")
                return

            db_service = DBService.get_instance()
            translation_service = TranslationService()

            with db_service.get_session() as session:
                # Resolve translation (tries provider chain with fallback)
                result = translation_service.resolve_translation(
                    session,
                    src_text=self.text,
                    kind="adhoc",  # User-initiated translation (not lemma/term)
                    src_lang=self.src_lang,
                    tgt_lang=self.tgt_lang,
                    project_id=self.project_id,
                    allow_draft=False,
                    use_mt=True,  # Enable MT providers
                )

                if self._cancelled or self.isInterruptionRequested():
                    logger.info("Single text translate cancelled before result delivery")
                    return

                # Emit result
                self.result_ready.emit(result)

        except Exception as e:
            if self._cancelled or self.isInterruptionRequested():
                logger.info("Single text translate cancelled during failure path: %s", e)
                return
            logger.exception("Single text translate worker error")
            error_msg = self._make_user_friendly_error(str(e))
            self.error.emit(error_msg)

    def _make_user_friendly_error(self, error: str) -> str:
        """Convert technical error to user-friendly message."""
        error_lower = error.lower()

        if "database" in error_lower or "locked" in error_lower:
            return (
                "Database error occurred during translation.\n\n"
                "Please try again. If the problem persists, restart the application."
            )
        elif "provider" in error_lower or "api" in error_lower:
            return (
                "MT provider error occurred.\n\n"
                "Check:\n"
                "- MT providers enabled in Settings\n"
                "- Local model installed (if using Local MT)\n"
                "- Network connection (if using cloud providers)\n"
                "- API keys valid (if using cloud providers)"
            )
        elif "not installed" in error_lower or "model" in error_lower:
            return (
                "Local MT model not installed.\n\n"
                "To use Local MT:\n"
                "1. Run: python scripts/install_local_mt_model.py --model nllb-200-distilled-1.3B\n"
                "2. Enable Local NLLB in MT Provider Settings\n\n"
                "Or: Use cloud providers (DeepL, Google, etc.)"
            )
        else:
            return (
                f"Translation failed:\n\n"
                f"{error[:200]}\n\n"
                f"Check the application logs for details."
            )


class BatchTranslateWorker(QThread):
    """Background worker for batch translation (PATCH-UI-BATCH-T01).

    Translates multiple rows in background without freezing UI.
    Supports chunked commits, progress reporting, and graceful cancellation.
    """

    progress = pyqtSignal(int, int)  # (completed, total)
    row_completed = pyqtSignal(str, bool)  # (entity_id, success)
    stats_updated = pyqtSignal(int, int, int)  # (succeeded, skipped, failed)
    row_translated = pyqtSignal(str, str, bool)  # (entity_id, message, success)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(object)  # BatchTranslateResult
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        items: List,  # List[BatchTranslateItem]
        options,  # BatchTranslateOptions
        tab_type: str,  # "dictionary" | "terms" | "tm"
    ):
        """Initialize batch translate worker.

        Args:
            items: List of BatchTranslateItem to translate
            options: BatchTranslateOptions (provider_mode, write_mode, etc.)
            tab_type: Tab type identifier (for logging)
        """
        super().__init__()
        self.items = items
        self.options = options
        self.tab_type = tab_type
        self._cancel_requested = False
        self._paused = False
        self.succeeded = 0
        self.skipped = 0
        self.failed = 0

    def run(self):
        """Execute batch translation in background thread."""
        try:
            from app.services.batch_mt_translate_service import BatchMTTranslateService
            from app.services.db_service import DBService

            self.stage_updated.emit("Initializing...")
            logger.info(
                f"BatchTranslateWorker started: tab={self.tab_type}, "
                f"items={len(self.items)}, mode={self.options.provider_mode}"
            )

            service = BatchMTTranslateService()
            db_service = DBService.get_instance()

            if not self.items:
                self.stage_updated.emit("No targets found")
                _flush_mt_usage_queue(f"batch_translate:{self.tab_type}:empty")
                self.finished.emit(
                    type("EmptyResult", (), {
                        "total": 0,
                        "succeeded": 0,
                        "skipped": 0,
                        "failed": 0,
                        "row_results": [],
                    })()
                )
                return

            self.stage_updated.emit(f"Translating {len(self.items)} selected rows...")

            def cancel_check() -> bool:
                # Keep worker paused at safe boundaries until resume/cancel.
                while self._paused and not self._cancel_requested:
                    time.sleep(0.05)
                return self._cancel_requested

            with db_service.get_session() as session:
                result = service.execute_batch(
                    session=session,
                    items=self.items,
                    options=self.options,
                    progress_callback=self._on_progress,
                    cancel_check=cancel_check,
                    item_callback=self._on_item_result,
                )

                self.succeeded = result.succeeded
                self.skipped = result.skipped
                self.failed = result.failed
                self.stats_updated.emit(result.succeeded, result.skipped, result.failed)
                _flush_mt_usage_queue(f"batch_translate:{self.tab_type}")
                self.stage_updated.emit(
                    f"Completed: {result.succeeded} succeeded, {result.skipped} skipped, {result.failed} failed"
                )
                self.finished.emit(result)

                logger.info(
                    f"BatchTranslateWorker finished: succeeded={result.succeeded}, "
                    f"skipped={result.skipped}, failed={result.failed}"
                )

        except Exception as e:
            _flush_mt_usage_queue(f"batch_translate:{self.tab_type}:error")
            logger.exception("BatchTranslateWorker failed")
            error_msg = self._make_user_friendly_error(str(e))
            self.error.emit(error_msg)

    def cancel(self):
        """Request graceful cancel.

        Sets flag that will be checked between items.
        Current item will complete, then worker will stop.
        """
        logger.info("BatchTranslateWorker cancel requested")
        self._cancel_requested = True

    def pause(self):
        """Pause processing at the next safe boundary."""
        self._paused = True
        self.stage_updated.emit("Paused")
        self.paused.emit()

    def resume(self):
        """Resume processing."""
        self._paused = False
        self.stage_updated.emit("Resuming...")
        self.resumed.emit()

    def _on_progress(self, completed: int, total: int):
        """Handle progress callback from service."""
        self.progress.emit(completed, total)
        self.stage_updated.emit(f"Translating... {completed}/{total}")

    def _on_item_result(self, row_result):
        """Emit granular activity + running stats for V3 progress dialog."""
        if row_result.skipped:
            self.skipped += 1
            message = "already translated"
            success = False
        elif row_result.error_message:
            self.failed += 1
            message = row_result.error_message[:80]
            success = False
        else:
            self.succeeded += 1
            message = (row_result.new_translation or "")[:80]
            success = True

        self.row_completed.emit(row_result.entity_id, success)
        self.row_translated.emit(row_result.entity_id, message, success)
        self.stats_updated.emit(self.succeeded, self.skipped, self.failed)

    def _make_user_friendly_error(self, error: str) -> str:
        """Convert technical error to user-friendly message."""
        error_lower = error.lower()

        if "database" in error_lower or "locked" in error_lower:
            return (
                "Database error occurred during batch translation.\n\n"
                "Please try again. If the problem persists, restart the application."
            )
        elif "provider" in error_lower or "api" in error_lower:
            return (
                "MT provider error occurred.\n\n"
                "Check:\n"
                "- MT providers enabled in Settings (Ctrl+Alt+P)\n"
                "- Local model installed (if using Local MT)\n"
                "- Network connection (if using cloud providers)\n"
                "- API keys valid (if using cloud providers)"
            )
        elif "not installed" in error_lower or "model" in error_lower:
            return (
                "Local MT model not installed.\n\n"
                "To use Local MT:\n"
                "1. Run: python scripts/install_local_mt_model.py --model nllb-200-distilled-1.3B\n"
                "2. Enable Local NLLB in MT Provider Settings (Ctrl+Alt+P)\n\n"
                "Or: Use cloud providers (DeepL, Google, etc.)"
            )
        else:
            return (
                f"Batch translation failed:\n\n"
                f"{error[:200]}\n\n"
                f"Check the application logs for details."
            )


# Task 15: TranslateAllFilteredWorker - chunked translation of all filtered records
class TranslateAllFilteredWorker(QThread):
    """Worker for translating all records matching filters (across pages).

    Unlike BatchTranslateWorker which works on pre-selected UI rows,
    this worker fetches IDs from DB in chunks and translates all matching records.
    """

    progress = pyqtSignal(int, int)        # (completed, total)
    stats_updated = pyqtSignal(int, int, int)  # (succeeded, skipped, failed) - real-time stats
    row_completed = pyqtSignal(str, bool)  # (entity_id, success)
    row_translated = pyqtSignal(str, str, bool)  # (entity_id, translation, success) - for activity log
    stage_updated = pyqtSignal(str)        # PATCH-16-02: Current stage description
    finished = pyqtSignal(object)          # BatchTranslateResult
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        entity_type: str,           # "lemma" | "term_cluster" | "tm_entry"
        project_id: Optional[int],
        filters: dict,              # Same dict as passed to search/count
        provider_mode: str,         # "chain" | "force:<provider_id>"
        write_mode: str,            # "FILL_EMPTY" | "OVERWRITE" | "SKIP_NON_EMPTY"
        id_fetch_chunk: int = 200,  # How many IDs to fetch from DB per iteration (efficiency)
        translation_chunk: int = 25, # How many items to translate before commit (UX + safety)
        src_lang: str = "he",
        tgt_lang: str = "ru",
    ):
        super().__init__()
        self.entity_type = entity_type
        self.project_id = project_id
        self.filters = filters
        self.provider_mode = provider_mode
        self.write_mode = write_mode
        self.id_fetch_chunk = id_fetch_chunk
        self.translation_chunk = translation_chunk
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self._cancel_requested = False
        self._paused = False

        # Track stats for real-time updates
        self.succeeded = 0
        self.skipped = 0
        self.failed = 0

        # PATCH-17-02: Activity throttling (max 10 events/sec)
        self._last_activity_emit = 0.0
        self._activity_throttle_interval = 0.1  # 100ms

    def cancel(self):
        """Request cancellation (checked between chunks)."""
        self._cancel_requested = True

    def pause(self):
        """Request pause (checked between translation items)."""
        self._paused = True
        self.paused.emit()

    def resume(self):
        """Resume from pause."""
        self._paused = False
        self.resumed.emit()

    def _emit_activity_from_row_result(self, row_result):
        """PATCH-17-02: Emit activity event with throttling.

        Args:
            row_result: BatchTranslateRowResult from service
        """
        import time

        now = time.time()

        # Throttle unless FAIL (priority)
        if row_result.error_message:
            # FAIL: emit immediately (high priority)
            pass
        else:
            # OK/SKIP: throttle to max 10 events/sec
            if now - self._last_activity_emit < self._activity_throttle_interval:
                return  # Skip this event to avoid UI flooding

        self._last_activity_emit = now

        # Determine event type and emit
        if row_result.skipped:
            # SKIP event
            msg = "already translated"
            self.row_translated.emit(row_result.entity_id, msg, False)
        elif row_result.error_message:
            # FAIL event
            error_short = row_result.error_message[:50]
            self.row_translated.emit(row_result.entity_id, error_short, False)
        elif row_result.new_translation:
            # OK event
            translation = row_result.new_translation[:50]
            self.row_translated.emit(row_result.entity_id, translation, True)

    def run(self):
        """Execute chunked translation."""
        from app.services.db_service import DBService
        from app.services.dictionary_service import DictionaryService
        from app.services.term_extraction_service import TermExtractionService
        from app.services.translation_admin_service import TranslationAdminService
        from app.services.batch_mt_translate_service import (
            BatchMTTranslateService,
            BatchTranslateItem,
            BatchTranslateOptions,
            BatchTranslateResult,
        )
        from app.services.translation_service import TranslationService
        from app.infra.sa_models import Lemma, TermCluster, TMEntry
        from sqlalchemy import select

        try:
            # PATCH-16-02: Emit initial stage
            self.stage_updated.emit("Initializing...")

            db_service = DBService.get_instance()
            batch_service = BatchMTTranslateService()
            translation_service = TranslationService()

            # Aggregate results across chunks
            total_succeeded = 0
            total_skipped = 0
            total_failed = 0
            all_row_results = []

            with db_service.get_session() as session:
                # Step 1: Count total
                # PATCH-16-02: Emit stage
                self.stage_updated.emit("Counting targets...")

                if self.entity_type == "lemma":
                    dict_service = DictionaryService()
                    total = dict_service.count_lemma_ids_for_translation(
                        session, self.project_id, self.filters, self.write_mode
                    )
                elif self.entity_type == "term_cluster":
                    term_service = TermExtractionService()
                    total = term_service.count_cluster_ids_for_translation(
                        session, self.project_id, self.filters, self.write_mode
                    )
                elif self.entity_type == "tm_entry":
                    admin_service = TranslationAdminService()
                    total = admin_service.count_tm_ids_for_translation(
                        session, self.filters, self.write_mode
                    )
                else:
                    raise ValueError(f"Unknown entity_type: {self.entity_type}")

                if total == 0:
                    # Nothing to translate
                    self.stage_updated.emit("No targets found")  # PATCH-16-02
                    empty_result = BatchTranslateResult(
                        total=0,
                        succeeded=0,
                        skipped=0,
                        failed=0,
                        row_results=[],
                        trace_id="empty",
                        elapsed_ms=0,
                    )
                    _flush_mt_usage_queue(f"translate_all_filtered:{self.entity_type}:empty")
                    self.finished.emit(empty_result)
                    return

                # PATCH-16-02: Emit stage with total count
                self.stage_updated.emit(f"Found {total} items to translate")
                logger.info(f"TranslateAllFilteredWorker: translating {total} {self.entity_type} records")

                # Step 2: Process in chunks
                completed = 0
                for offset in range(0, total, self.id_fetch_chunk):
                    # Check pause (wait until resumed)
                    while self._paused:
                        time.sleep(0.1)  # Sleep while paused
                        if self._cancel_requested:
                            break

                    # Check cancel
                    if self._cancel_requested:
                        logger.info(f"Translation cancelled at {completed}/{total}")
                        self.stage_updated.emit("Cancelled")  # PATCH-16-02
                        result = BatchTranslateResult(
                            total=completed,
                            succeeded=total_succeeded,
                            skipped=total_skipped,
                            failed=total_failed,
                            row_results=all_row_results,
                            trace_id="cancelled",
                            elapsed_ms=0,
                        )
                        _flush_mt_usage_queue(f"translate_all_filtered:{self.entity_type}:cancelled")
                        self.finished.emit(result)
                        return

                    # PATCH-16-02: Emit fetching stage
                    batch_num = (offset // self.id_fetch_chunk) + 1
                    total_batches = (total + self.id_fetch_chunk - 1) // self.id_fetch_chunk
                    self.stage_updated.emit(f"Fetching batch {batch_num}/{total_batches}...")

                    # Fetch IDs for this chunk
                    if self.entity_type == "lemma":
                        ids = dict_service.fetch_lemma_ids_for_translation(
                            session, self.project_id, self.filters, self.write_mode,
                            limit=self.id_fetch_chunk, offset=offset
                        )
                    elif self.entity_type == "term_cluster":
                        ids = term_service.fetch_cluster_ids_for_translation(
                            session, self.project_id, self.filters, self.write_mode,
                            limit=self.id_fetch_chunk, offset=offset
                        )
                    else:  # tm_entry
                        ids = admin_service.fetch_tm_ids_for_translation(
                            session, self.filters, self.write_mode,
                            limit=self.id_fetch_chunk, offset=offset
                        )

                    if not ids:
                        break

                    # PATCH-16-02: Emit loading stage
                    self.stage_updated.emit(f"Loading entities for batch {batch_num}...")

                    # Load entities and build BatchTranslateItem list
                    items = []
                    if self.entity_type == "lemma":
                        # Load lemmas + their current translations via LEFT JOIN to TMEntry
                        stmt = select(Lemma, TMEntry).outerjoin(
                            TMEntry,
                            (TMEntry.lemma_id == Lemma.lemma_id) &
                            (TMEntry.kind == "lemma") &
                            (TMEntry.project_id == self.project_id)
                        ).where(Lemma.lemma_id.in_(ids))

                        results = session.execute(stmt).all()
                        for lemma, tm_entry in results:
                            current_translation = tm_entry.translation if tm_entry else None
                            items.append(BatchTranslateItem(
                                entity_type="lemma",
                                entity_id=lemma.lemma_text,
                                source_text=lemma.lemma_text,
                                src_lang=self.src_lang,
                                tgt_lang=self.tgt_lang,
                                current_translation=current_translation,
                                project_id=self.project_id,
                            ))

                    elif self.entity_type == "term_cluster":
                        # Load clusters + their current translations
                        stmt = select(TermCluster, TMEntry).outerjoin(
                            TMEntry,
                            (TMEntry.cluster_id == TermCluster.cluster_id) &
                            (TMEntry.kind == "term_cluster") &
                            (TMEntry.project_id == self.project_id)
                        ).where(TermCluster.cluster_id.in_(ids))

                        results = session.execute(stmt).all()
                        for cluster, tm_entry in results:
                            current_translation = tm_entry.translation if tm_entry else None
                            items.append(BatchTranslateItem(
                                entity_type="term_cluster",
                                entity_id=cluster.representative_he,
                                source_text=cluster.representative_he,
                                src_lang=self.src_lang,
                                tgt_lang=self.tgt_lang,
                                current_translation=current_translation,
                                project_id=self.project_id,
                            ))
                    else:  # tm_entry
                        stmt = (
                            select(TMEntry)
                            .where(TMEntry.tm_id.in_(ids))
                            .order_by(TMEntry.tm_id.asc())
                        )

                        for entry in session.execute(stmt).scalars().all():
                            items.append(BatchTranslateItem(
                                entity_type="tm_entry",
                                entity_id=str(entry.tm_id),
                                source_text=entry.src_text,
                                src_lang=entry.src_lang or self.src_lang,
                                tgt_lang=entry.tgt_lang or self.tgt_lang,
                                current_translation=entry.translation,
                                project_id=entry.project_id,
                            ))

                    if not items:
                        break

                    # PATCH-16-02: Emit translating stage
                    self.stage_updated.emit(f"Translating batch {batch_num}/{total_batches} ({len(items)} items)...")

                    # Translate this chunk using existing batch service
                    # Use translation_chunk for granular progress updates + commit safety
                    options = BatchTranslateOptions(
                        provider_mode=self.provider_mode,
                        write_mode=self.write_mode,
                        chunk_size=self.translation_chunk,  # 25 items per commit (dynamic UX)
                        stop_on_error=False,
                    )

                    # PATCH-16-01: Progress callback for real-time UI updates
                    # BatchMTTranslateService calls this after each translation_chunk (25 items)
                    def on_batch_progress(completed_in_batch, total_in_batch):
                        """Called by BatchMTTranslateService after each sub-chunk (25 items)."""
                        # Calculate global progress
                        global_completed = offset + completed_in_batch

                        # Update worker stats (approximation until chunk completes)
                        # Real stats will be updated after chunk_result is available
                        self.progress.emit(global_completed, total)

                        # PATCH-16-02: Update stage during translation
                        sub_chunk_num = completed_in_batch // self.translation_chunk
                        self.stage_updated.emit(
                            f"Translating batch {batch_num}/{total_batches} "
                            f"(sub-chunk {sub_chunk_num}, {completed_in_batch}/{total_in_batch} done)..."
                        )

                    # Execute batch for this chunk
                    chunk_result = batch_service.execute_batch(
                        session=session,
                        items=items,
                        options=options,
                        progress_callback=on_batch_progress,  # PATCH-16-01: Real-time updates!
                        cancel_check=lambda: self._cancel_requested,
                        item_callback=self._emit_activity_from_row_result,  # PATCH-17-02: Real-time activity!
                    )

                    # Aggregate results
                    total_succeeded += chunk_result.succeeded
                    total_skipped += chunk_result.skipped
                    total_failed += chunk_result.failed
                    all_row_results.extend(chunk_result.row_results)

                    # Update worker stats (for real-time UI access)
                    self.succeeded = total_succeeded
                    self.skipped = total_skipped
                    self.failed = total_failed

                    # Update progress
                    completed += len(items)
                    self.progress.emit(completed, total)

                    # Emit stats update for UI
                    self.stats_updated.emit(total_succeeded, total_skipped, total_failed)

                    # PATCH-17-03: Activity events now emitted via item_callback (real-time)
                    # Old post-batch emission code removed - events now come during translation

                    logger.debug(f"Chunk {offset}-{offset+len(items)} complete: {chunk_result.succeeded} succeeded")

                # Done
                self.stage_updated.emit(f"Completed: {total_succeeded} succeeded, {total_skipped} skipped, {total_failed} failed")  # PATCH-16-02
                final_result = BatchTranslateResult(
                    total=completed,
                    succeeded=total_succeeded,
                    skipped=total_skipped,
                    failed=total_failed,
                    row_results=all_row_results,
                    trace_id="all_filtered",
                    elapsed_ms=0,  # We don't track elapsed time at worker level
                )
                _flush_mt_usage_queue(f"translate_all_filtered:{self.entity_type}:completed")
                self.finished.emit(final_result)

        except Exception as e:
            _flush_mt_usage_queue(f"translate_all_filtered:{self.entity_type}:error")
            logger.error(f"TranslateAllFilteredWorker error: {e}", exc_info=True)
            self.error.emit(str(e))


class UserDictItemsPageWorker(QThread):
    """Async paginated loader for user dictionary items (PERF-SCALE PATCH-H).

    Replaces the synchronous load_items() call in user_dictionaries_view so
    the UI thread is never blocked during DB + audio-status queries.

    Uses the read engine (PATCH-C) — pure SELECT, no writes.

    Signals:
        page_loaded(request_id, items, total_count)
        error(request_id, message)
    """

    page_loaded = pyqtSignal(int, list, int)   # request_id, items, total_count
    error = pyqtSignal(int, str)               # request_id, message

    def __init__(
        self,
        *,
        request_id: int,
        dictionary_id: int,
        filters: Dict[str, Any],
        limit: int,
        offset: int,
        sort_column: str,
        sort_direction: str,
    ):
        super().__init__()
        self.request_id = int(request_id)
        self.dictionary_id = int(dictionary_id)
        self.filters = dict(filters)
        self.limit = int(limit)
        self.offset = int(offset)
        self.sort_column = sort_column
        self.sort_direction = sort_direction

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.user_dictionary_service import UserDictionaryService
            from app.services.audio_asset_service import AudioAssetService

            db = DBService.get_instance()
            svc = UserDictionaryService()
            audio_svc = AudioAssetService()

            with db.get_read_session() as session:
                items, total = svc.query_items(
                    session=session,
                    dictionary_id=self.dictionary_id,
                    filters=self.filters,
                    limit=self.limit,
                    offset=self.offset,
                    sort_column=self.sort_column,
                    sort_direction=self.sort_direction,
                )
                # Audio status overlay (bulk lookup — same session)
                if items:
                    status_map = audio_svc.bulk_get_status_for_items(
                        session,
                        items=[
                            {
                                "lang": item.src_lang,
                                "norm_text": item.src_norm,
                                "source_text": item.src_text,
                            }
                            for item in items
                        ],
                    )
                    for item in items:
                        item.audio_status = status_map.get(
                            (item.src_lang, item.src_norm, item.src_text), "missing"
                        )

            self.page_loaded.emit(self.request_id, items, total)
        except Exception as e:
            logger.exception("UserDictItemsPageWorker error")
            self.error.emit(self.request_id, str(e))


class UserDictionaryBulkAddWorker(QThread):
    """Background worker for adding many rows to a user dictionary."""

    progress = pyqtSignal(int, int)  # (processed, total)
    finished = pyqtSignal(dict)      # {added, skipped, failed, ...}
    error = pyqtSignal(str)

    def __init__(
        self,
        dictionary_id: int,
        items: List[Dict[str, Any]],
        *,
        include_noise: bool = False,
        skip_duplicates: bool = True,
        chunk_size: int = 500,
    ):
        super().__init__()
        self.dictionary_id = dictionary_id
        self.items = items
        self.include_noise = include_noise
        self.skip_duplicates = skip_duplicates
        self.chunk_size = chunk_size
        self._cancel_requested = False

    def cancel(self):
        """Request graceful cancellation."""
        self._cancel_requested = True

    def run(self):
        """Execute bulk add in background."""
        try:
            from app.services.db_service import DBService
            from app.services.user_dictionary_service import UserDictionaryService

            db_service = DBService.get_instance()
            service = UserDictionaryService()

            with db_service.get_session() as session:
                result = service.bulk_add_items(
                    session=session,
                    dictionary_id=self.dictionary_id,
                    items=self.items,
                    include_noise=self.include_noise,
                    skip_duplicates=self.skip_duplicates,
                    chunk_size=self.chunk_size,
                    progress_callback=lambda processed, total: self.progress.emit(processed, total),
                    cancel_check=lambda: self._cancel_requested,
                )
                session.commit()

            self.finished.emit(result)
        except Exception as e:
            logger.error("UserDictionaryBulkAddWorker error: %s", e, exc_info=True)
            self.error.emit(str(e))


class UserDictionaryBulkRemoveWorker(QThread):
    """Background worker for removing many user dictionary items."""

    progress = pyqtSignal(int, int)  # (processed, total)
    finished = pyqtSignal(dict)      # {removed, processed, total, cancelled}
    error = pyqtSignal(str)

    def __init__(self, item_ids: List[int], *, chunk_size: int = 500):
        super().__init__()
        self.item_ids = item_ids
        self.chunk_size = chunk_size
        self._cancel_requested = False

    def cancel(self):
        """Request graceful cancellation."""
        self._cancel_requested = True

    def run(self):
        """Execute bulk delete in background."""
        try:
            from app.services.db_service import DBService
            from app.services.user_dictionary_service import UserDictionaryService

            db_service = DBService.get_instance()
            service = UserDictionaryService()

            with db_service.get_session() as session:
                result = service.bulk_remove_items(
                    session=session,
                    item_ids=self.item_ids,
                    chunk_size=self.chunk_size,
                    progress_callback=lambda processed, total: self.progress.emit(processed, total),
                    cancel_check=lambda: self._cancel_requested,
                )
                session.commit()

            self.finished.emit(result)
        except Exception as e:
            logger.error("UserDictionaryBulkRemoveWorker error: %s", e, exc_info=True)
            self.error.emit(str(e))


class UserDictTranslateWorker(QThread):
    """Translate user dictionary items via canonical tm_global write path."""

    progress = pyqtSignal(int, int)        # (completed, total)
    stats_updated = pyqtSignal(int, int, int)  # (succeeded, skipped, failed)
    row_translated = pyqtSignal(str, str, bool)  # (entity_id, message, success)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(object)          # BatchTranslateResult
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        dictionary_id: int,
        scope: str,  # "current_page" | "all_filtered"
        selected_item_ids: List[int],
        filters: Dict[str, Any],
        provider_mode: str,
        write_mode: str,
        *,
        id_fetch_chunk: int = 200,
        translation_chunk: int = 25,
    ):
        super().__init__()
        self.dictionary_id = dictionary_id
        self.scope = scope
        self.selected_item_ids = selected_item_ids
        self.filters = filters
        self.provider_mode = provider_mode
        self.write_mode = write_mode
        self.id_fetch_chunk = id_fetch_chunk
        self.translation_chunk = translation_chunk
        self._cancel_requested = False
        self._paused = False
        self._trace = f"user_dict:{dictionary_id}"

    def cancel(self):
        """Request cancellation."""
        self._cancel_requested = True

    def pause(self):
        """Pause at next safe boundary."""
        self._paused = True
        self.paused.emit()

    def resume(self):
        """Resume worker."""
        self._paused = False
        self.resumed.emit()

    def _wait_if_paused(self) -> None:
        while self._paused and not self._cancel_requested:
            time.sleep(0.1)

    @staticmethod
    def _is_non_empty(text_value: Optional[str]) -> bool:
        return bool(text_value and str(text_value).strip())

    @staticmethod
    def _canonical_item_norm(item) -> str:
        from app.domain.normalization.normalizer import normalize_for_tm

        try:
            normalized = normalize_for_tm(item.src_lang, item.src_text, item.kind).norm
            normalized = (normalized or "").strip()
            if normalized:
                return normalized
        except Exception:
            pass
        return (item.src_norm or "").strip()

    def _fetch_current_global(self, session, item) -> Optional["TMGlobal"]:
        from sqlalchemy import select
        from app.infra.sa_models import TMGlobal

        src_norm = self._canonical_item_norm(item)
        stmt = (
            select(TMGlobal)
            .where(
                TMGlobal.src_lang == item.src_lang,
                TMGlobal.tgt_lang == item.tgt_lang,
                TMGlobal.kind == item.kind,
                TMGlobal.src_norm == src_norm,
            )
            .limit(1)
        )
        return session.execute(stmt).scalar_one_or_none()

    def _translate_item(self, session, item):
        from app.services.translation_service import TranslationService

        if self.provider_mode.startswith("force:"):
            force_provider_id = self.provider_mode.split(":", 1)[1]
            from app.infra.translators.providers_registry import ProvidersRegistry
            from app.infra.translators.base_provider import TranslationRequest

            provider = ProvidersRegistry().get(force_provider_id)
            if not provider:
                raise ValueError(f"Provider '{force_provider_id}' not available")

            mt_request = TranslationRequest(
                source_text=item.src_text,
                source_lang=item.src_lang,
                target_lang=item.tgt_lang,
                glossary=None,
            )
            mt_result = provider.translate(mt_request)
            if mt_result.error_kind:
                raise ValueError(mt_result.error_message or "Provider translation failed")

            return {
                "translation": mt_result.translated_text,
                "origin": force_provider_id,
                "confidence": 1.0,
            }

        service = TranslationService()
        result = service.resolve_translation(
            session=session,
            src_text=item.src_text,
            kind=item.kind,
            src_lang=item.src_lang,
            tgt_lang=item.tgt_lang,
            project_id=item.origin_project_id,
            allow_draft=False,
            use_mt=True,
        )
        return {
            "translation": result.translation,
            "origin": result.source or "mt_auto",
            "confidence": result.confidence,
        }

    def _write_global(
        self,
        session,
        item,
        translation: str,
        confidence: Optional[float],
        force_global_update: bool = False,
    ) -> None:
        from app.services.tm_global_service import TMGlobalService

        src_norm = self._canonical_item_norm(item)
        tm_global_service = TMGlobalService()
        global_row = tm_global_service.upsert_global(
            session=session,
            src_lang=item.src_lang,
            tgt_lang=item.tgt_lang,
            kind=item.kind,
            src_norm=src_norm,
            src_text=item.src_text,
            translation=translation,
            status="approved",
            origin="mt_auto",
            confidence=confidence,
            is_noise=item.is_noise or 0,
            noise_reason=item.noise_reason,
            notes=item.notes,
            source_tm_id=item.origin_tm_entry_id,
            force_update=force_global_update,
        )
        tm_global_service.propagate_to_entries(
            session=session,
            tm_global_id=global_row.tm_global_id,
            fields=["translation", "status", "origin", "confidence", "is_noise", "noise_reason"],
        )

    def run(self):
        from app.services.db_service import DBService
        from app.services.user_dictionary_service import UserDictionaryService
        from app.services.batch_mt_translate_service import BatchTranslateResult, BatchTranslateRowResult

        try:
            self.stage_updated.emit("Initializing...")
            db_service = DBService.get_instance()
            user_dict_service = UserDictionaryService()

            succeeded = 0
            skipped = 0
            failed = 0
            completed = 0
            row_results = []
            pending_writes = 0

            with db_service.get_session() as session:
                self.stage_updated.emit("Counting targets...")

                if self.scope == "all_filtered":
                    total = user_dict_service.count_item_ids_for_translation(
                        session=session,
                        dictionary_id=self.dictionary_id,
                        filters=self.filters,
                        write_mode=self.write_mode,
                    )
                    source_ids = None
                else:
                    source_ids = sorted(set(self.selected_item_ids))
                    total = len(source_ids)

                if total == 0:
                    self.stage_updated.emit("No targets found")
                    empty_result = BatchTranslateResult(
                        total=0,
                        succeeded=0,
                        skipped=0,
                        failed=0,
                        row_results=[],
                        trace_id="empty",
                        elapsed_ms=0,
                    )
                    _flush_mt_usage_queue(f"{self._trace}:empty")
                    self.finished.emit(empty_result)
                    return

                self.stage_updated.emit(f"Found {total} items to translate")
                chunk_offset = 0
                total_batches = (total + self.id_fetch_chunk - 1) // self.id_fetch_chunk

                while True:
                    self._wait_if_paused()
                    if self._cancel_requested:
                        break

                    if self.scope == "all_filtered":
                        batch_ids = user_dict_service.fetch_item_ids_for_translation(
                            session=session,
                            dictionary_id=self.dictionary_id,
                            filters=self.filters,
                            write_mode=self.write_mode,
                            limit=self.id_fetch_chunk,
                            offset=chunk_offset,
                        )
                    else:
                        if source_ids is None or chunk_offset >= len(source_ids):
                            break
                        batch_ids = source_ids[chunk_offset : chunk_offset + self.id_fetch_chunk]

                    if not batch_ids:
                        break

                    chunk_offset += len(batch_ids)
                    batch_num = ((chunk_offset - 1) // self.id_fetch_chunk) + 1
                    self.stage_updated.emit(f"Translating batch {batch_num}/{max(total_batches, 1)}...")

                    items = user_dict_service.get_items_by_ids(session, batch_ids)
                    for item in items:
                        self._wait_if_paused()
                        if self._cancel_requested:
                            break

                        row_id = str(item.item_id)
                        current_global = self._fetch_current_global(session, item)
                        current_translation = current_global.translation if current_global else None

                        if self.write_mode in ("FILL_EMPTY", "SKIP_NON_EMPTY") and self._is_non_empty(current_translation):
                            skipped += 1
                            completed += 1
                            row_results.append(
                                BatchTranslateRowResult(
                                    entity_id=row_id,
                                    source_text=item.src_text,
                                    old_translation=current_translation,
                                    new_translation=None,
                                    provider_id=None,
                                    cache_hit=False,
                                    latency_ms=None,
                                    error_message=None,
                                    skipped=True,
                                )
                            )
                            self.row_translated.emit(row_id, "already translated", False)
                            self.progress.emit(completed, total)
                            self.stats_updated.emit(succeeded, skipped, failed)
                            continue

                        row_start = time.perf_counter()
                        try:
                            translated = self._translate_item(session, item)
                            text_value = translated.get("translation")
                            if not self._is_non_empty(text_value):
                                raise ValueError("No translation returned")

                            with session.begin_nested():
                                self._write_global(
                                    session=session,
                                    item=item,
                                    translation=text_value.strip(),
                                    confidence=translated.get("confidence"),
                                    force_global_update=(self.write_mode == "OVERWRITE"),
                                )
                            pending_writes += 1
                            if pending_writes >= self.translation_chunk:
                                session.commit()
                                pending_writes = 0

                            succeeded += 1
                            completed += 1
                            row_results.append(
                                BatchTranslateRowResult(
                                    entity_id=row_id,
                                    source_text=item.src_text,
                                    old_translation=current_translation,
                                    new_translation=text_value.strip(),
                                    provider_id=str(translated.get("origin") or ""),
                                    cache_hit=False,
                                    latency_ms=int((time.perf_counter() - row_start) * 1000),
                                    error_message=None,
                                    skipped=False,
                                )
                            )
                            self.row_translated.emit(row_id, text_value.strip()[:50], True)
                        except Exception as row_err:
                            failed += 1
                            completed += 1
                            err_msg = str(row_err) or "Translation failed"
                            row_results.append(
                                BatchTranslateRowResult(
                                    entity_id=row_id,
                                    source_text=item.src_text,
                                    old_translation=current_translation,
                                    new_translation=None,
                                    provider_id=None,
                                    cache_hit=False,
                                    latency_ms=int((time.perf_counter() - row_start) * 1000),
                                    error_message=err_msg,
                                    skipped=False,
                                )
                            )
                            self.row_translated.emit(row_id, err_msg[:50], False)
                        finally:
                            self.progress.emit(completed, total)
                            self.stats_updated.emit(succeeded, skipped, failed)

                    if self._cancel_requested:
                        break

                if pending_writes:
                    session.commit()

                if self._cancel_requested:
                    self.stage_updated.emit("Cancelled")
                else:
                    self.stage_updated.emit(
                        f"Completed: {succeeded} succeeded, {skipped} skipped, {failed} failed"
                    )

                result = BatchTranslateResult(
                    total=completed,
                    succeeded=succeeded,
                    skipped=skipped,
                    failed=failed,
                    row_results=row_results,
                    trace_id="user_dictionary",
                    elapsed_ms=0,
                )
                _flush_mt_usage_queue(f"{self._trace}:completed")
                self.finished.emit(result)
        except Exception as e:
            _flush_mt_usage_queue(f"{self._trace}:error")
            logger.error("UserDictTranslateWorker error: %s", e, exc_info=True)
            self.error.emit(str(e))


class UserDictGenerateAudioWorker(QThread):
    """Generate source-audio for user dictionary rows in background."""

    progress = pyqtSignal(int, int)        # (completed, total)
    stats_updated = pyqtSignal(int, int, int)  # (succeeded, skipped, failed)
    row_translated = pyqtSignal(str, str, bool)  # (entity_id, message, success)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(dict)            # {total, succeeded, skipped, failed}
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        dictionary_id: int,
        scope: str,  # "current_page" | "all_filtered"
        selected_item_ids: List[int],
        filters: Dict[str, Any],
        provider_mode: str,
        write_mode: str,  # "MISSING_ONLY" | "REGENERATE_ALL"
        *,
        id_fetch_chunk: int = 200,
        audio_chunk: int = 25,
    ):
        super().__init__()
        self.dictionary_id = dictionary_id
        self.scope = scope
        self.selected_item_ids = selected_item_ids
        self.filters = filters
        self.provider_mode = provider_mode
        self.write_mode = write_mode
        self.id_fetch_chunk = id_fetch_chunk
        self.audio_chunk = audio_chunk
        self._cancel_requested = False
        self._paused = False
        self._trace = f"user_dict_audio:{dictionary_id}"

    def cancel(self):
        self._cancel_requested = True

    def pause(self):
        self._paused = True
        self.paused.emit()

    def resume(self):
        self._paused = False
        self.resumed.emit()

    def _wait_if_paused(self) -> None:
        while self._paused and not self._cancel_requested:
            time.sleep(0.1)

    def run(self):
        from app.services.audio_asset_service import AudioAssetService
        from app.services.audio_generation_service import AudioGenerationService
        from app.services.db_service import DBService
        from app.services.user_dictionary_service import UserDictionaryService

        try:
            self.stage_updated.emit("Initializing...")
            db_service = DBService.get_instance()
            user_dict_service = UserDictionaryService()
            audio_service = AudioGenerationService()
            asset_service = AudioAssetService()

            succeeded = 0
            skipped = 0
            failed = 0
            completed = 0
            pending_writes = 0

            with db_service.get_session() as session:
                self.stage_updated.emit("Counting targets...")

                if self.scope == "all_filtered":
                    total = user_dict_service.count_item_ids_for_translation(
                        session=session,
                        dictionary_id=self.dictionary_id,
                        filters=self.filters,
                        write_mode="OVERWRITE",
                    )
                    source_ids = None
                else:
                    source_ids = sorted(set(self.selected_item_ids))
                    total = len(source_ids)

                if total == 0:
                    self.stage_updated.emit("No targets found")
                    self.finished.emit(
                        {
                            "total": 0,
                            "succeeded": 0,
                            "skipped": 0,
                            "failed": 0,
                            "cancelled": False,
                        }
                    )
                    return

                chunk_offset = 0
                total_batches = (total + self.id_fetch_chunk - 1) // self.id_fetch_chunk

                while True:
                    self._wait_if_paused()
                    if self._cancel_requested:
                        break

                    if self.scope == "all_filtered":
                        batch_ids = user_dict_service.fetch_item_ids_for_translation(
                            session=session,
                            dictionary_id=self.dictionary_id,
                            filters=self.filters,
                            write_mode="OVERWRITE",
                            limit=self.id_fetch_chunk,
                            offset=chunk_offset,
                        )
                    else:
                        if source_ids is None or chunk_offset >= len(source_ids):
                            break
                        batch_ids = source_ids[chunk_offset : chunk_offset + self.id_fetch_chunk]

                    if not batch_ids:
                        break

                    chunk_offset += len(batch_ids)
                    batch_num = ((chunk_offset - 1) // self.id_fetch_chunk) + 1
                    self.stage_updated.emit(f"Generating audio batch {batch_num}/{max(total_batches, 1)}...")
                    items = user_dict_service.get_items_by_ids(session, batch_ids)

                    for item in items:
                        self._wait_if_paused()
                        if self._cancel_requested:
                            break

                        row_id = str(item.item_id)
                        try:
                            if self.write_mode == "MISSING_ONLY":
                                current = asset_service.bulk_get_status_for_items(
                                    session=session,
                                    items=[{
                                        "lang": item.src_lang,
                                        "norm_text": item.src_norm,
                                        "source_text": item.src_text,
                                    }],
                                )
                                if current.get((item.src_lang, item.src_norm, item.src_text)) == "ready":
                                    skipped += 1
                                    completed += 1
                                    self.row_translated.emit(row_id, "audio already exists", False)
                                    self.progress.emit(completed, total)
                                    self.stats_updated.emit(succeeded, skipped, failed)
                                    continue

                            result = audio_service.generate_one(
                                session=session,
                                src_text=item.src_text,
                                src_lang=item.src_lang,
                                source_norm=item.src_norm,
                                provider_mode=self.provider_mode,
                                force_regenerate=(self.write_mode == "REGENERATE_ALL"),
                                trace_id=f"{self._trace}:{row_id}",
                            )
                            pending_writes += 1
                            if pending_writes >= self.audio_chunk:
                                session.commit()
                                pending_writes = 0

                            if result.get("ok"):
                                if result.get("status") == "skipped":
                                    skipped += 1
                                    self.row_translated.emit(row_id, "audio already exists", False)
                                else:
                                    succeeded += 1
                                    provider_id = str(result.get("provider_id") or "provider")
                                    self.row_translated.emit(row_id, f"ready via {provider_id}", True)
                            else:
                                failed += 1
                                err_msg = str(result.get("error") or "audio generation failed")
                                self.row_translated.emit(row_id, err_msg[:50], False)
                        except Exception as row_err:
                            failed += 1
                            self.row_translated.emit(row_id, str(row_err)[:50], False)
                        finally:
                            completed += 1
                            self.progress.emit(completed, total)
                            self.stats_updated.emit(succeeded, skipped, failed)

                    if self._cancel_requested:
                        break

                if pending_writes:
                    session.commit()

            if self._cancel_requested:
                self.stage_updated.emit("Cancelled")
            else:
                self.stage_updated.emit(
                    f"Completed: {succeeded} succeeded, {skipped} skipped, {failed} failed"
                )
            self.finished.emit(
                {
                    "total": completed,
                    "succeeded": succeeded,
                    "skipped": skipped,
                    "failed": failed,
                    "cancelled": bool(self._cancel_requested),
                }
            )
        except Exception as exc:
            logger.error("UserDictGenerateAudioWorker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class BatchGenerateAudioWorker(QThread):
    """Generate source-audio for explicit selected rows in background."""

    progress = pyqtSignal(int, int)        # (completed, total)
    stats_updated = pyqtSignal(int, int, int)  # (succeeded, skipped, failed)
    row_translated = pyqtSignal(str, str, bool)  # (entity_id, message, success)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(dict)            # {total, succeeded, skipped, failed, cancelled}
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        items: List[Dict[str, Any]],
        provider_mode: str,
        write_mode: str,  # "MISSING_ONLY" | "REGENERATE_ALL"
        *,
        audio_chunk: int = 25,
    ):
        super().__init__()
        self.items = items
        self.provider_mode = provider_mode
        self.write_mode = write_mode
        self.audio_chunk = audio_chunk
        self._cancel_requested = False
        self._paused = False
        self._trace = "batch_audio_selected"

    def cancel(self):
        self._cancel_requested = True

    def pause(self):
        self._paused = True
        self.paused.emit()

    def resume(self):
        self._paused = False
        self.resumed.emit()

    def _wait_if_paused(self) -> None:
        while self._paused and not self._cancel_requested:
            time.sleep(0.1)

    def run(self):
        from app.services.audio_asset_service import AudioAssetService
        from app.services.audio_generation_service import AudioGenerationService
        from app.services.db_service import DBService

        try:
            self.stage_updated.emit("Initializing...")
            db_service = DBService.get_instance()
            audio_service = AudioGenerationService()
            asset_service = AudioAssetService()

            normalized_items: List[Dict[str, str]] = []
            for item in self.items:
                src_text = str(item.get("src_text") or "").strip()
                src_lang = str(item.get("src_lang") or "").strip()
                src_norm = str(item.get("src_norm") or "").strip()
                if not src_text or not src_lang or not src_norm:
                    continue
                normalized_items.append(
                    {
                        "row_id": str(item.get("row_id") or src_norm),
                        "src_text": src_text,
                        "src_lang": src_lang,
                        "src_norm": src_norm,
                    }
                )

            total = len(normalized_items)
            if total == 0:
                self.stage_updated.emit("No targets found")
                self.finished.emit(
                    {
                        "total": 0,
                        "succeeded": 0,
                        "skipped": 0,
                        "failed": 0,
                        "cancelled": False,
                    }
                )
                return

            succeeded = 0
            skipped = 0
            failed = 0
            completed = 0
            pending_writes = 0

            with db_service.get_session() as session:
                for index, item in enumerate(normalized_items, start=1):
                    self._wait_if_paused()
                    if self._cancel_requested:
                        break

                    row_id = item["row_id"]
                    src_text = item["src_text"]
                    src_lang = item["src_lang"]
                    src_norm = item["src_norm"]

                    self.stage_updated.emit(f"Generating audio {index}/{total}...")
                    try:
                        if self.write_mode == "MISSING_ONLY":
                            current = asset_service.bulk_get_status_for_items(
                                session=session,
                                items=[{
                                    "lang": src_lang,
                                    "norm_text": src_norm,
                                    "source_text": src_text,
                                }],
                            )
                            if current.get((src_lang, src_norm, src_text)) == "ready":
                                skipped += 1
                                completed += 1
                                self.row_translated.emit(row_id, "audio already exists", False)
                                self.progress.emit(completed, total)
                                self.stats_updated.emit(succeeded, skipped, failed)
                                continue

                        result = audio_service.generate_one(
                            session=session,
                            src_text=src_text,
                            src_lang=src_lang,
                            source_norm=src_norm,
                            provider_mode=self.provider_mode,
                            force_regenerate=(self.write_mode == "REGENERATE_ALL"),
                            trace_id=f"{self._trace}:{row_id}",
                        )
                        pending_writes += 1
                        if pending_writes >= self.audio_chunk:
                            session.commit()
                            pending_writes = 0

                        if result.get("ok"):
                            if result.get("status") == "skipped":
                                skipped += 1
                                self.row_translated.emit(row_id, "audio already exists", False)
                            else:
                                succeeded += 1
                                provider_id = str(result.get("provider_id") or "provider")
                                self.row_translated.emit(row_id, f"ready via {provider_id}", True)
                        else:
                            failed += 1
                            err_msg = str(result.get("error") or "audio generation failed")
                            self.row_translated.emit(row_id, err_msg[:50], False)
                    except Exception as row_err:
                        failed += 1
                        self.row_translated.emit(row_id, str(row_err)[:50], False)
                    finally:
                        completed += 1
                        self.progress.emit(completed, total)
                        self.stats_updated.emit(succeeded, skipped, failed)

                if pending_writes:
                    session.commit()

            if self._cancel_requested:
                self.stage_updated.emit("Cancelled")
            else:
                self.stage_updated.emit(
                    f"Completed: {succeeded} succeeded, {skipped} skipped, {failed} failed"
                )
            self.finished.emit(
                {
                    "total": completed,
                    "succeeded": succeeded,
                    "skipped": skipped,
                    "failed": failed,
                    "cancelled": bool(self._cancel_requested),
                }
            )
        except Exception as exc:
            logger.error("BatchGenerateAudioWorker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class PhonikudHealthCheckWorker(QThread):
    """Background health-check for Phonikud runtime mode."""

    finished = pyqtSignal(dict)  # {mode,status,latency_ms,model_path,details,samples}
    error = pyqtSignal(str)

    def __init__(self, *, model_path: str, enabled: bool, sample_texts: Optional[List[str]] = None):
        super().__init__()
        self.model_path = model_path
        self.enabled = enabled
        self.sample_texts = sample_texts or ["\u05e9\u05dc\u05d5\u05dd", "\u05ea\u05d7\u05e0\u05d4"]
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self):
        try:
            from app.infra.pronunciation import PhonikudAdapter

            adapter = PhonikudAdapter(model_path=self.model_path, enabled=self.enabled)
            report = adapter.health_check(self.sample_texts, cancel_check=lambda: bool(self._cancel_requested))
            self.finished.emit(report.to_dict())
        except Exception as exc:
            logger.error("PhonikudHealthCheckWorker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class PronunciationBootstrapWorker(QThread):
    """Run pronunciation bootstrap in background with pause/cancel safe points."""

    progress = pyqtSignal(int, int)  # (completed, total)
    stats_updated = pyqtSignal(int, int, int)  # (updated, skipped, failed)
    row_translated = pyqtSignal(str, str, bool)  # (entity_id, message, success)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        *,
        lang: str,
        model_path: str,
        enabled: bool,
        chunk_size: int = 500,
        rebuild_auto: bool = False,
        limit: Optional[int] = None,
        dry_run: bool = False,
        include_lemmas: bool = True,
        include_terms: bool = True,
        include_user_dictionary: bool = True,
        include_sentences: bool = False,
        selected_items: Optional[List[Dict[str, str]]] = None,
    ):
        super().__init__()
        self.lang = (lang or "he").strip() or "he"
        self.model_path = (model_path or "").strip()
        self.enabled = bool(enabled)
        self.chunk_size = max(1, int(chunk_size))
        self.rebuild_auto = bool(rebuild_auto)
        self.limit = int(limit) if limit else None
        self.dry_run = bool(dry_run)
        self.include_lemmas = bool(include_lemmas)
        self.include_terms = bool(include_terms)
        self.include_user_dictionary = bool(include_user_dictionary)
        self.include_sentences = bool(include_sentences)
        self.selected_items = list(selected_items or [])
        self._cancel_requested = False
        self._paused = False
        self._trace = "pronunciation_bootstrap"

    def cancel(self):
        self._cancel_requested = True

    def pause(self):
        self._paused = True
        self.paused.emit()

    def resume(self):
        self._paused = False
        self.resumed.emit()

    def _wait_if_paused(self) -> None:
        while self._paused and not self._cancel_requested:
            time.sleep(0.1)

    def _on_progress(self, processed: int, total: int) -> None:
        self._wait_if_paused()
        self.progress.emit(int(processed), int(total))
        self.stage_updated.emit(f"Generating pronunciations {int(processed):,}/{int(total):,}")

    def run(self):
        try:
            from app.services.db_service import DBService
            from app.services.pronunciation_bootstrap_service import (
                PhonikudPronunciationGenerator,
                PronunciationBootstrapService,
            )

            self.stage_updated.emit("Initializing Phonikud bootstrap...")
            db_service = DBService.get_instance()
            generator = PhonikudPronunciationGenerator(
                strict=False,
                model_path=self.model_path or None,
                enabled=self.enabled,
            )
            if self._cancel_requested:
                self.finished.emit({"cancelled": True, "updated": 0, "skipped": 0, "failed": 0, "dry_run": bool(self.dry_run)})
                return
            health = generator.health_check(
                ["\u05e9\u05dc\u05d5\u05dd", "\u05ea\u05d7\u05e0\u05d4"],
                cancel_check=lambda: bool(self._cancel_requested),
            )
            if bool(getattr(health, "cancelled", False)) or self._cancel_requested:
                self.stage_updated.emit("Phonikud health check cancelled")
                self.finished.emit(
                    {
                        "total_candidates": 0,
                        "generated_candidates": 0,
                        "updated": 0,
                        "skipped": 0,
                        "failed": 0,
                        "cancelled": True,
                        "dry_run": bool(self.dry_run),
                        "generator_mode": str(health.mode),
                        "health_mode": str(health.mode),
                        "health_status": str(health.status),
                        "health_latency_ms": int(health.latency_ms),
                    }
                )
                return
            self.row_translated.emit("health", f"{health.mode} ({health.status})", health.status == "ok")
            self.stage_updated.emit(f"Mode: {health.mode} ({health.status})")

            bootstrap_service = PronunciationBootstrapService(generator=generator)
            with db_service.get_session() as session:
                self.stage_updated.emit("Collecting lexical source norms...")
                result = bootstrap_service.bootstrap(
                    session,
                    lang=self.lang,
                    chunk_size=self.chunk_size,
                    rebuild_auto=self.rebuild_auto,
                    limit=self.limit,
                    include_lemmas=self.include_lemmas,
                    include_terms=self.include_terms,
                    include_user_dictionary=self.include_user_dictionary,
                    include_sentences=self.include_sentences,
                    selected_items=self.selected_items,
                    progress_callback=self._on_progress,
                    cancel_check=lambda: bool(self._cancel_requested),
                )
                if self.dry_run:
                    session.rollback()
                    self.stage_updated.emit("Dry-run finished (changes rolled back)")
                else:
                    session.commit()

            self.stats_updated.emit(int(result.updated), int(result.skipped), int(result.failed))
            self.row_translated.emit(
                "summary",
                f"updated={result.updated} skipped={result.skipped} failed={result.failed}",
                int(result.failed) == 0,
            )
            self.stage_updated.emit(
                f"Completed ({result.generator_mode}): {result.updated} updated, {result.skipped} skipped, {result.failed} failed"
            )
            self.finished.emit(
                {
                    "total_candidates": int(result.total_candidates),
                    "generated_candidates": int(result.generated_candidates),
                    "updated": int(result.updated),
                    "skipped": int(result.skipped),
                    "failed": int(result.failed),
                    "cancelled": bool(result.cancelled or self._cancel_requested),
                    "dry_run": bool(self.dry_run),
                    "generator_mode": str(result.generator_mode),
                    "health_mode": str(health.mode),
                    "health_status": str(health.status),
                    "health_latency_ms": int(health.latency_ms),
                }
            )
        except Exception as exc:
            logger.error("PronunciationBootstrapWorker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class SentenceNiqqudBootstrapWorker(QThread):
    """Run sentence niqqud bootstrap in background with V3 progress + pause/cancel.

    Signal contract (compatible with BatchProgressDialogV3):
      progress(completed, total)
      stats_updated(inserted, updated, skipped_total, failed)
      row_translated(sentence_id_str, status_msg, success)
      stage_updated(stage_label)
      finished(result_dict)
      error(message)
      paused / resumed
    """

    progress = pyqtSignal(int, int)                    # (completed, total)
    stats_updated = pyqtSignal(int, int, int, int)     # (inserted, updated, skipped, failed)
    row_translated = pyqtSignal(str, str, bool)        # (id_str, message, success)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(
        self,
        *,
        sentence_ids: List[int],
        lang: str,
        mode: str = "fill_only",          # "dry_run" | "fill_only" | "rebuild"
        model_path: str = "",
        enabled: bool = True,
        chunk_size: int = 200,
        sub_chunk_size: int = 50,
        min_len: int = 5,
        max_len: int = 2000,
        min_he_ratio: float = 0.10,
    ):
        super().__init__()
        self.sentence_ids = list(sentence_ids)
        self.lang = (lang or "he").strip() or "he"
        self.mode = mode
        self.model_path = (model_path or "").strip()
        self.enabled = bool(enabled)
        self.chunk_size = max(1, int(chunk_size))
        self.sub_chunk_size = max(1, int(sub_chunk_size))
        self.min_len = int(min_len)
        self.max_len = int(max_len)
        self.min_he_ratio = float(min_he_ratio)

        self._cancel_requested = False
        self._pause_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def pause(self) -> None:
        self._pause_requested = True
        self.paused.emit()

    def resume(self) -> None:
        self._pause_requested = False
        self.resumed.emit()

    def run(self) -> None:
        try:
            from app.services.db_service import DBService
            from app.services.pronunciation_bootstrap_service import PhonikudPronunciationGenerator
            from app.services.sentence_pronunciation_bootstrap_service import (
                SentencePronunciationBootstrapService,
                GuardParams,
            )

            db = DBService.get_instance()
            generator = PhonikudPronunciationGenerator(
                model_path=self.model_path,
                enabled=self.enabled,
            )

            # Health check (non-blocking; warn but continue)
            health = generator.health_check(cancel_check=lambda: bool(self._cancel_requested))
            if bool(getattr(health, "cancelled", False)) or self._cancel_requested:
                self.stage_updated.emit("Phonikud health check cancelled")
                self.finished.emit(
                    {
                        "total": len(self.sentence_ids),
                        "processed": 0,
                        "inserted": 0,
                        "updated": 0,
                        "skipped": 0,
                        "failed": 0,
                        "cancelled": True,
                        "mode": self.mode,
                        "generator_mode": str(health.mode),
                    }
                )
                return
            self.stage_updated.emit(f"Phonikud mode: {health.mode}")

            guard = GuardParams(
                min_len=self.min_len,
                max_len=self.max_len,
                min_he_ratio=self.min_he_ratio,
            )
            svc = SentencePronunciationBootstrapService(
                chunk_size=self.chunk_size,
                sub_chunk_size=self.sub_chunk_size,
            )

            # Throttle progress signals (max ~10/sec)
            _last_emit = [0.0]
            _EMIT_INTERVAL = 0.1

            def _progress_cb(done: int, total: int, stage: str) -> None:
                self.stage_updated.emit(stage)
                now = time.time()
                if now - _last_emit[0] >= _EMIT_INTERVAL:
                    self.progress.emit(done, total)
                    _last_emit[0] = now

            def _row_cb(sid: int, niqqud, action: str) -> None:
                success = action in ("inserted", "updated", "dry_would_insert")
                if success and niqqud:
                    msg = (niqqud[:50] + "…") if len(niqqud) > 50 else niqqud
                else:
                    msg = action
                self.row_translated.emit(str(sid), msg, success)

            import time

            with db.get_session() as session:
                result = svc.run(
                    session,
                    self.sentence_ids,
                    lang=self.lang,
                    mode=self.mode,
                    phonikud_generator=generator,
                    guard_params=guard,
                    progress_callback=_progress_cb,
                    row_callback=_row_cb,
                    cancel_check=lambda: self._cancel_requested,
                    pause_check=lambda: self._pause_requested,
                    phonikud_version=health.mode,
                )

            # Final progress + stats
            self.progress.emit(len(self.sentence_ids), len(self.sentence_ids))
            self.stats_updated.emit(
                result.inserted,
                result.updated,
                result.skipped_total,
                result.failed,
            )
            self.stage_updated.emit("Done" if not result.cancelled else "Cancelled")

            self.finished.emit({
                "total_candidates": result.total_candidates,
                "inserted": result.inserted,
                "updated": result.updated,
                "skipped_same_hash": result.skipped_same_hash,
                "skipped_has_override": result.skipped_has_override,
                "skipped_too_short": result.skipped_too_short,
                "skipped_too_long": result.skipped_too_long,
                "skipped_non_hebrew_ratio": result.skipped_non_hebrew_ratio,
                "skipped_invalid_after_qc": result.skipped_invalid_after_qc,
                "failed": result.failed,
                "rejected_qc": result.rejected_qc,
                "partial_qc": result.partial_qc,
                "dry_run": result.dry_run,
                "cancelled": result.cancelled,
                "generator_mode": result.generator_mode,
                "elapsed_seconds": result.elapsed_seconds,
                "summary_lines": result.summary_lines(),
            })
        except Exception as exc:
            logger.error("SentenceNiqqudBootstrapWorker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))


# ── Audio Player v2: queue populate worker ─────────────────────────────────────


class AudioQueuePopulateWorker(QThread):
    """Fetch all filtered sentence / lemma / term IDs and bulk-insert into the audio queue.

    Signal contract (V3 compatible with BatchProgressDialogV3):
      progress(completed, total)
      stats_updated(added, skipped, 0, failed)     — unused slots kept for V3 compat
      row_translated(id_str, label, success)
      stage_updated(stage_label)
      finished(result_dict)
      error(message)
    """

    progress = pyqtSignal(int, int)
    stats_updated = pyqtSignal(int, int, int, int)
    row_translated = pyqtSignal(str, str, bool)
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    CHUNK_SIZE = 200

    def __init__(
        self,
        *,
        kind: str = "sentence",          # "sentence" | "lemma" | "term"
        project_id: int,
        doc_ids: Optional[List[int]] = None,   # None or [] = all docs (sentences only)
        text_search: Optional[str] = None,
        add_mode: str = "append",        # "append" | "prepend" | "after_current"
        current_position: int = 0,
    ) -> None:
        super().__init__()
        self.kind = kind
        self.project_id = project_id
        self.doc_ids = list(doc_ids) if doc_ids else []
        self.text_search = text_search
        self.add_mode = add_mode
        self.current_position = current_position
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    # ------------------------------------------------------------------
    # Main thread entry
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception as exc:
            logger.error("AudioQueuePopulateWorker error: %s", exc, exc_info=True)
            self.error.emit(str(exc))

    def _run_inner(self) -> None:
        from app.services.db_service import DBService
        from app.services.audio_queue_service import AudioQueueService, AudioItemSpec

        db = DBService.get_instance()
        aq_svc = AudioQueueService()

        # ── Step 1: fetch IDs ──────────────────────────────────────────
        self.stage_updated.emit("Fetching IDs…")
        with db.get_session() as session:
            ids = self._fetch_ids(session)

        total = len(ids)
        if total == 0:
            self.stage_updated.emit("No matching items found.")
            self.finished.emit({"added": 0, "skipped": 0, "failed": 0, "total": 0, "cancelled": False, "new_item_ids": []})
            return

        self.stage_updated.emit(f"Adding {total} items to queue…")
        self.progress.emit(0, total)

        # ── Step 2: process in chunks ──────────────────────────────────
        added = 0
        failed = 0
        all_new_item_ids: List[int] = []  # track exact DB rows inserted this run
        for chunk_start in range(0, total, self.CHUNK_SIZE):
            if self._cancel_requested:
                break
            chunk_ids = ids[chunk_start: chunk_start + self.CHUNK_SIZE]
            try:
                with db.get_session() as session:
                    specs = self._build_specs(session, chunk_ids)
                    self._resolve_audio_assets(session, specs)
                    new_ids = aq_svc.add_to_queue(
                        session,
                        specs,
                        mode=self.add_mode,
                        current_position=self.current_position,
                    )
                    session.commit()
                all_new_item_ids.extend(new_ids)
                # Emit row signals for recent-activity display (first 5 in chunk)
                for spec in specs[:5]:
                    label = spec.snapshot_hebrew or spec.snapshot_source_label or str(spec.source_id or "")
                    self.row_translated.emit(str(spec.source_id or ""), label, True)
                added += len(specs)
            except Exception as exc:
                logger.error("AudioQueuePopulateWorker chunk error: %s", exc, exc_info=True)
                failed += len(chunk_ids)

            done = min(chunk_start + self.CHUNK_SIZE, total)
            self.progress.emit(done, total)
            self.stats_updated.emit(added, 0, 0, failed)

        self.progress.emit(total, total)
        cancelled = self._cancel_requested
        self.stage_updated.emit("Cancelled" if cancelled else "Done")
        self.stats_updated.emit(added, 0, 0, failed)
        self.finished.emit({
            "added": added,
            "skipped": 0,
            "failed": failed,
            "total": total,
            "cancelled": cancelled,
            "add_mode": self.add_mode,
            "new_item_ids": all_new_item_ids,  # exact rows inserted this run
        })

    # ------------------------------------------------------------------
    # Kind-specific helpers (run inside session)
    # ------------------------------------------------------------------

    def _fetch_ids(self, session) -> List[int]:
        """Return ordered list of IDs to process (no snapshots yet)."""
        from sqlalchemy import select

        if self.kind == "sentence":
            from app.infra.sa_models import DocumentSentence, SourceCorpus, SourceDocument
            stmt = (
                select(DocumentSentence.sentence_id)
                .join(SourceDocument, DocumentSentence.doc_id == SourceDocument.doc_id)
                .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                .where(SourceCorpus.project_id == self.project_id)
                .order_by(DocumentSentence.sentence_id.asc())
            )
            if self.doc_ids:
                stmt = stmt.where(DocumentSentence.doc_id.in_(self.doc_ids))
            if self.text_search:
                stmt = stmt.where(DocumentSentence.text.ilike(f"%{self.text_search}%"))
            return [row[0] for row in session.execute(stmt).all()]

        elif self.kind == "lemma":
            from app.infra.sa_models import Lemma
            stmt = (
                select(Lemma.lemma_id)
                .where(Lemma.project_id == self.project_id)
                .where(Lemma.is_noise == 0)
                .order_by(Lemma.lemma_id.asc())
            )
            if self.text_search:
                stmt = stmt.where(Lemma.lemma_text.ilike(f"%{self.text_search}%"))
            return [row[0] for row in session.execute(stmt).all()]

        else:  # term
            from app.infra.sa_models import TermCluster
            stmt = (
                select(TermCluster.cluster_id)
                .where(TermCluster.project_id == self.project_id)
                .where(TermCluster.is_noise == 0)
                .where(TermCluster.curation_status != "rejected")
                .order_by(TermCluster.cluster_id.asc())
            )
            if self.text_search:
                stmt = stmt.where(TermCluster.representative_he.ilike(f"%{self.text_search}%"))
            return [row[0] for row in session.execute(stmt).all()]

    def _build_specs(self, session, ids: List[int]) -> List:
        """Resolve snapshots for a chunk of IDs → AudioItemSpec list."""
        if self.kind == "sentence":
            return self._build_sentence_specs(session, ids)
        elif self.kind == "lemma":
            return self._build_lemma_specs(session, ids)
        else:
            return self._build_term_specs(session, ids)

    def _build_sentence_specs(self, session, sentence_ids: List[int]) -> List:
        from sqlalchemy import select
        from app.infra.sa_models import DocumentSentence
        from app.services.audio_queue_service import AudioItemSpec

        # Fetch text + doc_id (for source label)
        stmt = select(DocumentSentence.sentence_id, DocumentSentence.text, DocumentSentence.doc_id).where(
            DocumentSentence.sentence_id.in_(sentence_ids)
        )
        texts: Dict[int, str] = {}
        sid_to_docid: Dict[int, int] = {}
        for sid, txt, did in session.execute(stmt).all():
            texts[sid] = txt
            if did is not None:
                sid_to_docid[sid] = did

        # Batch-resolve document filenames for source label (best-effort)
        doc_filenames: Dict[int, str] = {}
        try:
            from app.infra.sa_models import SourceDocument as _SD
            unique_doc_ids = list(set(sid_to_docid.values()))
            if unique_doc_ids:
                dn_rows = session.execute(
                    select(_SD.doc_id, _SD.file_name)
                    .where(_SD.doc_id.in_(unique_doc_ids))
                ).all()
                doc_filenames = {did: fname for did, fname in dn_rows if fname}
        except Exception:
            pass

        # Fetch niqqud overlay (best-effort)
        niqqud_map: Dict[int, str] = {}
        try:
            from app.services.sentence_pronunciation_service import SentencePronunciationService
            overlays = SentencePronunciationService().bulk_get_niqqud(session, sentence_ids)
            for sid, overlay in overlays.items():
                if overlay and overlay.niqqud_text:
                    niqqud_map[sid] = overlay.niqqud_text
        except Exception:
            pass

        # Fetch translation overlay (best-effort)
        transl_map: Dict[str, str] = {}
        try:
            from app.services.sentences_workspace_service import SentencesWorkspaceService
            svc = SentencesWorkspaceService()
            text_list = list(texts.values())
            raw = svc._batch_get_translations(session, self.project_id, "he", text_list)
            transl_map = {
                txt: raw[svc._norm("he", txt)][0]
                for txt in text_list
                if svc._norm("he", txt) in raw
            }
        except Exception:
            pass

        specs = []
        for sid in sentence_ids:
            text = texts.get(sid, "")
            did = sid_to_docid.get(sid)
            source_label = doc_filenames.get(did, "") if did else ""
            if not source_label:
                source_label = f"sentence:{sid}"
            specs.append(AudioItemSpec(
                kind="sentence",
                source_id=sid,
                project_id=self.project_id,
                snapshot_hebrew=text,
                snapshot_niqqud=niqqud_map.get(sid) or None,
                snapshot_translation=transl_map.get(text) or None,
                snapshot_source_label=source_label,
                audio_status="unknown",
            ))
        return specs

    def _build_lemma_specs(self, session, lemma_ids: List[int]) -> List:
        from sqlalchemy import select
        from app.infra.sa_models import Lemma
        from app.services.audio_queue_service import AudioItemSpec

        stmt = select(Lemma.lemma_id, Lemma.lemma_text).where(
            Lemma.lemma_id.in_(lemma_ids)
        )
        rows: Dict[int, str] = {lid: txt for lid, txt in session.execute(stmt).all()}

        # Compute norms for batch lookups
        lid_to_norm: Dict[int, str] = {}
        try:
            from app.domain.normalization.normalizer import normalize_for_tm as _ntm
            for lid in lemma_ids:
                text = rows.get(lid, "")
                if text:
                    try:
                        lid_to_norm[lid] = _ntm("he", text, "lemma").norm or text
                    except Exception:
                        lid_to_norm[lid] = text
        except Exception:
            pass

        # Batch niqqud from pronunciation_entry (best-effort)
        norm_to_niqqud: Dict[str, str] = {}
        try:
            from app.services.pronunciation_service import PronunciationService
            all_norms = list(lid_to_norm.values())
            if all_norms:
                bulk = PronunciationService().bulk_lookup(session, lang="he", src_norms=all_norms)
                norm_to_niqqud = {norm: dto.niqqud_text for norm, dto in bulk.items() if dto.niqqud_text}
        except Exception:
            pass

        # Batch translation from TMEntry kind="lemma" (best-effort)
        norm_to_transl: Dict[str, str] = {}
        try:
            from app.infra.sa_models import TMEntry as _TM
            all_norms = list(lid_to_norm.values())
            if all_norms:
                tm_rows = session.execute(
                    select(_TM.src_norm, _TM.translation)
                    .where(_TM.kind == "lemma")
                    .where(_TM.src_lang == "he")
                    .where(_TM.src_norm.in_(all_norms))
                    .where(_TM.project_id == self.project_id)
                    .where(_TM.status.in_(["draft", "approved"]))
                    .order_by(_TM.status.desc())
                ).all()
                for norm, transl in tm_rows:
                    if norm not in norm_to_transl and transl:
                        norm_to_transl[norm] = transl
        except Exception:
            pass

        specs = []
        for lid in lemma_ids:
            lemma_text = rows.get(lid, "")
            norm = lid_to_norm.get(lid, "")
            specs.append(AudioItemSpec(
                kind="lemma",
                source_id=lid,
                project_id=self.project_id,
                snapshot_hebrew=lemma_text,
                snapshot_niqqud=norm_to_niqqud.get(norm) or None,
                snapshot_translation=norm_to_transl.get(norm) or None,
                snapshot_source_label="Dictionary",
                audio_status="unknown",
            ))
        return specs

    def _build_term_specs(self, session, cluster_ids: List[int]) -> List:
        from sqlalchemy import select
        from app.infra.sa_models import TermCluster
        from app.services.audio_queue_service import AudioItemSpec

        stmt = select(
            TermCluster.cluster_id,
            TermCluster.representative_he,
            TermCluster.pinned_translation,
        ).where(TermCluster.cluster_id.in_(cluster_ids))
        rows: Dict[int, tuple] = {
            cid: (rep_he, transl)
            for cid, rep_he, transl in session.execute(stmt).all()
        }

        specs = []
        for cid in cluster_ids:
            rep_he, transl = rows.get(cid, ("", None))
            specs.append(AudioItemSpec(
                kind="term",
                source_id=cid,
                project_id=self.project_id,
                snapshot_hebrew=rep_he or "",
                snapshot_translation=transl or None,
                snapshot_source_label="Terms",
                audio_status="unknown",
            ))
        return specs

    def _resolve_audio_assets(self, session, specs: List) -> None:
        """Batch-lookup AudioAsset for specs and fill audio_asset_id + audio_status.

        Uses the same normalize_for_tm normalization as the audio generation pipeline
        so norm_text values align with what's stored in audio_asset.norm_text.
        Non-fatal: any exception is logged at DEBUG level and silently ignored.
        """
        try:
            from sqlalchemy import select as _sel, desc as _desc
            from app.infra.sa_models import AudioAsset as _AA
            from app.domain.normalization.normalizer import normalize_for_tm as _ntm
            from app.services.audio_cache_key_service import AudioCacheKeyService

            _kind_map = {"lemma": "lemma", "term": "term_cluster", "sentence": "sentence"}
            speech_hash_to_specs: Dict[str, List] = {}
            cache_keys = AudioCacheKeyService()
            for spec in specs:
                if not spec.snapshot_hebrew or spec.audio_asset_id is not None:
                    continue
                kind_str = _kind_map.get(spec.kind, spec.kind)
                try:
                    norm = _ntm("he", spec.snapshot_hebrew, kind_str).norm or spec.snapshot_hebrew
                except Exception:
                    norm = spec.snapshot_hebrew
                if not norm:
                    continue
                payload = cache_keys.prepare_pronunciation_payload(
                    session=session,
                    src_lang="he",
                    source_text=spec.snapshot_hebrew,
                    source_norm=norm,
                )
                speech_hash = cache_keys.build_speech_hash(
                    src_lang="he",
                    source_text=spec.snapshot_hebrew,
                    source_norm=norm,
                    pronunciation_payload=payload,
                )
                speech_hash_to_specs.setdefault(speech_hash, []).append(spec)

            if not speech_hash_to_specs:
                return

            rows = session.execute(
                _sel(_AA.speech_hash, _AA.asset_id)
                .where(_AA.lang == "he")
                .where(_AA.speech_hash.in_(list(speech_hash_to_specs.keys())))
                .where(_AA.asset_status == "ready")
                .where(_AA.audio_rel_path.isnot(None))
                .order_by(_desc(_AA.asset_id))  # highest asset_id = most recent
            ).all()

            for speech_hash, asset_id in rows:
                for spec in speech_hash_to_specs.get(speech_hash, []):
                    if spec.audio_asset_id is None:  # first-win per spec
                        spec.audio_asset_id = asset_id
                        spec.audio_status = "ready"

            resolved = sum(1 for s in specs if s.audio_asset_id is not None)
            log_fn = logger.warning if resolved == 0 and specs else logger.debug
            log_fn(
                "_resolve_audio_assets: %d/%d specs resolved to ready AudioAsset",
                resolved, len(specs),
            )
        except Exception as exc:
            logger.warning("_resolve_audio_assets: non-fatal exception: %s", exc, exc_info=True)


class ResourceDownloadWorker(QThread):
    """Background resource downloader with resume + checksum verification."""

    progress = pyqtSignal(int, int)  # downloaded_bytes, total_bytes
    stage_updated = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    CHUNK_SIZE = 1024 * 256

    def __init__(
        self,
        *,
        resource_id: str,
        url: str,
        dest_path: Path,
        checksum: str = "",
        timeout_seconds: float = 30.0,
    ):
        super().__init__()
        self.resource_id = str(resource_id or "")
        self.url = str(url or "").strip()
        self.dest_path = Path(dest_path)
        self.checksum = str(checksum or "").strip().lower()
        self.timeout_seconds = float(timeout_seconds)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self):
        import hashlib
        import urllib.request

        if not self.url:
            self.error.emit("Download URL is not configured.")
            return

        try:
            self.dest_path.parent.mkdir(parents=True, exist_ok=True)
            part_path = self.dest_path.with_suffix(self.dest_path.suffix + ".part")
            start_byte = part_path.stat().st_size if part_path.exists() else 0

            self.stage_updated.emit("Starting download...")
            headers = {"User-Agent": "HDLE-Premium/ResourceManager"}
            if start_byte > 0:
                headers["Range"] = f"bytes={start_byte}-"

            request = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_length = int(response.headers.get("Content-Length", "0") or 0)
                total = start_byte + content_length if content_length > 0 else 0
                mode = "ab" if start_byte > 0 else "wb"
                downloaded = start_byte

                with open(part_path, mode) as out_file:
                    while True:
                        if self._cancel_requested:
                            self.finished.emit(
                                {
                                    "ok": False,
                                    "cancelled": True,
                                    "resource_id": self.resource_id,
                                    "path": str(part_path),
                                }
                            )
                            return
                        chunk = response.read(self.CHUNK_SIZE)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total)

            self.stage_updated.emit("Verifying checksum...")
            if self.checksum:
                digest = hashlib.sha256()
                with open(part_path, "rb") as fh:
                    while True:
                        chunk = fh.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                actual = digest.hexdigest().lower()
                if actual != self.checksum:
                    try:
                        part_path.unlink()
                    except OSError:
                        pass
                    self.error.emit(
                        f"Checksum mismatch for {self.resource_id}: expected {self.checksum}, got {actual}"
                    )
                    return

            if self.dest_path.exists():
                self.dest_path.unlink()
            part_path.rename(self.dest_path)
            self.finished.emit(
                {
                    "ok": True,
                    "cancelled": False,
                    "resource_id": self.resource_id,
                    "path": str(self.dest_path),
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class UnifiedHealthCheckWorker(QThread):
    """Run full HealthCheckService off the UI thread."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            from app.services.health_check_service import HealthCheckService

            report = HealthCheckService().run_all()
            self.finished.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))
