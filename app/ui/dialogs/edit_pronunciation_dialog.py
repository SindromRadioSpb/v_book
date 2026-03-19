"""Dialog for manual pronunciation overrides."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services.db_service import DBService
from app.services.pronunciation_quality_service import PronunciationQualityService
from app.services.pronunciation_service import PronunciationService


class EditPronunciationDialog(QDialog):
    """Edit pronunciation payload for one canonical source norm."""

    def __init__(
        self,
        *,
        src_lang: str,
        src_norm: str,
        src_text: str,
        niqqud_text: str | None,
        ipa: str | None,
        reading_text: str | None,
        notes: str | None,
        is_override: bool,
        parent=None,
    ):
        super().__init__(parent)
        self._clear_requested = False
        self._source_text = src_text or src_norm
        self.setWindowTitle("Edit Pronunciation")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        head = QLabel(
            f"<b>Source:</b> {src_text}<br><b>Lang:</b> {src_lang}<br><b>Norm:</b> {src_norm}"
        )
        head.setWordWrap(True)
        root.addWidget(head)

        form = QFormLayout()
        self.niqqud_edit = QLineEdit(niqqud_text or "")
        self.ipa_edit = QLineEdit(ipa or "")
        self.reading_edit = QLineEdit(reading_text or "")
        self.notes_edit = QLineEdit(notes or "")
        self.override_checkbox = QCheckBox("Manual override (wins over auto bootstrap)")
        self.override_checkbox.setChecked(bool(is_override))
        form.addRow("Niqqud:", self.niqqud_edit)
        form.addRow("IPA:", self.ipa_edit)
        form.addRow("Reading:", self.reading_edit)
        form.addRow("Notes:", self.notes_edit)
        form.addRow("", self.override_checkbox)
        root.addLayout(form)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        root.addWidget(self.preview_label)
        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet("color: #c62828;")
        self.warning_label.setWordWrap(True)
        root.addWidget(self.warning_label)

        controls = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Entry")
        self.clear_btn.clicked.connect(self._on_clear)
        controls.addWidget(self.clear_btn)
        controls.addStretch()
        root.addLayout(controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        save_btn.setText("Save")
        save_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.niqqud_edit.textChanged.connect(self._refresh_preview)
        self.reading_edit.textChanged.connect(self._refresh_preview)
        self.override_checkbox.stateChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def clear_requested(self) -> bool:
        return self._clear_requested

    def payload(self) -> dict:
        return {
            "niqqud_text": self.niqqud_edit.text().strip() or None,
            "ipa": self.ipa_edit.text().strip() or None,
            "reading_text": self.reading_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
            "is_override": self.override_checkbox.isChecked(),
        }

    def _on_clear(self):
        answer = QMessageBox.question(
            self,
            "Clear Pronunciation",
            "Delete pronunciation entry for this source?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._clear_requested = True
        self.accept()

    def _refresh_preview(self):
        candidate = (
            (self.niqqud_edit.text() or "").strip()
            or (self.reading_edit.text() or "").strip()
            or self._source_text
        )
        strict = self.override_checkbox.isChecked()
        result = PronunciationQualityService.normalize_field(candidate, strict=strict)
        if result.is_valid and result.value:
            self.preview_label.setText(f"<b>What will be spoken:</b> {result.value}")
            if result.qc_flag:
                self.warning_label.setText(
                    "Input was auto-fixed for playback safety " f"(qc={result.qc_flag})."
                )
            else:
                self.warning_label.setText("")
        else:
            self.preview_label.setText("<b>What will be spoken:</b> -")
            self.warning_label.setText(result.reason or "Invalid pronunciation payload.")


def show_edit_pronunciation_dialog(
    *,
    parent,
    src_lang: str,
    src_norm: str,
    src_text: str,
) -> bool:
    """Open pronunciation editor and persist changes. Returns True on change."""
    src_lang_clean = (src_lang or "").strip()
    src_norm_clean = (src_norm or "").strip()
    src_text_clean = (src_text or "").strip()
    if not src_lang_clean or not src_norm_clean:
        QMessageBox.warning(
            parent, "Edit Pronunciation", "Cannot edit pronunciation: invalid source payload."
        )
        return False

    db_service = DBService.get_instance()
    service = PronunciationService()

    with db_service.get_session() as session:
        existing = service.get_entry(session, lang=src_lang_clean, src_norm=src_norm_clean)

    dialog = EditPronunciationDialog(
        src_lang=src_lang_clean,
        src_norm=src_norm_clean,
        src_text=src_text_clean or src_norm_clean,
        niqqud_text=existing.niqqud_text if existing else None,
        ipa=existing.ipa if existing else None,
        reading_text=existing.reading_text if existing else None,
        notes=existing.notes if existing else None,
        is_override=bool(existing.is_override) if existing else True,
        parent=parent,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    with db_service.get_session() as session:
        if dialog.clear_requested:
            changed = service.delete_entry(session, lang=src_lang_clean, src_norm=src_norm_clean)
            session.commit()
            return bool(changed)

        payload = dialog.payload()
        source = "manual" if payload["is_override"] else "auto"
        try:
            service.upsert_entry(
                session,
                lang=src_lang_clean,
                src_norm=src_norm_clean,
                niqqud_text=payload["niqqud_text"],
                ipa=payload["ipa"],
                reading_text=payload["reading_text"],
                source=source,
                confidence=1.0 if payload["is_override"] else None,
                is_override=bool(payload["is_override"]),
                notes=payload["notes"],
                allow_auto_overwrite=True,
            )
        except ValueError as exc:
            QMessageBox.warning(parent, "Edit Pronunciation", str(exc))
            session.rollback()
            return False
        session.commit()
    return True
