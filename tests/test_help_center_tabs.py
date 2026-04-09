"""PATCH-13 — Help Center tabs: Prompt Policy, Policy Editor, Prompt Audit.

Verifies:
- All three new tabs exist in HelpCenterDialog._tab_names.
- Each doc file contains the required section headings.
- initial_tab navigation works for new tabs.
- show_help_center_dialog docstring lists all new tab labels.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.help_center_dialog import HelpCenterDialog, show_help_center_dialog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _doc_text(filename: str) -> str:
    path = _repo_root() / "docs" / filename
    assert path.exists(), f"Missing help doc: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tab existence
# ---------------------------------------------------------------------------


def test_prompt_policy_tab_exists(qtbot):
    """'Prompt Policy' tab must be present in HelpCenterDialog."""
    w = HelpCenterDialog()
    qtbot.addWidget(w)
    assert "Prompt Policy" in w._tab_names


def test_policy_editor_tab_exists(qtbot):
    """'Policy Editor' tab must be present in HelpCenterDialog."""
    w = HelpCenterDialog()
    qtbot.addWidget(w)
    assert "Policy Editor" in w._tab_names


def test_prompt_audit_tab_exists(qtbot):
    """'Prompt Audit' tab must be present in HelpCenterDialog."""
    w = HelpCenterDialog()
    qtbot.addWidget(w)
    assert "Prompt Audit" in w._tab_names


# ---------------------------------------------------------------------------
# Doc content — key sections
# ---------------------------------------------------------------------------


def test_prompt_policy_content_has_key_sections():
    """HELP_PROMPT_POLICY.md must contain required section headings."""
    text = _doc_text("HELP_PROMPT_POLICY.md")
    required = [
        "Что такое Prompt Policy",
        "Как выбрать Policy",
        "Практические советы",
        "Ограничения Basic Mode",
    ]
    for heading in required:
        assert heading in text, f"Missing section: {heading!r}"


def test_policy_editor_content_has_key_sections():
    """HELP_POLICY_EDITOR.md must contain required section headings."""
    text = _doc_text("HELP_POLICY_EDITOR.md")
    required = [
        "Включение Advanced Mode",
        "Параметры семплирования",
        "Запись трассировки промптов",
        "Типичные сценарии",
        "Частые ошибки",
    ]
    for heading in required:
        assert heading in text, f"Missing section: {heading!r}"


def test_prompt_audit_content_has_key_sections():
    """HELP_PROMPT_AUDIT.md must contain required section headings."""
    text = _doc_text("HELP_PROMPT_AUDIT.md")
    required = [
        "Что записывается в трейс",
        "Как включить запись трейсов",
        "Действия с трейсами",
        "Практические сценарии",
        "Частые вопросы",
        "Ограничения",
    ]
    for heading in required:
        assert heading in text, f"Missing section: {heading!r}"


# ---------------------------------------------------------------------------
# initial_tab navigation
# ---------------------------------------------------------------------------


def test_initial_tab_prompt_policy(qtbot):
    """initial_tab='Prompt Policy' must activate the correct tab."""
    w = HelpCenterDialog(initial_tab="Prompt Policy")
    qtbot.addWidget(w)
    idx = w._tab_names.index("Prompt Policy")
    assert w._tabs.currentIndex() == idx


def test_initial_tab_prompt_audit(qtbot):
    """initial_tab='Prompt Audit' must activate the correct tab."""
    w = HelpCenterDialog(initial_tab="Prompt Audit")
    qtbot.addWidget(w)
    idx = w._tab_names.index("Prompt Audit")
    assert w._tabs.currentIndex() == idx


# ---------------------------------------------------------------------------
# Docstring coverage
# ---------------------------------------------------------------------------


def test_show_help_center_dialog_docstring_lists_new_tabs():
    """show_help_center_dialog docstring must mention all three new tab labels."""
    doc = show_help_center_dialog.__doc__ or ""
    for label in ("Prompt Policy", "Policy Editor", "Prompt Audit"):
        assert label in doc, f"Tab label missing from docstring: {label!r}"
