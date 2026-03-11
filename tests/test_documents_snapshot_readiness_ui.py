from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from app.domain.dto import SnapshotReadinessSummaryDTO
from app.ui.documents_view import DocumentsView
from app.ui.widgets.snapshot_readiness_panel import SnapshotReadinessPanel


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = value


class _FakePanel:
    def __init__(self):
        self.loading = []
        self.summary = None
        self.error = None

    def set_loading(self, message):
        self.loading.append(message)

    def set_summary(self, summary):
        self.summary = summary

    def set_error(self, message):
        self.error = message


def _sample_summary() -> SnapshotReadinessSummaryDTO:
    return SnapshotReadinessSummaryDTO(
        project_id=5,
        project_name="Test project",
        is_general_corpus=True,
        is_reference_project=False,
        processed_docs=120000,
        fully_covered_docs=50000,
        zero_snapshot_docs=60000,
        partial_snapshot_docs=10000,
        remaining_uncovered_docs=70000,
        sentence_count_total=300000,
        snapshot_count_total=150000,
        sentence_coverage_pct=50.0,
        doc_coverage_pct=41.6667,
        latest_backfill_run_id=387620,
        latest_backfill_status="ok",
        latest_backfill_stage="completed",
        latest_backfill_last_doc_id=120000,
        latest_backfill_finished_at="2026-03-11T10:00:00.000000Z",
        latest_backfill_docs_processed=70000,
        latest_backfill_docs_total=70000,
        contract_state="bounded_validated",
        contract_note="Bounded staged validation exists for this workflow. Full-scale validation remains deferred.",
        summary_note="Observational only. This panel does not approve production rollout or start backfill.",
        last_refreshed_at="2026-03-11T10:05:00.000000Z",
    )


def test_snapshot_readiness_panel_preserves_last_known_data_while_refreshing(qtbot):
    panel = SnapshotReadinessPanel()
    qtbot.addWidget(panel)

    summary = _sample_summary()
    panel.set_summary(summary)

    assert panel.doc_coverage_value.text() == "41.67%"
    assert panel.sentence_coverage_value.text() == "50.00%"
    assert "Run #387620" in panel.meta_label.text()

    panel.set_loading("Refreshing snapshot readiness...")

    assert panel.doc_coverage_value.text() == "41.67%"
    assert panel.sentence_coverage_value.text() == "50.00%"
    assert panel.status_label.text() == "Refreshing snapshot readiness..."


def test_snapshot_readiness_panel_renders_bounded_validation_summary(qtbot):
    panel = SnapshotReadinessPanel()
    qtbot.addWidget(panel)

    panel.set_summary(_sample_summary())

    assert panel.badge_label.text() == "Bounded validated"
    assert panel.subtitle_label.text() == "Full-scale validation deferred"
    assert panel.fully_covered_value.text() == "50,000 / 120,000"
    assert panel.remaining_value.text() == "70,000"
    assert "Observational only" in panel.note_label.text()


def test_documents_view_snapshot_readiness_ignores_stale_requests():
    view = DocumentsView.__new__(DocumentsView)
    view.snapshot_readiness_panel = _FakePanel()
    view._active_snapshot_request_id = 4

    stale_summary = _sample_summary()
    DocumentsView.on_snapshot_readiness_loaded(view, 3, stale_summary)
    assert view.snapshot_readiness_panel.summary is None

    DocumentsView.on_snapshot_readiness_loaded(view, 4, stale_summary)
    assert view.snapshot_readiness_panel.summary is stale_summary


def test_documents_view_copy_snapshot_coverage_cli_uses_safe_command(qtbot):
    view = DocumentsView.__new__(DocumentsView)
    view.project_id = 5
    view.status_label = _FakeLabel()
    view.db_service = SimpleNamespace(
        db_manager=SimpleNamespace(
            db_path=Path(r"J:\Project_Vibe\V_book\ref_corpora\hewiki test.db")
        )
    )

    app = QApplication.instance()
    assert app is not None

    DocumentsView._copy_snapshot_coverage_cli(view)

    text = app.clipboard().text()
    assert "--coverage-only" in text
    assert "--backfill-snapshots" in text
    assert '--project-id 5' in text
    assert "hewiki test.db" in text
    assert view.status_label.text == "Coverage CLI copied to clipboard."
