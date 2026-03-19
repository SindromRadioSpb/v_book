"""AudioQueueService — persistent Queue / Playlist / History for Audio Player v2.

Design principles:
- Queue is non-destructive: items are never removed after playing; a cursor
  in the UI layer (AudioPlayerService) advances instead.
- Playlists are independent snapshots; they survive queue clears.
- History is append-only; rows are never deleted.
- All writes use short transactions (caller must commit).
- Source references: (kind, source_id, project_id) + snapshot columns for
  display without extra joins.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.infra.sa_models import (
    AudioHistory,
    AudioPlaylist,
    AudioPlaylistEntry,
    AudioQueueItem,
)

logger = logging.getLogger(__name__)


# ── DTOs ─────────────────────────────────────────────────────────────────────


@dataclass
class AudioItemSpec:
    """Input descriptor for adding an item to the queue or a playlist.

    Callers (views) populate whichever snapshot fields they have available.
    """

    kind: str = "sentence"  # sentence | lemma | term | custom_text
    source_id: int | None = None
    project_id: int | None = None
    snapshot_hebrew: str | None = None
    snapshot_niqqud: str | None = None
    snapshot_translation: str | None = None
    snapshot_source_label: str | None = None
    audio_asset_id: int | None = None
    audio_status: str = "unknown"


@dataclass
class AudioQueueItemDTO:
    """Read model returned from get_queue()."""

    item_id: int
    position: int
    kind: str
    source_id: int | None
    project_id: int | None
    snapshot_hebrew: str | None
    snapshot_niqqud: str | None
    snapshot_translation: str | None
    snapshot_source_label: str | None
    audio_asset_id: int | None
    audio_status: str
    is_stale: bool
    play_count: int
    last_played_at: str | None


@dataclass
class AudioPlaylistDTO:
    """Read model for a playlist header."""

    playlist_id: int
    name: str
    entry_count: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class AudioPlaylistEntryDTO:
    """Read model for a playlist entry."""

    entry_id: int
    playlist_id: int
    position: int
    kind: str
    source_id: int | None
    project_id: int | None
    snapshot_hebrew: str | None
    snapshot_niqqud: str | None
    snapshot_translation: str | None
    snapshot_source_label: str | None
    audio_asset_id: int | None
    audio_status: str


@dataclass
class AudioHistoryDTO:
    """Read model for a history entry."""

    history_id: int
    kind: str
    source_id: int | None
    project_id: int | None
    snapshot_hebrew: str | None
    rate_used: float
    played_at: str


@dataclass
class SourceLink:
    """Deep-link payload returned by resolve_source_link()."""

    view_name: str  # "sentences" | "dictionary" | "terms"
    row_id: int | None  # sentence_id / lemma entry_id / term entry_id
    project_id: int | None
    extra: dict[str, Any] = field(default_factory=dict)


# ── Service ───────────────────────────────────────────────────────────────────


class AudioQueueService:
    """CRUD service for Audio Player v2 Queue / Playlist / History.

    All methods accept an open SQLAlchemy ``Session``.  The caller is
    responsible for committing (to allow chunked batch inserts).
    """

    # ── Queue ─────────────────────────────────────────────────────────────────

    def get_queue(self, session: Session) -> list[AudioQueueItemDTO]:
        """Return all queue items ordered by position."""
        rows = session.query(AudioQueueItem).order_by(AudioQueueItem.position).all()
        return [self._row_to_queue_dto(r) for r in rows]

    def add_to_queue(
        self,
        session: Session,
        specs: list[AudioItemSpec],
        *,
        mode: str = "append",  # "append" | "prepend" | "after_current"
        current_position: int = 0,
    ) -> list[int]:
        """Insert specs into the queue and return new item_ids.

        ``mode``:
          - ``append``        — add after the last existing item.
          - ``prepend``       — add before position 0 (shift existing up).
          - ``after_current`` — insert after ``current_position`` (shift the
                                rest up).

        Returns list of new item_ids in insertion order.
        """
        if not specs:
            return []

        existing = session.query(AudioQueueItem).order_by(AudioQueueItem.position).all()
        max_pos = existing[-1].position if existing else -1

        if mode == "prepend":
            insert_after = -1
        elif mode == "after_current":
            insert_after = current_position
        else:  # append
            insert_after = max_pos

        # Shift rows that come after the insertion point
        if mode != "append":
            shift_amount = len(specs)
            for row in existing:
                if row.position > insert_after:
                    row.position += shift_amount

        item_ids: list[int] = []
        for i, spec in enumerate(specs):
            item = AudioQueueItem(
                position=insert_after + 1 + i,
                kind=spec.kind,
                source_id=spec.source_id,
                project_id=spec.project_id,
                snapshot_hebrew=spec.snapshot_hebrew,
                snapshot_niqqud=spec.snapshot_niqqud,
                snapshot_translation=spec.snapshot_translation,
                snapshot_source_label=spec.snapshot_source_label,
                audio_asset_id=spec.audio_asset_id,
                audio_status=spec.audio_status,
            )
            session.add(item)
            session.flush()  # get item_id
            item_ids.append(item.item_id)

        return item_ids

    def remove_from_queue(self, session: Session, item_ids: list[int]) -> int:
        """Delete queue items by ID.  Returns count deleted."""
        if not item_ids:
            return 0
        count = (
            session.query(AudioQueueItem)
            .filter(AudioQueueItem.item_id.in_(item_ids))
            .delete(synchronize_session="fetch")
        )
        self._repack_positions(session)
        return count

    def clear_queue(self, session: Session) -> None:
        """Remove all items from the queue."""
        session.query(AudioQueueItem).delete()

    def reorder_queue(self, session: Session, ordered_item_ids: list[int]) -> None:
        """Re-assign positions according to the supplied order.

        ``ordered_item_ids`` must contain every item_id currently in the queue
        (extra IDs are silently ignored; missing IDs keep their old position).
        """
        id_to_row = {r.item_id: r for r in session.query(AudioQueueItem).all()}
        for new_pos, item_id in enumerate(ordered_item_ids):
            if item_id in id_to_row:
                id_to_row[item_id].position = new_pos

    def mark_played(self, session: Session, item_id: int, rate_used: float = 1.0) -> None:
        """Increment play_count, update last_played_at, and append a history row."""
        from datetime import datetime

        now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        item = session.get(AudioQueueItem, item_id)
        if item is None:
            logger.warning("mark_played: item_id %d not found", item_id)
            return

        item.play_count += 1
        item.last_played_at = now_str

        history = AudioHistory(
            kind=item.kind,
            source_id=item.source_id,
            project_id=item.project_id,
            snapshot_hebrew=item.snapshot_hebrew,
            rate_used=rate_used,
            played_at=now_str,
        )
        session.add(history)

    def mark_stale(self, session: Session, item_ids: list[int]) -> int:
        """Set is_stale=1 on the given items.  Returns count updated."""
        if not item_ids:
            return 0
        return (
            session.query(AudioQueueItem)
            .filter(AudioQueueItem.item_id.in_(item_ids))
            .update({"is_stale": 1}, synchronize_session="fetch")
        )

    def mark_fresh(self, session: Session, item_ids: list[int]) -> int:
        """Clear is_stale on the given items.  Returns count updated."""
        if not item_ids:
            return 0
        return (
            session.query(AudioQueueItem)
            .filter(AudioQueueItem.item_id.in_(item_ids))
            .update({"is_stale": 0}, synchronize_session="fetch")
        )

    def update_snapshot(
        self,
        session: Session,
        item_id: int,
        *,
        snapshot_hebrew: str | None = None,
        snapshot_niqqud: str | None = None,
        snapshot_translation: str | None = None,
        audio_asset_id: int | None = None,
        audio_status: str | None = None,
        is_stale: bool | None = None,
    ) -> None:
        """Patch snapshot / status fields on a queue item."""
        item = session.get(AudioQueueItem, item_id)
        if item is None:
            return
        if snapshot_hebrew is not None:
            item.snapshot_hebrew = snapshot_hebrew
        if snapshot_niqqud is not None:
            item.snapshot_niqqud = snapshot_niqqud
        if snapshot_translation is not None:
            item.snapshot_translation = snapshot_translation
        if audio_asset_id is not None:
            item.audio_asset_id = audio_asset_id
        if audio_status is not None:
            item.audio_status = audio_status
        if is_stale is not None:
            item.is_stale = 1 if is_stale else 0

    def find_stale_by_source(
        self,
        session: Session,
        kind: str,
        source_id: int,
        project_id: int | None = None,
    ) -> list[int]:
        """Return item_ids matching (kind, source_id[, project_id]) so callers
        can mark them stale after editing pronunciation/niqqud."""
        q = session.query(AudioQueueItem.item_id).filter(
            AudioQueueItem.kind == kind,
            AudioQueueItem.source_id == source_id,
        )
        if project_id is not None:
            q = q.filter(AudioQueueItem.project_id == project_id)
        return [row.item_id for row in q.all()]

    def mark_stale_by_source(
        self,
        session: Session,
        *,
        kind: str,
        source_id: int,
        project_id: int | None = None,
    ) -> int:
        """Mark all queue rows for a source as stale.

        Returns number of updated queue rows.
        """
        item_ids = self.find_stale_by_source(
            session,
            kind=kind,
            source_id=source_id,
            project_id=project_id,
        )
        return self.mark_stale(session, item_ids)

    # ── Playlists ─────────────────────────────────────────────────────────────

    def get_playlists(self, session: Session) -> list[AudioPlaylistDTO]:
        """Return all playlists ordered by name, with entry counts."""
        playlists = session.query(AudioPlaylist).order_by(AudioPlaylist.name).all()
        result = []
        for pl in playlists:
            count = (
                session.query(AudioPlaylistEntry)
                .filter(AudioPlaylistEntry.playlist_id == pl.playlist_id)
                .count()
            )
            result.append(
                AudioPlaylistDTO(
                    playlist_id=pl.playlist_id,
                    name=pl.name,
                    entry_count=count,
                    created_at=pl.created_at,
                    updated_at=pl.updated_at,
                )
            )
        return result

    def create_playlist(self, session: Session, name: str) -> int:
        """Create a new playlist with the given name.  Returns playlist_id."""
        pl = AudioPlaylist(name=name)
        session.add(pl)
        session.flush()
        return pl.playlist_id

    def rename_playlist(self, session: Session, playlist_id: int, new_name: str) -> None:
        from datetime import datetime

        pl = session.get(AudioPlaylist, playlist_id)
        if pl:
            pl.name = new_name
            pl.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def delete_playlist(self, session: Session, playlist_id: int) -> None:
        pl = session.get(AudioPlaylist, playlist_id)
        if pl:
            session.delete(pl)

    def get_playlist_entries(
        self, session: Session, playlist_id: int
    ) -> list[AudioPlaylistEntryDTO]:
        rows = (
            session.query(AudioPlaylistEntry)
            .filter(AudioPlaylistEntry.playlist_id == playlist_id)
            .order_by(AudioPlaylistEntry.position)
            .all()
        )
        return [self._row_to_entry_dto(r) for r in rows]

    def add_to_playlist(
        self,
        session: Session,
        playlist_id: int,
        specs: list[AudioItemSpec],
    ) -> list[int]:
        """Append specs to a playlist.  Returns new entry_ids."""
        if not specs:
            return []
        existing_count = (
            session.query(AudioPlaylistEntry)
            .filter(AudioPlaylistEntry.playlist_id == playlist_id)
            .count()
        )
        entry_ids: list[int] = []
        for i, spec in enumerate(specs):
            entry = AudioPlaylistEntry(
                playlist_id=playlist_id,
                position=existing_count + i,
                kind=spec.kind,
                source_id=spec.source_id,
                project_id=spec.project_id,
                snapshot_hebrew=spec.snapshot_hebrew,
                snapshot_niqqud=spec.snapshot_niqqud,
                snapshot_translation=spec.snapshot_translation,
                snapshot_source_label=spec.snapshot_source_label,
                audio_asset_id=spec.audio_asset_id,
                audio_status=spec.audio_status,
            )
            session.add(entry)
            session.flush()
            entry_ids.append(entry.entry_id)

        # bump playlist updated_at
        from datetime import datetime

        pl = session.get(AudioPlaylist, playlist_id)
        if pl:
            pl.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        return entry_ids

    def add_items_to_playlist(
        self,
        session: Session,
        playlist_id: int,
        specs: list[AudioItemSpec],
        *,
        add_mode: str = "append",  # append | prepend | after_selected
        after_entry_id: int | None = None,
        dedup_by_source: bool = True,
    ) -> tuple[int, int]:
        """Insert specs into playlist with optional dedup and positional mode.

        Returns ``(added_count, skipped_duplicates_count)``.
        """
        if not specs:
            return (0, 0)

        from datetime import datetime

        existing_rows = (
            session.query(AudioPlaylistEntry)
            .filter(AudioPlaylistEntry.playlist_id == playlist_id)
            .order_by(AudioPlaylistEntry.position)
            .all()
        )

        existing_keys: set[tuple[int | None, str, int | None]] = set()
        if dedup_by_source:
            for row in existing_rows:
                if row.source_id is not None:
                    existing_keys.add((row.project_id, row.kind, row.source_id))

        filtered_specs: list[AudioItemSpec] = []
        seen_new_keys: set[tuple[int | None, str, int | None]] = set()
        skipped = 0
        for spec in specs:
            key = (spec.project_id, spec.kind, spec.source_id)
            if (
                dedup_by_source
                and spec.source_id is not None
                and (key in existing_keys or key in seen_new_keys)
            ):
                skipped += 1
                continue
            filtered_specs.append(spec)
            if spec.source_id is not None:
                seen_new_keys.add(key)

        if not filtered_specs:
            return (0, skipped)

        insert_at = len(existing_rows)
        mode = (add_mode or "append").strip().lower()
        if mode == "prepend":
            insert_at = 0
        elif mode == "after_selected" and after_entry_id is not None:
            after_row = next((row for row in existing_rows if row.entry_id == after_entry_id), None)
            if after_row is not None:
                insert_at = int(after_row.position) + 1

        if insert_at < len(existing_rows):
            shift_by = len(filtered_specs)
            for row in existing_rows:
                if int(row.position) >= insert_at:
                    row.position = int(row.position) + shift_by

        for idx, spec in enumerate(filtered_specs):
            entry = AudioPlaylistEntry(
                playlist_id=playlist_id,
                position=insert_at + idx,
                kind=spec.kind,
                source_id=spec.source_id,
                project_id=spec.project_id,
                snapshot_hebrew=spec.snapshot_hebrew,
                snapshot_niqqud=spec.snapshot_niqqud,
                snapshot_translation=spec.snapshot_translation,
                snapshot_source_label=spec.snapshot_source_label,
                audio_asset_id=spec.audio_asset_id,
                audio_status=spec.audio_status,
            )
            session.add(entry)

        pl = session.get(AudioPlaylist, playlist_id)
        if pl:
            pl.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return (len(filtered_specs), skipped)

    def remove_from_playlist(self, session: Session, playlist_id: int, entry_ids: list[int]) -> int:
        if not entry_ids:
            return 0
        count = (
            session.query(AudioPlaylistEntry)
            .filter(
                AudioPlaylistEntry.playlist_id == playlist_id,
                AudioPlaylistEntry.entry_id.in_(entry_ids),
            )
            .delete(synchronize_session="fetch")
        )
        self._repack_playlist_positions(session, playlist_id)
        return count

    def reorder_playlist_entries(
        self,
        session: Session,
        playlist_id: int,
        ordered_entry_ids: list[int],
    ) -> None:
        """Reassign playlist entry positions based on the supplied order.

        Any playlist entries not present in ``ordered_entry_ids`` are appended
        after the ordered block, preserving their previous relative order.
        """
        rows = (
            session.query(AudioPlaylistEntry)
            .filter(AudioPlaylistEntry.playlist_id == playlist_id)
            .order_by(AudioPlaylistEntry.position)
            .all()
        )
        if not rows:
            return

        row_by_id = {row.entry_id: row for row in rows}
        seen: set[int] = set()
        ordered_rows: list[AudioPlaylistEntry] = []
        for entry_id in ordered_entry_ids:
            row = row_by_id.get(entry_id)
            if row is None or entry_id in seen:
                continue
            ordered_rows.append(row)
            seen.add(entry_id)

        for row in rows:
            if row.entry_id not in seen:
                ordered_rows.append(row)

        for position, row in enumerate(ordered_rows):
            row.position = position

        from datetime import datetime

        pl = session.get(AudioPlaylist, playlist_id)
        if pl:
            pl.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def move_queue_to_playlist(
        self,
        session: Session,
        item_ids: list[int],
        playlist_id: int,
    ) -> None:
        """Copy queue items into a playlist (items stay in the queue)."""
        items = session.query(AudioQueueItem).filter(AudioQueueItem.item_id.in_(item_ids)).all()
        specs = [
            AudioItemSpec(
                kind=item.kind,
                source_id=item.source_id,
                project_id=item.project_id,
                snapshot_hebrew=item.snapshot_hebrew,
                snapshot_niqqud=item.snapshot_niqqud,
                snapshot_translation=item.snapshot_translation,
                snapshot_source_label=item.snapshot_source_label,
                audio_asset_id=item.audio_asset_id,
                audio_status=item.audio_status,
            )
            for item in items
        ]
        self.add_to_playlist(session, playlist_id, specs)

    def load_playlist_to_queue(
        self,
        session: Session,
        playlist_id: int,
        mode: str = "append",
        current_position: int = 0,
    ) -> int:
        """Copy all playlist entries to the queue.  Returns count added."""
        return len(
            self.load_playlist_to_queue_ids(
                session,
                playlist_id,
                mode=mode,
                current_position=current_position,
            )
        )

    def load_playlist_to_queue_ids(
        self,
        session: Session,
        playlist_id: int,
        mode: str = "append",
        current_position: int = 0,
    ) -> list[int]:
        """Copy playlist entries to queue and return inserted queue item_ids."""
        entries = self.get_playlist_entries(session, playlist_id)
        specs = [
            AudioItemSpec(
                kind=e.kind,
                source_id=e.source_id,
                project_id=e.project_id,
                snapshot_hebrew=e.snapshot_hebrew,
                snapshot_niqqud=e.snapshot_niqqud,
                snapshot_translation=e.snapshot_translation,
                snapshot_source_label=e.snapshot_source_label,
                audio_asset_id=e.audio_asset_id,
                audio_status=e.audio_status,
            )
            for e in entries
        ]
        return self.add_to_queue(session, specs, mode=mode, current_position=current_position)

    # ── History ───────────────────────────────────────────────────────────────

    def get_history(
        self,
        session: Session,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AudioHistoryDTO]:
        rows = (
            session.query(AudioHistory)
            .order_by(AudioHistory.played_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [
            AudioHistoryDTO(
                history_id=r.history_id,
                kind=r.kind,
                source_id=r.source_id,
                project_id=r.project_id,
                snapshot_hebrew=r.snapshot_hebrew,
                rate_used=r.rate_used,
                played_at=r.played_at,
            )
            for r in rows
        ]

    # ── Source deep-links ─────────────────────────────────────────────────────

    def resolve_source_link(self, item: AudioQueueItemDTO) -> SourceLink | None:
        """Map (kind, source_id, project_id) → SourceLink for "Go to source"."""
        if item.source_id is None:
            return None

        kind_to_view = {
            "sentence": "sentences",
            "lemma": "dictionary",
            "term": "terms",
        }
        view_name = kind_to_view.get(item.kind)
        if view_name is None:
            return None

        return SourceLink(
            view_name=view_name,
            row_id=item.source_id,
            project_id=item.project_id,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _repack_positions(self, session: Session) -> None:
        """Re-assign consecutive positions (0, 1, 2, …) after a deletion."""
        rows = session.query(AudioQueueItem).order_by(AudioQueueItem.position).all()
        for new_pos, row in enumerate(rows):
            row.position = new_pos

    def _repack_playlist_positions(self, session: Session, playlist_id: int) -> None:
        rows = (
            session.query(AudioPlaylistEntry)
            .filter(AudioPlaylistEntry.playlist_id == playlist_id)
            .order_by(AudioPlaylistEntry.position)
            .all()
        )
        for new_pos, row in enumerate(rows):
            row.position = new_pos

    @staticmethod
    def _row_to_queue_dto(row: AudioQueueItem) -> AudioQueueItemDTO:
        return AudioQueueItemDTO(
            item_id=row.item_id,
            position=row.position,
            kind=row.kind,
            source_id=row.source_id,
            project_id=row.project_id,
            snapshot_hebrew=row.snapshot_hebrew,
            snapshot_niqqud=row.snapshot_niqqud,
            snapshot_translation=row.snapshot_translation,
            snapshot_source_label=row.snapshot_source_label,
            audio_asset_id=row.audio_asset_id,
            audio_status=row.audio_status,
            is_stale=bool(row.is_stale),
            play_count=row.play_count,
            last_played_at=row.last_played_at,
        )

    @staticmethod
    def _row_to_entry_dto(row: AudioPlaylistEntry) -> AudioPlaylistEntryDTO:
        return AudioPlaylistEntryDTO(
            entry_id=row.entry_id,
            playlist_id=row.playlist_id,
            position=row.position,
            kind=row.kind,
            source_id=row.source_id,
            project_id=row.project_id,
            snapshot_hebrew=row.snapshot_hebrew,
            snapshot_niqqud=row.snapshot_niqqud,
            snapshot_translation=row.snapshot_translation,
            snapshot_source_label=row.snapshot_source_label,
            audio_asset_id=row.audio_asset_id,
            audio_status=row.audio_status,
        )
