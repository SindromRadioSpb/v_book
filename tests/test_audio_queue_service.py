from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.infra.sa_models import Base
from app.services.audio_queue_service import AudioItemSpec, AudioQueueService


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def svc():
    return AudioQueueService()


def _specs(n, kind="sentence"):
    return [
        AudioItemSpec(kind=kind, source_id=i + 1, snapshot_hebrew=f"item_{i}")
        for i in range(n)
    ]


def test_add_and_get_queue(session, svc):
    svc.add_to_queue(session, _specs(3))
    session.commit()
    assert len(svc.get_queue(session)) == 3


def test_queue_positions_sequential(session, svc):
    svc.add_to_queue(session, _specs(3))
    session.commit()
    positions = [r.position for r in svc.get_queue(session)]
    assert positions == [0, 1, 2]


def test_add_prepend(session, svc):
    svc.add_to_queue(session, _specs(3))
    session.commit()
    new_spec = AudioItemSpec(kind="sentence", source_id=99, snapshot_hebrew="new")
    svc.add_to_queue(session, [new_spec], mode="prepend")
    session.commit()
    rows = svc.get_queue(session)
    assert len(rows) == 4
    assert rows[0].source_id == 99
    assert rows[0].position == 0


def test_remove_from_queue(session, svc):
    ids = svc.add_to_queue(session, _specs(3))
    session.commit()
    count = svc.remove_from_queue(session, [ids[1]])
    session.commit()
    assert count == 1
    rows = svc.get_queue(session)
    assert len(rows) == 2
    assert [r.position for r in rows] == [0, 1]


def test_clear_queue(session, svc):
    svc.add_to_queue(session, _specs(3))
    session.commit()
    svc.clear_queue(session)
    session.commit()
    assert svc.get_queue(session) == []


def test_reorder_queue(session, svc):
    ids = svc.add_to_queue(session, _specs(3))
    session.commit()
    id_a, id_b, id_c = ids
    svc.reorder_queue(session, [id_c, id_a, id_b])
    session.commit()
    rows = svc.get_queue(session)
    assert rows[0].item_id == id_c
    assert rows[1].item_id == id_a
    assert rows[2].item_id == id_b


def test_mark_played_increments_count(session, svc):
    ids = svc.add_to_queue(session, _specs(1))
    session.commit()
    svc.mark_played(session, ids[0], rate_used=1.0)
    session.commit()
    rows = svc.get_queue(session)
    assert rows[0].play_count == 1
    assert rows[0].last_played_at is not None


def test_mark_played_appends_history(session, svc):
    ids = svc.add_to_queue(session, _specs(1))
    session.commit()
    svc.mark_played(session, ids[0], rate_used=1.5)
    session.commit()
    history = svc.get_history(session)
    assert len(history) == 1
    assert history[0].rate_used == 1.5


def test_mark_stale(session, svc):
    ids = svc.add_to_queue(session, _specs(2))
    session.commit()
    updated = svc.mark_stale(session, [ids[0]])
    session.commit()
    assert updated == 1
    rows = svc.get_queue(session)
    assert rows[0].is_stale is True
    assert rows[1].is_stale is False


def test_find_stale_by_source(session, svc):
    specs = [
        AudioItemSpec(kind="sentence", source_id=42, snapshot_hebrew="A"),
        AudioItemSpec(kind="sentence", source_id=42, snapshot_hebrew="B"),
    ]
    ids = svc.add_to_queue(session, specs)
    session.commit()
    found = svc.find_stale_by_source(session, kind="sentence", source_id=42)
    assert set(found) == set(ids)


def test_mark_stale_by_source(session, svc):
    specs = [
        AudioItemSpec(kind="term", source_id=7, project_id=3, snapshot_hebrew="A"),
        AudioItemSpec(kind="term", source_id=7, project_id=3, snapshot_hebrew="B"),
        AudioItemSpec(kind="term", source_id=8, project_id=3, snapshot_hebrew="C"),
    ]
    ids = svc.add_to_queue(session, specs)
    session.commit()

    updated = svc.mark_stale_by_source(
        session,
        kind="term",
        source_id=7,
        project_id=3,
    )
    session.commit()

    assert updated == 2
    rows = svc.get_queue(session)
    stale_flags = {row.item_id: row.is_stale for row in rows}
    assert stale_flags[ids[0]] is True
    assert stale_flags[ids[1]] is True
    assert stale_flags[ids[2]] is False


def test_create_and_get_playlist(session, svc):
    pl_id = svc.create_playlist(session, "My Playlist")
    session.commit()
    playlists = svc.get_playlists(session)
    assert len(playlists) == 1
    assert playlists[0].name == "My Playlist"
    assert playlists[0].playlist_id == pl_id


def test_add_to_playlist(session, svc):
    pl_id = svc.create_playlist(session, "Test PL")
    session.commit()
    svc.add_to_playlist(session, pl_id, _specs(3))
    session.commit()
    entries = svc.get_playlist_entries(session, pl_id)
    assert len(entries) == 3


def test_move_queue_to_playlist(session, svc):
    ids = svc.add_to_queue(session, _specs(3))
    session.commit()
    pl_id = svc.create_playlist(session, "Snapshot PL")
    session.commit()
    svc.move_queue_to_playlist(session, ids[:2], pl_id)
    session.commit()
    entries = svc.get_playlist_entries(session, pl_id)
    assert len(entries) == 2
    assert len(svc.get_queue(session)) == 3


def test_load_playlist_to_queue(session, svc):
    pl_id = svc.create_playlist(session, "Load PL")
    session.commit()
    svc.add_to_playlist(session, pl_id, _specs(3))
    session.commit()
    added = svc.load_playlist_to_queue(session, pl_id)
    session.commit()
    assert added == 3
    assert len(svc.get_queue(session)) == 3


def test_load_playlist_to_queue_ids_returns_inserted_ids(session, svc):
    pl_id = svc.create_playlist(session, "Load IDs")
    session.commit()
    svc.add_to_playlist(session, pl_id, _specs(2))
    session.commit()
    new_ids = svc.load_playlist_to_queue_ids(session, pl_id, mode="append")
    session.commit()
    assert len(new_ids) == 2
    queue_ids = [row.item_id for row in svc.get_queue(session)]
    assert new_ids == queue_ids


def test_reorder_playlist_entries(session, svc):
    pl_id = svc.create_playlist(session, "Reorder PL")
    session.commit()
    svc.add_to_playlist(session, pl_id, _specs(3))
    session.commit()
    entries = svc.get_playlist_entries(session, pl_id)
    ids = [entry.entry_id for entry in entries]
    svc.reorder_playlist_entries(session, pl_id, [ids[2], ids[0], ids[1]])
    session.commit()
    reordered = svc.get_playlist_entries(session, pl_id)
    assert [entry.entry_id for entry in reordered] == [ids[2], ids[0], ids[1]]
    assert [entry.position for entry in reordered] == [0, 1, 2]


def test_add_items_to_playlist_dedup_by_source(session, svc):
    pl_id = svc.create_playlist(session, "Dedup")
    session.commit()
    specs = [
        AudioItemSpec(kind="term", source_id=10, project_id=1, snapshot_hebrew="a"),
        AudioItemSpec(kind="term", source_id=10, project_id=1, snapshot_hebrew="a-dup"),
        AudioItemSpec(kind="term", source_id=11, project_id=1, snapshot_hebrew="b"),
    ]
    added, skipped = svc.add_items_to_playlist(
        session,
        pl_id,
        specs,
        add_mode="append",
        dedup_by_source=True,
    )
    session.commit()
    assert added == 2
    assert skipped == 1
    entries = svc.get_playlist_entries(session, pl_id)
    assert len(entries) == 2
    assert [e.position for e in entries] == [0, 1]


def test_add_items_to_playlist_prepend_and_after_selected(session, svc):
    pl_id = svc.create_playlist(session, "Insert modes")
    session.commit()
    svc.add_to_playlist(
        session,
        pl_id,
        [
            AudioItemSpec(kind="term", source_id=1, snapshot_hebrew="one"),
            AudioItemSpec(kind="term", source_id=2, snapshot_hebrew="two"),
        ],
    )
    session.commit()
    # Prepend one item.
    added, skipped = svc.add_items_to_playlist(
        session,
        pl_id,
        [AudioItemSpec(kind="term", source_id=3, snapshot_hebrew="three")],
        add_mode="prepend",
        dedup_by_source=False,
    )
    assert added == 1
    assert skipped == 0
    session.commit()
    entries = svc.get_playlist_entries(session, pl_id)
    assert [e.source_id for e in entries] == [3, 1, 2]

    # Insert after selected (after source_id=1).
    after_entry_id = next(e.entry_id for e in entries if e.source_id == 1)
    added2, skipped2 = svc.add_items_to_playlist(
        session,
        pl_id,
        [AudioItemSpec(kind="term", source_id=4, snapshot_hebrew="four")],
        add_mode="after_selected",
        after_entry_id=after_entry_id,
        dedup_by_source=False,
    )
    assert added2 == 1
    assert skipped2 == 0
    session.commit()
    entries2 = svc.get_playlist_entries(session, pl_id)
    assert [e.source_id for e in entries2] == [3, 1, 4, 2]


def test_get_history(session, svc):
    ids = svc.add_to_queue(session, _specs(5))
    session.commit()
    for item_id in ids:
        svc.mark_played(session, item_id)
        session.commit()
    history = svc.get_history(session)
    assert len(history) == 5
    played_ats = [h.played_at for h in history]
    assert played_ats == sorted(played_ats, reverse=True)


def test_resolve_source_link_sentence(session, svc):
    svc.add_to_queue(session, [AudioItemSpec(kind="sentence", source_id=42, project_id=7)])
    session.commit()
    rows = svc.get_queue(session)
    link = svc.resolve_source_link(rows[0])
    assert link is not None
    assert link.view_name == "sentences"
    assert link.row_id == 42
    assert link.project_id == 7


def test_resolve_source_link_none_for_custom(session, svc):
    svc.add_to_queue(session, [AudioItemSpec(kind="custom_text", source_id=10)])
    session.commit()
    rows = svc.get_queue(session)
    link = svc.resolve_source_link(rows[0])
    assert link is None
