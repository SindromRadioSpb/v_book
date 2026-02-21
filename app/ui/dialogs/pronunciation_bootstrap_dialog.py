"""Dialog for Phonikud model gate + worker-safe pronunciation bootstrap."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from app.infra.settings import SettingsService
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.workers import PhonikudHealthCheckWorker, PronunciationBootstrapWorker


class PronunciationBootstrapDialog(QDialog):
    """Premium UI gate for offline pronunciation bootstrap."""

    def __init__(self, parent=None, *, selected_items: Optional[List[Dict[str, str]]] = None):
        super().__init__(parent)
        self.setWindowTitle("Pronunciation Bootstrap (Phonikud)")
        self.setMinimumWidth(760)

        self.settings = SettingsService.get_instance()
        self.selected_items = self._normalize_selected_items(selected_items)
        self._health_worker = None
        self._bootstrap_worker = None
        self._should_refresh_parent = False
        self._init_ui()
        self._load_settings()

    @staticmethod
    def _normalize_selected_items(selected_items: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for raw in selected_items or []:
            src_norm = str(raw.get("src_norm") or "").strip()
            src_text = str(raw.get("src_text") or "").strip()
            src_lang = str(raw.get("src_lang") or "he").strip()
            source_group = str(raw.get("source_group") or "user_dictionary").strip().lower()
            if source_group not in {"lemmas", "terms", "user_dictionary"}:
                source_group = "user_dictionary"
            if not src_norm or not src_text:
                continue
            normalized.append(
                {
                    "src_norm": src_norm,
                    "src_text": src_text,
                    "src_lang": src_lang,
                    "source_group": source_group,
                }
            )
        return normalized

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel("<h2>Pronunciation Bootstrap</h2>")
        root.addWidget(title)
        info = QLabel(
            "Offline baseline for source pronunciation metadata. "
            "Manual overrides remain authoritative."
        )
        info.setWordWrap(True)
        root.addWidget(info)
        if self.selected_items:
            selected_total = len(self.selected_items)
            selected_text = QLabel(
                f"<b>Selection scope:</b> {selected_total:,} row(s) from current table."
            )
            selected_text.setWordWrap(True)
            root.addWidget(selected_text)

        model_group = QGroupBox("Phonikud Runtime Gate")
        model_form = QFormLayout(model_group)

        self.enabled_checkbox = QCheckBox("Enable Phonikud baseline generation")
        self.enabled_checkbox.setChecked(True)
        model_form.addRow("State:", self.enabled_checkbox)

        path_row = QHBoxLayout()
        self.model_path_edit = QLineEdit()
        self.model_path_edit.setPlaceholderText("Local model/checkpoint path (optional)")
        path_row.addWidget(self.model_path_edit, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_model_path)
        path_row.addWidget(browse_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self.model_path_edit.setText(""))
        path_row.addWidget(clear_btn)
        model_form.addRow("Model path:", path_row)

        health_row = QHBoxLayout()
        self.health_btn = QPushButton("Health Check")
        self.health_btn.clicked.connect(self._run_health_check)
        health_row.addWidget(self.health_btn)
        self.health_mode_label = QLabel("Mode: unknown")
        health_row.addWidget(self.health_mode_label)
        health_row.addStretch()
        model_form.addRow("Health:", health_row)

        self.health_details_label = QLabel("No health-check run yet.")
        self.health_details_label.setWordWrap(True)
        model_form.addRow("Details:", self.health_details_label)

        self.health_samples_label = QLabel("")
        self.health_samples_label.setWordWrap(True)
        model_form.addRow("Samples:", self.health_samples_label)
        root.addWidget(model_group)

        opts_group = QGroupBox("Bootstrap Options")
        opts_form = QFormLayout(opts_group)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Hebrew (he)", "he")
        self.lang_combo.addItem("Hebrew (he-IL)", "he-IL")
        opts_form.addRow("Language:", self.lang_combo)

        mode_row = QHBoxLayout()
        self.fill_only_radio = QRadioButton("Fill missing auto rows")
        self.fill_only_radio.setChecked(True)
        self.rebuild_radio = QRadioButton("Rebuild auto rows")
        mode_row.addWidget(self.fill_only_radio)
        mode_row.addWidget(self.rebuild_radio)
        mode_row.addStretch()
        opts_form.addRow("Mode:", mode_row)

        source_row = QHBoxLayout()
        self.include_lemmas_cb = QCheckBox("Lemmas")
        self.include_terms_cb = QCheckBox("Terms")
        self.include_ud_cb = QCheckBox("User Dictionaries")
        self.include_lemmas_cb.setChecked(True)
        self.include_terms_cb.setChecked(True)
        self.include_ud_cb.setChecked(True)
        if self.selected_items:
            selected_groups = {item.get("source_group") for item in self.selected_items}
            self.include_lemmas_cb.setChecked("lemmas" in selected_groups)
            self.include_terms_cb.setChecked("terms" in selected_groups)
            self.include_ud_cb.setChecked("user_dictionary" in selected_groups)
        source_row.addWidget(self.include_lemmas_cb)
        source_row.addWidget(self.include_terms_cb)
        source_row.addWidget(self.include_ud_cb)
        source_row.addStretch()
        opts_form.addRow("Sources:", source_row)

        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(1, 5000)
        self.chunk_size_spin.setValue(500)
        opts_form.addRow("Chunk size:", self.chunk_size_spin)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 2_000_000)
        self.limit_spin.setValue(0)
        self.limit_spin.setSpecialValueText("No limit")
        opts_form.addRow("Limit:", self.limit_spin)

        self.dry_run_cb = QCheckBox("Dry-run (rollback changes)")
        self.dry_run_cb.setChecked(False)
        opts_form.addRow("", self.dry_run_cb)

        root.addWidget(opts_group)

        buttons = QHBoxLayout()
        docs_btn = QPushButton("Open Docs")
        docs_btn.clicked.connect(self._open_docs)
        buttons.addWidget(docs_btn)
        buttons.addStretch()

        self.run_btn = QPushButton("Run Bootstrap")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._run_bootstrap)
        buttons.addWidget(self.run_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def _browse_model_path(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        current = self.model_path_edit.text().strip()
        start_dir = current or "J:/Models/phonikud"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Phonikud ONNX Model",
            start_dir,
            "ONNX Model (*.onnx);;All Files (*)",
        )
        if file_path:
            self.model_path_edit.setText(file_path)
            return

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Phonikud model folder",
            start_dir,
        )
        if directory:
            self.model_path_edit.setText(directory)

    def _load_settings(self) -> None:
        self.enabled_checkbox.setChecked(self.settings.get_bool("pronunciation/phonikud/enabled", True))
        self.model_path_edit.setText(self.settings.get_string("pronunciation/phonikud/model_path", ""))

        mode = (self.settings.get_string("pronunciation/phonikud/last_health_mode", "") or "").strip()
        status = (self.settings.get_string("pronunciation/phonikud/last_health_status", "") or "").strip()
        details = (self.settings.get_string("pronunciation/phonikud/last_health_details", "") or "").strip()
        if mode:
            self._render_health({"mode": mode, "status": status or "error", "details": details, "samples": []})

    def _save_settings(self) -> None:
        model_path = self._sanitize_model_path(self.model_path_edit.text())
        self.model_path_edit.setText(model_path)
        self.settings.set_value("pronunciation/phonikud/enabled", bool(self.enabled_checkbox.isChecked()))
        self.settings.set_value("pronunciation/phonikud/model_path", model_path)
        self.settings.sync()

    @staticmethod
    def _sanitize_model_path(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        return text.strip("\"'").rstrip(" .")

    def _open_docs(self) -> None:
        docs_path = Path(__file__).resolve().parents[3] / "docs" / "PRONUNCIATION_BOOTSTRAP.md"
        if not docs_path.exists():
            QMessageBox.information(self, "Docs", f"File not found:\n{docs_path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(docs_path))):
            QMessageBox.information(self, "Docs", f"Open manually:\n{docs_path}")

    def _run_health_check(self) -> None:
        if self._health_worker is not None:
            return
        self._save_settings()
        self.health_btn.setEnabled(False)
        self.health_mode_label.setText("Mode: checking...")
        self.health_details_label.setText("Running health-check...")
        self.health_samples_label.setText("")

        worker = PhonikudHealthCheckWorker(
            model_path=self.model_path_edit.text().strip(),
            enabled=self.enabled_checkbox.isChecked(),
        )
        self._health_worker = worker
        worker.finished.connect(self._on_health_finished)
        worker.error.connect(self._on_health_error)
        worker.finished.connect(lambda *_: self._clear_health_worker())
        worker.error.connect(lambda *_: self._clear_health_worker())
        worker.start()

    def _clear_health_worker(self) -> None:
        self._health_worker = None
        self.health_btn.setEnabled(True)

    def _on_health_finished(self, report: dict) -> None:
        self._render_health(report)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.settings.set_value("pronunciation/phonikud/last_health_status", str(report.get("status") or "error"))
        self.settings.set_value("pronunciation/phonikud/last_health_mode", str(report.get("mode") or "error"))
        self.settings.set_value("pronunciation/phonikud/last_health_details", str(report.get("details") or ""))
        self.settings.set_value("pronunciation/phonikud/last_health_checked_at", now)
        self.settings.set_json("pronunciation/phonikud/last_health_report", report)
        self.settings.sync()

    def _on_health_error(self, error_msg: str) -> None:
        self.health_mode_label.setText("Mode: error")
        self.health_mode_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.health_details_label.setText(f"Health-check failed: {error_msg}")
        self.health_samples_label.setText("")

    def _render_health(self, report: dict) -> None:
        mode = str(report.get("mode") or "error")
        status = str(report.get("status") or "error")
        details = str(report.get("details") or "")
        latency = int(report.get("latency_ms") or 0)
        samples = report.get("samples") or []

        if status == "ok":
            color = "#2e7d32"
        elif status == "fallback":
            color = "#f57c00"
        else:
            color = "#d32f2f"

        self.health_mode_label.setText(f"Mode: {mode} ({status})")
        self.health_mode_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.health_details_label.setText(f"{details} | latency={latency}ms")

        if samples:
            rendered = " | ".join(
                f"{str(item.get('input') or '')} -> {str(item.get('output') or '')}" for item in samples[:2]
            )
            self.health_samples_label.setText(rendered)
        else:
            self.health_samples_label.setText("")

    def _run_bootstrap(self) -> None:
        if self._bootstrap_worker is not None:
            return

        if not (
            self.include_lemmas_cb.isChecked()
            or self.include_terms_cb.isChecked()
            or self.include_ud_cb.isChecked()
        ):
            QMessageBox.warning(self, "Pronunciation Bootstrap", "Select at least one source group.")
            return

        self._save_settings()
        health_status = (self.settings.get_string("pronunciation/phonikud/last_health_status", "") or "").strip()
        if health_status == "fallback":
            answer = QMessageBox.question(
                self,
                "Fallback Mode",
                "Phonikud is in fallback mode. Baseline quality may be degraded.\n\nContinue bootstrap?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        elif health_status == "error":
            answer = QMessageBox.question(
                self,
                "Health Error",
                "Latest health-check reported error.\nContinue bootstrap anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        rebuild_auto = self.rebuild_radio.isChecked()
        limit = int(self.limit_spin.value()) or None
        total_hint = int(limit or 1)
        progress_dialog = BatchProgressDialogV3(parent=self, total=total_hint)
        progress_dialog.setWindowTitle("Pronunciation Bootstrap (Phonikud)")
        progress_dialog.set_stage("Starting...")
        progress_dialog.show()

        worker = PronunciationBootstrapWorker(
            lang=str(self.lang_combo.currentData() or "he"),
            model_path=self.model_path_edit.text().strip(),
            enabled=self.enabled_checkbox.isChecked(),
            chunk_size=int(self.chunk_size_spin.value()),
            rebuild_auto=bool(rebuild_auto),
            limit=limit,
            dry_run=self.dry_run_cb.isChecked(),
            include_lemmas=self.include_lemmas_cb.isChecked(),
            include_terms=self.include_terms_cb.isChecked(),
            include_user_dictionary=self.include_ud_cb.isChecked(),
            selected_items=self.selected_items,
        )
        self._bootstrap_worker = worker
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda result: self._on_bootstrap_finished(result, progress_dialog))
        worker.error.connect(lambda err: self._on_bootstrap_error(err, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.run_btn.setEnabled(False)
        worker.finished.connect(lambda *_: self._clear_bootstrap_worker())
        worker.error.connect(lambda *_: self._clear_bootstrap_worker())
        worker.start()

    def _clear_bootstrap_worker(self) -> None:
        self._bootstrap_worker = None
        self.run_btn.setEnabled(True)

    def _on_bootstrap_finished(self, result: dict, progress_dialog: BatchProgressDialogV3) -> None:
        progress_dialog.set_completed()
        progress_dialog.update_counts(
            int(result.get("updated", 0)),
            int(result.get("skipped", 0)),
            int(result.get("failed", 0)),
        )
        progress_dialog.accept()

        dry_run = bool(result.get("dry_run"))
        title = "Bootstrap Dry-Run Complete" if dry_run else "Bootstrap Complete"
        msg = (
            f"Mode: {result.get('health_mode')} ({result.get('health_status')})\n"
            f"Total candidates: {int(result.get('total_candidates', 0))}\n"
            f"Generated candidates: {int(result.get('generated_candidates', 0))}\n"
            f"Updated: {int(result.get('updated', 0))}\n"
            f"Skipped: {int(result.get('skipped', 0))}\n"
            f"Failed: {int(result.get('failed', 0))}"
        )
        if dry_run:
            msg += "\n\nDry-run mode: all DB changes were rolled back."
        else:
            self._should_refresh_parent = True

        if int(result.get("failed", 0)) > 0:
            QMessageBox.warning(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)

    def _on_bootstrap_error(self, error_msg: str, progress_dialog: BatchProgressDialogV3) -> None:
        progress_dialog.reject()
        QMessageBox.warning(self, "Bootstrap Failed", f"Pronunciation bootstrap failed:\n{error_msg}")


def show_pronunciation_bootstrap_dialog(
    *,
    parent=None,
    selected_items: Optional[List[Dict[str, str]]] = None,
) -> bool:
    dialog = PronunciationBootstrapDialog(parent=parent, selected_items=selected_items)
    dialog.exec()
    return bool(dialog._should_refresh_parent)
