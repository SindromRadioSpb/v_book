"""Dialog for sentence-level niqqud bootstrap (sentence_pronunciation table).

Separate from lexical PronunciationBootstrapDialog.
See docs/SENTENCES_NIQQUD.md for contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
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
from app.infra.resource_paths import ResourcePaths
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.workers import PhonikudHealthCheckWorker

logger = logging.getLogger(__name__)

_MODE_FILL = "fill_only"
_MODE_REBUILD = "rebuild"
_MODE_DRY = "dry_run"


class SentenceNiqqudBootstrapDialog(QDialog):
    """Sentence niqqud bootstrap — scope + mode selector with V3 progress."""

    def __init__(
        self,
        parent=None,
        *,
        selected_ids: Optional[List[int]] = None,
        page_ids: Optional[List[int]] = None,
        all_ids: Optional[List[int]] = None,
        lang: str = "he",
    ):
        super().__init__(parent)
        self.setWindowTitle("Sentence Niqqud Bootstrap")
        self.setMinimumWidth(620)

        self.settings = SettingsService.get_instance()
        self._selected_ids = list(selected_ids or [])
        self._page_ids = list(page_ids or [])
        self._all_ids = list(all_ids or [])
        self._lang = lang
        self._worker = None
        self._health_worker = None
        self._should_refresh = False

        self._init_ui()
        self._load_settings()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("<h2>Sentence Niqqud Bootstrap</h2>"))
        info = QLabel(
            "Generates Hebrew niqqud (vowel marks) for sentences. "
            "Manual overrides are never overwritten."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        # ── Phonikud Runtime Gate (mirrors PronunciationBootstrapDialog) ──
        gate_box = QGroupBox("Phonikud Runtime Gate")
        gate_form = QFormLayout(gate_box)

        self._enabled_checkbox = QCheckBox("Enable Phonikud baseline generation")
        self._enabled_checkbox.setChecked(True)
        gate_form.addRow("State:", self._enabled_checkbox)

        path_row = QHBoxLayout()
        self._model_path_edit = QLineEdit()
        self._model_path_edit.setPlaceholderText("Local model/checkpoint path (optional)")
        path_row.addWidget(self._model_path_edit, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_model_path)
        path_row.addWidget(browse_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._model_path_edit.setText(""))
        path_row.addWidget(clear_btn)
        gate_form.addRow("Model path:", path_row)

        health_row = QHBoxLayout()
        self._health_btn = QPushButton("Health Check")
        self._health_btn.clicked.connect(self._run_health_check)
        health_row.addWidget(self._health_btn)
        self._health_mode_label = QLabel("Mode: unknown")
        health_row.addWidget(self._health_mode_label)
        health_row.addStretch()
        gate_form.addRow("Health:", health_row)

        self._health_details_label = QLabel("No health-check run yet.")
        self._health_details_label.setWordWrap(True)
        gate_form.addRow("Details:", self._health_details_label)

        self._health_samples_label = QLabel("")
        self._health_samples_label.setWordWrap(True)
        gate_form.addRow("Samples:", self._health_samples_label)
        root.addWidget(gate_box)

        # ── Scope ────────────────────────────────────────────────────────────
        scope_box = QGroupBox("Scope")
        scope_layout = QVBoxLayout(scope_box)

        n_sel = len(self._selected_ids)
        n_page = len(self._page_ids)
        n_all = len(self._all_ids)

        self._rb_selected = QRadioButton(f"Selected rows ({n_sel})")
        self._rb_selected.setEnabled(n_sel > 0)
        self._rb_page = QRadioButton(f"Current page ({n_page})")
        self._rb_page.setEnabled(n_page > 0)
        self._rb_all = QRadioButton(f"All filtered ({n_all})")
        self._rb_all.setEnabled(n_all > 0)

        if n_sel > 0:
            self._rb_selected.setChecked(True)
        elif n_page > 0:
            self._rb_page.setChecked(True)
        else:
            self._rb_all.setChecked(True)

        scope_layout.addWidget(self._rb_selected)
        scope_layout.addWidget(self._rb_page)
        scope_layout.addWidget(self._rb_all)
        root.addWidget(scope_box)

        # ── Mode ─────────────────────────────────────────────────────────────
        mode_box = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_box)
        self._rb_fill = QRadioButton("Fill-only (recommended) — skip already-processed rows")
        self._rb_fill.setChecked(True)
        self._rb_rebuild = QRadioButton("Rebuild — re-generate all non-override rows")
        self._rb_dry = QRadioButton("Dry-run — preview without writing to DB")
        mode_layout.addWidget(self._rb_fill)
        mode_layout.addWidget(self._rb_rebuild)
        mode_layout.addWidget(self._rb_dry)
        root.addWidget(mode_box)

        # ── Advanced ─────────────────────────────────────────────────────────
        adv_box = QGroupBox("Advanced")
        adv_box.setCheckable(True)
        adv_box.setChecked(False)
        adv_layout = QFormLayout()

        self._spin_min_len = QSpinBox()
        self._spin_min_len.setRange(1, 100)
        self._spin_min_len.setValue(5)
        adv_layout.addRow("Min length (chars):", self._spin_min_len)

        self._spin_max_len = QSpinBox()
        self._spin_max_len.setRange(100, 10000)
        self._spin_max_len.setValue(2000)
        adv_layout.addRow("Max length (chars):", self._spin_max_len)

        self._spin_he_ratio = QDoubleSpinBox()
        self._spin_he_ratio.setRange(0.0, 1.0)
        self._spin_he_ratio.setSingleStep(0.05)
        self._spin_he_ratio.setValue(0.10)
        self._spin_he_ratio.setDecimals(2)
        adv_layout.addRow("Min Hebrew ratio:", self._spin_he_ratio)

        adv_box.setLayout(adv_layout)
        root.addWidget(adv_box)

        # ── Results (2-column grid, hidden until bootstrap completes) ────────
        self._results_box = QGroupBox("Results")
        self._results_box.setVisible(False)
        results_grid = QGridLayout(self._results_box)
        results_grid.setColumnMinimumWidth(1, 70)
        results_grid.setColumnMinimumWidth(3, 70)
        results_grid.setColumnStretch(2, 1)  # spacer between columns

        # (grid_key, left_label, right_key, right_label)
        _stat_rows = [
            ("total",      "Total:",        "mode",        "Mode:"),
            ("processed",  "Processed:",    "elapsed",     "Elapsed:"),
            ("inserted",   "Inserted:",     "failed",      "Failed:"),
            ("updated",    "Updated:",      "partial_qc",  "QC partial:"),
            ("skipped",    "Skipped:",      "rejected_qc", "QC rejected:"),
            ("same_hash",  "  same_hash:",  "too_short",   "  too_short:"),
            ("override",   "  has_override:", "non_hebrew", "  non_hebrew:"),
        ]
        self._sv: dict = {}  # stat value labels
        for row_idx, (k1, lbl1, k2, lbl2) in enumerate(_stat_rows):
            results_grid.addWidget(QLabel(lbl1), row_idx, 0, Qt.AlignmentFlag.AlignRight)
            v1 = QLabel("—")
            self._sv[k1] = v1
            results_grid.addWidget(v1, row_idx, 1)
            results_grid.addWidget(QLabel(lbl2), row_idx, 2, Qt.AlignmentFlag.AlignRight)
            v2 = QLabel("—")
            self._sv[k2] = v2
            results_grid.addWidget(v2, row_idx, 3)

        root.addWidget(self._results_box)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run Bootstrap")
        self._run_btn.setDefault(True)
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        self._enabled_checkbox.setChecked(
            self.settings.get_bool("pronunciation/phonikud/enabled", True)
        )
        self._model_path_edit.setText(
            self.settings.get_string("pronunciation/phonikud/model_path", "")
        )
        # Restore last health-check result from cache
        mode = (self.settings.get_string("pronunciation/phonikud/last_health_mode", "") or "").strip()
        status = (self.settings.get_string("pronunciation/phonikud/last_health_status", "") or "").strip()
        details = (self.settings.get_string("pronunciation/phonikud/last_health_details", "") or "").strip()
        if mode:
            self._render_health({"mode": mode, "status": status or "error", "details": details, "samples": []})

    def _save_settings(self) -> None:
        model_path = (self._model_path_edit.text() or "").strip().strip("\"'").rstrip(" .")
        self._model_path_edit.setText(model_path)
        self.settings.set_value("pronunciation/phonikud/enabled", bool(self._enabled_checkbox.isChecked()))
        self.settings.set_value("pronunciation/phonikud/model_path", model_path)
        self.settings.sync()

    # ── Model path browser ────────────────────────────────────────────────────

    def _browse_model_path(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        current = self._model_path_edit.text().strip()
        default_dir = ResourcePaths.build(create=True).models_root / "phonikud"
        start_dir = current or str(default_dir)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Phonikud ONNX Model",
            start_dir,
            "ONNX Model (*.onnx);;All Files (*)",
        )
        if file_path:
            self._model_path_edit.setText(file_path)
            return
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Phonikud model folder",
            start_dir,
        )
        if directory:
            self._model_path_edit.setText(directory)

    # ── Health check ──────────────────────────────────────────────────────────

    def _run_health_check(self) -> None:
        if self._health_worker is not None:
            return
        self._save_settings()
        self._health_btn.setEnabled(False)
        self._health_mode_label.setText("Mode: checking...")
        self._health_details_label.setText("Running health-check...")
        self._health_samples_label.setText("")

        worker = PhonikudHealthCheckWorker(
            model_path=self._model_path_edit.text().strip(),
            enabled=self._enabled_checkbox.isChecked(),
        )
        self._health_worker = worker
        worker.finished.connect(self._on_health_finished)
        worker.error.connect(self._on_health_error)
        worker.finished.connect(lambda *_: self._clear_health_worker())
        worker.error.connect(lambda *_: self._clear_health_worker())
        worker.start()

    def _clear_health_worker(self) -> None:
        self._health_worker = None
        self._health_btn.setEnabled(True)

    def _on_health_finished(self, report: dict) -> None:
        self._render_health(report)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.settings.set_value("pronunciation/phonikud/last_health_status", str(report.get("status") or "error"))
        self.settings.set_value("pronunciation/phonikud/last_health_mode", str(report.get("mode") or "error"))
        self.settings.set_value("pronunciation/phonikud/last_health_details", str(report.get("details") or ""))
        self.settings.set_value("pronunciation/phonikud/last_health_checked_at", now)
        self.settings.sync()

    def _on_health_error(self, error_msg: str) -> None:
        self._health_mode_label.setText("Mode: error")
        self._health_mode_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self._health_details_label.setText(f"Health-check failed: {error_msg}")
        self._health_samples_label.setText("")

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

        self._health_mode_label.setText(f"Mode: {mode} ({status})")
        self._health_mode_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._health_details_label.setText(f"{details} | latency={latency}ms")

        if samples:
            rendered = " | ".join(
                f"{str(item.get('input') or '')} -> {str(item.get('output') or '')}"
                for item in samples[:2]
            )
            self._health_samples_label.setText(rendered)
        else:
            self._health_samples_label.setText("")

    # ── Scope resolution ──────────────────────────────────────────────────────

    def _resolved_ids(self) -> List[int]:
        if self._rb_selected.isChecked():
            return self._selected_ids
        if self._rb_page.isChecked():
            return self._page_ids
        return self._all_ids

    def _resolved_mode(self) -> str:
        if self._rb_rebuild.isChecked():
            return _MODE_REBUILD
        if self._rb_dry.isChecked():
            return _MODE_DRY
        return _MODE_FILL

    # ── Run ───────────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        ids = self._resolved_ids()
        if not ids:
            QMessageBox.warning(self, "No sentences", "No sentences in selected scope.")
            return

        self._save_settings()

        mode = self._resolved_mode()
        min_len = self._spin_min_len.value()
        max_len = self._spin_max_len.value()
        min_he_ratio = self._spin_he_ratio.value()
        model_path = (self._model_path_edit.text() or "").strip()
        enabled = self._enabled_checkbox.isChecked()

        from app.ui.workers import SentenceNiqqudBootstrapWorker
        self._worker = SentenceNiqqudBootstrapWorker(
            sentence_ids=ids,
            lang=self._lang,
            mode=mode,
            model_path=model_path,
            enabled=enabled,
            chunk_size=200,
            sub_chunk_size=50,
            min_len=min_len,
            max_len=max_len,
            min_he_ratio=min_he_ratio,
        )

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(ids))
        progress_dialog.setWindowTitle("Sentence Niqqud Bootstrap")

        self._worker.progress.connect(progress_dialog.update_progress)
        self._worker.stage_updated.connect(progress_dialog.set_stage)
        self._worker.row_translated.connect(progress_dialog.add_recent_item)

        def _on_stats(ins, upd, skp, fail):
            progress_dialog.update_counts(ins + upd, skp, fail)

        self._worker.stats_updated.connect(_on_stats)
        self._worker.finished.connect(lambda r: self._on_finished(r, progress_dialog))
        self._worker.error.connect(lambda e: self._on_error(e, progress_dialog))
        progress_dialog.cancel_requested.connect(self._worker.cancel)
        progress_dialog.pause_requested.connect(self._worker.pause)
        progress_dialog.resume_requested.connect(self._worker.resume)

        self._run_btn.setEnabled(False)
        self._worker.finished.connect(lambda _: self._run_btn.setEnabled(True))
        self._worker.error.connect(lambda _: self._run_btn.setEnabled(True))

        self._worker.start()
        progress_dialog.exec()

    def _on_finished(self, result: dict, progress_dialog: BatchProgressDialogV3) -> None:
        progress_dialog.set_completed()
        progress_dialog.accept()  # dismiss blocking exec() so the app is not stuck

        dry_run = bool(result.get("dry_run"))
        cancelled = bool(result.get("cancelled"))
        if not dry_run:
            self._should_refresh = True

        # ── Populate 2-column stats grid ──────────────────────────────────────
        total     = int(result.get("total_candidates", 0))
        inserted  = int(result.get("inserted", 0))
        updated   = int(result.get("updated", 0))
        failed    = int(result.get("failed", 0))
        partial   = int(result.get("partial_qc", 0))
        rejected  = int(result.get("rejected_qc", 0))
        same_hash = int(result.get("skipped_same_hash", 0))
        override  = int(result.get("skipped_has_override", 0))
        too_short = int(result.get("skipped_too_short", 0))
        non_heb   = int(result.get("skipped_non_hebrew_ratio", 0))
        too_long  = int(result.get("skipped_too_long", 0))
        qc_skip   = int(result.get("skipped_invalid_after_qc", 0))
        skipped   = same_hash + override + too_short + too_long + non_heb + qc_skip
        processed = total - failed
        mode_str  = str(result.get("generator_mode", "?"))
        elapsed   = float(result.get("elapsed_seconds", 0.0))

        self._sv["total"].setText(str(total))
        self._sv["mode"].setText(mode_str)
        self._sv["processed"].setText(str(processed))
        self._sv["elapsed"].setText(f"{elapsed:.1f}s")
        self._sv["inserted"].setText(str(inserted))
        self._sv["failed"].setText(str(failed))
        self._sv["updated"].setText(str(updated))
        self._sv["partial_qc"].setText(str(partial))
        self._sv["skipped"].setText(str(skipped))
        self._sv["rejected_qc"].setText(str(rejected))
        self._sv["same_hash"].setText(str(same_hash))
        self._sv["too_short"].setText(str(too_short))
        self._sv["override"].setText(str(override))
        self._sv["non_hebrew"].setText(str(non_heb))

        # Colour-code key values
        self._sv["inserted"].setStyleSheet("color: #2e7d32; font-weight: bold;" if inserted else "")
        self._sv["failed"].setStyleSheet("color: #d32f2f; font-weight: bold;" if failed else "")

        if dry_run:
            self._sv["mode"].setText(f"{mode_str}  [DRY RUN]")
        elif cancelled:
            self._sv["mode"].setText(f"{mode_str}  [CANCELLED]")

        self._results_box.setVisible(True)
        self.adjustSize()

        # ── Summary popup (matches PronunciationBootstrapDialog pattern) ──────
        title = (
            "Sentence Niqqud — Dry Run Complete" if dry_run
            else "Sentence Niqqud — Cancelled" if cancelled
            else "Sentence Niqqud — Complete"
        )
        msg = (
            f"Mode:        {mode_str}\n"
            f"Total:       {total}\n"
            f"Inserted:    {inserted}\n"
            f"Updated:     {updated}\n"
            f"Skipped:     {skipped}\n"
            f"  same_hash: {same_hash}\n"
            f"  override:  {override}\n"
            f"  too_short: {too_short}\n"
            f"  non_hebrew:{non_heb}\n"
            f"Failed:      {failed}\n"
            f"QC partial:  {partial}\n"
            f"QC rejected: {rejected}\n"
            f"Elapsed:     {elapsed:.1f}s"
        )
        if dry_run:
            msg += "\n\nDry-run mode — no DB changes were written."
        if cancelled:
            msg += "\n\nBootstrap was cancelled before completion."

        if failed > 0:
            QMessageBox.warning(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)

    def _on_error(self, msg: str, progress_dialog: BatchProgressDialogV3) -> None:
        progress_dialog.set_stage(f"Error: {msg[:80]}")
        progress_dialog.accept()  # dismiss blocking exec() before showing the error box
        QMessageBox.critical(self, "Bootstrap Error", msg)

    def should_refresh(self) -> bool:
        return self._should_refresh


def show_sentence_niqqud_bootstrap_dialog(
    parent=None,
    *,
    selected_ids: Optional[List[int]] = None,
    page_ids: Optional[List[int]] = None,
    all_ids: Optional[List[int]] = None,
    lang: str = "he",
) -> bool:
    """Show the dialog and return True if a refresh is needed."""
    dlg = SentenceNiqqudBootstrapDialog(
        parent,
        selected_ids=selected_ids,
        page_ids=page_ids,
        all_ids=all_ids,
        lang=lang,
    )
    dlg.exec()
    return dlg.should_refresh()
