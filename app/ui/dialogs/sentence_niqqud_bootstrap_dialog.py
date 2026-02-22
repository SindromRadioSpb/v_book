"""Dialog for sentence-level niqqud bootstrap (sentence_pronunciation table).

Separate from lexical PronunciationBootstrapDialog.
See docs/SENTENCES_NIQQUD.md for contract.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QDoubleSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from app.infra.settings import SettingsService
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3

logger = logging.getLogger(__name__)

_MODE_FILL = "fill_only"
_MODE_REBUILD = "rebuild"
_MODE_DRY = "dry_run"

_SCOPE_SELECTED = "selected"
_SCOPE_PAGE = "current_page"
_SCOPE_ALL = "all_filtered"


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
        phonikud_mode: str = "unknown",   # "real" | "fallback" | "error" | "unknown"
    ):
        super().__init__(parent)
        self.setWindowTitle("Sentence Niqqud Bootstrap")
        self.setMinimumWidth(560)

        self.settings = SettingsService.get_instance()
        self._selected_ids = list(selected_ids or [])
        self._page_ids = list(page_ids or [])
        self._all_ids = list(all_ids or [])
        self._lang = lang
        self._phonikud_mode = phonikud_mode
        self._worker = None
        self._should_refresh = False

        self._init_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        # Title
        root.addWidget(QLabel("<h2>Sentence Niqqud Bootstrap</h2>"))
        info = QLabel(
            "Generates Hebrew niqqud (vowel marks) for sentences. "
            "Manual overrides are never overwritten."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        # Phonikud gate status
        gate_box = QGroupBox("Phonikud Gate")
        gate_layout = QHBoxLayout(gate_box)
        mode_label = QLabel(f"<b>Mode:</b> {self._phonikud_mode}")
        gate_layout.addWidget(mode_label)
        if self._phonikud_mode in ("fallback", "error", "unknown"):
            warn = QLabel("⚠ Fallback mode — output quality may be low")
            warn.setStyleSheet("color: orange;")
            gate_layout.addWidget(warn)
        elif self._phonikud_mode == "real":
            ok_lbl = QLabel("✓ Real inference active")
            ok_lbl.setStyleSheet("color: green;")
            gate_layout.addWidget(ok_lbl)
        gate_layout.addStretch()
        root.addWidget(gate_box)

        # Scope
        scope_box = QGroupBox("Scope")
        scope_form = QVBoxLayout(scope_box)

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

        scope_form.addWidget(self._rb_selected)
        scope_form.addWidget(self._rb_page)
        scope_form.addWidget(self._rb_all)
        root.addWidget(scope_box)

        # Mode
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

        # Advanced
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

        # Log area
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setVisible(False)
        root.addWidget(self._log)

        # Buttons
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run Bootstrap")
        self._run_btn.setDefault(True)
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        root.addLayout(btn_row)

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

        mode = self._resolved_mode()
        min_len = self._spin_min_len.value()
        max_len = self._spin_max_len.value()
        min_he_ratio = self._spin_he_ratio.value()

        # Get phonikud settings
        phonikud_settings = self._get_phonikud_settings()

        # Build worker
        from app.ui.workers import SentenceNiqqudBootstrapWorker
        self._worker = SentenceNiqqudBootstrapWorker(
            sentence_ids=ids,
            lang=self._lang,
            mode=mode,
            model_path=phonikud_settings.get("model_path", ""),
            enabled=phonikud_settings.get("enabled", True),
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

    def _get_phonikud_settings(self) -> dict:
        try:
            model_path = self.settings.get_str("phonikud/model_path", "")
            enabled = self.settings.get_bool("phonikud/enabled", True)
            return {"model_path": model_path, "enabled": enabled}
        except Exception:
            return {"model_path": "", "enabled": True}

    def _on_finished(self, result: dict, progress_dialog: BatchProgressDialogV3) -> None:
        self._should_refresh = True
        progress_dialog.set_completed()

        lines = result.get("summary_lines") or []
        if lines:
            self._log.setVisible(True)
            self._log.setPlainText("\n".join(lines))

        summary = "\n".join(lines) if lines else "Done."
        progress_dialog.set_stage("Done")

    def _on_error(self, msg: str, progress_dialog: BatchProgressDialogV3) -> None:
        progress_dialog.set_stage(f"Error: {msg[:80]}")
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
    phonikud_mode: str = "unknown",
) -> bool:
    """Show the dialog and return True if a refresh is needed."""
    dlg = SentenceNiqqudBootstrapDialog(
        parent,
        selected_ids=selected_ids,
        page_ids=page_ids,
        all_ids=all_ids,
        lang=lang,
        phonikud_mode=phonikud_mode,
    )
    dlg.exec()
    return dlg.should_refresh()
