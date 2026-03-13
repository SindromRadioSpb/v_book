"""First-run setup wizard for resources and provider onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.infra.db_path_resolver import (
    SETTINGS_KEY_ACTIVE_DB_PATH,
    clear_deferred_db_startup_guard,
    discover_baseline_db_path,
    get_default_db_path,
    inspect_db_path,
)
from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService
from app.services.db_service import DBService
from app.services.resources import ResourceRegistry
from app.ui.workers import UnifiedHealthCheckWorker


class FirstRunWizardDialog(QDialog):
    """Guided setup for local resources, baseline pack, and cloud credentials."""

    def __init__(
        self,
        parent=None,
        *,
        open_resources_manager: Optional[Callable[[], None]] = None,
        open_mt_settings: Optional[Callable[[], None]] = None,
        open_audio_settings: Optional[Callable[[], None]] = None,
        restart_with_db_path: Optional[Callable[[Path], bool]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("HDLE Premium Setup Wizard")
        self.setMinimumSize(760, 520)
        self.settings = SettingsService.get_instance()
        self.registry = ResourceRegistry(settings=self.settings)
        self.open_resources_manager = open_resources_manager
        self.open_mt_settings = open_mt_settings
        self.open_audio_settings = open_audio_settings
        self.restart_with_db_path = restart_with_db_path
        self._restart_candidate_path: Optional[Path] = None
        self._health_worker: Optional[UnifiedHealthCheckWorker] = None
        self._health_request_seq = 0
        self._active_health_request_id = 0
        self._health_refresh_pending = False

        self._pages = QStackedWidget()
        self._page_count = 0
        self._init_ui()
        self._update_page()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("<h2>Welcome to HDLE Premium</h2>")
        root.addWidget(title)

        subtitle = QLabel(
            "Complete the first-run setup to enable offline niqqud workflows, optional baseline data, "
            "and cloud providers."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self._build_pages()
        root.addWidget(self._pages, 1)

        btn_row = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self._go_back)
        btn_row.addWidget(self.back_btn)

        btn_row.addStretch()

        self.skip_btn = QPushButton("Skip for now")
        self.skip_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.skip_btn)

        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._go_next)
        btn_row.addWidget(self.next_btn)

        self.finish_btn = QPushButton("Finish")
        self.finish_btn.clicked.connect(self._finish)
        btn_row.addWidget(self.finish_btn)
        root.addLayout(btn_row)

    def _build_pages(self) -> None:
        # Page 1: Data folder
        page1 = QWidget()
        l1 = QVBoxLayout(page1)
        l1.addWidget(QLabel("<b>Step 1/6 - Data folder</b>"))
        l1.addWidget(QLabel("Choose where HDLE stores models, datasets, logs, and temporary files."))
        row = QHBoxLayout()
        self.data_root_edit = QLineEdit(self.settings.get_string(ResourcePaths.SETTINGS_KEY_DATA_ROOT, ""))
        row.addWidget(self.data_root_edit, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_data_root)
        row.addWidget(browse)
        l1.addLayout(row)
        l1.addStretch()
        self._pages.addWidget(page1)

        # Page 2: Database profile
        page2 = QWidget()
        l2 = QVBoxLayout(page2)
        l2.addWidget(QLabel("<b>Step 2/6 - Working database</b>"))
        l2.addWidget(
            QLabel(
                "Select the active database profile. Default starts with a clean AppData DB. "
                "You can switch later from Tools -> Switch Database."
            )
        )

        self.db_default_radio = QRadioButton("Use default empty DB (recommended)")
        self.db_default_radio.setChecked(True)
        l2.addWidget(self.db_default_radio)
        self.db_default_path_label = QLabel("")
        self.db_default_path_label.setWordWrap(True)
        l2.addWidget(self.db_default_path_label)

        self.db_browse_radio = QRadioButton("Select existing DB file")
        l2.addWidget(self.db_browse_radio)
        db_row = QHBoxLayout()
        self.db_path_edit = QLineEdit("")
        self.db_path_edit.setPlaceholderText("Choose existing .db file...")
        db_row.addWidget(self.db_path_edit, 1)
        browse_db_btn = QPushButton("Browse...")
        browse_db_btn.clicked.connect(self._browse_db_path)
        db_row.addWidget(browse_db_btn)
        self.db_browse_btn = browse_db_btn
        l2.addLayout(db_row)

        self.db_baseline_radio = QRadioButton("Use Hebrew Wikipedia Baseline (processed)")
        l2.addWidget(self.db_baseline_radio)
        self.db_baseline_path_label = QLabel("")
        self.db_baseline_path_label.setWordWrap(True)
        l2.addWidget(self.db_baseline_path_label)

        self.db_status_label = QLabel("")
        self.db_status_label.setWordWrap(True)
        l2.addWidget(self.db_status_label)
        l2.addStretch()
        self._pages.addWidget(page2)

        self.db_default_radio.toggled.connect(self._update_db_step_state)
        self.db_browse_radio.toggled.connect(self._update_db_step_state)
        self.db_baseline_radio.toggled.connect(self._update_db_step_state)
        self.db_path_edit.textChanged.connect(self._update_db_step_state)

        # Page 3: Local models
        page3 = QWidget()
        l3 = QVBoxLayout(page3)
        l3.addWidget(QLabel("<b>Step 3/6 - Local models</b>"))
        self.models_status_label = QLabel("")
        self.models_status_label.setWordWrap(True)
        l3.addWidget(self.models_status_label)
        open_resources_models = QPushButton("Open Resources Manager")
        open_resources_models.clicked.connect(self._open_resources_manager)
        l3.addWidget(open_resources_models)
        l3.addStretch()
        self._pages.addWidget(page3)

        # Page 4: Optional baseline resource bundle
        page4 = QWidget()
        l4 = QVBoxLayout(page4)
        l4.addWidget(QLabel("<b>Step 4/6 - Optional Hebrew Wikipedia Baseline Resource</b>"))
        self.baseline_status_label = QLabel("")
        self.baseline_status_label.setWordWrap(True)
        l4.addWidget(self.baseline_status_label)
        open_resources_baseline = QPushButton("Open Resources Manager")
        open_resources_baseline.clicked.connect(self._open_resources_manager)
        l4.addWidget(open_resources_baseline)
        l4.addStretch()
        self._pages.addWidget(page4)

        # Page 5: Cloud providers
        page5 = QWidget()
        l5 = QVBoxLayout(page5)
        l5.addWidget(QLabel("<b>Step 5/6 - Cloud providers</b>"))
        l5.addWidget(
            QLabel(
                "Cloud providers are optional. Configure credentials when needed.\n"
                "Translation and audio provider settings are opened in dedicated dialogs."
            )
        )
        row4 = QHBoxLayout()
        mt_btn = QPushButton("Open MT Provider Settings")
        mt_btn.clicked.connect(self._open_mt_settings)
        row4.addWidget(mt_btn)
        audio_btn = QPushButton("Open Audio Provider Settings")
        audio_btn.clicked.connect(self._open_audio_settings)
        row4.addWidget(audio_btn)
        row4.addStretch()
        l5.addLayout(row4)
        l5.addStretch()
        self._pages.addWidget(page5)

        # Page 6: Health summary
        page6 = QWidget()
        l6 = QVBoxLayout(page6)
        l6.addWidget(QLabel("<b>Step 6/6 - Health Check</b>"))
        self.health_status_label = QLabel("Health summary will load in background after the wizard opens.")
        self.health_status_label.setWordWrap(True)
        l6.addWidget(self.health_status_label)
        self.refresh_health_btn = QPushButton("Run Health Check")
        self.refresh_health_btn.clicked.connect(self._refresh_health_summary)
        l6.addWidget(self.refresh_health_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.health_text = QTextEdit()
        self.health_text.setReadOnly(True)
        self.health_text.setPlainText("Checking health summary in background...")
        l6.addWidget(self.health_text, 1)
        self._pages.addWidget(page6)

        self._page_count = self._pages.count()
        self._refresh_db_step_paths()
        self._update_db_step_state()
        self._refresh_resource_status()
        self._set_health_summary_loading(
            "Health summary will load in background after the wizard opens."
        )
        QTimer.singleShot(0, self._refresh_health_summary)

    def _browse_data_root(self) -> None:
        start = self.data_root_edit.text().strip() or str(ResourcePaths.resolve_data_root(create=True))
        selected = QFileDialog.getExistingDirectory(self, "Select data folder", start)
        if selected:
            self.data_root_edit.setText(selected)

    def _go_back(self) -> None:
        current = self._pages.currentIndex()
        if current > 0:
            self._pages.setCurrentIndex(current - 1)
            self._update_page()

    def _go_next(self) -> None:
        current = self._pages.currentIndex()
        if current < self._page_count - 1:
            if current == 0:
                self._apply_data_root()
                self._refresh_db_step_paths()
            elif current == 1:
                if not self._apply_database_selection():
                    return
            self._pages.setCurrentIndex(current + 1)
            self._update_page()
            if self._pages.currentIndex() in (2, 3):
                self._refresh_resource_status()
            if self._pages.currentIndex() == self._page_count - 1:
                self._refresh_health_summary()

    def _update_page(self) -> None:
        current = self._pages.currentIndex()
        self.back_btn.setEnabled(current > 0)
        self.next_btn.setVisible(current < self._page_count - 1)
        self.finish_btn.setVisible(current == self._page_count - 1)

    def _apply_data_root(self) -> None:
        value = (self.data_root_edit.text() or "").strip()
        self.settings.set_value(ResourcePaths.SETTINGS_KEY_DATA_ROOT, value)
        self.settings.sync()
        ResourcePaths.build(settings=self.settings, create=True)

    def _browse_db_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Existing Database",
            str(get_default_db_path(settings=self.settings).parent),
            "SQLite Database (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if path:
            self.db_path_edit.setText(path)
            self.db_browse_radio.setChecked(True)

    def _refresh_db_step_paths(self) -> None:
        default_db = get_default_db_path(settings=self.settings)
        self.db_default_path_label.setText(str(default_db))
        baseline_db = discover_baseline_db_path()
        if baseline_db is None:
            self.db_baseline_radio.setEnabled(False)
            self.db_baseline_path_label.setText(
                "Baseline DB is not available locally. Use Resources Manager or installer baseline component."
            )
        else:
            self.db_baseline_radio.setEnabled(True)
            self.db_baseline_path_label.setText(str(baseline_db))

        saved_db = self.settings.get_string(SETTINGS_KEY_ACTIVE_DB_PATH, "")
        if saved_db:
            self.db_browse_radio.setChecked(True)
            self.db_path_edit.setText(saved_db)

    def _selected_db_path(self) -> Path:
        if self.db_browse_radio.isChecked():
            return Path((self.db_path_edit.text() or "").strip()).expanduser().resolve()
        if self.db_baseline_radio.isChecked():
            baseline = discover_baseline_db_path()
            if baseline is not None:
                return baseline.resolve()
        return get_default_db_path(settings=self.settings).resolve()

    def _update_db_step_state(self) -> None:
        browse_enabled = self.db_browse_radio.isChecked()
        self.db_path_edit.setEnabled(browse_enabled)
        self.db_browse_btn.setEnabled(browse_enabled)

        selected = self._selected_db_path()
        info = inspect_db_path(selected)
        if selected == get_default_db_path(settings=self.settings):
            if info.exists:
                self.db_status_label.setText("Default DB exists and will be reused.")
            else:
                self.db_status_label.setText("Default DB will be created on next startup.")
            return

        if not info.exists:
            self.db_status_label.setText("Selected DB file is missing.")
            return
        if info.error:
            self.db_status_label.setText(f"Selected DB is not readable: {info.error}")
            return

        schema = info.schema_version if info.schema_version is not None else "unknown"
        self.db_status_label.setText(f"Selected DB ready (schema: {schema}).")

    def _apply_database_selection(self) -> bool:
        selected = self._selected_db_path()
        default_db = get_default_db_path(settings=self.settings).resolve()
        info = inspect_db_path(selected)

        if selected != default_db:
            if not info.exists:
                QMessageBox.warning(self, "Database Selection", "Selected database file does not exist.")
                return False
            if info.error:
                QMessageBox.warning(self, "Database Selection", f"Cannot read selected DB.\n\n{info.error}")
                return False
            if info.schema_version is not None and info.supported_schema_version > 0:
                if info.schema_version > info.supported_schema_version:
                    QMessageBox.warning(
                        self,
                        "Database Selection",
                        "Selected database schema is newer than this app supports.",
                    )
                    return False

        if selected == default_db:
            self.settings.remove(SETTINGS_KEY_ACTIVE_DB_PATH)
        else:
            self.settings.set_value(SETTINGS_KEY_ACTIVE_DB_PATH, str(selected))
        clear_deferred_db_startup_guard(settings=self.settings)
        self.settings.sync()

        try:
            current_db = Path(DBService.get_instance().db_manager.db_path).resolve()
        except Exception:
            current_db = None
        self._restart_candidate_path = selected if (current_db is None or selected != current_db) else None
        return True

    def _refresh_resource_status(self) -> None:
        model_statuses = []
        for resource_id in ("nikud_pronunciation_model", "sentence_niqqud_model"):
            status = self.registry.get_status(resource_id)
            model_statuses.append(f"{resource_id}: {status.state} ({status.message})")
        self.models_status_label.setText("\n".join(model_statuses))

        baseline = self.registry.get_status("hewiki_baseline_processed_bundle")
        self.baseline_status_label.setText(
            f"hewiki_baseline_processed_bundle: {baseline.state} ({baseline.message})"
        )

    def _refresh_health_summary(self) -> None:
        worker = self._health_worker
        if worker is not None and worker.isRunning():
            self._health_refresh_pending = True
            self._set_health_summary_loading(
                "Health check already running; refresh queued...",
                preserve_text=True,
            )
            return

        self._health_request_seq += 1
        request_id = int(self._health_request_seq)
        self._active_health_request_id = request_id
        self._health_refresh_pending = False
        self._set_health_summary_loading("Checking health summary in background...", preserve_text=True)

        worker = UnifiedHealthCheckWorker()
        app = QApplication.instance()
        if app is not None:
            worker.setParent(app)
        self._health_worker = worker
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        worker.finished.connect(lambda report, seq=request_id: self._on_health_summary_loaded(report, seq))
        worker.error.connect(lambda message, seq=request_id: self._on_health_summary_error(message, seq))
        worker.finished.connect(
            lambda _report, current=worker, seq=request_id: self._on_health_worker_finished(current, seq)
        )
        worker.error.connect(
            lambda _message, current=worker, seq=request_id: self._on_health_worker_finished(current, seq)
        )
        worker.start()

    def _set_health_summary_loading(self, status_text: str, *, preserve_text: bool = False) -> None:
        self.health_status_label.setText(status_text)
        self.refresh_health_btn.setEnabled(False)
        if preserve_text and self.health_text.toPlainText().strip():
            return
        self.health_text.setPlainText("Checking health summary in background...")

    def _render_health_summary(self, report: dict) -> None:
        lines = [f"Overall: {report.get('overall', 'unknown')}"]
        for row in report.get("items", []):
            title = row.get("title", row.get("check_id", "check"))
            status = row.get("status", "unknown")
            message = row.get("message", "")
            lines.append(f"[{status}] {title}: {message}")
            remediation = row.get("remediation", "")
            if remediation:
                lines.append(f"  remediation: {remediation}")
        self.health_text.setPlainText("\n".join(lines))
        self.health_status_label.setText(f"Health summary ready ({report.get('overall', 'unknown')}).")
        self.refresh_health_btn.setEnabled(True)

    def _on_health_summary_loaded(self, report: dict, request_id: int) -> None:
        if int(request_id) != self._active_health_request_id:
            return
        self._render_health_summary(report)

    def _on_health_summary_error(self, message: str, request_id: int) -> None:
        if int(request_id) != self._active_health_request_id:
            return
        self.health_status_label.setText(f"Health check failed: {message}")
        self.health_text.setPlainText(f"Health check failed.\n\n{message}")
        self.refresh_health_btn.setEnabled(True)

    def _on_health_worker_finished(self, worker: UnifiedHealthCheckWorker, request_id: int) -> None:
        if self._health_worker is worker:
            self._health_worker = None
        if int(request_id) != self._active_health_request_id:
            return
        self.refresh_health_btn.setEnabled(True)
        if self._health_refresh_pending:
            self._health_refresh_pending = False
            QTimer.singleShot(0, self._refresh_health_summary)

    def _open_resources_manager(self) -> None:
        if callable(self.open_resources_manager):
            self.open_resources_manager()
        self._refresh_resource_status()
        self._refresh_health_summary()

    def _open_mt_settings(self) -> None:
        if callable(self.open_mt_settings):
            self.open_mt_settings()
        self._refresh_health_summary()

    def _open_audio_settings(self) -> None:
        if callable(self.open_audio_settings):
            self.open_audio_settings()
        self._refresh_health_summary()

    def _finish(self) -> None:
        self._apply_data_root()
        if not self._apply_database_selection():
            return
        self.settings.set_value("setup/first_run_completed", True)
        self.settings.sync()

        if self._restart_candidate_path is not None and callable(self.restart_with_db_path):
            answer = QMessageBox.question(
                self,
                "Restart Required",
                "Database profile was changed. Restart now to apply it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                if not self.restart_with_db_path(self._restart_candidate_path):
                    QMessageBox.warning(
                        self,
                        "Restart Failed",
                        "Failed to restart application. New DB path is saved for next launch.",
                    )
        self.accept()


def show_first_run_wizard(
    parent=None,
    *,
    open_resources_manager: Optional[Callable[[], None]] = None,
    open_mt_settings: Optional[Callable[[], None]] = None,
    open_audio_settings: Optional[Callable[[], None]] = None,
    restart_with_db_path: Optional[Callable[[Path], bool]] = None,
) -> int:
    dialog = FirstRunWizardDialog(
        parent=parent,
        open_resources_manager=open_resources_manager,
        open_mt_settings=open_mt_settings,
        open_audio_settings=open_audio_settings,
        restart_with_db_path=restart_with_db_path,
    )
    return int(dialog.exec())
