"""QThread workers for project export/import operations."""

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.services.project_exchange.export_engine import ProjectExportEngine
from app.services.project_exchange.import_engine import ProjectImportEngine
from app.services.project_exchange.dto import (
    ExportOptions,
    ImportOptions,
    ExportReport,
    ImportReport,
)

logger = logging.getLogger(__name__)


def _format_heavy_operation_busy_error(operation_label: str, error: Exception) -> str:
    active_ops = list(getattr(error, "active_ops", []) or [])
    active_names = [str(getattr(op, "name", "")).strip() for op in active_ops if getattr(op, "name", None)]
    active_names = [name for name in active_names if name]
    if active_names:
        details = "\n".join(f"- {name}" for name in active_names[:5])
        if len(active_names) > 5:
            details += f"\n- ... and {len(active_names) - 5} more"
    else:
        details = "- Another heavy operation is already running"
    return (
        f"Cannot start '{operation_label}' right now.\n\n"
        "Another heavy background operation is already using the SQLite write slot:\n\n"
        f"{details}\n\n"
        "Wait for it to finish and try again."
    )


class ProjectExportWorker(QThread):
    """Worker thread for project export."""

    progress = pyqtSignal(str, int, int)  # stage, current, total
    finished = pyqtSignal(object)          # ExportReport
    error = pyqtSignal(str)

    def __init__(self, project_id: int, out_path: Path, options: ExportOptions):
        super().__init__()
        self.project_id = project_id
        self.out_path = out_path
        self.options = options
        self._cancelled = False

    def run(self):
        """Run export in background thread."""
        try:
            logger.info(f"Export worker starting for project {self.project_id}")
            engine = ProjectExportEngine()

            report = engine.export_project(
                project_id=self.project_id,
                out_path=self.out_path,
                options=self.options,
                progress_callback=self._on_progress,
                cancel_check=lambda: bool(self._cancelled),
            )

            if report.success:
                self.finished.emit(report)
            else:
                self.error.emit(report.error_message or "Export failed")

        except Exception as e:
            logger.exception("Export worker error")
            self.error.emit(self._make_user_friendly_error(e))

    def _on_progress(self, stage: str, current: int, total: int):
        """Progress callback from engine."""
        if not self._cancelled:
            self.progress.emit(stage, current, total)

    def cancel(self):
        """Cancel the export operation."""
        self._cancelled = True
        logger.info("Export worker cancelled")

    def _make_user_friendly_error(self, error: Exception) -> str:
        """Convert technical error to user-friendly message."""
        error_str = str(error)

        if "Insufficient disk space" in error_str:
            return f"Export failed: Not enough disk space. {error_str}"
        elif "Project" in error_str and "not found" in error_str:
            return "Export failed: Project not found. It may have been deleted."
        elif "malformed" in error_str.lower() or "corrupt" in error_str.lower():
            return f"Export failed: {error_str}"
        elif "Permission denied" in error_str or "Access is denied" in error_str:
            return "Export failed: Permission denied. Check file permissions and try again."
        else:
            return f"Export failed: {error_str}"


class ProjectImportWorker(QThread):
    """Worker thread for project import."""

    progress = pyqtSignal(str, int, int)  # stage, current, total
    finished = pyqtSignal(object)          # ImportReport
    error = pyqtSignal(str)

    def __init__(self, bundle_path: Path, options: ImportOptions):
        super().__init__()
        self.bundle_path = bundle_path
        self.options = options
        self._cancelled = False

    def run(self):
        """Run import in background thread."""
        from app.services.operations_center import OperationsCenter, OperationsCenterBusyError

        op_id = None
        try:
            op_id = OperationsCenter.instance().register(
                f"Project Import ({self.bundle_path.name})",
                "project_import",
                enforce_limit=True,
            )
            logger.info(f"Import worker starting for bundle {self.bundle_path}")
            engine = ProjectImportEngine()

            report = engine.import_project(
                bundle_path=self.bundle_path,
                options=self.options,
                progress_callback=self._on_progress,
                cancel_check=lambda: bool(self._cancelled),
            )

            if report.success:
                self.finished.emit(report)
            else:
                self.error.emit(report.error_message or "Import failed")

        except OperationsCenterBusyError as e:
            self.error.emit(_format_heavy_operation_busy_error("Project Import", e))
        except Exception as e:
            logger.exception("Import worker error")
            self.error.emit(self._make_user_friendly_error(e))
        finally:
            if op_id:
                OperationsCenter.instance().unregister(op_id)

    def _on_progress(self, stage: str, current: int, total: int):
        """Progress callback from engine."""
        if not self._cancelled:
            self.progress.emit(stage, current, total)

    def cancel(self):
        """Cancel the import operation."""
        self._cancelled = True
        logger.info("Import worker cancelled")

    def _make_user_friendly_error(self, error: Exception) -> str:
        """Convert technical error to user-friendly message."""
        error_str = str(error)

        if "schema" in error_str.lower() and "requires" in error_str.lower():
            return f"Import failed: {error_str}\n\nPlease update HDLE Premium to import this bundle."
        elif "Checksum mismatch" in error_str or "corrupted" in error_str.lower():
            return "Import failed: Bundle is corrupted or tampered.\n\nPlease re-download the bundle and try again."
        elif "Project name" in error_str and "already exists" in error_str:
            return f"Import failed: {error_str}\n\nPlease use a different name or enable auto-rename."
        elif "Permission denied" in error_str or "Access is denied" in error_str:
            return "Import failed: Permission denied. Check file permissions and try again."
        else:
            return f"Import failed: {error_str}"
