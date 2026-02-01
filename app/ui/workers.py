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
