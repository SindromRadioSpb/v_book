"""Epic 5A PATCH-01: TM entry provenance schema tests.

Tests:
1. promoted_from_cluster_id column exists and is nullable
2. promoted_at_params_hash column exists and is nullable
3. promoted_at_run_id column exists and is nullable
4. promoted_from_cluster_id is plain int (no FK cascade) — survives cluster delete
5. promoted_at_run_id goes NULL when run is deleted (SET NULL)
6. source_status == 'linked' when cluster_id is set
7. source_status == 'source_cluster_missing' when cluster gone but promoted_from set
8. source_status == 'manual' when both cluster_id and promoted_from_cluster_id are None
"""

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    TermCluster,
    TermExtractRun,
    TMEntry,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    lib = Library(library_id=1, name="Lib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(project_id=1, library_id=1, name="P1", src_lang="he", tgt_lang="ru")
    sess.add(proj)
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


def _make_entry(session, *, cluster_id=None, promoted_from=None, run_id=None) -> TMEntry:
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
        promoted_from_cluster_id=promoted_from,
        promoted_at_params_hash="abc123" if promoted_from else None,
        promoted_at_run_id=run_id,
    )
    session.add(entry)
    session.flush()
    return entry


# --- Column existence tests ---


def test_promoted_from_cluster_id_column_exists(session):
    """Column promoted_from_cluster_id is present and nullable."""
    cols = {c["name"] for c in inspect(session.bind).get_columns("tm_entry")}
    assert "promoted_from_cluster_id" in cols


def test_promoted_at_params_hash_column_exists(session):
    """Column promoted_at_params_hash is present and nullable."""
    cols = {c["name"] for c in inspect(session.bind).get_columns("tm_entry")}
    assert "promoted_at_params_hash" in cols


def test_promoted_at_run_id_column_exists(session):
    """Column promoted_at_run_id is present and nullable."""
    cols = {c["name"] for c in inspect(session.bind).get_columns("tm_entry")}
    assert "promoted_at_run_id" in cols


# --- Nullable defaults ---


def test_provenance_columns_default_to_null(session):
    """New TMEntry has all provenance columns NULL by default."""
    entry = _make_entry(session)
    session.refresh(entry)
    assert entry.promoted_from_cluster_id is None
    assert entry.promoted_at_params_hash is None
    assert entry.promoted_at_run_id is None


# --- Permanence: promoted_from_cluster_id survives without FK ---


def test_promoted_from_cluster_id_survives_cluster_delete(session):
    """promoted_from_cluster_id stays set even when the original cluster is gone.

    It is a plain INTEGER with no FK — no cascade, no SET NULL.
    """
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
    cid = cluster.cluster_id

    entry = _make_entry(session, cluster_id=cid, promoted_from=cid)
    session.commit()

    # Delete cluster — cluster_id goes NULL (FK SET NULL), promoted_from stays
    session.delete(cluster)
    session.commit()

    session.refresh(entry)
    assert entry.cluster_id is None, "cluster_id must go NULL (FK SET NULL)"
    assert entry.promoted_from_cluster_id == cid, "promoted_from_cluster_id must survive"


# --- promoted_at_run_id: SET NULL on run deletion ---


def test_promoted_at_run_id_set_null_on_run_delete(session):
    """promoted_at_run_id goes NULL when the extraction run is deleted."""
    run = TermExtractRun(
        project_id=1,
        status="ok",
        enable_ngrams=1,
        include_np=0,
        overwrite=1,
        min_freq=2,
        ngram_ns_json="[2,3]",
        np_max_len=5,
        docs_total=10,
        chunks_total=1,
        params_hash="abc123def456",
    )
    session.add(run)
    session.flush()
    rid = run.run_id

    entry = _make_entry(session, promoted_from=42, run_id=rid)
    entry.promoted_at_params_hash = "abc123def456"
    session.commit()

    session.delete(run)
    session.commit()

    session.refresh(entry)
    assert entry.promoted_at_run_id is None, "run_id must go NULL (FK SET NULL)"
    # params_hash snapshot is preserved (it's just TEXT, no FK)
    assert entry.promoted_at_params_hash == "abc123def456"


# --- source_status property ---


def test_source_status_linked(session):
    """source_status == 'linked' when cluster_id is set."""
    cluster = TermCluster(
        project_id=1,
        canonical_key="שלום",
        representative_he="שלום",
        freq_abs=3,
        doc_freq=1,
        source_kinds="ngram",
    )
    session.add(cluster)
    session.flush()

    entry = _make_entry(session, cluster_id=cluster.cluster_id, promoted_from=cluster.cluster_id)
    assert entry.source_status == "linked"


def test_source_status_source_cluster_missing(session):
    """source_status == 'source_cluster_missing' when cluster gone but provenance set."""
    entry = _make_entry(session, cluster_id=None, promoted_from=999)
    assert entry.source_status == "source_cluster_missing"


def test_source_status_manual(session):
    """source_status == 'manual' when both cluster_id and promoted_from are None."""
    entry = _make_entry(session, cluster_id=None, promoted_from=None)
    assert entry.source_status == "manual"
