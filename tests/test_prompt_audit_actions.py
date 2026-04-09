"""PPS PATCH-11 — Prompt Audit Panel action tests.

Tests verify:
- [Copy Trace JSON] writes valid JSON to clipboard when a trace is selected.
- [Copy Trace JSON] shows QMessageBox.information when no trace is selected.
- [Export to File] writes a valid JSON file at the given path.
- [Export to File] shows QMessageBox.information when no trace is selected.
- [Compare with Previous] opens _CompareTracesDialog with >= 2 traces in history.
- [Compare with Previous] shows QMessageBox.information when < 2 traces available.
- _get_selected_trace() returns None when list is empty.
- _get_selected_trace() returns the trace object for the selected item.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from app.infra.translators.prompt_policy import ContentKind, EffectivePromptTrace
from app.ui.prompt_audit_dialog import PromptAuditPanel

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_trace(trace_id: str = "t1", policy_id: str = "sentence_ru") -> EffectivePromptTrace:
    return EffectivePromptTrace(
        trace_id=trace_id,
        policy_id=policy_id,
        policy_version="1.0.0",
        policy_hash="abc123",
        template_profile_id="hy_mt_standard_observed",
        sampling_profile_id="balanced",
        content_kind=ContentKind.SENTENCE,
        source_lang="he",
        target_lang="ru",
        model_id="tencent/HY-MT1.5-1.8B",
        model_quant_id=None,
        provider_id="local_hymt",
        source_text="שלום",
        source_text_hash=None,
        source_length_chars=4,
        rendered_role_instruction="You are a translator.",
        rendered_task_instruction="Translate.",
        rendered_output_policy="",
        rendered_glossary_block=None,
        rendered_context_block=None,
        rendered_formatting_note=None,
        rendered_user_payload="שלום",
        effective_prompt_preview="You are a translator.\nTranslate.\nשלום",
        glossary_hash=None,
        context_hash=None,
        applied_sampling={"temperature": 0.7},
        placeholder_tokens_protected=[],
        placeholder_tokens_restored=0,
        raw_model_output="Привет",
        translated_text="Привет",
        output_length_chars=6,
        output_tokens_generated=2,
        latency_ms=200,
        worker_latency_ms=180,
        glossary_applied=False,
        context_applied=False,
        fallback_triggered=False,
        fallback_reason=None,
        created_at=datetime(2026, 4, 8, 12, 0, 0, tzinfo=_UTC),
    )


@pytest.fixture(autouse=True)
def _clear_history():
    """Clear class-level history before and after every test."""
    PromptAuditPanel.clear_history()
    yield
    PromptAuditPanel.clear_history()


@pytest.fixture
def panel(qtbot):
    w = PromptAuditPanel()
    qtbot.addWidget(w)
    yield w


# ---------------------------------------------------------------------------
# _get_selected_trace
# ---------------------------------------------------------------------------


def test_get_selected_trace_empty_list(panel):
    """Returns None when no item is in the list."""
    assert panel._get_selected_trace() is None


def test_get_selected_trace_returns_trace_object(panel):
    """Returns the correct trace object for the selected list item."""
    trace = _make_trace()
    PromptAuditPanel.add_trace(trace)
    panel._refresh()
    panel._list.setCurrentRow(0)
    result = panel._get_selected_trace()
    assert result is trace


# ---------------------------------------------------------------------------
# [Copy Trace JSON]
# ---------------------------------------------------------------------------


def test_copy_trace_json_no_selection_shows_info(panel):
    """With no trace selected, clicking Copy shows an information dialog."""
    with patch("app.ui.prompt_audit_dialog.QMessageBox.information") as mock_info:
        panel._on_copy_trace_json()
        mock_info.assert_called_once()


def test_copy_trace_json_writes_valid_json_to_clipboard(panel, qtbot):
    """With a trace selected, Copy writes pretty JSON to the clipboard."""
    trace = _make_trace()
    PromptAuditPanel.add_trace(trace)
    panel._refresh()
    panel._list.setCurrentRow(0)

    captured: list[str] = []
    mock_clipboard = MagicMock()
    mock_clipboard.setText.side_effect = lambda t: captured.append(t)

    with patch("app.ui.prompt_audit_dialog.QApplication.clipboard", return_value=mock_clipboard):
        panel._on_copy_trace_json()

    assert len(captured) == 1
    parsed = json.loads(captured[0])
    assert parsed["trace_id"] == "t1"
    assert parsed["policy_id"] == "sentence_ru"
    assert isinstance(parsed["created_at"], str)


def test_copy_trace_json_clipboard_text_is_pretty_printed(panel):
    """Clipboard JSON must be indented (pretty-printed)."""
    trace = _make_trace()
    PromptAuditPanel.add_trace(trace)
    panel._refresh()
    panel._list.setCurrentRow(0)

    captured: list[str] = []
    mock_clipboard = MagicMock()
    mock_clipboard.setText.side_effect = lambda t: captured.append(t)

    with patch("app.ui.prompt_audit_dialog.QApplication.clipboard", return_value=mock_clipboard):
        panel._on_copy_trace_json()

    assert "\n" in captured[0], "Expected pretty-printed (multi-line) JSON"


# ---------------------------------------------------------------------------
# [Export to File]
# ---------------------------------------------------------------------------


def test_export_to_file_no_selection_shows_info(panel):
    """With no trace selected, clicking Export shows an information dialog."""
    with patch("app.ui.prompt_audit_dialog.QMessageBox.information") as mock_info:
        panel._on_export_to_file()
        mock_info.assert_called_once()


def test_export_to_file_cancelled_writes_nothing(panel):
    """If the user cancels the file dialog, no file is written."""
    trace = _make_trace()
    PromptAuditPanel.add_trace(trace)
    panel._refresh()
    panel._list.setCurrentRow(0)

    with patch(
        "app.ui.prompt_audit_dialog.QFileDialog.getSaveFileName",
        return_value=("", ""),
    ):
        panel._on_export_to_file()
    # Nothing to assert — just that it does not crash and no file appears


def test_export_to_file_writes_valid_json(panel, tmp_path):
    """Export writes a valid JSON file at the chosen path."""
    trace = _make_trace()
    PromptAuditPanel.add_trace(trace)
    panel._refresh()
    panel._list.setCurrentRow(0)

    out_file = str(tmp_path / "trace.json")
    with patch(
        "app.ui.prompt_audit_dialog.QFileDialog.getSaveFileName",
        return_value=(out_file, "JSON files (*.json)"),
    ):
        panel._on_export_to_file()

    assert os.path.exists(out_file)
    with open(out_file, encoding="utf-8") as fh:
        parsed = json.load(fh)
    assert parsed["trace_id"] == "t1"
    assert parsed["policy_id"] == "sentence_ru"


def test_export_to_file_json_is_pretty_printed(panel, tmp_path):
    """Exported file must contain indented JSON."""
    trace = _make_trace()
    PromptAuditPanel.add_trace(trace)
    panel._refresh()
    panel._list.setCurrentRow(0)

    out_file = str(tmp_path / "trace.json")
    with patch(
        "app.ui.prompt_audit_dialog.QFileDialog.getSaveFileName",
        return_value=(out_file, ""),
    ):
        panel._on_export_to_file()

    with open(out_file, encoding="utf-8") as fh:
        content = fh.read()
    assert "\n" in content, "Expected pretty-printed (multi-line) JSON"


# ---------------------------------------------------------------------------
# [Compare with Previous]
# ---------------------------------------------------------------------------


def test_compare_with_previous_fewer_than_2_shows_info(panel):
    """With 0 or 1 traces, Compare shows an information dialog."""
    with patch("app.ui.prompt_audit_dialog.QMessageBox.information") as mock_info:
        panel._on_compare_with_previous()
        mock_info.assert_called_once()


def test_compare_with_previous_1_trace_shows_info(panel):
    """With exactly 1 trace in history, Compare still shows information dialog."""
    PromptAuditPanel.add_trace(_make_trace("t1"))
    panel._refresh()
    with patch("app.ui.prompt_audit_dialog.QMessageBox.information") as mock_info:
        panel._on_compare_with_previous()
        mock_info.assert_called_once()


def test_compare_with_previous_opens_dialog(panel, qtbot):
    """With >= 2 traces, Compare opens _CompareTracesDialog."""
    PromptAuditPanel.add_trace(_make_trace("t1"))
    PromptAuditPanel.add_trace(_make_trace("t2", policy_id="sentence_ru_glossary"))
    panel._refresh()

    from app.ui.prompt_audit_dialog import _CompareTracesDialog

    with patch.object(_CompareTracesDialog, "exec", return_value=0) as mock_exec:
        panel._on_compare_with_previous()
        mock_exec.assert_called_once()


def test_compare_dialog_shows_both_traces(panel, qtbot):
    """CompareTracesDialog left pane = previous trace, right pane = current trace."""
    trace1 = _make_trace("t1", "sentence_ru")
    trace2 = _make_trace("t2", "sentence_ru_glossary")
    PromptAuditPanel.add_trace(trace1)
    PromptAuditPanel.add_trace(trace2)
    panel._refresh()

    from app.ui.prompt_audit_dialog import _CompareTracesDialog

    dlg = _CompareTracesDialog(trace1, trace2)
    qtbot.addWidget(dlg)

    left_text = dlg._left.toPlainText()
    right_text = dlg._right.toPlainText()

    left_parsed = json.loads(left_text)
    right_parsed = json.loads(right_text)

    assert left_parsed["trace_id"] == "t1"
    assert right_parsed["trace_id"] == "t2"
    assert right_parsed["policy_id"] == "sentence_ru_glossary"
