"""Coverage panel staged first-usable-state tests."""

from app.domain.dto import CoverageMetrics, LemmaCoverageRow, TermClusterCoverageRow
from app.ui.coverage_panel import CoveragePanel
from app.ui.workers import CoverageWorker


def _panel_without_initial_load(monkeypatch, project_id=1):
    original = CoveragePanel.load_coverage
    monkeypatch.setattr(CoveragePanel, "load_coverage", lambda self: None)
    panel = CoveragePanel(project_id=project_id)
    monkeypatch.setattr(CoveragePanel, "load_coverage", original)
    return panel


def test_coverage_worker_emits_partial_before_lemma_metrics(monkeypatch):
    class _FakeSession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeDBService:
        def get_session(self):
            return _FakeSession()

    class _FakeCoverageService:
        def compute_termcluster_coverage(self, session, project_id, include_draft=False):
            return CoverageMetrics(total=10, covered=9, uncovered=1, coverage_pct=90.0)

        def list_untranslated_lemmas(
            self, session, project_id, limit=100, order_by="freq", include_draft=False
        ):
            return [
                LemmaCoverageRow(
                    lemma_id=1,
                    lemma_text="alpha",
                    pos="NOUN",
                    freq_abs=20,
                    doc_freq=3,
                )
            ]

        def list_untranslated_termclusters(
            self,
            session,
            project_id,
            limit=100,
            order_by="termhood",
            include_draft=False,
        ):
            return [
                TermClusterCoverageRow(
                    cluster_id=2,
                    representative_he="beta",
                    canonical_key="beta",
                    freq_abs=12,
                    doc_freq=2,
                    termhood_score=1.5,
                )
            ]

        def compute_lemma_coverage(self, session, project_id, include_draft=False):
            return CoverageMetrics(total=10, covered=4, uncovered=6, coverage_pct=40.0)

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance",
        lambda: _FakeDBService(),
    )
    monkeypatch.setattr(
        "app.services.coverage_service.CoverageService",
        lambda: _FakeCoverageService(),
    )

    worker = CoverageWorker(project_id=1)
    events = []
    worker.partial_ready.connect(
        lambda payload: events.append(
            (
                "partial",
                payload["cluster_metrics"].coverage_pct,
                len(payload["untranslated_lemmas"]),
                len(payload["untranslated_clusters"]),
            )
        )
    )
    worker.lemma_metrics_ready.connect(
        lambda metrics: events.append(("lemma", metrics.coverage_pct))
    )
    worker.results_ready.connect(
        lambda payload: events.append(("legacy", payload["lemma_metrics"].coverage_pct))
    )

    worker.run()

    assert events == [
        ("partial", 90.0, 1, 1),
        ("lemma", 40.0),
        ("legacy", 40.0),
    ]


def test_coverage_panel_request_seq_stages_partial_before_lemma(monkeypatch, qtbot):
    panel = _panel_without_initial_load(monkeypatch, project_id=77)
    qtbot.addWidget(panel)

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
    lemma_metrics = CoverageMetrics(total=10, covered=4, uncovered=6, coverage_pct=40.0)

    panel._active_coverage_seq = 2

    panel.on_coverage_partial_results(partial, request_seq=1)
    assert panel.cluster_pct_label.text() == "0%"
    assert panel.lemmas_table.rowCount() == 0
    assert panel.clusters_table.rowCount() == 0

    panel.on_coverage_partial_results(partial, request_seq=2)
    assert panel.cluster_pct_label.text() == "90.0%"
    assert panel.lemmas_table.rowCount() == 1
    assert panel.clusters_table.rowCount() == 1
    assert panel.lemma_pct_label.text() == "..."
    assert "counting lemma coverage" in panel.status_label.text().lower()

    panel.on_lemma_metrics_ready(lemma_metrics, request_seq=1)
    assert panel.lemma_pct_label.text() == "..."

    panel.on_lemma_metrics_ready(lemma_metrics, request_seq=2)
    assert panel.lemma_pct_label.text() == "40.0%"
    assert panel.lemma_detail_label.text() == "4 / 10 (6 untranslated)"
    assert panel.status_label.text() == "Ready"


def test_coverage_panel_queues_refresh_when_worker_active(monkeypatch, qtbot):
    panel = _panel_without_initial_load(monkeypatch, project_id=77)
    qtbot.addWidget(panel)

    class _BusyWorker:
        def __init__(self):
            self.cancel_called = False

        def isRunning(self):
            return True

        def cancel(self):
            self.cancel_called = True

    busy = _BusyWorker()
    panel.worker = busy

    CoveragePanel.load_coverage(panel)

    assert busy.cancel_called is True
    assert panel._coverage_retry_pending is True
    assert panel.status_label.text() == "Coverage refresh queued..."
