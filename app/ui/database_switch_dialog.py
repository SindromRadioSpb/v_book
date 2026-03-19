"""Dialog for switching active working database with restart flow."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from app.infra.db_path_resolver import (
    SETTINGS_KEY_ACTIVE_DB_PATH,
    SETTINGS_KEY_DEFERRED_DB_PATH,
    SETTINGS_KEY_DEFERRED_DB_REASON,
    STARTUP_DEFER_SIZE_THRESHOLD_BYTES,
    classify_db_profile,
    clear_deferred_db_startup_guard,
    discover_baseline_db_path,
    get_default_db_path,
    inspect_db_path,
)
from app.infra.settings import SettingsService

logger = logging.getLogger(__name__)


class _DBBackupWorker(QThread):
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source_path: Path, target_path: Path):
        super().__init__()
        self.source_path = Path(source_path).resolve()
        self.target_path = Path(target_path).resolve()

    def run(self) -> None:
        src_conn = None
        dst_conn = None
        try:
            self.target_path.parent.mkdir(parents=True, exist_ok=True)
            src_conn = sqlite3.connect(str(self.source_path))
            dst_conn = sqlite3.connect(str(self.target_path))
            with dst_conn:
                src_conn.backup(dst_conn)
            self.finished.emit(str(self.target_path))
        except Exception as exc:
            try:
                if self.target_path.exists():
                    self.target_path.unlink()
            except Exception:
                pass
            self.failed.emit(str(exc))
        finally:
            if src_conn is not None:
                src_conn.close()
            if dst_conn is not None:
                dst_conn.close()


class DatabaseSwitchDialog(QDialog):
    """Select active DB profile and restart app safely."""

    def __init__(
        self,
        *,
        current_db_path: Path,
        parent=None,
        settings: SettingsService | None = None,
        restart_callback: Callable[[Path], bool] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Switch Database")
        self.setMinimumSize(760, 520)
        self.settings = settings or SettingsService.get_instance()
        self.current_db_path = Path(current_db_path).resolve()
        self.default_db_path = get_default_db_path(settings=self.settings)
        self.baseline_db_path = discover_baseline_db_path()
        self.restart_callback = restart_callback

        self._backup_worker: _DBBackupWorker | None = None
        self._backup_progress: QProgressDialog | None = None

        self._init_ui()
        self._load_current_metadata()
        self._update_selected_state()

    @staticmethod
    def build_restart_command(db_path: Path) -> list[str]:
        target = str(Path(db_path).resolve())
        if getattr(sys, "frozen", False):
            return [str(Path(sys.executable).resolve()), "--db-path", target]
        return [str(Path(sys.executable).resolve()), "-m", "app.main", "--db-path", target]

    @classmethod
    def restart_application(cls, db_path: Path) -> bool:
        command = cls.build_restart_command(db_path)
        try:
            subprocess.Popen(command)
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return True
        except Exception:
            logger.exception("Failed to restart application with database: %s", db_path)
            return False

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<h2>Database Profile Selection</h2>"))

        intro = QLabel(
            "Choose the working database profile. The selected database is applied after restart."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        current_group = QGroupBox("Current Database (read-only)")
        current_form = QFormLayout(current_group)
        self.current_path_edit = QLineEdit(str(self.current_db_path))
        self.current_path_edit.setReadOnly(True)
        current_form.addRow("Path:", self.current_path_edit)
        self.current_profile_label = QLabel("-")
        current_form.addRow("Profile:", self.current_profile_label)
        self.current_size_label = QLabel("-")
        current_form.addRow("Size:", self.current_size_label)
        self.current_schema_label = QLabel("-")
        current_form.addRow("Schema version:", self.current_schema_label)
        root.addWidget(current_group)

        select_group = QGroupBox("Switch To")
        select_layout = QVBoxLayout(select_group)

        self.default_radio = QRadioButton("Default DB (AppData)")
        self.default_radio.setChecked(True)
        select_layout.addWidget(self.default_radio)
        self.default_path_label = QLabel(str(self.default_db_path))
        self.default_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.default_path_label.setWordWrap(True)
        select_layout.addWidget(self.default_path_label)

        self.browse_radio = QRadioButton("Select existing DB file")
        select_layout.addWidget(self.browse_radio)
        browse_row = QHBoxLayout()
        self.browse_edit = QLineEdit()
        self.browse_edit.setPlaceholderText("Choose .db file...")
        browse_row.addWidget(self.browse_edit, 1)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_db_file)
        browse_row.addWidget(self.browse_btn)
        select_layout.addLayout(browse_row)

        baseline_text = "Hebrew Wikipedia Baseline (processed)"
        if self.baseline_db_path is None:
            baseline_text += " - not available on this machine"
        self.baseline_radio = QRadioButton(baseline_text)
        self.baseline_radio.setEnabled(self.baseline_db_path is not None)
        select_layout.addWidget(self.baseline_radio)
        self.baseline_path_label = QLabel(
            str(self.baseline_db_path) if self.baseline_db_path is not None else "-"
        )
        self.baseline_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.baseline_path_label.setWordWrap(True)
        select_layout.addWidget(self.baseline_path_label)

        root.addWidget(select_group, 1)

        self.selection_info_label = QLabel("")
        self.selection_info_label.setWordWrap(True)
        root.addWidget(self.selection_info_label)

        self.reconnect_guidance_label = QLabel("")
        self.reconnect_guidance_label.setWordWrap(True)
        self.reconnect_guidance_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.reconnect_guidance_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open DB Folder")
        self.open_folder_btn.clicked.connect(self._open_selected_folder)
        buttons.addWidget(self.open_folder_btn)

        self.copy_path_btn = QPushButton("Copy Path")
        self.copy_path_btn.clicked.connect(self._copy_selected_path)
        buttons.addWidget(self.copy_path_btn)

        self.backup_btn = QPushButton("Make Backup...")
        self.backup_btn.clicked.connect(self._create_backup)
        buttons.addWidget(self.backup_btn)

        buttons.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)

        self.switch_btn = QPushButton("Switch && Restart")
        self.switch_btn.setDefault(True)
        self.switch_btn.clicked.connect(self._on_switch_and_restart)
        buttons.addWidget(self.switch_btn)
        root.addLayout(buttons)

        self.default_radio.toggled.connect(self._update_selected_state)
        self.browse_radio.toggled.connect(self._update_selected_state)
        self.baseline_radio.toggled.connect(self._update_selected_state)
        self.browse_edit.textChanged.connect(self._update_selected_state)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(str(text or "").strip())

    def _browse_db_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Database",
            str(self.current_db_path.parent),
            "SQLite Database (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if path:
            self.browse_edit.setText(path)
            self.browse_radio.setChecked(True)

    def _selected_path(self) -> Path:
        if self.browse_radio.isChecked():
            return Path((self.browse_edit.text() or "").strip()).expanduser().resolve()
        if self.baseline_radio.isChecked() and self.baseline_db_path is not None:
            return self.baseline_db_path.resolve()
        return self.default_db_path.resolve()

    def _load_current_metadata(self) -> None:
        info = inspect_db_path(self.current_db_path)
        self.current_profile_label.setText(
            f"{classify_db_profile(self.current_db_path, settings=self.settings)}"
        )
        if info.exists:
            size_mb = info.size_bytes / (1024 * 1024)
            self.current_size_label.setText(f"{size_mb:.1f} MB")
        else:
            self.current_size_label.setText("Not created yet")
        schema_text = str(info.schema_version) if info.schema_version is not None else "unknown"
        self.current_schema_label.setText(schema_text)

    def _update_selected_state(self) -> None:
        browse_enabled = self.browse_radio.isChecked()
        self.browse_edit.setEnabled(browse_enabled)
        self.browse_btn.setEnabled(browse_enabled)

        selected = self._selected_path()
        info = inspect_db_path(selected)
        profile = classify_db_profile(selected, settings=self.settings)
        lines = [f"Selected profile: {profile}", f"Selected path: {selected}"]
        if info.exists:
            lines.append(f"Size: {info.size_bytes / (1024 * 1024):.1f} MB")
            if info.schema_version is not None:
                lines.append(
                    f"Schema: {info.schema_version} (app supports up to {info.supported_schema_version})"
                )
            else:
                lines.append("Schema: unknown")
        else:
            if selected == self.default_db_path:
                lines.append("Default DB file will be created on next startup if missing.")
            else:
                lines.append("File does not exist.")
        self.selection_info_label.setText("\n".join(lines))
        self.reconnect_guidance_label.setText(
            self._build_reconnect_guidance(selected=selected, info=info, profile=profile)
        )

        self.backup_btn.setEnabled(info.exists and not info.error)

    def _build_reconnect_guidance(self, *, selected: Path, info, profile: str) -> str:
        guidance: list[str] = []
        deferred_path = str(
            self.settings.get_string(SETTINGS_KEY_DEFERRED_DB_PATH, "") or ""
        ).strip()
        deferred_reason = str(
            self.settings.get_string(SETTINGS_KEY_DEFERRED_DB_REASON, "") or ""
        ).strip()
        selected_resolved = selected.resolve()
        if deferred_path:
            try:
                deferred_resolved = Path(deferred_path).expanduser().resolve()
            except Exception:
                deferred_resolved = None
            if deferred_resolved is not None and deferred_resolved == selected_resolved:
                guidance.append(
                    "This DB was previously deferred at startup. Switching now is the explicit reconnect path."
                )
                if deferred_reason:
                    guidance.append(f"Deferred reason: {deferred_reason}")

        if selected_resolved == self.default_db_path.resolve():
            guidance.append(
                "Recommended for the fastest local startup and the safest default operator workflow."
            )
            guidance.append(
                "Use this when you want to keep working immediately and reconnect a heavier DB later from Tools -> Switch Database."
            )
        else:
            guidance.append("Switching databases always requires a restart.")
            guidance.append(
                "Recommended reconnect order: confirm the target DB, switch once, then let the restart complete before making another DB change."
            )
            if (
                info.exists
                and info.schema_version is not None
                and info.supported_schema_version > 0
            ):
                if info.schema_version < info.supported_schema_version:
                    guidance.append(
                        "This DB is older than the current app schema. Expect one longer restart while backup and migration complete."
                    )
                elif info.schema_version == info.supported_schema_version:
                    guidance.append(
                        "Schema is current. If this is the DB you expect to use next, this is the lowest-risk reconnect case."
                    )
            if info.exists and info.size_bytes >= STARTUP_DEFER_SIZE_THRESHOLD_BYTES:
                guidance.append(
                    "This is a heavy DB. Prefer creating a backup before switching if you have not already validated it, and avoid repeated switch/restart loops."
                )
            if profile == "Baseline (dev)":
                guidance.append(
                    "Baseline quick-pick is intended for explicit reconnect after the UI is visible. Use it when you want the large reference workspace next, not as the default local-first profile."
                )
        return "\n".join(guidance)

    def _copy_selected_path(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        app.clipboard().setText(str(self._selected_path()))
        self._set_status("Database path copied to clipboard.")

    def _open_selected_folder(self) -> None:
        selected = self._selected_path()
        folder = selected.parent if selected.parent.exists() else self.current_db_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _create_backup(self) -> None:
        selected = self._selected_path()
        info = inspect_db_path(selected)
        if not info.exists or info.error:
            QMessageBox.warning(
                self, "Backup", "Backup is available only for existing readable DB files."
            )
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suggestion = selected.with_name(f"{selected.stem}.backup_{ts}{selected.suffix}")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Backup As",
            str(suggestion),
            "SQLite Database (*.db *.sqlite *.sqlite3);;All Files (*)",
        )
        if not target:
            return
        target_path = Path(target).expanduser().resolve()

        self._backup_progress = QProgressDialog("Creating backup...", "Cancel", 0, 0, self)
        self._backup_progress.setWindowTitle("Database Backup")
        self._backup_progress.setAutoClose(False)
        self._backup_progress.setAutoReset(False)
        self._backup_progress.show()

        worker = _DBBackupWorker(selected, target_path)
        self._backup_worker = worker
        worker.finished.connect(self._on_backup_finished)
        worker.failed.connect(self._on_backup_failed)
        worker.finished.connect(lambda *_: self._clear_backup_worker())
        worker.failed.connect(lambda *_: self._clear_backup_worker())
        worker.start()

    def _clear_backup_worker(self) -> None:
        self._backup_worker = None
        if self._backup_progress is not None:
            self._backup_progress.close()
            self._backup_progress = None

    def _on_backup_finished(self, backup_path: str) -> None:
        self._set_status(f"Backup created: {backup_path}")

    def _on_backup_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Backup Failed", str(message))
        self._set_status("Backup failed.")

    def _validate_selected(self) -> tuple[bool, str, str | None]:
        selected = self._selected_path()
        info = inspect_db_path(selected)

        if selected != self.default_db_path and not info.exists:
            return False, "Selected database file does not exist.", None
        if info.exists and info.error:
            return False, f"Cannot read selected database.\n\n{info.error}", None
        if info.schema_version is not None and info.supported_schema_version > 0:
            if info.schema_version > info.supported_schema_version:
                return (
                    False,
                    "Selected database uses a newer schema that this app version cannot open safely.",
                    None,
                )
            if info.schema_version < info.supported_schema_version:
                warning = (
                    f"Selected database schema is older ({info.schema_version}) than app schema "
                    f"({info.supported_schema_version}). Migrations may run on next startup.\n\n"
                    "For large databases this can take longer because backup and migration happen before the next full UI session opens."
                )
                return True, "", warning
        return True, "", None

    def _on_switch_and_restart(self) -> None:
        selected = self._selected_path()
        valid, error_msg, warning_msg = self._validate_selected()
        if not valid:
            QMessageBox.warning(self, "Switch Database", error_msg)
            return
        if warning_msg:
            answer = QMessageBox.question(
                self,
                "Schema Migration Warning",
                warning_msg + "\n\nProceed with switch?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.settings.set_value(SETTINGS_KEY_ACTIVE_DB_PATH, str(selected))
        clear_deferred_db_startup_guard(settings=self.settings)
        self.settings.sync()

        restarted = False
        if callable(self.restart_callback):
            restarted = bool(self.restart_callback(selected))
        else:
            restarted = self.restart_application(selected)

        if not restarted:
            QMessageBox.warning(
                self,
                "Switch Database",
                "Failed to restart application. The new DB path is saved and will be used on next launch.",
            )
            return
        self.accept()


def show_database_switch_dialog(
    *,
    current_db_path: Path,
    parent=None,
    restart_callback: Callable[[Path], bool] | None = None,
) -> int:
    dialog = DatabaseSwitchDialog(
        current_db_path=current_db_path,
        parent=parent,
        restart_callback=restart_callback,
    )
    return int(dialog.exec())
