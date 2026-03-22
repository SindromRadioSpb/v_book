"""Epic 5A PATCH-02: Populate provenance at promotion time.

Tests:
1. Provenance populated when cluster is promoted via _attach_source_links
2. promoted_from_cluster_id not overwritten on second promotion (idempotent)
3. Provenance captured from last 'ok' extraction run (params_hash + run_id)
4. No run → provenance fields stay NULL (graceful fallback)
5. Bulk creation via update_item_translation also populates provenance
6. promoted_from_cluster_id is set even when no extraction run exists
"""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    TermCluster,
    TermExtractRun,
    TMEntry,
    UserDictionary,
    UserDictionaryItem,
)
from app.services.user_dictionary_service import UserDictionaryService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    sess = Session_()

    lib = Library(library_id=1, name="Lib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(project_id=1, library_id=1, name="P1", src_lang="he", tgt_lang="ru")
    sess.add(proj)
    sess.flush()
    d = UserDictionary(name="Dict")
    sess.add(d)
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


def _make_run(session, params_hash: str = "abc123def456", status: str = "ok") -> TermExtractRun:
    run = TermExtractRun(
        project_id=1,
        status=status,
        enable_ngrams=1,
        include_np=0,
        overwrite=1,
        min_freq=2,
        ngram_ns_json="[2,3]",
        np_max_len=5,
        docs_total=10,
        chunks_total=1,
        params_hash=params_hash,
    )
    session.add(run)
    session.flush()
    return run


def _make_cluster(session) -> TermCluster:
    cluster = TermCluster(
        project_id=1,
        canonical_key="מילה",
        representative_he="מילה",
        freq_abs=5,
        doc_freq=2,
        source_kinds="ngram",
    )
    session.add(cluster)
    session.flush()
    return cluster


def _make_item(session, cluster_id: int, dict_id: int) -> UserDictionaryItem:
    item = UserDictionaryItem(
        dictionary_id=dict_id,
        kind="term_cluster",
        src_lang="he",
        tgt_lang="ru",
        src_text="מילה",
        src_norm="מילה",
        canonical_hash=f"hash_{cluster_id}",
        origin_project_id=1,
        origin_entity_type="term_cluster",
        origin_entity_id=str(cluster_id),
    )
    session.add(item)
    session.flush()
    return item


def _make_entry(session, cluster_id: int | None = None) -> TMEntry:
    entry = TMEntry(
        project_id=1,
        kind="term_cluster",
        src_lang="he",
        tgt_lang="ru",
        src_text="מילה",
        src_norm="מילה",
        translation="слово",
        status="draft",
        origin="import",
        cluster_id=cluster_id,
    )
    session.add(entry)
    session.flush()
    return entry


def test_provenance_populated_on_first_attach(db):
    """_attach_source_links sets all provenance fields at first promotion."""
    svc = UserDictionaryService()
    cluster = _make_cluster(db)
    run = _make_run(db, params_hash="deadbeef1234")
    db.commit()

    dict_id = db.execute(select(UserDictionary.dictionary_id)).scalar_one()
    item = _make_item(db, cluster.cluster_id, dict_id)
    entry = _make_entry(db)

    svc._attach_source_links(entry, item, db)

    assert entry.cluster_id == cluster.cluster_id
    assert entry.promoted_from_cluster_id == cluster.cluster_id
    assert entry.promoted_at_params_hash == "deadbeef1234"
    assert entry.promoted_at_run_id == run.run_id


def test_promoted_from_cluster_id_not_overwritten(db):
    """Second _attach_source_links call does not overwrite promoted_from_cluster_id."""
    svc = UserDictionaryService()
    cluster = _make_cluster(db)
    _make_run(db, params_hash="first_hash_1234")
    db.commit()

    dict_id = db.execute(select(UserDictionary.dictionary_id)).scalar_one()
    item = _make_item(db, cluster.cluster_id, dict_id)

    # First promotion
    entry = _make_entry(db)
    svc._attach_source_links(entry, item, db)
    original_from_id = entry.promoted_from_cluster_id
    original_hash = entry.promoted_at_params_hash

    # Add a second run (newer)
    _make_run(db, params_hash="second_hash_5678")
    db.commit()

    # Re-link (e.g. after some state reset)
    entry.cluster_id = None
    svc._attach_source_links(entry, item, db)

    # promoted_from_cluster_id must NOT be overwritten (idempotent)
    assert entry.promoted_from_cluster_id == original_from_id
    assert entry.promoted_at_params_hash == original_hash


def test_provenance_uses_last_ok_run(db):
    """Uses the latest 'ok' run, not a failed/running run."""
    svc = UserDictionaryService()
    cluster = _make_cluster(db)

    # Create a failed run (should be ignored)
    _make_run(db, params_hash="failed_hash_1234", status="failed")
    # Create the successful run
    ok_run = _make_run(db, params_hash="ok_hash_5678", status="ok")
    db.commit()

    dict_id = db.execute(select(UserDictionary.dictionary_id)).scalar_one()
    item = _make_item(db, cluster.cluster_id, dict_id)
    entry = _make_entry(db)
    svc._attach_source_links(entry, item, db)

    assert entry.promoted_at_params_hash == "ok_hash_5678"
    assert entry.promoted_at_run_id == ok_run.run_id


def test_provenance_no_run_stays_null(db):
    """When no extraction run exists, params_hash and run_id stay NULL."""
    svc = UserDictionaryService()
    cluster = _make_cluster(db)
    # No run created
    dict_id = db.execute(select(UserDictionary.dictionary_id)).scalar_one()
    item = _make_item(db, cluster.cluster_id, dict_id)
    entry = _make_entry(db)
    svc._attach_source_links(entry, item, db)

    assert entry.cluster_id == cluster.cluster_id
    assert entry.promoted_from_cluster_id == cluster.cluster_id
    assert entry.promoted_at_params_hash is None
    assert entry.promoted_at_run_id is None


def test_bulk_add_populates_provenance(db):
    """bulk_add_items via _materialize_tm_entries_for_items populates provenance."""
    svc = UserDictionaryService()
    cluster = _make_cluster(db)
    run = _make_run(db, params_hash="bulk_hash_abcd")
    db.commit()

    dict_id = db.execute(select(UserDictionary.dictionary_id)).scalar_one()
    svc.bulk_add_items(
        db,
        dictionary_id=dict_id,
        items=[
            {
                "kind": "term_cluster",
                "src_lang": "he",
                "tgt_lang": "ru",
                "src_text": "מילה",
                "origin_project_id": 1,
                "origin_entity_type": "term_cluster",
                "origin_entity_id": cluster.cluster_id,
            }
        ],
    )
    db.commit()

    item = db.execute(
        select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dict_id)
    ).scalar_one()
    entry = db.get(TMEntry, item.origin_tm_entry_id)
    assert entry is not None
    assert entry.promoted_from_cluster_id == cluster.cluster_id
    assert entry.promoted_at_params_hash == "bulk_hash_abcd"
    assert entry.promoted_at_run_id == run.run_id
