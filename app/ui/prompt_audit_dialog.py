"""Prompt Audit Dialog — PPS PATCH-05 Debug UI.

Provides a colour-coded display of EffectivePromptTrace records, enabling
developers and advanced users to inspect how each translation was constructed:
which semantic layers were rendered, what sampling parameters were applied,
and how placeholders + glossary terms were handled.

Architecture:
- ``PromptAuditDialog``: standalone QDialog, wraps ``PromptAuditPanel``.
- ``PromptAuditPanel``: embeddable QWidget; class-level trace history (deque, maxlen=100).
- ``add_trace(trace)``: classmethod — thread-safe append; oldest entry evicted at cap.
- ``get_history()``: classmethod — snapshot of current history.
- ``clear_history()``: classmethod — wipe all stored traces.

History cap: 100 entries (oldest evicted deterministically on overflow).

Usage::

    # After a translation with trace_id set:
    result = provider.translate(request_with_trace_id)
    trace = result.meta["prompt_policy"]["trace"]
    if trace is not None:
        PromptAuditPanel.add_trace(trace)

    # Open the dialog:
    dialog = PromptAuditDialog(parent=main_window)
    dialog.exec()

Layer colour legend:
    Layer 1 (role instruction)  — #3B82F6 (blue)
    Layer 2 (task instruction)  — #22C55E (green)
    Layer 3 (output policy)     — #F97316 (orange)
    Layer 4a (glossary block)   — #A855F7 (purple)
    Layer 4b (context block)    — #14B8A6 (teal)
    Layer 5 (user payload)      — #1E293B (dark, bold)
    Metadata / empty            — #64748B (gray)
"""

from __future__ import annotations

import html
import json
import logging
from collections import deque
from datetime import datetime
from typing import Any, ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_logger = logging.getLogger(__name__)

# EffectivePromptTrace is imported lazily inside methods to avoid hard UI dep
# on the prompt_policy module at class definition time.

# ---------------------------------------------------------------------------
# Colour palette for semantic layers
# ---------------------------------------------------------------------------

_LAYER_COLOURS: dict[str, str] = {
    "role": "#3B82F6",  # Layer 1 — blue
    "task": "#22C55E",  # Layer 2 — green
    "output_policy": "#F97316",  # Layer 3 — orange
    "glossary": "#A855F7",  # Layer 4a — purple
    "context": "#14B8A6",  # Layer 4b — teal
    "payload": "#1E293B",  # Layer 5 — dark
    "meta": "#64748B",  # metadata — gray
}

# Max entries kept in history
_HISTORY_MAXLEN: int = 100


def _e(text: str) -> str:
    """HTML-escape a string for safe insertion into QTextBrowser HTML."""
    return html.escape(str(text), quote=True)


def _layer_html(label: str, colour: str, content: str) -> str:
    """Return an HTML block for one semantic layer."""
    if not content:
        return (
            f'<div style="margin:4px 0">'
            f'<span style="color:{colour};font-weight:bold">[{_e(label)}]</span> '
            f'<span style="color:#94A3B8;font-style:italic">(empty)</span>'
            f"</div>"
        )
    safe = _e(content).replace("\n", "<br>")
    return (
        f'<div style="margin:6px 0;border-left:3px solid {colour};padding-left:8px">'
        f'<div style="color:{colour};font-weight:bold;margin-bottom:2px">[{_e(label)}]</div>'
        f'<div style="color:#1E293B;font-family:monospace;font-size:11px">{safe}</div>'
        f"</div>"
    )


def _build_layers_html(trace: object) -> str:  # type: ignore[type-arg]
    """Render all semantic layers of a trace into colour-coded HTML."""
    c = _LAYER_COLOURS
    parts: list[str] = [
        '<div style="font-family:sans-serif;font-size:12px;padding:8px">',
        "<h3 style='margin:0 0 8px 0'>Semantic Layers (1–5)</h3>",
    ]
    parts.append(
        _layer_html(
            "Layer 1 — Role Instruction",
            c["role"],
            getattr(trace, "rendered_role_instruction", "") or "",
        )
    )
    parts.append(
        _layer_html(
            "Layer 2 — Task Instruction",
            c["task"],
            getattr(trace, "rendered_task_instruction", "") or "",
        )
    )
    parts.append(
        _layer_html(
            "Layer 3 — Output Policy",
            c["output_policy"],
            getattr(trace, "rendered_output_policy", "") or "",
        )
    )
    parts.append(
        _layer_html(
            "Layer 4a — Glossary Block",
            c["glossary"],
            getattr(trace, "rendered_glossary_block", None) or "",
        )
    )
    parts.append(
        _layer_html(
            "Layer 4b — Context Block",
            c["context"],
            getattr(trace, "rendered_context_block", None) or "",
        )
    )
    parts.append(
        _layer_html(
            "Layer 4c — Formatting Note",
            c["context"],
            getattr(trace, "rendered_formatting_note", None) or "",
        )
    )
    parts.append(
        _layer_html(
            "Layer 5 — User Payload (protected source)",
            c["payload"],
            getattr(trace, "rendered_user_payload", "") or "",
        )
    )
    parts.append("</div>")
    return "".join(parts)


def _build_meta_html(trace: object) -> str:  # type: ignore[type-arg]
    """Render policy + performance metadata into HTML."""
    c = _LAYER_COLOURS["meta"]

    def row(key: str, val: object) -> str:
        safe_val = _e(str(val)) if val is not None else '<em style="color:#94A3B8">None</em>'
        return (
            f"<tr>"
            f'<td style="color:{c};padding:2px 8px 2px 0;white-space:nowrap">'
            f"<b>{_e(key)}</b></td>"
            f'<td style="font-family:monospace;font-size:11px">{safe_val}</td>'
            f"</tr>"
        )

    applied = getattr(trace, "applied_sampling", {}) or {}
    applied_str = ", ".join(f"{k}={v}" for k, v in sorted(applied.items()))

    ph_protected = getattr(trace, "placeholder_tokens_protected", []) or []
    ph_restored = getattr(trace, "placeholder_tokens_restored", 0)

    rows: list[str] = [
        row("trace_id", getattr(trace, "trace_id", None)),
        row("policy_id", getattr(trace, "policy_id", None)),
        row("policy_version", getattr(trace, "policy_version", None)),
        row("template_profile_id", getattr(trace, "template_profile_id", None)),
        row("sampling_profile_id", getattr(trace, "sampling_profile_id", None)),
        row("content_kind", getattr(trace, "content_kind", None)),
        row("terminology_mode", getattr(trace, "terminology_mode", None))
        if hasattr(trace, "terminology_mode")
        else "",
        row("source_lang", getattr(trace, "source_lang", None)),
        row("target_lang", getattr(trace, "target_lang", None)),
        row("model_id", getattr(trace, "model_id", None)),
        row("model_quant_id", getattr(trace, "model_quant_id", None)),
        row("provider_id", getattr(trace, "provider_id", None)),
        row("source_length_chars", getattr(trace, "source_length_chars", None)),
        row("applied_sampling", applied_str or "(none)"),
        row("placeholder_tokens_protected", ", ".join(ph_protected) or "(none)"),
        row("placeholder_tokens_restored", ph_restored),
        row("glossary_applied", getattr(trace, "glossary_applied", None)),
        row("context_applied", getattr(trace, "context_applied", None)),
        row("fallback_triggered", getattr(trace, "fallback_triggered", None)),
        row("fallback_reason", getattr(trace, "fallback_reason", None)),
        row("latency_ms", getattr(trace, "latency_ms", None)),
        row("worker_latency_ms", getattr(trace, "worker_latency_ms", None)),
        row("output_length_chars", getattr(trace, "output_length_chars", None)),
        row("created_at", getattr(trace, "created_at", None)),
    ]
    return (
        '<div style="font-family:sans-serif;font-size:12px;padding:8px">'
        "<h3 style='margin:0 0 8px 0'>Policy & Performance Metadata</h3>"
        "<table cellspacing='0' cellpadding='0'>"
        + "".join(rows)
        + "</table></div>"
    )


def _build_output_html(trace: object) -> str:  # type: ignore[type-arg]
    """Render raw vs final output comparison HTML."""
    raw = getattr(trace, "raw_model_output", "") or ""
    final = getattr(trace, "translated_text", "") or ""
    source = getattr(trace, "source_text", "") or ""

    def box(title: str, colour: str, content: str) -> str:
        safe = _e(content).replace("\n", "<br>")
        return (
            f'<div style="margin-bottom:12px">'
            f'<div style="color:{colour};font-weight:bold;margin-bottom:4px">{_e(title)}</div>'
            f'<div style="border:1px solid #E2E8F0;border-radius:4px;padding:8px;'
            f'font-family:monospace;font-size:12px;background:#F8FAFC">{safe}</div>'
            f"</div>"
        )

    return (
        '<div style="font-family:sans-serif;font-size:12px;padding:8px">'
        "<h3 style='margin:0 0 8px 0'>Input / Output</h3>"
        + box("Source Text", _LAYER_COLOURS["meta"], source)
        + box("Raw Model Output (before postprocess)", _LAYER_COLOURS["glossary"], raw)
        + box("Final Translation (after restore + glossary)", _LAYER_COLOURS["task"], final)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# PromptAuditPanel — embeddable widget with class-level trace history
# ---------------------------------------------------------------------------


class PromptAuditPanel(QWidget):
    """Embeddable trace history + detail panel.

    Class-level state:
        _history: deque[EffectivePromptTrace] — shared across all instances,
            maxlen=100.  Oldest entry evicted when cap is reached.
    """

    _history: ClassVar[deque] = deque(maxlen=_HISTORY_MAXLEN)

    # ------------------------------------------------------------------
    # Class-level history API (no widget required)
    # ------------------------------------------------------------------

    @classmethod
    def add_trace(cls, trace: object) -> None:
        """Append a trace to the history.

        Thread-safe for append (CPython GIL).  History is capped at 100.

        Args:
            trace: An ``EffectivePromptTrace`` instance.
        """
        cls._history.append(trace)

    @classmethod
    def get_history(cls) -> list:
        """Return a snapshot of the current trace history (oldest first)."""
        return list(cls._history)

    @classmethod
    def clear_history(cls) -> None:
        """Clear all stored traces."""
        cls._history.clear()

    # ------------------------------------------------------------------
    # Widget
    # ------------------------------------------------------------------

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header + controls
        header = QHBoxLayout()
        title = QLabel(
            "<b>Prompt Audit History</b> "
            '<span style="color:#64748B;font-size:11px">'
            f"(cap: {_HISTORY_MAXLEN} entries)</span>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Reload history from latest traces")
        refresh_btn.clicked.connect(self._refresh)
        header.addWidget(refresh_btn)
        clear_btn = QPushButton("Clear History")
        clear_btn.setToolTip("Remove all stored traces")
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)

        self._copy_btn = QPushButton("Copy Trace JSON")
        self._copy_btn.setToolTip("Copy selected trace as JSON to clipboard")
        self._copy_btn.clicked.connect(self._on_copy_trace_json)
        header.addWidget(self._copy_btn)

        self._export_btn = QPushButton("Export to File")
        self._export_btn.setToolTip("Save selected trace JSON to a file")
        self._export_btn.clicked.connect(self._on_export_to_file)
        header.addWidget(self._export_btn)

        self._compare_btn = QPushButton("Compare with Previous")
        self._compare_btn.setToolTip(
            "Side-by-side diff of the two most recent traces (requires ≥ 2 traces)"
        )
        self._compare_btn.clicked.connect(self._on_compare_with_previous)
        header.addWidget(self._compare_btn)

        layout.addLayout(header)

        # Help text
        help_label = QLabel(
            "Traces are recorded when a translation request carries a non-empty "
            "<code>trace_id</code>. Set <code>trace_id</code> on the "
            "<code>TranslationRequest</code> to enable debug recording."
        )
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        help_label.setStyleSheet("color: #64748B; font-size: 11px; margin-bottom: 4px;")
        layout.addWidget(help_label)

        # Splitter: history list | detail tabs
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # History list (left)
        self._list = QListWidget()
        self._list.setMinimumWidth(200)
        self._list.setMaximumWidth(300)
        self._list.currentRowChanged.connect(self._on_row_changed)
        splitter.addWidget(self._list)

        # Detail panel (right)
        self._tabs = QTabWidget()

        self._layers_view = QTextBrowser()
        self._layers_view.setOpenLinks(False)
        self._tabs.addTab(self._layers_view, "Layers")

        self._meta_view = QTextBrowser()
        self._meta_view.setOpenLinks(False)
        self._tabs.addTab(self._meta_view, "Metadata")

        self._output_view = QTextBrowser()
        self._output_view.setOpenLinks(False)
        self._tabs.addTab(self._output_view, "Output")

        splitter.addWidget(self._tabs)
        splitter.setSizes([220, 580])
        layout.addWidget(splitter)

        self._refresh()

    def _refresh(self) -> None:
        """Reload history list from class-level deque."""
        current_row = self._list.currentRow()
        self._list.clear()
        history = self.get_history()
        for trace in history:
            policy_id = getattr(trace, "policy_id", "?")
            ts = getattr(trace, "created_at", None)
            ts_str = ts.strftime("%H:%M:%S") if isinstance(ts, datetime) else "?"
            item = QListWidgetItem(f"{ts_str}  {policy_id}")
            item.setData(Qt.ItemDataRole.UserRole, trace)
            self._list.addItem(item)
        # Restore selection
        if 0 <= current_row < self._list.count():
            self._list.setCurrentRow(current_row)
        elif self._list.count() > 0:
            self._list.setCurrentRow(self._list.count() - 1)
        else:
            self._clear_detail()

    def _clear(self) -> None:
        self.clear_history()
        self._refresh()

    def _clear_detail(self) -> None:
        self._layers_view.setHtml("")
        self._meta_view.setHtml("")
        self._output_view.setHtml("")

    def _on_row_changed(self, row: int) -> None:
        item = self._list.item(row)
        if item is None:
            self._clear_detail()
            return
        trace = item.data(Qt.ItemDataRole.UserRole)
        if trace is None:
            self._clear_detail()
            return
        self._layers_view.setHtml(_build_layers_html(trace))
        self._meta_view.setHtml(_build_meta_html(trace))
        self._output_view.setHtml(_build_output_html(trace))

    # ------------------------------------------------------------------
    # Action slots — Copy / Export / Compare
    # ------------------------------------------------------------------

    def _get_selected_trace(self) -> Any | None:
        """Return the trace object for the currently selected list row, or None."""
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_copy_trace_json(self) -> None:
        """Copy selected trace to clipboard as pretty-printed JSON."""
        trace = self._get_selected_trace()
        if trace is None:
            QMessageBox.information(self, "No Selection", "Select a trace entry first.")
            return
        if not hasattr(trace, "to_dict"):
            QMessageBox.warning(self, "Unsupported", "This trace cannot be serialised.")
            return
        try:
            payload = json.dumps(trace.to_dict(), indent=2, ensure_ascii=False)
        except Exception as exc:
            _logger.error("trace_to_dict_failed: %s", exc)
            QMessageBox.critical(self, "Serialisation Error", str(exc))
            return
        clipboard: QClipboard = QApplication.clipboard()
        clipboard.setText(payload)

    def _on_export_to_file(self) -> None:
        """Export selected trace JSON to a user-chosen file."""
        trace = self._get_selected_trace()
        if trace is None:
            QMessageBox.information(self, "No Selection", "Select a trace entry first.")
            return
        if not hasattr(trace, "to_dict"):
            QMessageBox.warning(self, "Unsupported", "This trace cannot be serialised.")
            return
        try:
            payload = json.dumps(trace.to_dict(), indent=2, ensure_ascii=False)
        except Exception as exc:
            _logger.error("trace_export_serialise_failed: %s", exc)
            QMessageBox.critical(self, "Serialisation Error", str(exc))
            return
        ts = getattr(trace, "created_at", None)
        ts_str = ts.strftime("%Y%m%d_%H%M%S") if isinstance(ts, datetime) else "trace"
        policy_id = getattr(trace, "policy_id", "unknown")
        default_name = f"trace_{policy_id}_{ts_str}.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Trace JSON",
            default_name,
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError as exc:
            _logger.error("trace_export_write_failed path=%s: %s", path, exc)
            QMessageBox.critical(self, "Write Error", str(exc))

    def _on_compare_with_previous(self) -> None:
        """Open a side-by-side compare dialog for the two most recent traces."""
        history = self.get_history()
        if len(history) < 2:
            QMessageBox.information(
                self,
                "Not Enough Traces",
                "At least 2 traces are required for comparison.\n"
                "Run two translations with trace_id set.",
            )
            return
        prev, current = history[-2], history[-1]
        dlg = _CompareTracesDialog(prev, current, parent=self)
        dlg.exec()


# ---------------------------------------------------------------------------
# _CompareTracesDialog — side-by-side JSON diff of two traces
# ---------------------------------------------------------------------------


class _CompareTracesDialog(QDialog):
    """Side-by-side display of two EffectivePromptTrace records.

    Shows pretty-printed JSON of ``prev`` (left) and ``current`` (right)
    in two read-only QTextEdit panels.  Used internally by PromptAuditPanel.
    """

    def __init__(
        self,
        prev: Any,
        current: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare Traces — Previous vs Current")
        self.setMinimumSize(1000, 600)
        self.resize(1200, 700)

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._left = QTextEdit()
        self._left.setReadOnly(True)
        self._left.setFontFamily("Courier New")
        self._left.setFontPointSize(10)

        self._right = QTextEdit()
        self._right.setReadOnly(True)
        self._right.setFontFamily("Courier New")
        self._right.setFontPointSize(10)

        splitter.addWidget(self._left)
        splitter.addWidget(self._right)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._left.setPlainText(self._serialise(prev, "Previous"))
        self._right.setPlainText(self._serialise(current, "Current"))

    @staticmethod
    def _serialise(trace: Any, label: str) -> str:
        """Return pretty JSON for a trace, or an error message."""
        if not hasattr(trace, "to_dict"):
            return f"# {label}\n# (trace cannot be serialised — missing to_dict)"
        try:
            return json.dumps(trace.to_dict(), indent=2, ensure_ascii=False)
        except Exception as exc:
            return f"# {label}\n# Serialisation error: {exc}"


# ---------------------------------------------------------------------------
# PromptAuditDialog — standalone dialog wrapper
# ---------------------------------------------------------------------------


class PromptAuditDialog(QDialog):
    """Standalone dialog that wraps ``PromptAuditPanel``.

    Open from provider settings or any menu entry:

        dialog = PromptAuditDialog(parent=self)
        dialog.exec()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Prompt Audit — PPS Debug Mode")
        self.setMinimumSize(900, 600)
        self.resize(1000, 650)

        layout = QVBoxLayout(self)
        self._panel = PromptAuditPanel()
        layout.addWidget(self._panel)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # Delegate class-level history API for convenience
    @classmethod
    def add_trace(cls, trace: object) -> None:
        """Add a trace to the shared history (delegates to PromptAuditPanel)."""
        PromptAuditPanel.add_trace(trace)

    @classmethod
    def get_history(cls) -> list:
        """Return snapshot of trace history (delegates to PromptAuditPanel)."""
        return PromptAuditPanel.get_history()

    @classmethod
    def clear_history(cls) -> None:
        """Clear trace history (delegates to PromptAuditPanel)."""
        PromptAuditPanel.clear_history()
