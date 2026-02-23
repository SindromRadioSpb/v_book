"""Tests for AudioPlayerPanel._refresh_display_contexts() (PATCH-04i)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication(sys.argv)


def _make_panel(qapp):
    """Create a minimal AudioPlayerPanel without a real backend or DB."""
    from app.services.audio_player_service import AudioPlayerService
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    AudioPlayerService.reset_instance_for_tests()
    settings_mock = MagicMock()
    settings_mock.get_int.return_value = 0
    settings_mock.get_string.return_value = "1.0"
    settings_mock.get_bool.return_value = False

    with patch.object(AudioPlayerService, "_build_default_backend", return_value=None):
        panel = AudioPlayerPanel.__new__(AudioPlayerPanel)
        # Minimal attribute initialisation (avoid full __init__ which needs Qt event loop running)
        from app.services.audio_player_service import AudioPlayerService as _APS
        panel.player = _APS(settings=settings_mock)

    return panel


def _make_track(kind: str, source_id: int, hebrew: str = "", source_label: str = "",
                project_id: int = 1) -> object:
    """Create a minimal AudioTrack-like namespace for testing."""
    from app.services.audio_player_service import AudioTrack
    ctx = {
        "kind": kind,
        "source_id": source_id,
        "snapshot_hebrew": hebrew,
        "snapshot_source_label": source_label,
        "snapshot_niqqud": None,
        "snapshot_translation": None,
        "project_id": project_id,
    }
    return AudioTrack(path=Path(""), label=hebrew, context=ctx)


# ---------------------------------------------------------------------------
# _refresh_term_display — pure label update, no DB needed
# ---------------------------------------------------------------------------


def test_refresh_term_display_updates_source_label(qapp):
    """_refresh_term_display sets source_label to 'Terms' and returns updated count."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    t = _make_track("term", 5, "שלום", source_label="term:5")
    panel.player._tracks = [t]

    count = panel._refresh_term_display(MagicMock(), [t])

    assert count == 1
    assert t.context["snapshot_source_label"] == "Terms"


def test_refresh_term_display_no_change_if_already_terms(qapp):
    """_refresh_term_display returns 0 when label is already 'Terms'."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    t = _make_track("term", 5, "שלום", source_label="Terms")
    panel.player._tracks = [t]

    count = panel._refresh_term_display(MagicMock(), [t])

    assert count == 0


def test_refresh_term_display_populates_niqqud_and_translation(qapp):
    """_refresh_term_display enriches term rows with niqqud + TM translation."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    t = _make_track("term", 5, "שלום עולם", source_label="term:5", project_id=7)
    panel.player._tracks = [t]
    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = [("shalom_olam", "peace world")]

    def fake_ntm(lang, text, kind):
        r = MagicMock()
        r.norm = "shalom_olam"
        return r

    mock_niqqud_dto = MagicMock()
    mock_niqqud_dto.niqqud_text = "שָׁלוֹם עוֹלָם"
    mock_pron_svc = MagicMock()
    mock_pron_svc.return_value.bulk_lookup.return_value = {"shalom_olam": mock_niqqud_dto}

    with patch("app.domain.normalization.normalizer.normalize_for_tm", side_effect=fake_ntm), \
         patch("app.services.pronunciation_service.PronunciationService", mock_pron_svc):
        count = panel._refresh_term_display(mock_session, [t])

    assert count >= 1
    assert t.context["snapshot_source_label"] == "Terms"
    assert t.context["snapshot_niqqud"] == "שָׁלוֹם עוֹלָם"
    assert t.context["snapshot_translation"] == "peace world"


def test_refresh_term_display_empty_list(qapp):
    """_refresh_term_display with empty list returns 0 without error."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    panel.player._tracks = []

    count = panel._refresh_term_display(MagicMock(), [])

    assert count == 0


# ---------------------------------------------------------------------------
# _refresh_lemma_display — label + niqqud + translation
# ---------------------------------------------------------------------------


def test_refresh_lemma_display_updates_source_label(qapp):
    """_refresh_lemma_display sets source_label to 'Dictionary'."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    t = _make_track("lemma", 10, "שלום", source_label="lemma:10")
    panel.player._tracks = [t]

    mock_session = MagicMock()

    def fake_ntm(lang, text, kind):
        r = MagicMock()
        r.norm = "shalom"
        return r

    mock_pron_svc = MagicMock()
    mock_pron_svc.return_value.bulk_lookup.return_value = {}

    mock_session.execute.return_value.all.return_value = []

    with patch("app.domain.normalization.normalizer.normalize_for_tm", side_effect=fake_ntm), \
         patch("app.services.pronunciation_service.PronunciationService", mock_pron_svc):
        count = panel._refresh_lemma_display(mock_session, [t])

    assert count >= 1
    assert t.context["snapshot_source_label"] == "Dictionary"


def test_refresh_lemma_display_populates_niqqud(qapp):
    """_refresh_lemma_display fills snapshot_niqqud when PronunciationService has it."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    t = _make_track("lemma", 10, "שלום", source_label="Dictionary")
    panel.player._tracks = [t]

    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = []

    def fake_ntm(lang, text, kind):
        r = MagicMock()
        r.norm = "shalom"
        return r

    mock_niqqud_dto = MagicMock()
    mock_niqqud_dto.niqqud_text = "שָׁלוֹם"

    mock_pron_svc = MagicMock()
    mock_pron_svc.return_value.bulk_lookup.return_value = {"shalom": mock_niqqud_dto}

    with patch("app.domain.normalization.normalizer.normalize_for_tm", side_effect=fake_ntm), \
         patch("app.services.pronunciation_service.PronunciationService", mock_pron_svc):
        panel._refresh_lemma_display(mock_session, [t])

    assert t.context["snapshot_niqqud"] == "שָׁלוֹם"


# ---------------------------------------------------------------------------
# _refresh_display_contexts — top-level non-fatal contract
# ---------------------------------------------------------------------------


def test_refresh_display_contexts_nonfatal_on_db_error(qapp):
    """_refresh_display_contexts silently ignores DB errors."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    t = _make_track("sentence", 1, "שלום", "sentence:1")
    panel.player._tracks = [t]

    with patch("app.services.db_service.DBService.get_instance", side_effect=RuntimeError("DB down")):
        panel._refresh_display_contexts()  # must not raise

    # Track should be unchanged
    assert t.context["snapshot_source_label"] == "sentence:1"


def test_refresh_display_contexts_empty_queue_is_noop(qapp):
    """_refresh_display_contexts returns immediately with no tracks."""
    from app.ui.widgets.audio_player_panel import AudioPlayerPanel

    panel = _make_panel(qapp)
    panel.player._tracks = []

    # Should not raise or make any DB calls
    with patch("app.services.db_service.DBService.get_instance") as mock_db:
        panel._refresh_display_contexts()
        mock_db.assert_not_called()
