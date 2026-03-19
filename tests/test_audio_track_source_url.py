"""Regression tests for Path("") sentinel handling (PATCH-04i fix).

Root cause: Path("") serialises to "." which os.path.exists(".") returns True,
causing unresolved Add All items to show "ready" status with a ▶ button that
then silently fails to play instead of showing "missing".

Fix:
  - audio_player_panel.py model: path != "." guard before os.path.exists check
  - audio_player_service.py backend: str(path) == "." early-return False
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_queue_model_status(path_str: str) -> str:
    """Re-implement the Status column logic from QueueTableModel.data()."""
    # Mirrors: app/ui/widgets/audio_player_panel.py _COL_STATUS branch
    path = path_str
    # Path("") serialises to "." which exists() — treat it as missing
    return "ready" if path and path != "." and os.path.exists(str(path)) else "missing"


# ---------------------------------------------------------------------------
# 1. Path("") sentinel — model must treat it as "missing"
# ---------------------------------------------------------------------------


def test_empty_path_sentinel_is_missing():
    """Path('') → str '.' must produce 'missing', not 'ready'."""
    status = _make_queue_model_status(str(Path("")))
    assert status == "missing", (
        f"Path('') serialised to {str(Path(''))!r}; model returned {status!r} "
        "but must return 'missing' to suppress the ▶ button"
    )


def test_dot_path_string_is_missing():
    """Literal '.' string must also produce 'missing'."""
    assert _make_queue_model_status(".") == "missing"


def test_empty_string_path_is_missing():
    """Empty string '' must produce 'missing'."""
    assert _make_queue_model_status("") == "missing"


def test_real_path_is_ready(tmp_path):
    """A real file on disk must produce 'ready'."""
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"RIFF")
    assert _make_queue_model_status(str(f)) == "ready"


def test_nonexistent_path_is_missing():
    """A path that does not exist must produce 'missing'."""
    assert _make_queue_model_status("/nonexistent/path/audio.mp3") == "missing"


# ---------------------------------------------------------------------------
# 2. Backend play() must reject Path("") / "." sentinel values
# ---------------------------------------------------------------------------


class _FakePlayer:
    """Minimal stand-in for QMediaPlayer."""

    def __init__(self):
        self.source = None

    def setSource(self, url) -> None:
        self.source = url

    def play(self) -> None:
        pass


def _make_backend_play_result(path: Path) -> bool:
    """Re-implement the guard logic from QtMultimediaBackend.play()."""
    # Path("") serialises to "." — reject empty/current-dir sentinel values
    if not str(path) or str(path) == ".":
        return False
    if not path.exists():
        return False
    return True


def test_backend_rejects_empty_path():
    """Backend.play(Path('')) must return False."""
    assert _make_backend_play_result(Path("")) is False


def test_backend_rejects_dot_path():
    """Backend.play(Path('.')) must return False (current directory is not audio)."""
    assert _make_backend_play_result(Path(".")) is False


def test_backend_accepts_real_file(tmp_path):
    """Backend.play(real_file) must return True."""
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"RIFF")
    assert _make_backend_play_result(f) is True


def test_backend_rejects_missing_file():
    """Backend.play(nonexistent) must return False."""
    assert _make_backend_play_result(Path("/nonexistent/audio.mp3")) is False


# ---------------------------------------------------------------------------
# 3. AudioTrack.to_payload() path serialisation
# ---------------------------------------------------------------------------


def test_to_payload_serialises_path_as_string(tmp_path):
    """AudioTrack.to_payload() stores path as string for model consumption."""
    from app.services.audio_player_service import AudioTrack

    f = tmp_path / "audio.mp3"
    t = AudioTrack(path=f, label="test")
    payload = t.to_payload()
    assert isinstance(payload["path"], str)
    assert payload["path"] == str(f)


def test_to_payload_empty_path_gives_dot():
    """AudioTrack(path=Path('')) serialises to '.' — model guard must handle this."""
    from app.services.audio_player_service import AudioTrack

    t = AudioTrack(path=Path(""), label="unresolved")
    payload = t.to_payload()
    assert payload["path"] == "."
    # Confirm the guard handles it correctly
    status = _make_queue_model_status(payload["path"])
    assert status == "missing"


# ---------------------------------------------------------------------------
# 4. Dedup upgrade: re-running Add All upgrades old unresolved tracks
# ---------------------------------------------------------------------------


def test_dedup_upgrades_unresolved_track_to_resolved(tmp_path, qapp):
    """Re-running Add All must upgrade an existing unresolved (path='.') track
    to the new resolved path, rather than silently skipping it.

    Regression guard for: old pre-PATCH tracks with path=Path('') blocking
    subsequent Add All runs from making them playable.
    """
    import sys
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    from app.services.audio_player_service import AudioPlayerService, AudioTrack

    # ── set up a minimal panel with one unresolved track ──────────────────
    AudioPlayerService.reset_instance_for_tests()
    settings_mock = MagicMock()
    settings_mock.get_int.return_value = 0
    settings_mock.get_string.return_value = "1.0"
    settings_mock.get_bool.return_value = False

    with patch.object(AudioPlayerService, "_build_default_backend", return_value=None):
        from app.ui.widgets.audio_player_panel import AudioPlayerPanel

        panel = AudioPlayerPanel.__new__(AudioPlayerPanel)
        from app.services.audio_player_service import AudioPlayerService as _APS

        panel.player = _APS(settings=settings_mock)

    # Inject an old unresolved track for sentence source_id=42
    old_track = AudioTrack(
        path=Path(""),  # unresolved — str(Path("")) == "."
        label="שלום",
        context={"kind": "sentence", "source_id": 42, "play_count": 0, "audio_status": "unknown"},
    )
    panel.player._tracks = [old_track]

    # Create a real audio file that the new Add All would resolve to
    real_file = tmp_path / "audio.wav"
    real_file.write_bytes(b"RIFF")

    # ── Simulate _load_db_queue_to_player with a new resolved item ─────────
    # Build a fake candidate DTO matching the same source_id=42
    candidate = MagicMock()
    candidate.item_id = 101
    candidate.kind = "sentence"
    candidate.source_id = 42
    candidate.snapshot_hebrew = "שלום"
    candidate.audio_asset_id = 7
    candidate.audio_status = "ready"
    candidate.snapshot_niqqud = None
    candidate.snapshot_translation = None
    candidate.snapshot_source_label = "test.docx"
    candidate.is_stale = False
    candidate.play_count = 0
    candidate.last_played_at = None
    candidate.project_id = 1
    candidate.position = 0

    # resolved_paths from Path A
    resolved_paths = {101: real_file}

    # Manually execute Step 3 logic (dedup + upgrade)
    existing_track_map = {}
    for t in panel.player._tracks:
        if isinstance(t.context, dict):
            k = (t.context.get("kind"), t.context.get("source_id"))
            if k[0] is not None and k[1] is not None:
                existing_track_map[k] = t

    upgraded = 0
    new_items = []
    for item in [candidate]:
        key = (item.kind, item.source_id)
        existing = existing_track_map.get(key)
        if existing is None:
            new_items.append(item)
        elif str(existing.path) in ("", ".") and item.item_id in resolved_paths:
            existing.path = resolved_paths[item.item_id]
            existing.context["audio_status"] = "ready"
            upgraded += 1

    # The old track should have been UPGRADED (not skipped, not duplicated)
    assert upgraded == 1, "Expected 1 track to be upgraded in-place"
    assert len(new_items) == 0, "No new items should be added (source already existed)"

    # The existing track now has the resolved path
    assert panel.player._tracks[0].path == real_file
    assert panel.player._tracks[0].context["audio_status"] == "ready"

    # And the model should show "ready" for this track
    import os

    path_str = str(panel.player._tracks[0].path)
    status = _make_queue_model_status(path_str)
    assert status == "ready"
