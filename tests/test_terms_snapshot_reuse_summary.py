from __future__ import annotations

from types import SimpleNamespace

from app.ui.terms_view import TermsView


class _FakeToggle:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = value


class _FakeProgressBar:
    def __init__(self):
        self.visible = None

    def setVisible(self, value):
        self.visible = value


class _FakeDialog:
    def __init__(self):
        self.completed = False
        self.accepted = False
        self.deleted = False

    def set_completed(self):
        self.completed = True

    def accept(self):
        self.accepted = True

    def reject(self):
        pass

    def deleteLater(self):
        self.deleted = True


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = value


def test_terms_view_formats_snapshot_reuse_summary() -> None:
    view = TermsView.__new__(TermsView)

    text = TermsView._format_extract_source_mix(
        view,
        SimpleNamespace(
            snapshot_rows_used=1200,
            reparsed_sentences=300,
            snapshot_reuse_pct=80.0,
        ),
    )

    assert "Snapshots used: 1,200" in text
    assert "Reparsed: 300" in text
    assert "Reuse: 80.00%" in text


def test_terms_view_sets_last_extract_source_mix_label() -> None:
    view = TermsView.__new__(TermsView)
    view.last_extract_source_mix_label = _FakeLabel()

    TermsView._set_last_extract_source_mix(
        view,
        SimpleNamespace(
            snapshot_rows_used=42,
            reparsed_sentences=8,
            snapshot_reuse_pct=84.0,
        ),
    )

    assert "Snapshots used: 42" in view.last_extract_source_mix_label.text
    assert "Reparsed: 8" in view.last_extract_source_mix_label.text
    assert "Reuse: 84.00%" in view.last_extract_source_mix_label.text


def test_terms_extract_finished_surfaces_snapshot_reuse_summary(monkeypatch) -> None:
    view = TermsView.__new__(TermsView)
    view.progress_bar = _FakeProgressBar()
    view.status_label = _FakeLabel()
    view.extract_btn = _FakeToggle()
    view.refresh_btn = _FakeToggle()
    view.extract_progress_dialog = _FakeDialog()
    view.extract_worker = SimpleNamespace(deleteLater=lambda: None)
    view.last_extract_source_mix_label = _FakeLabel()
    info_calls = []
    view.perform_search = lambda: None
    monkeypatch.setattr("app.ui.terms_view.show_info", lambda *args: info_calls.append(args))

    report = SimpleNamespace(
        success=True,
        cancelled=False,
        ngrams_extracted=12,
        np_chunks_extracted=3,
        clusters_created=4,
        snapshot_rows_used=30,
        reparsed_sentences=10,
        snapshot_reuse_pct=75.0,
    )

    TermsView.on_extract_finished(view, report)

    assert view.status_label.text == "Extraction complete"
    assert "Snapshots used: 30" in view.last_extract_source_mix_label.text
    assert info_calls
    assert "Reuse: 75.00%" in info_calls[0][2]
