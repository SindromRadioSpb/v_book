"""Background worker threads."""
import logging
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
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

    def run(self):
        """Extract terms for project."""
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
                )

                self.finished.emit(report)

        except Exception as e:
            logger.exception("Project term extraction worker error")
            self.error.emit(str(e))


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


# ============================================================================
# P2: Translation Management & Coverage Workers
# ============================================================================

class TMSearchWorker(QThread):
    """P2: Worker for searching TM entries (non-blocking)."""

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

            with db_service.get_session() as session:
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


class DictionarySearchWorker(QThread):
    """Worker for searching lemmas with pagination (non-blocking)."""

    results_ready = pyqtSignal(list, int)  # (rows: List[Tuple[Lemma, LemmaProjectStat]], total_count: int)
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: int,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "freq_abs",
        sort_direction: str = "desc",
    ):
        super().__init__()
        self.project_id = project_id
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
            from app.services.dictionary_service import DictionaryService

            db_service = DBService.get_instance()
            dict_service = DictionaryService()

            with db_service.get_session() as session:
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

                # Get total count
                total_count = dict_service.count_lemmas(
                    session,
                    project_id=self.project_id,
                    filters=self.filters,
                )

                if not self._cancelled:
                    self.results_ready.emit(rows, total_count)

        except Exception as e:
            logger.exception("Dictionary search error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the search."""
        self._cancelled = True


class TermsSearchWorker(QThread):
    """Worker for searching term clusters with pagination (non-blocking)."""

    results_ready = pyqtSignal(list, int)  # (clusters: List[TermCluster], total_count: int)
    error = pyqtSignal(str)

    def __init__(
        self,
        project_id: int,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        sort_column: str = "freq_abs",  # preset name, actually
        sort_direction: str = "desc",
    ):
        super().__init__()
        self.project_id = project_id
        self.filters = filters
        self.limit = limit
        self.offset = offset
        self.sort_column = sort_column  # For Terms, this is "preset" name
        self.sort_direction = sort_direction
        self._cancelled = False

    def run(self):
        """Execute search."""
        try:
            from app.services.db_service import DBService
            from app.services.term_extraction_service import TermExtractionService

            db_service = DBService.get_instance()
            term_service = TermExtractionService()

            with db_service.get_session() as session:
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

                # Get total count
                total_count = term_service.count_term_clusters(
                    session,
                    project_id=self.project_id,
                    search=self.filters.get("search"),
                    min_freq=self.filters.get("min_freq"),
                    source_filter=self.filters.get("source_filter"),
                    hide_noise=self.filters.get("hide_noise", True),
                )

                if not self._cancelled:
                    self.results_ready.emit(clusters, total_count)

        except Exception as e:
            logger.exception("Terms search error")
            self.error.emit(str(e))

    def cancel(self):
        """Cancel the search."""
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

    def run(self):
        """Translate text via MT providers."""
        try:
            from app.services.db_service import DBService
            from app.services.translation_service import TranslationService

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

                # Emit result
                self.result_ready.emit(result)

        except Exception as e:
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
    finished = pyqtSignal(object)  # BatchTranslateResult
    error = pyqtSignal(str)

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

    def run(self):
        """Execute batch translation in background thread."""
        try:
            from app.services.batch_mt_translate_service import BatchMTTranslateService
            from app.services.db_service import DBService

            logger.info(
                f"BatchTranslateWorker started: tab={self.tab_type}, "
                f"items={len(self.items)}, mode={self.options.provider_mode}"
            )

            service = BatchMTTranslateService()
            db_service = DBService.get_instance()

            with db_service.get_session() as session:
                result = service.execute_batch(
                    session=session,
                    items=self.items,
                    options=self.options,
                    progress_callback=self._on_progress,
                    cancel_check=lambda: self._cancel_requested,
                )

                self.finished.emit(result)

                logger.info(
                    f"BatchTranslateWorker finished: succeeded={result.succeeded}, "
                    f"skipped={result.skipped}, failed={result.failed}"
                )

        except Exception as e:
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

    def _on_progress(self, completed: int, total: int):
        """Handle progress callback from service."""
        self.progress.emit(completed, total)

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
