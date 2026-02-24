"""First-run setup wizard for resources and provider onboarding."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.infra.resource_paths import ResourcePaths
from app.infra.settings import SettingsService
from app.services.health_check_service import HealthCheckService
from app.services.resources import ResourceRegistry


class FirstRunWizardDialog(QDialog):
    """Guided setup for local resources, baseline pack, and cloud credentials."""

    def __init__(
        self,
        parent=None,
        *,
        open_resources_manager: Optional[Callable[[], None]] = None,
        open_mt_settings: Optional[Callable[[], None]] = None,
        open_audio_settings: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("HDLE Premium Setup Wizard")
        self.setMinimumSize(760, 520)
        self.settings = SettingsService.get_instance()
        self.registry = ResourceRegistry(settings=self.settings)
        self.health_service = HealthCheckService(settings=self.settings)
        self.open_resources_manager = open_resources_manager
        self.open_mt_settings = open_mt_settings
        self.open_audio_settings = open_audio_settings

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
        l1.addWidget(QLabel("<b>Step 1/5 - Data folder</b>"))
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

        # Page 2: Local models
        page2 = QWidget()
        l2 = QVBoxLayout(page2)
        l2.addWidget(QLabel("<b>Step 2/5 - Local models</b>"))
        self.models_status_label = QLabel("")
        self.models_status_label.setWordWrap(True)
        l2.addWidget(self.models_status_label)
        open_resources_models = QPushButton("Open Resources Manager")
        open_resources_models.clicked.connect(self._open_resources_manager)
        l2.addWidget(open_resources_models)
        l2.addStretch()
        self._pages.addWidget(page2)

        # Page 3: Optional baseline
        page3 = QWidget()
        l3 = QVBoxLayout(page3)
        l3.addWidget(QLabel("<b>Step 3/5 - Optional Hebrew Wikipedia Baseline</b>"))
        self.baseline_status_label = QLabel("")
        self.baseline_status_label.setWordWrap(True)
        l3.addWidget(self.baseline_status_label)
        open_resources_baseline = QPushButton("Open Resources Manager")
        open_resources_baseline.clicked.connect(self._open_resources_manager)
        l3.addWidget(open_resources_baseline)
        l3.addStretch()
        self._pages.addWidget(page3)

        # Page 4: Cloud providers
        page4 = QWidget()
        l4 = QVBoxLayout(page4)
        l4.addWidget(QLabel("<b>Step 4/5 - Cloud providers</b>"))
        l4.addWidget(
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
        l4.addLayout(row4)
        l4.addStretch()
        self._pages.addWidget(page4)

        # Page 5: Health summary
        page5 = QWidget()
        l5 = QVBoxLayout(page5)
        l5.addWidget(QLabel("<b>Step 5/5 - Health Check</b>"))
        refresh_health_btn = QPushButton("Run Health Check")
        refresh_health_btn.clicked.connect(self._refresh_health_summary)
        l5.addWidget(refresh_health_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.health_text = QTextEdit()
        self.health_text.setReadOnly(True)
        l5.addWidget(self.health_text, 1)
        self._pages.addWidget(page5)

        self._page_count = self._pages.count()
        self._refresh_resource_status()
        self._refresh_health_summary()

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
            self._pages.setCurrentIndex(current + 1)
            self._update_page()
            if self._pages.currentIndex() in (1, 2):
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
        report = self.health_service.run_all()
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
        self.settings.set_value("setup/first_run_completed", True)
        self.settings.sync()
        self.accept()


def show_first_run_wizard(
    parent=None,
    *,
    open_resources_manager: Optional[Callable[[], None]] = None,
    open_mt_settings: Optional[Callable[[], None]] = None,
    open_audio_settings: Optional[Callable[[], None]] = None,
) -> int:
    dialog = FirstRunWizardDialog(
        parent=parent,
        open_resources_manager=open_resources_manager,
        open_mt_settings=open_mt_settings,
        open_audio_settings=open_audio_settings,
    )
    return int(dialog.exec())

