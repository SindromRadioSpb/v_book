from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app.domain.dto import CoverageMetrics, LemmaCoverageRow, TermClusterCoverageRow
from app.ui.coverage_panel import CoveragePanel


def _panel_without_initial_load(monkeypatch, project_id=1):
    original = CoveragePanel.load_coverage
    monkeypatch.setattr(CoveragePanel, "load_coverage", lambda self: None)
    panel = CoveragePanel(project_id=project_id)
    monkeypatch.setattr(CoveragePanel, "load_coverage", original)
    return panel


def _seed_report_state(panel: CoveragePanel) -> None:
    partial = {
        "cluster_metrics": CoverageMetrics(total=10, covered=9, uncovered=1, coverage_pct=90.0),
        "untranslated_lemmas": [
            LemmaCoverageRow(lemma_id=1, lemma_text="alpha", pos="NOUN", freq_abs=20, doc_freq=3)
        ],
        "untranslated_clusters": [
            TermClusterCoverageRow(
                cluster_id=2,
                representative_he="beta",
                canonical_key="beta",
                freq_abs=12,
                doc_freq=2,
                termhood_score=1.5,
            )
        ],
    }
    panel._active_coverage_seq = 1
    panel.on_coverage_partial_results(partial, request_seq=1)
    panel.on_lemma_metrics_ready(
        CoverageMetrics(total=10, covered=4, uncovered=6, coverage_pct=40.0),
        request_seq=1,
    )


def test_coverage_panel_build_report_uses_current_panel_state(monkeypatch, qtbot):
    panel = _panel_without_initial_load(monkeypatch, project_id=77)
    qtbot.addWidget(panel)
    _seed_report_state(panel)

    text = panel._build_report_text()

    assert "# Coverage Report" in text
    assert "- Project ID: 77" in text
    assert "- Include Draft TM: no" in text
    assert "- Lemma Coverage: 40.0% (4 / 10, 6 untranslated)" in text
    assert "- Term Cluster Coverage: 90.0% (9 / 10, 1 untranslated)" in text
    assert "- alpha | POS=NOUN | freq=20 | doc_freq=3" in text
    assert "- beta | canonical=beta | termhood=1.500 | freq=12" in text


def test_coverage_panel_copy_report_updates_clipboard(monkeypatch, qtbot):
    panel = _panel_without_initial_load(monkeypatch, project_id=5)
    qtbot.addWidget(panel)
    _seed_report_state(panel)

    panel.copy_report_to_clipboard()

    assert "Coverage Report" in QApplication.instance().clipboard().text()
    assert panel.status_label.text() == "Coverage report copied to clipboard."


def test_coverage_panel_export_report_writes_file(monkeypatch, qtbot, tmp_path: Path):
    panel = _panel_without_initial_load(monkeypatch, project_id=9)
    qtbot.addWidget(panel)
    _seed_report_state(panel)

    export_path = tmp_path / "coverage_report.md"
    monkeypatch.setattr(
        "app.ui.coverage_panel.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "Markdown Files (*.md)"),
    )

    panel.export_report()

    assert export_path.exists()
    exported = export_path.read_text(encoding="utf-8")
    assert "Coverage Report" in exported
    assert "Project ID: 9" in exported
    assert panel.status_label.text() == f"Coverage report exported: {export_path}"


def test_coverage_panel_report_actions_enable_after_partial_results(monkeypatch, qtbot):
    panel = _panel_without_initial_load(monkeypatch, project_id=12)
    qtbot.addWidget(panel)

    assert panel.copy_report_btn.isEnabled() is False
    assert panel.export_report_btn.isEnabled() is False

    partial = {
        "cluster_metrics": CoverageMetrics(total=10, covered=9, uncovered=1, coverage_pct=90.0),
        "untranslated_lemmas": [],
        "untranslated_clusters": [],
    }
    panel._active_coverage_seq = 4
    panel.on_coverage_partial_results(partial, request_seq=4)

    assert panel.copy_report_btn.isEnabled() is True
    assert panel.export_report_btn.isEnabled() is True
