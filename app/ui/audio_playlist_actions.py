from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PyQt6.QtWidgets import QDialog, QMessageBox, QWidget

from app.services.audio_queue_service import AudioItemSpec, AudioQueueService


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_kind(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"term_cluster", "terms"}:
        return "term"
    if value in {"surface", "sentences"}:
        return "sentence"
    return value


def _build_specs(items: Iterable[dict[str, Any]]) -> list[AudioItemSpec]:
    specs: list[AudioItemSpec] = []
    for payload in items:
        if not isinstance(payload, dict):
            continue
        kind = _normalize_kind(str(payload.get("kind") or "sentence"))
        src_text = str(payload.get("src_text") or "").strip()
        src_label = str(payload.get("source_label") or "").strip()
        snapshot_hebrew = src_text or src_label
        if not snapshot_hebrew:
            continue
        specs.append(
            AudioItemSpec(
                kind=kind,
                source_id=_to_int(payload.get("source_id")),
                project_id=_to_int(payload.get("project_id")),
                snapshot_hebrew=snapshot_hebrew,
                snapshot_niqqud=str(
                    payload.get("pronunciation_text")
                    or payload.get("snapshot_niqqud")
                    or payload.get("niqqud")
                    or ""
                ).strip()
                or None,
                snapshot_translation=str(
                    payload.get("translation") or payload.get("snapshot_translation") or ""
                ).strip()
                or None,
                snapshot_source_label=src_label or None,
                audio_asset_id=_to_int(payload.get("audio_asset_id")),
                audio_status=str(payload.get("audio_status") or "unknown").strip() or "unknown",
            )
        )
    return specs


def _refresh_audio_player_playlists(
    parent: QWidget | None, *, select_playlist_id: int | None = None
) -> None:
    """Best-effort refresh for Audio Player playlists tab after external modifications."""
    if parent is None:
        return
    try:
        window = parent.window()
    except Exception:
        window = None
    panel = getattr(window, "audio_player_panel", None) if window is not None else None
    if panel is None:
        return
    try:
        refresh_method = getattr(panel, "refresh_playlists_view", None)
        if callable(refresh_method):
            refresh_method(select_playlist_id=select_playlist_id)
            return
        fallback = getattr(panel, "_refresh_playlists", None)
        if callable(fallback):
            fallback(select_playlist_id=select_playlist_id)
    except Exception:
        # Non-fatal: external views should not fail if Audio Player is hidden/unavailable.
        return


def add_selected_items_to_playlist_dialog(
    *,
    parent: QWidget,
    items: Iterable[dict[str, Any]],
    db_manager: Any = None,
    default_playlist_id: int | None = None,
    default_after_entry_id: int | None = None,
) -> bool:
    """Open AddQueueToPlaylistDialog and persist selected items to playlist.

    Returns True if rows were added, False otherwise.
    """
    specs = _build_specs(items)
    if not specs:
        QMessageBox.information(parent, "Playlists", "No valid rows selected.")
        return False

    if db_manager is None:
        from app.services.db_service import DBService

        db_manager = DBService.get_instance()
    if db_manager is None:
        QMessageBox.warning(parent, "Playlists", "Database connection is unavailable.")
        return False

    from app.ui.widgets.audio_player_panel import AddQueueToPlaylistDialog

    dialog = AddQueueToPlaylistDialog(
        parent=parent,
        db_manager=db_manager,
        selected_count=len(specs),
        source_keys=[(spec.project_id, spec.kind, spec.source_id) for spec in specs],
        default_playlist_id=default_playlist_id,
        default_after_entry_id=default_after_entry_id,
    )
    if hasattr(dialog, "playlist_created"):
        try:
            dialog.playlist_created.connect(  # type: ignore[attr-defined]
                lambda playlist_id: _refresh_audio_player_playlists(
                    parent,
                    select_playlist_id=int(playlist_id) if playlist_id is not None else None,
                )
            )
        except Exception:
            pass
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    playlist_id = dialog.selected_playlist_id()
    if playlist_id is None:
        QMessageBox.warning(parent, "Playlists", "Select a playlist.")
        return False

    try:
        with db_manager.get_session() as session:
            added_count, skipped_count = AudioQueueService().add_items_to_playlist(
                session,
                playlist_id,
                specs,
                add_mode=dialog.selected_add_mode(),
                after_entry_id=dialog.selected_after_entry_id(),
                dedup_by_source=dialog.dedup_enabled(),
            )
            session.commit()
    except Exception as exc:
        QMessageBox.warning(parent, "Playlists", f"Failed to add entries:\n{exc}")
        return False

    _refresh_audio_player_playlists(parent, select_playlist_id=int(playlist_id))

    QMessageBox.information(
        parent,
        "Playlists",
        f"Added: {added_count}\nSkipped duplicates: {skipped_count}",
    )
    return added_count > 0
