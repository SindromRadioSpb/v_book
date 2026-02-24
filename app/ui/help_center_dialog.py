"""In-app help center dialog with topic tabs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QTabWidget, QTextBrowser, QVBoxLayout


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_doc(relative_path: str, fallback: str) -> str:
    try:
        path = _repo_root() / relative_path
        if not path.exists():
            return fallback
        return path.read_text(encoding="utf-8")
    except Exception:
        return fallback


class HelpCenterDialog(QDialog):
    """Premium help center shell (tabs + markdown content)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help Center")
        self.resize(980, 720)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        layout.addWidget(tabs, 1)

        overview_md = _read_doc(
            "docs/HELP_CENTER.md",
            "# Help Center\n\nDocumentation is not available yet.",
        )
        shortcuts_md = _read_doc(
            "docs/KEYBOARD_SHORTCUTS.md",
            "# Keyboard Shortcuts\n\nNo shortcuts documentation found.",
        )
        keyboard_flows_md = _read_doc(
            "docs/KEYBOARD_INTERACTIONS.md",
            "# Keyboard Interaction Patterns\n\nNo interaction patterns documentation found.",
        )

        tabs.addTab(self._markdown_view(overview_md), "Overview")
        tabs.addTab(self._markdown_view(shortcuts_md), "Shortcuts")
        tabs.addTab(self._markdown_view(keyboard_flows_md), "Keyboard Flows")
        tabs.addTab(
            self._markdown_view(
                "# Translation\n\n"
                "- Translate Selected\n"
                "- Scope chips (Current Project / All)\n"
                "- Batch progress/cancel contracts\n"
                "\n"
                "Detailed runbook is linked from the Overview tab."
            ),
            "Translation",
        )
        tabs.addTab(
            self._markdown_view(
                "# Audio & Pronunciation\n\n"
                "- Generate Audio (source-only)\n"
                "- Pronunciation Bootstrap\n"
                "- Audio Player queue / playlists / history\n"
                "\n"
                "Detailed runbook is linked from the Overview tab."
            ),
            "Audio",
        )

    @staticmethod
    def _markdown_view(markdown_text: str) -> QTextBrowser:
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setReadOnly(True)
        view.setMarkdown(markdown_text)
        return view


def show_help_center_dialog(parent=None) -> bool:
    dialog = HelpCenterDialog(parent=parent)
    dialog.exec()
    return True
