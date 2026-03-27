"""In-app Resources Manager for local models and reference datasets."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService
from app.services.project_exchange.dto import ImportOptions
from app.services.project_exchange.worker import ProjectImportWorker
from app.services.nlp_runtime import NlpRuntimeProbe
from app.services.resources import ResourceRegistry
from app.ui.workers import ResourceDownloadWorker, UnifiedHealthCheckWorker

logger = logging.getLogger(__name__)


class ResourcesManagerDialog(QDialog):
    """Manage required/optional local resources with worker-safe operations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resources Manager")
        self.setMinimumSize(980, 640)

        self.settings = SettingsService.get_instance()
        self.registry = ResourceRegistry(settings=self.settings)
        self.nlp_probe = NlpRuntimeProbe()
        self._entries = {}
        self._statuses = {}
        self._download_worker = None
        self._health_worker = None
        self._import_worker = None
        self._progress_dialog: QProgressDialog | None = None
        self._last_nlp_runtime_status = None
        self._last_nlp_runtime_message = ""

        self._init_ui()
        self._load_data_root()
        self.refresh_resources()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("<h2>Resources Manager</h2>")
        root.addWidget(title)

        subtitle = QLabel(
            "Install or repair local models and optional baseline bundles. "
            "All operations run in background and validate integrity before activation."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.nlp_runtime_title_label = QLabel("<b>External Runtime Dependency</b>")
        root.addWidget(self.nlp_runtime_title_label)

        self.nlp_runtime_label = QLabel("Checking Python runtime, stanza package, and torch state...")
        self.nlp_runtime_label.setWordWrap(True)
        root.addWidget(self.nlp_runtime_label)

        self.hebrew_resource_title_label = QLabel("<b>Managed Hebrew Resource</b>")
        root.addWidget(self.hebrew_resource_title_label)

        self.hebrew_resource_label = QLabel("Checking Hebrew model path and local resource presence...")
        self.hebrew_resource_label.setWordWrap(True)
        root.addWidget(self.hebrew_resource_label)

        nlp_actions = QHBoxLayout()
        self.refresh_nlp_btn = QPushButton("Re-run NLP Probe")
        self.refresh_nlp_btn.clicked.connect(self._refresh_nlp_runtime_status)
        nlp_actions.addWidget(self.refresh_nlp_btn)

        self.show_nlp_guide_btn = QPushButton("Show Repair Steps")
        self.show_nlp_guide_btn.clicked.connect(self._show_nlp_setup_guide)
        nlp_actions.addWidget(self.show_nlp_guide_btn)

        self.open_nlp_model_folder_btn = QPushButton("Open NLP Model Folder")
        self.open_nlp_model_folder_btn.clicked.connect(self._open_nlp_model_folder)
        self.open_nlp_model_folder_btn.setEnabled(False)
        nlp_actions.addWidget(self.open_nlp_model_folder_btn)
        nlp_actions.addStretch()
        root.addLayout(nlp_actions)

        data_row = QGridLayout()
        data_row.addWidget(QLabel("Data folder:"), 0, 0)
        self.data_root_edit = QLineEdit()
        data_row.addWidget(self.data_root_edit, 0, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_data_root)
        data_row.addWidget(browse_btn, 0, 2)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_data_root)
        data_row.addWidget(apply_btn, 0, 3)
        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_data_root)
        data_row.addWidget(open_btn, 0, 4)
        root.addLayout(data_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Resource", "Type", "Required", "Status", "Version", "Location"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_resources)
        actions.addWidget(self.refresh_btn)

        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self._download_selected)
        actions.addWidget(self.download_btn)

        self.import_btn = QPushButton("Import from File...")
        self.import_btn.clicked.connect(self._import_selected_file)
        actions.addWidget(self.import_btn)

        self.verify_btn = QPushButton("Verify")
        self.verify_btn.clicked.connect(self._verify_selected)
        actions.addWidget(self.verify_btn)

        self.repair_btn = QPushButton("Repair")
        self.repair_btn.clicked.connect(self._repair_selected)
        actions.addWidget(self.repair_btn)

        self.open_folder_btn = QPushButton("Open Resource Folder")
        self.open_folder_btn.clicked.connect(self._open_selected_folder)
        actions.addWidget(self.open_folder_btn)

        self.import_baseline_btn = QPushButton("Import Baseline Bundle")
        self.import_baseline_btn.clicked.connect(self._import_baseline_bundle)
        actions.addWidget(self.import_baseline_btn)

        self.health_btn = QPushButton("Run Health Check")
        self.health_btn.clicked.connect(self._run_health_check)
        actions.addWidget(self.health_btn)
        actions.addStretch()
        root.addLayout(actions)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Operation log...")
        root.addWidget(self.log_view, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _append_log(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self._append_log(text)

    def _load_data_root(self) -> None:
        root = self.settings.get_string(ResourcePaths.SETTINGS_KEY_DATA_ROOT, "")
        self.data_root_edit.setText(root)

    def _browse_data_root(self) -> None:
        current = self.data_root_edit.text().strip() or str(
            ResourcePaths.resolve_data_root(create=True)
        )
        directory = QFileDialog.getExistingDirectory(self, "Select Data Folder", current)
        if directory:
            self.data_root_edit.setText(directory)

    def _apply_data_root(self) -> None:
        value = (self.data_root_edit.text() or "").strip()
        self.settings.set_value(ResourcePaths.SETTINGS_KEY_DATA_ROOT, value)
        self.settings.sync()
        ResourcePaths.build(settings=self.settings, create=True)
        self._set_status("Data folder updated.")
        self.refresh_resources()

    def _open_data_root(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        root = ResourcePaths.build(settings=self.settings, create=True).data_root
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def refresh_resources(self) -> None:
        entries = self.registry.list_entries()
        statuses = {entry.id: self.registry.get_status(entry.id) for entry in entries}
        self._entries = {entry.id: entry for entry in entries}
        self._statuses = statuses
        self._refresh_nlp_runtime_status()

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            status = statuses.get(entry.id)
            location = ""
            if status and status.install_paths:
                location = str(status.install_paths[0].parent)
            values = [
                entry.display_name,
                entry.type,
                "Yes" if entry.required else "No",
                status.state if status else "unknown",
                entry.version,
                location,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, entry.id)
                if col == 3 and status:
                    item.setToolTip(status.message)
                self.table.setItem(row, col, item)

        self.table.resizeColumnsToContents()
        self._set_status("Resources list refreshed.")

    def _build_nlp_runtime_message(self, status) -> str:
        mode = "Packaged" if self.nlp_probe.is_packaged_runtime() else "Development"
        if status.stanza_ready:
            runtime = "GPU-capable" if status.cuda_available else "CPU-only"
            return (
                "External runtime dependency is ready. "
                f"Environment: {mode}. "
                "Package: stanza installed. "
                f"Runtime: {runtime}. "
                f"Reason code: none."
            )

        return (
            "External runtime dependency is unavailable. "
            f"Environment: {mode}. "
            f"Reason: {status.error_code or 'unavailable'}. "
            f"Remediation: {status.remediation or 'Repair the runtime outside this dialog.'}"
        )

    @staticmethod
    def _build_hebrew_resource_message(status) -> str:
        model_path = getattr(status, "model_path", None) if status is not None else None
        model_present = bool(getattr(status, "model_present", False)) if status is not None else False
        if model_present and model_path:
            return (
                "Managed Hebrew resource is present. "
                f"Model path: {model_path}. "
                "Use Open NLP Model Folder to inspect or replace the local files."
            )
        if model_path:
            return (
                "Managed Hebrew resource path is known but the resource is not ready. "
                f"Model path: {model_path}. "
                "Use offline import or copy the Hebrew model files into this location."
            )
        return (
            "Managed Hebrew resource is not detected. "
            "No Hebrew model path is currently known. "
            "Use offline import guidance or configure the resource path first."
        )

    def _apply_nlp_runtime_ui_state(self, status, message: str) -> None:
        self._last_nlp_runtime_status = status
        self._last_nlp_runtime_message = message
        self.nlp_runtime_label.setText(message)
        self.nlp_runtime_label.setToolTip(message)
        resource_message = self._build_hebrew_resource_message(status)
        self.hebrew_resource_label.setText(resource_message)
        self.hebrew_resource_label.setToolTip(resource_message)
        model_path = getattr(status, "model_path", None) if status is not None else None
        self.open_nlp_model_folder_btn.setEnabled(bool(model_path))
        if model_path:
            self.open_nlp_model_folder_btn.setToolTip(f"Open {model_path}")
        else:
            self.open_nlp_model_folder_btn.setToolTip("No Hebrew model path is currently detected.")
        self.show_nlp_guide_btn.setToolTip(
            "Open packaging-aware repair guidance for the external runtime and Hebrew model resource."
        )

    def _build_nlp_setup_guide_text(self) -> str:
        status = self._last_nlp_runtime_status
        mode = "Packaged mode" if self.nlp_probe.is_packaged_runtime() else "Development mode"
        plan = self.nlp_probe.build_guided_repair_plan(status)
        sections = [
            mode,
            "External runtime dependency:\n" + (self._last_nlp_runtime_message or "Run the isolated NLP probe first."),
            "Managed Hebrew resource:\n" + self._build_hebrew_resource_message(status),
            f"Recommended route: {plan['title']}",
            f"Next action: {plan['next_action']}",
        ]
        if status is not None and status.error_detail:
            sections.append(f"Details: {status.error_detail}")
        steps = self.nlp_probe.build_setup_steps(status) + [
            f"Guided flow: {step}" for step in plan["steps"]
        ]
        sections.append(
            "Repair steps:\n" + "\n".join(
                f"{index}. {step}" for index, step in enumerate(steps, start=1)
            )
        )
        return "\n\n".join(sections)

    def _refresh_nlp_runtime_status(self) -> None:
        try:
            status = self.nlp_probe.probe_stanza(use_gpu=False, run_smoke=True)
            self._apply_nlp_runtime_ui_state(status, self._build_nlp_runtime_message(status))
            return
        except Exception as exc:
            logger.warning("Resources Manager NLP runtime probe failed: %s", exc)
            self._apply_nlp_runtime_ui_state(
                None,
                "External runtime dependency is unavailable. "
                "Environment: unknown. "
                "Reason: runtime_probe_failed. "
                "Remediation: Check the local Torch/Stanza runtime and retry.",
            )

    def _show_nlp_setup_guide(self) -> None:
        QMessageBox.information(self, "NLP Setup Guide", self._build_nlp_setup_guide_text())

    def _open_nlp_model_folder(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        status = self._last_nlp_runtime_status
        model_path = getattr(status, "model_path", None) if status is not None else None
        if not model_path:
            QMessageBox.information(
                self,
                "NLP Model Folder",
                "No Hebrew model path is currently detected. Run the NLP probe or import the model first.",
            )
            return

        target = Path(model_path)
        folder = target if target.is_dir() else target.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _selected_entry_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _selected_entry(self):
        entry_id = self._selected_entry_id()
        if not entry_id:
            return None
        return self._entries.get(entry_id)

    def _selected_status(self):
        entry_id = self._selected_entry_id()
        if not entry_id:
            return None
        return self._statuses.get(entry_id)

    def _download_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(self, "Resources", "Select a resource first.")
            return
        if entry.payload_kind != "downloadable":
            QMessageBox.information(self, "Resources", "Selected resource is not downloadable.")
            return
        if not entry.download_url:
            QMessageBox.warning(
                self, "Resources", "Download URL is not configured for this resource."
            )
            return
        install_paths = self.registry.resolve_install_paths(entry)
        if not install_paths:
            QMessageBox.warning(self, "Resources", "No install path configured.")
            return

        self._progress_dialog = QProgressDialog("Downloading resource...", "Cancel", 0, 100, self)
        self._progress_dialog.setWindowTitle("Resource Download")
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.show()

        worker = ResourceDownloadWorker(
            resource_id=entry.id,
            url=entry.download_url,
            dest_path=install_paths[0],
            checksum=entry.checksum,
        )
        self._download_worker = worker
        worker.stage_updated.connect(self._set_status)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        self._progress_dialog.canceled.connect(worker.cancel)
        worker.start()

    def _on_download_progress(self, downloaded: int, total: int) -> None:
        if not self._progress_dialog:
            return
        if total <= 0:
            self._progress_dialog.setRange(0, 0)
            return
        self._progress_dialog.setRange(0, 100)
        percent = int((downloaded * 100) / total) if total else 0
        self._progress_dialog.setValue(max(0, min(100, percent)))
        self._progress_dialog.setLabelText(f"Downloading... {downloaded:,}/{total:,} bytes")

    def _on_download_finished(self, result: dict) -> None:
        if self._progress_dialog:
            self._progress_dialog.setValue(100)
            self._progress_dialog.close()
            self._progress_dialog = None
        self._download_worker = None
        if result.get("cancelled"):
            self._set_status("Download cancelled.")
            return
        self._set_status(f"Download completed: {result.get('path')}")
        self.refresh_resources()

    def _on_download_error(self, message: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        self._download_worker = None
        QMessageBox.warning(self, "Download Failed", str(message))
        self._set_status(f"Download failed: {message}")
        self.refresh_resources()

    def _import_selected_file(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            QMessageBox.information(self, "Resources", "Select a resource first.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Resource File", "", "All Files (*)"
        )
        if not file_path:
            return
        try:
            status = self.registry.install_from_file(entry.id, Path(file_path))
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))
            return
        self._set_status(f"Imported {entry.display_name}: {status.state}")
        self.refresh_resources()

    def _verify_selected(self) -> None:
        status = self._selected_status()
        entry = self._selected_entry()
        if entry is None or status is None:
            return
        status = self.registry.get_status(entry.id)
        self._set_status(f"Verify {entry.display_name}: {status.state} ({status.message})")
        self.refresh_resources()

    def _repair_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        if entry.payload_kind == "downloadable" and entry.download_url:
            self._download_selected()
            return
        QMessageBox.information(
            self,
            "Repair",
            "This resource requires manual import.\nUse 'Import from File...'.",
        )

    def _open_selected_folder(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        status = self._selected_status()
        if status is None or not status.install_paths:
            return
        folder = status.install_paths[0].parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _import_baseline_bundle(self) -> None:
        entry = self.registry.get_entry("hewiki_baseline_processed_bundle")
        if entry is None:
            QMessageBox.warning(self, "Baseline", "Baseline resource is not present in manifest.")
            return

        status = self.registry.get_status(entry.id)
        bundle_path = status.install_paths[0] if status.install_paths else None
        if bundle_path is None or not bundle_path.exists():
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Baseline Bundle",
                "",
                "HDLE Project Bundle (*.hdleproj);;All Files (*)",
            )
            if not file_path:
                return
            bundle_path = Path(file_path)

        if bundle_path.suffix.lower() != ".hdleproj":
            QMessageBox.warning(self, "Baseline", "Expected .hdleproj bundle file.")
            return

        worker = ProjectImportWorker(
            bundle_path=bundle_path,
            options=ImportOptions(rename_if_conflict=True),
        )
        self._import_worker = worker
        worker.progress.connect(self._on_baseline_import_progress)
        worker.finished.connect(self._on_baseline_import_finished)
        worker.error.connect(self._on_baseline_import_error)
        worker.start()
        self._set_status("Baseline import started...")

    def _on_baseline_import_progress(self, stage: str, current: int, total: int) -> None:
        self._set_status(f"{stage} ({current}/{total})")

    def _on_baseline_import_finished(self, report) -> None:
        self._import_worker = None
        project_id = int(getattr(report, "new_project_id", 0) or 0)
        if project_id > 0:
            self.settings.set_value("resources/baseline_project_id", project_id)
            self.settings.sync()
        self._set_status(f"Baseline import completed. New project ID: {project_id or 'unknown'}")
        self.refresh_resources()

    def _on_baseline_import_error(self, message: str) -> None:
        self._import_worker = None
        QMessageBox.warning(self, "Baseline Import Failed", str(message))
        self._set_status(f"Baseline import failed: {message}")

    def _run_health_check(self) -> None:
        if self._health_worker is not None:
            return
        worker = UnifiedHealthCheckWorker()
        self._health_worker = worker
        self.health_btn.setEnabled(False)
        self._set_status("Running health checks...")
        worker.finished.connect(self._on_health_finished)
        worker.error.connect(self._on_health_error)
        worker.finished.connect(lambda *_: self._clear_health_worker())
        worker.error.connect(lambda *_: self._clear_health_worker())
        worker.start()

    def _clear_health_worker(self) -> None:
        self._health_worker = None
        self.health_btn.setEnabled(True)

    def _on_health_finished(self, report: dict) -> None:
        overall = str(report.get("overall") or "unknown")
        self._append_log(f"Health overall: {overall}")
        for row in report.get("items", []):
            title = str(row.get("title") or row.get("check_id") or "")
            status = str(row.get("status") or "unknown")
            message = str(row.get("message") or "")
            remediation = str(row.get("remediation") or "")
            line = f"[{status.upper()}] {title}: {message}"
            if remediation:
                line += f" | remediation: {remediation}"
            self._append_log(line)
        self._set_status(f"Health check finished: {overall}")

    def _on_health_error(self, message: str) -> None:
        self._set_status(f"Health check failed: {message}")
        QMessageBox.warning(self, "Health Check", str(message))


def show_resources_manager(parent=None) -> int:
    dialog = ResourcesManagerDialog(parent=parent)
    return int(dialog.exec())


