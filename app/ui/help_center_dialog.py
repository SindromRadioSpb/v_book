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

    def __init__(self, parent=None, initial_tab: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Help Center")
        self.resize(980, 720)
        self._initial_tab = initial_tab
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget(self)
        layout.addWidget(self._tabs, 1)

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
        semantics_md = _read_doc(
            "docs/USER_GUIDE_SEMANTICS.md",
            "# Справочник по сущностям\n\nДокументация недоступна.",
        )
        terms_guide_md = _read_doc(
            "docs/TERMS_EXTRACTION_GUIDE.md",
            "# Настройки Terms\n\nДокументация недоступна.",
        )
        prompt_policy_md = _read_doc(
            "docs/HELP_PROMPT_POLICY.md",
            "# Prompt Policy\n\nДокументация недоступна.",
        )
        policy_editor_md = _read_doc(
            "docs/HELP_POLICY_EDITOR.md",
            "# Policy Editor\n\nДокументация недоступна.",
        )
        prompt_audit_md = _read_doc(
            "docs/HELP_PROMPT_AUDIT.md",
            "# Prompt Audit\n\nДокументация недоступна.",
        )

        self._tab_names: list[str] = []

        def _add(widget: QTextBrowser, label: str) -> None:
            self._tabs.addTab(widget, label)
            self._tab_names.append(label)

        _add(self._markdown_view(overview_md), "Overview")
        _add(self._markdown_view(shortcuts_md), "Shortcuts")
        _add(self._markdown_view(keyboard_flows_md), "Keyboard Flows")
        _add(
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
        _add(
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
        _add(self._markdown_view(prompt_policy_md), "Prompt Policy")
        _add(self._markdown_view(policy_editor_md), "Policy Editor")
        _add(self._markdown_view(prompt_audit_md), "Prompt Audit")
        _add(self._markdown_view(semantics_md), "Справочник сущностей")
        _add(self._markdown_view(terms_guide_md), "Настройки Terms")

        # Jump to requested tab if specified
        if self._initial_tab and self._initial_tab in self._tab_names:
            self._tabs.setCurrentIndex(self._tab_names.index(self._initial_tab))

    @staticmethod
    def _markdown_view(markdown_text: str) -> QTextBrowser:
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setReadOnly(True)
        view.setMarkdown(markdown_text)
        return view


def show_help_center_dialog(
    parent=None,
    initial_tab: str | None = None,
) -> bool:
    """Open the Help Center dialog.

    Args:
        parent: Parent widget.
        initial_tab: Optional tab label to show on open.
            Supported values: "Overview", "Shortcuts", "Keyboard Flows",
            "Translation", "Audio", "Prompt Policy", "Policy Editor",
            "Prompt Audit", "Справочник сущностей", "Настройки Terms".
    """
    dialog = HelpCenterDialog(parent=parent, initial_tab=initial_tab)
    dialog.exec()
    return True
