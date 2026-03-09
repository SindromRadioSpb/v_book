"""Translate Text Dialog - User-initiated MT translation.

Allows users to:
- Translate arbitrary text via MT providers (Local MT + Cloud)
- Select source/target languages
- View translation metadata (provider, cache, glossary, latency)
- Copy translated text to clipboard
"""
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QComboBox,
    QProgressBar,
    QGroupBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from app.services.translation_service import TranslationService, TranslationResult
from app.ui.workers import SingleTextTranslateWorker
from app.infra.security import sanitize_for_log

logger = logging.getLogger(__name__)


# Language pairs supported by Local MT (NLLB-200) and most cloud providers
LANGUAGES = [
    ("English", "en"),
    ("Hebrew", "he"),
    ("Russian", "ru"),
    ("Arabic", "ar"),
    ("Chinese (Simplified)", "zh"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
]


class TranslateTextDialog(QDialog):
    """Dialog for translating arbitrary text via MT providers."""

    # Signal emitted when translation completes (for testing)
    translation_completed = pyqtSignal(TranslationResult)

    def __init__(self, parent=None, initial_text: str = "", src_lang: str = "en", tgt_lang: str = "he"):
        """Initialize translate text dialog.

        Args:
            parent: Parent widget
            initial_text: Pre-filled source text (optional)
            src_lang: Default source language (default: en)
            tgt_lang: Default target language (default: he)
        """
        super().__init__(parent)
        self.setWindowTitle("Translate Text")
        self.setMinimumSize(700, 600)

        self.translation_service = TranslationService()
        self.translate_worker: Optional[SingleTextTranslateWorker] = None
        self._translation_request_seq = 0
        self._active_translation_seq: Optional[int] = None
        self._retired_translate_workers: list[SingleTextTranslateWorker] = []

        self.initial_text = initial_text
        self.initial_src_lang = src_lang
        self.initial_tgt_lang = tgt_lang

        self.init_ui()

    def init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout()

        # Header
        header = QLabel("Translate Text via MT Providers")
        header.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(header)

        # Language selection
        lang_layout = QHBoxLayout()

        lang_layout.addWidget(QLabel("Source Language:"))
        self.source_combo = QComboBox()
        for lang_name, lang_code in LANGUAGES:
            self.source_combo.addItem(lang_name, lang_code)
        # Set default
        src_index = self.source_combo.findData(self.initial_src_lang)
        if src_index >= 0:
            self.source_combo.setCurrentIndex(src_index)
        lang_layout.addWidget(self.source_combo)

        lang_layout.addWidget(QLabel("Target Language:"))
        self.target_combo = QComboBox()
        for lang_name, lang_code in LANGUAGES:
            self.target_combo.addItem(lang_name, lang_code)
        # Set default
        tgt_index = self.target_combo.findData(self.initial_tgt_lang)
        if tgt_index >= 0:
            self.target_combo.setCurrentIndex(tgt_index)
        lang_layout.addWidget(self.target_combo)

        lang_layout.addStretch()
        layout.addLayout(lang_layout)

        # Input text
        input_group = QGroupBox("Source Text")
        input_layout = QVBoxLayout()

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("Enter text to translate...")
        self.input_text.setMinimumHeight(150)
        if self.initial_text:
            self.input_text.setPlainText(self.initial_text)
        input_layout.addWidget(self.input_text)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # Translate button + progress
        translate_layout = QHBoxLayout()

        self.translate_btn = QPushButton("Translate")
        self.translate_btn.setDefault(True)  # Enter triggers this
        self.translate_btn.clicked.connect(self.on_translate)
        translate_layout.addWidget(self.translate_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)  # Indeterminate
        translate_layout.addWidget(self.progress_bar)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.on_cancel_translation)
        translate_layout.addWidget(self.cancel_btn)

        translate_layout.addStretch()
        layout.addLayout(translate_layout)

        # Output text
        output_group = QGroupBox("Translated Text")
        output_layout = QVBoxLayout()

        self.output_text = QTextEdit()
        self.output_text.setPlaceholderText("Translation will appear here...")
        self.output_text.setReadOnly(True)
        self.output_text.setMinimumHeight(150)
        output_layout.addWidget(self.output_text)

        # Copy button
        copy_layout = QHBoxLayout()
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.on_copy)
        copy_layout.addWidget(self.copy_btn)
        copy_layout.addStretch()
        output_layout.addLayout(copy_layout)

        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # Metadata
        metadata_group = QGroupBox("Translation Metadata")
        metadata_layout = QVBoxLayout()

        self.metadata_label = QLabel("No translation yet")
        self.metadata_label.setWordWrap(True)
        metadata_font = QFont()
        metadata_font.setPointSize(9)
        self.metadata_label.setFont(metadata_font)
        metadata_layout.addWidget(self.metadata_label)

        metadata_group.setLayout(metadata_layout)
        layout.addWidget(metadata_group)

        # Close button
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        layout.addLayout(close_layout)

        self.setLayout(layout)

        # Connect Enter key in input to translate
        self.input_text.setTabChangesFocus(True)  # Tab moves focus (doesn't insert tab)

    def _finalize_translate_worker(self, worker: SingleTextTranslateWorker) -> None:
        """Release references once a worker has fully stopped."""
        if getattr(worker, "_hdle_cleanup_done", False):
            return

        setattr(worker, "_hdle_cleanup_done", True)

        if worker is self.translate_worker:
            self.translate_worker = None

        try:
            self._retired_translate_workers.remove(worker)
        except ValueError:
            pass

        worker.deleteLater()

    def _retire_translate_worker(self, *, wait_ms: int = 100) -> None:
        """Request cooperative stop for the current worker."""
        worker = self.translate_worker
        if worker is None:
            return

        worker.cancel()
        if worker.isRunning() and not worker.wait(wait_ms):
            logger.info("Single text translation worker is still stopping cooperatively")
            if worker not in self._retired_translate_workers:
                self._retired_translate_workers.append(worker)
        else:
            self._finalize_translate_worker(worker)

        self.translate_worker = None

    def on_translate(self):
        """Handle translate button click."""
        source_text = self.input_text.toPlainText().strip()

        # Validation
        if not source_text:
            QMessageBox.warning(self, "Empty Text", "Please enter text to translate.")
            return

        src_lang = self.source_combo.currentData()
        tgt_lang = self.target_combo.currentData()

        if src_lang == tgt_lang:
            QMessageBox.warning(
                self,
                "Same Language",
                "Source and target languages are the same.\n\nPlease select different languages."
            )
            return

        logger.info(f"Translating text ({src_lang} → {tgt_lang}): {sanitize_for_log(source_text[:50])}")

        # Cancel previous worker if running
        if self.translate_worker:
            self._active_translation_seq = None
            self._retire_translate_worker(wait_ms=100)

        self._translation_request_seq += 1
        request_seq = self._translation_request_seq

        # Create and start worker
        self.translate_worker = SingleTextTranslateWorker(
            text=source_text,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
        )
        self._active_translation_seq = request_seq

        self.translate_worker.result_ready.connect(
            lambda result, seq=request_seq: self.on_translation_result(result, seq)
        )
        self.translate_worker.error.connect(
            lambda error_msg, seq=request_seq: self.on_translation_error(error_msg, seq)
        )
        self.translate_worker.finished.connect(
            lambda worker=self.translate_worker: self._finalize_translate_worker(worker)
        )
        self.translate_worker.start()

        # Update UI
        self.translate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.output_text.clear()
        self.metadata_label.setText("Translating...")
        self.copy_btn.setEnabled(False)

    def on_cancel_translation(self):
        """Handle cancel button click."""
        if self.translate_worker:
            logger.info("Cancelling translation")
            self._active_translation_seq = None
            self._retire_translate_worker(wait_ms=100)

        # Reset UI
        self.translate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.metadata_label.setText("Translation cancelled")

    def on_translation_result(self, result: TranslationResult, request_seq: Optional[int] = None):
        """Handle translation result from worker."""
        if request_seq is not None and request_seq != self._active_translation_seq:
            logger.debug(
                "Ignoring stale translate-text result: seq=%s active=%s",
                request_seq,
                self._active_translation_seq,
            )
            return

        logger.info(
            "Translation completed: %s, provider=%s, cache_hit=%s",
            result.source,
            result.provider,
            getattr(result, "cache_hit", None),
        )

        # Display translation
        if result.translation:
            self.output_text.setPlainText(result.translation)
            self.copy_btn.setEnabled(True)
        else:
            self.output_text.setPlainText("(no translation)")

        # Build metadata string
        metadata_lines = []

        if result.provider:
            metadata_lines.append(f"Provider: {result.provider}")

        if result.source:
            metadata_lines.append(f"Source: {result.source}")

        if hasattr(result, 'cache_hit'):
            cache_status = "Yes ✓" if result.cache_hit else "No"
            metadata_lines.append(f"Cache Hit: {cache_status}")

        if hasattr(result, 'used_glossary'):
            glossary_status = "Yes ✓" if result.used_glossary else "No"
            metadata_lines.append(f"Used Glossary: {glossary_status}")

        if hasattr(result, 'latency_ms') and result.latency_ms is not None:
            metadata_lines.append(f"Latency: {result.latency_ms} ms")

        # Additional metadata from result.meta (if available)
        if hasattr(result, 'meta') and result.meta:
            if 'segment_count' in result.meta:
                metadata_lines.append(f"Segments: {result.meta['segment_count']}")
            if 'applied_terms_count' in result.meta:
                metadata_lines.append(f"Glossary Terms Applied: {result.meta['applied_terms_count']}")
            if 'model_id' in result.meta:
                metadata_lines.append(f"Model: {result.meta['model_id']}")

        metadata_text = " | ".join(metadata_lines) if metadata_lines else "No metadata available"
        self.metadata_label.setText(metadata_text)

        # Reset UI
        self.translate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._active_translation_seq = None

        # Emit signal (for testing)
        self.translation_completed.emit(result)

    def on_translation_error(self, error_msg: str, request_seq: Optional[int] = None):
        """Handle translation error from worker."""
        if request_seq is not None and request_seq != self._active_translation_seq:
            logger.debug(
                "Ignoring stale translate-text error: seq=%s active=%s",
                request_seq,
                self._active_translation_seq,
            )
            return

        logger.error(f"Translation error: {error_msg}")

        # Show error in UI (not modal spam - just update metadata)
        self.metadata_label.setText(f"Error: {error_msg}")
        self.output_text.setPlainText("(translation failed)")

        # Show error dialog
        QMessageBox.warning(
            self,
            "Translation Failed",
            f"Translation failed:\n\n{error_msg}\n\n"
            f"Check:\n"
            f"- MT providers enabled in Settings\n"
            f"- Local model installed (if using Local MT)\n"
            f"- Network connection (if using cloud providers)"
        )

        # Reset UI
        self.translate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._active_translation_seq = None

    def on_copy(self):
        """Copy translated text to clipboard."""
        from PyQt6.QtWidgets import QApplication

        translated_text = self.output_text.toPlainText()
        if translated_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(translated_text)
            logger.info("Copied translation to clipboard")

            # Brief feedback
            self.copy_btn.setText("Copied ✓")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy to Clipboard"))

    def closeEvent(self, event):
        """Handle dialog close - ensure worker is stopped."""
        if self.translate_worker:
            logger.info("Stopping translation worker on close")
            self._active_translation_seq = None
            self._retire_translate_worker(wait_ms=100)

        super().closeEvent(event)


def show_translate_text_dialog(parent=None, initial_text: str = "", src_lang: str = "en", tgt_lang: str = "he"):
    """Show translate text dialog.

    Args:
        parent: Parent widget
        initial_text: Pre-filled source text (optional)
        src_lang: Default source language
        tgt_lang: Default target language

    Returns:
        Dialog result (QDialog.DialogCode)
    """
    dialog = TranslateTextDialog(parent, initial_text, src_lang, tgt_lang)
    return dialog.exec()
