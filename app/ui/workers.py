"""Background worker threads."""
import logging
from pathlib import Path
from typing import List

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

            with db_service.get_session() as session:
                try:
                    for idx, doc_id in enumerate(self.doc_ids):
                        # Get document name for progress
                        from app.infra.sa_models import SourceDocument
                        doc = session.get(SourceDocument, doc_id)
                        doc_name = doc.file_name if doc else f"Doc {doc_id}"

                        self.progress.emit(idx + 1, len(self.doc_ids), doc_name)

                        # Process or re-process document
                        try:
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
                            # Continue with next document

                except Exception as session_error:
                    logger.exception("Session error during processing")
                    session.rollback()
                    raise

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
