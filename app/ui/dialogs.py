"""Dialog windows."""

import logging

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.infra.security import sanitize_for_log

logger = logging.getLogger(__name__)


class CreateProjectDialog(QDialog):
    """Dialog for creating a new project."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Project")
        self.setMinimumWidth(400)

        layout = QVBoxLayout()

        # Name field
        layout.addWidget(QLabel("Project Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("My Hebrew Project")
        layout.addWidget(self.name_edit)

        # Description field
        layout.addWidget(QLabel("Description (optional):"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(100)
        self.desc_edit.setPlaceholderText("Enter project description...")
        layout.addWidget(self.desc_edit)

        # Buttons
        button_layout = QHBoxLayout()
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(self.on_create)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(create_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def on_create(self):
        """Validate and create project."""
        name = self.name_edit.text().strip()
        description = self.desc_edit.toPlainText().strip()

        # UI-layer validation: Check project name
        if not name:
            QMessageBox.warning(self, "Validation Error", "Project name cannot be empty.")
            return

        if len(name) > 255:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Project name is too long (max 255 characters).\n\nPlease use a shorter name.",
            )
            return

        # Check for problematic characters (basic validation)
        forbidden_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        if any(char in name for char in forbidden_chars):
            QMessageBox.warning(
                self,
                "Validation Error",
                f"Project name contains forbidden characters.\n\n"
                f"Please avoid: {' '.join(forbidden_chars)}",
            )
            return

        if len(description) > 10000:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Description is too long (max 10,000 characters).\n\nPlease shorten the description.",
            )
            return

        # Log validated input (sanitized)
        logger.info(f"Creating project: {sanitize_for_log(name)}")

        # Accept dialog
        self.accept()

    def get_data(self):
        """Get the entered data."""
        return {
            "name": self.name_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
        }


def show_error(parent, title: str, message: str):
    """Show an error message box."""
    QMessageBox.critical(parent, title, message)


def show_info(parent, title: str, message: str):
    """Show an info message box."""
    QMessageBox.information(parent, title, message)


def show_warning(parent, title: str, message: str):
    """Show a warning message box."""
    QMessageBox.warning(parent, title, message)


class TextViewDialog(QDialog):
    """Dialog for viewing document text."""

    def __init__(self, text: str, parent=None, highlight_text: str = None):
        super().__init__(parent)
        self.setWindowTitle("Document Text")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout()

        # Text display
        text_edit = QTextEdit()
        text_edit.setPlainText(text)
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)

        # Apply highlighting if requested
        if highlight_text:
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QTextCharFormat, QTextCursor

            cursor = text_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            text_edit.setTextCursor(cursor)

            # Find and highlight the sentence
            format = QTextCharFormat()
            format.setBackground(Qt.GlobalColor.yellow)

            if text_edit.find(highlight_text):
                cursor = text_edit.textCursor()
                cursor.mergeCharFormat(format)

                # Scroll to the highlighted text
                text_edit.ensureCursorVisible()

        # Stats
        stats_label = QLabel(
            f"Characters: {len(text)} | "
            f"Lines: {text.count(chr(10)) + 1} | "
            f"Words: {len(text.split())}"
        )
        layout.addWidget(stats_label)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.setLayout(layout)


class WhyTranslationDialog(QDialog):
    """M7: Dialog showing translation explainability."""

    def __init__(self, translation_result, src_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Why Translation: {src_text}")
        self.setMinimumWidth(500)

        layout = QVBoxLayout()

        # Source text
        layout.addWidget(QLabel(f"<b>Source:</b> {src_text}"))
        layout.addWidget(QLabel(""))  # Spacer

        # Translation
        translation = translation_result.translation or "(no translation)"
        layout.addWidget(QLabel(f"<b>Translation:</b> {translation}"))
        layout.addWidget(QLabel(""))

        # Provenance information
        info_layout = QVBoxLayout()

        # Source
        source_display = {
            "tm": "Translation Memory (User Override)",
            "dict": "Offline Dictionary",
            "mt_cache": "Machine Translation (Cached)",
            "mt": "Machine Translation (Live)",
            "none": "No Translation Found",
        }.get(translation_result.source, translation_result.source)
        info_layout.addWidget(QLabel(f"<b>Source:</b> {source_display}"))

        # Status
        if translation_result.status:
            status_display = translation_result.status.capitalize()
            info_layout.addWidget(QLabel(f"<b>Status:</b> {status_display}"))

        # Origin
        if translation_result.origin:
            origin_display = {
                "user_edit": "Manual User Edit",
                "import": "Imported from Dictionary",
                "mt_accept": "MT Suggestion (Accepted)",
                "mt_auto": "MT Automatic",
                "merge": "Merged Entry",
            }.get(translation_result.origin, translation_result.origin)
            info_layout.addWidget(QLabel(f"<b>Origin:</b> {origin_display}"))

        # Matched on
        if translation_result.matched_on:
            info_layout.addWidget(QLabel(f"<b>Matched On:</b> {translation_result.matched_on}"))

        # Match key used
        if translation_result.match_key_used:
            info_layout.addWidget(QLabel(f"<b>Match Key:</b> {translation_result.match_key_used}"))

        # Dictionary source
        if translation_result.dict_source_name:
            info_layout.addWidget(
                QLabel(f"<b>Dictionary:</b> {translation_result.dict_source_name}")
            )

        # MT provider
        if translation_result.provider:
            info_layout.addWidget(QLabel(f"<b>MT Provider:</b> {translation_result.provider}"))

        # Confidence
        if translation_result.confidence is not None:
            info_layout.addWidget(QLabel(f"<b>Confidence:</b> {translation_result.confidence:.2%}"))

        # TM ID
        if translation_result.tm_id:
            info_layout.addWidget(QLabel(f"<b>TM Entry ID:</b> {translation_result.tm_id}"))

        # Notes
        if translation_result.notes:
            info_layout.addWidget(QLabel(f"<b>Notes:</b> {translation_result.notes}"))

        layout.addLayout(info_layout)
        layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.setLayout(layout)
