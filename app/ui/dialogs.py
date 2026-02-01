"""Dialog windows."""
import logging
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QMessageBox,
)

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
        create_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(create_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

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
            from PyQt6.QtGui import QTextCursor, QTextCharFormat
            from PyQt6.QtCore import Qt

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
