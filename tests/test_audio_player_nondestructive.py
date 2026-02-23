from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.audio_player_service import AudioPlayerService, AudioTrack


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    return app


def _make_service(qapp):
    AudioPlayerService.reset_instance_for_tests()
    settings_mock = MagicMock()
    settings_mock.get_int.return_value = 0
    settings_mock.get_string.return_value = "1.0"
    settings_mock.get_bool.return_value = False
    with patch.object(AudioPlayerService, "_build_default_backend", return_value=None):
        svc = AudioPlayerService(settings=settings_mock)
    return svc


@pytest.fixture
def service(qapp, tmp_path):
    svc = _make_service(qapp)
    yield svc
    AudioPlayerService.reset_instance_for_tests()


@pytest.fixture
def tmp_audio(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"track_{i}.wav"
        p.write_bytes(b"RIFF")
        paths.append(p)
    return paths


def _inject_tracks(svc, paths):
    svc._tracks = [AudioTrack(path=p, label=p.stem) for p in paths]
    svc._current_index = -1


# -- 1. all 3 tracks stay after advancing cursor --------------------------


def test_play_paths_nondestructive(service, tmp_audio):
    n = service.play_paths(tmp_audio[:3])
    assert n == 3
    assert len(service._tracks) == 3


# -- 2. items stay after advancing _current_index -------------------------


def test_items_stay_after_next_track(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    # Advance cursor 3 times (simulate next without actually calling backend)
    for _ in range(3):
        service._current_index = min(service._current_index + 1, 2)
    assert len(service._tracks) == 3


# -- 3. queue_snapshot returns all tracks ----------------------------------


def test_queue_snapshot_returns_all(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 1
    snap = service.queue_snapshot()
    assert len(snap) == 3


# -- 4. clear_queue empties tracks ----------------------------------------


def test_clear_queue_empties_tracks(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service.clear_queue()
    assert service._tracks == []
    assert service._current_index == -1


# -- 5. remove before current shifts cursor left --------------------------


def test_remove_queue_index_adjusts_cursor(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 2
    result = service.remove_queue_index(0)
    assert result is True
    assert len(service._tracks) == 2
    assert service._current_index == 1


# -- 6. remove current stops and backs cursor up --------------------------


def test_remove_current_item_stops(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 1
    service._current = service._tracks[1]
    result = service.remove_queue_index(1)
    assert result is True
    assert service._current is None
    # Cursor backed up: was 1, now 0
    assert service._current_index == 0


# -- 7. interrupt mode replaces queue -------------------------------------


def test_interrupt_mode_replaces_queue(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:2])
    n = service.play_paths(tmp_audio[2:4], play_mode="interrupt")
    assert n == 2
    assert len(service._tracks) == 2
    assert all("track_2" in str(t.path) or "track_3" in str(t.path) for t in service._tracks)


# -- 8. enqueue mode appends ----------------------------------------------


def test_enqueue_mode_appends(service, tmp_audio):
    _inject_tracks(service, tmp_audio[:2])
    # Pretend something is playing so enqueue does not auto-start
    service._current = service._tracks[0]
    n = service.play_paths(tmp_audio[2:4], play_mode="enqueue")
    assert n == 2
    assert len(service._tracks) == 4


def test_enqueue_start_immediately_plays_newly_added_item(service, tmp_audio):
    """enqueue + start_immediately plays newly appended item, not next old queue row."""
    _inject_tracks(service, tmp_audio[:3])
    service._current = service._tracks[0]
    service._current_index = 0

    with patch.object(service, "_begin_play_current") as begin_mock:
        n = service.play_paths(
            [tmp_audio[3]],
            labels=["clicked"],
            play_mode="enqueue",
            contexts=[{"kind": "term", "source_id": 999}],
            start_immediately=True,
        )

    assert n == 1
    assert len(service._tracks) == 4
    assert service._current_index == 3
    assert service._current is service._tracks[3]
    begin_mock.assert_called_once()


def test_enqueue_start_immediately_reuses_existing_source_track_without_duplicate(service, tmp_audio):
    """Single-row Play reuses existing queue row by (kind, source_id, project_id)."""
    _inject_tracks(service, tmp_audio[:3])
    service._tracks[1].context = {
        "kind": "term_cluster",
        "source_id": "42",
        "project_id": 11,
        "play_count": 3,
    }
    service._current = service._tracks[0]
    service._current_index = 0

    with patch.object(service, "_begin_play_current") as begin_mock:
        n = service.play_paths(
            [tmp_audio[3]],
            labels=["clicked"],
            play_mode="enqueue",
            contexts=[{"kind": "term", "source_id": 42, "project_id": 11}],
            start_immediately=True,
        )

    assert n == 0
    assert len(service._tracks) == 3
    assert service._current_index == 1
    assert service._current is service._tracks[1]
    assert service._tracks[1].path == tmp_audio[3]
    assert service._tracks[1].context["play_count"] == 3
    begin_mock.assert_called_once()


# -- enqueue_from_db: items appear in queue without audio file --


class _FakeDTO:
    """Minimal stub mimicking AudioQueueItemDTO for enqueue_from_db tests."""
    def __init__(self, item_id, hebrew, niqqud="", translation="", kind="sentence"):
        self.item_id = item_id
        self.snapshot_hebrew = hebrew
        self.snapshot_niqqud = niqqud
        self.snapshot_translation = translation
        self.snapshot_source_label = f"{kind}:{item_id}"
        self.source_id = item_id
        self.kind = kind
        self.project_id = 1
        self.audio_status = "unknown"
        self.play_count = 0


def test_enqueue_from_db_appends_items(service):
    """enqueue_from_db adds items to _tracks even with no audio file."""
    dtos = [_FakeDTO(1, "שלום"), _FakeDTO(2, "עולם"), _FakeDTO(3, "בית")]
    n = service.enqueue_from_db(dtos, mode="append")
    assert n == 3
    assert len(service._tracks) == 3
    assert service._tracks[0].label == "שלום"
    assert service._tracks[2].label == "בית"
    # path is empty (no audio yet)
    from pathlib import Path
    assert service._tracks[0].path == Path("")


def test_enqueue_from_db_stores_context(service):
    """Context dict includes item_id, kind, source_id, project_id."""
    dtos = [_FakeDTO(42, "מים", niqqud="מַיִם", translation="water", kind="lemma")]
    service.enqueue_from_db(dtos, mode="append")
    ctx = service._tracks[0].context
    assert ctx["item_id"] == 42
    assert ctx["kind"] == "lemma"
    assert ctx["snapshot_hebrew"] == "מים"
    assert ctx["snapshot_niqqud"] == "מַיִם"
    assert ctx["snapshot_translation"] == "water"


def test_enqueue_from_db_prepend_shifts_index(service, tmp_audio):
    """prepend mode inserts before existing tracks and adjusts current_index."""
    _inject_tracks(service, tmp_audio[:2])
    service._current_index = 1   # pretend track[1] is current
    dtos = [_FakeDTO(10, "אחד"), _FakeDTO(11, "שניים")]
    n = service.enqueue_from_db(dtos, mode="prepend")
    assert n == 2
    assert len(service._tracks) == 4
    # New items at positions 0,1; old items shifted to 2,3
    assert service._tracks[0].label == "אחד"
    assert service._tracks[2].path == tmp_audio[0]  # original track[0]
    # current_index shifted by 2
    assert service._current_index == 3


def test_enqueue_from_db_after_current_inserts_correctly(service, tmp_audio):
    """after_current mode inserts after the cursor position."""
    _inject_tracks(service, tmp_audio[:3])
    service._current_index = 0
    dtos = [_FakeDTO(20, "חדש")]
    service.enqueue_from_db(dtos, mode="after_current")
    assert len(service._tracks) == 4
    # Should be inserted at position 1
    assert service._tracks[1].label == "חדש"
    assert service._tracks[2].path == tmp_audio[1]  # original track[1]


def test_enqueue_from_db_empty_list(service):
    """Empty input returns 0 and leaves queue unchanged."""
    n = service.enqueue_from_db([], mode="append")
    assert n == 0
    assert len(service._tracks) == 0


def test_enqueue_from_db_does_not_start_playback(service):
    """enqueue_from_db never triggers _start_next_track automatically."""
    dtos = [_FakeDTO(1, "שלום")]
    service.enqueue_from_db(dtos, mode="append")
    # _current should remain None (no auto-start on db load)
    assert service._current is None


# -- resolved_paths: path propagated correctly --------------------------------


def test_enqueue_from_db_with_resolved_path(service, tmp_audio):
    """enqueue_from_db with resolved_paths={item_id: path} → track.path == path and exists."""
    dto = _FakeDTO(77, "שלום")
    real_path = tmp_audio[0]
    n = service.enqueue_from_db([dto], mode="append", resolved_paths={77: real_path})
    assert n == 1
    track = service._tracks[0]
    assert track.path == real_path
    assert track.path.exists()


def test_enqueue_from_db_unresolved_item_gets_empty_path(service, tmp_audio):
    """Items without a matching resolved_path get Path("") (missing audio)."""
    dto = _FakeDTO(99, "בית")
    # Only item 77 has a path; item 99 has none
    n = service.enqueue_from_db([dto], mode="append", resolved_paths={77: tmp_audio[0]})
    assert n == 1
    assert service._tracks[0].path == Path("")


# -- jump_to_index ------------------------------------------------------------


def test_jump_to_index_sets_current(service, tmp_audio):
    """jump_to_index(i) sets _current_index=i and _current=tracks[i]."""
    _inject_tracks(service, tmp_audio[:4])
    with patch.object(service, "_begin_play_current"):
        service.jump_to_index(2)
    assert service._current_index == 2
    assert service._current is service._tracks[2]


def test_jump_to_index_out_of_bounds_is_noop(service, tmp_audio):
    """jump_to_index with out-of-range index does nothing."""
    _inject_tracks(service, tmp_audio[:2])
    service._current_index = 0
    service.jump_to_index(5)   # beyond end
    service.jump_to_index(-1)  # below 0
    assert service._current_index == 0


# -- Full Add-All scenario: enqueue with path → jump_to plays correct track ---


def test_add_all_enqueue_then_jump_plays_correct_track(service, tmp_audio):
    """Simulate Add All: enqueue two items with resolved paths, then jump_to plays
    the right track.  This confirms the 'Add All → Play from Status column' flow.
    """
    dto_a = _FakeDTO(10, "שלום")
    dto_b = _FakeDTO(11, "עולם")
    path_a = tmp_audio[0]
    path_b = tmp_audio[1]

    # Both items have resolved audio paths
    service.enqueue_from_db(
        [dto_a, dto_b],
        mode="append",
        resolved_paths={10: path_a, 11: path_b},
    )
    assert len(service._tracks) == 2
    assert service._tracks[0].path == path_a
    assert service._tracks[1].path == path_b

    # Play track 1 via jump_to_index (simulating Status-column ▶ click)
    with patch.object(service, "_begin_play_current"):
        service.jump_to_index(1)

    assert service._current is service._tracks[1]
    assert service._current.path == path_b
    assert service._current.path.exists()


# -- play_count increments after _on_post_roll_done -------------------------


def test_play_count_increments_after_post_roll(service, tmp_audio):
    """context['play_count'] increments by 1 when _on_post_roll_done is called."""
    _inject_tracks(service, tmp_audio[:2])
    # Add play_count key (as enqueue_from_db would)
    service._tracks[0].context["play_count"] = 0
    service._current_index = 0
    service._current = service._tracks[0]

    service._on_post_roll_done()

    assert service._tracks[0].context["play_count"] == 1


def test_play_count_not_added_if_missing_from_context(service, tmp_audio):
    """Tracks without play_count key are unaffected (no crash, no insertion)."""
    _inject_tracks(service, tmp_audio[:2])
    # No play_count key in context
    service._current_index = 0
    service._current = service._tracks[0]

    service._on_post_roll_done()  # must not raise

    assert "play_count" not in service._tracks[0].context


def test_play_paths_initializes_play_count_for_ui_context(service, tmp_audio):
    """Direct play entrypoints must start with play_count=0 (not '-')."""
    n = service.play_paths(
        [tmp_audio[0]],
        labels=["שלום"],
        play_mode="enqueue",
        contexts=[{"kind": "lemma", "source_id": 1}],
    )
    assert n == 1
    assert service._tracks[0].context.get("play_count") == 0


def test_play_count_increments_multiple_times(service, tmp_audio):
    """Each _on_post_roll_done call increments play_count by 1."""
    _inject_tracks(service, tmp_audio[:3])
    service._tracks[0].context["play_count"] = 0
    service._tracks[1].context["play_count"] = 0

    # Simulate track[0] finishing
    service._current_index = 0
    service._current = service._tracks[0]
    service._on_post_roll_done()
    assert service._tracks[0].context["play_count"] == 1

    # Simulate track[1] finishing (service advanced _current_index in _start_next_track)
    service._current = service._tracks[1]
    service._on_post_roll_done()
    assert service._tracks[1].context["play_count"] == 1
    assert service._tracks[0].context["play_count"] == 1  # unchanged
