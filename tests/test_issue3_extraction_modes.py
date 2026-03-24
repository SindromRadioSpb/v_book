"""Diagnostic tests for Issues 3.1 and 3.2 — extraction mode cross-layer safety.

Issue 3.1 — Replace Layer wipes preserved layers:
  replace_layer dispatch calls _extract_terms_for_project_chunked(overwrite=True).
  At finalization this triggers _clear_existing_terms() which deletes ALL clusters —
  including those that _clear_terms_for_layer intentionally preserved.

Issue 3.2 — Full Overwrite bigrams-only must delete trigram clusters:
  extract_terms_for_project(extraction_mode="overwrite", ngram_ns=(2,)) must delete
  ALL existing clusters (including trigrams from a previous extraction) before
  re-inserting only the newly staged bigrams.
"""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    TermCluster,
)
from app.services.term_extraction_service import TermExtractionService, canonical_ngram_n_set


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def set_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    Session_ = sessionmaker(bind=engine)
    sess = Session_()

    lib = Library(library_id=1, name="Lib")
    sess.add(lib)
    sess.flush()
    proj = DictProject(project_id=1, library_id=1, name="P1", src_lang="he", tgt_lang="ru")
    sess.add(proj)
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


@pytest.fixture
def svc():
    return TermExtractionService.__new__(TermExtractionService)


def _add_cluster(sess, project_id: int, key: str, ngram_n_set: str | None) -> int:
    """Insert a TermCluster and return its cluster_id."""
    c = TermCluster(
        project_id=project_id,
        canonical_key=key,
        representative_he=key,
        freq_abs=3,
        doc_freq=1,
        source_kinds="ngram" if ngram_n_set else "np",
        ngram_n_set=ngram_n_set,
    )
    sess.add(c)
    sess.commit()
    return int(c.cluster_id)


def _cluster_ids(sess, project_id: int) -> set[int]:
    rows = (
        sess.execute(select(TermCluster.cluster_id).where(TermCluster.project_id == project_id))
        .scalars()
        .all()
    )
    return set(rows)


def _cluster_n_sets(sess, project_id: int) -> set[str | None]:
    rows = (
        sess.execute(select(TermCluster.ngram_n_set).where(TermCluster.project_id == project_id))
        .scalars()
        .all()
    )
    return set(rows)


# ---------------------------------------------------------------------------
# Issue 3.2 — Full Overwrite bigrams-only must delete trigram clusters
# ---------------------------------------------------------------------------


def test_full_overwrite_bigrams_only_deletes_trigram_clusters(svc, session):
    """Full Overwrite with ngram_ns=(2,) must wipe all existing clusters.

    Scenario: project has bigram + trigram clusters from a prior extraction.
    After Full Overwrite bigrams-only (empty corpus → total_docs=0 fast path),
    the trigram cluster must be gone.
    """
    bigram_id = _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
    trigram_id = _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

    assert _cluster_ids(session, 1) == {bigram_id, trigram_id}

    svc.extract_terms_for_project(
        session,
        project_id=1,
        extraction_mode="overwrite",
        ngram_ns=(2,),
        enable_ngrams=True,
        include_np=False,
        overwrite=True,
    )

    # All clusters must be gone (no corpus docs → nothing was re-extracted)
    remaining = _cluster_ids(session, 1)
    assert remaining == set(), (
        f"Full Overwrite should have deleted all clusters; " f"surviving cluster IDs: {remaining}"
    )


def test_full_overwrite_both_layers_deletes_everything(svc, session):
    """Full Overwrite with ngram_ns=(2,3) must wipe all existing clusters."""
    bigram_id = _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
    trigram_id = _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

    svc.extract_terms_for_project(
        session,
        project_id=1,
        extraction_mode="overwrite",
        ngram_ns=(2, 3),
        enable_ngrams=True,
        include_np=False,
        overwrite=True,
    )

    remaining = _cluster_ids(session, 1)
    assert remaining == set(), (
        f"Full Overwrite should have deleted all clusters; " f"surviving cluster IDs: {remaining}"
    )


# ---------------------------------------------------------------------------
# Issue 3.1 — Replace Layer must preserve clusters from other layers
# ---------------------------------------------------------------------------


def test_replace_layer_bigrams_preserves_trigram_clusters(svc, session):
    """Replace Layer [2] must NOT delete trigram clusters.

    Scenario: project has bigram + trigram clusters.
    Replace Layer with ngram_ns=(2,) should delete only bigrams,
    re-extract bigrams (empty corpus → none), and leave trigrams intact.

    This test documents Issue 3.1: if it FAILS, the bug is confirmed.
    """
    bigram_id = _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
    trigram_id = _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

    svc.extract_terms_for_project(
        session,
        project_id=1,
        extraction_mode="replace_layer",
        ngram_ns=(2,),
        enable_ngrams=True,
        include_np=False,
    )

    remaining_n_sets = _cluster_n_sets(session, 1)
    # Trigram cluster must survive; bigram cluster may be gone (cleared + no re-extraction)
    assert canonical_ngram_n_set([3]) in remaining_n_sets, (
        f"Replace Layer [2] must preserve trigram clusters. "
        f"Remaining ngram_n_sets: {remaining_n_sets}"
    )


def test_replace_layer_bigrams_removes_bigram_clusters(svc, session):
    """Replace Layer [2] must remove existing bigram clusters (before re-extraction)."""
    bigram_id = _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))
    _add_cluster(session, 1, "trigram_key", canonical_ngram_n_set([3]))

    svc.extract_terms_for_project(
        session,
        project_id=1,
        extraction_mode="replace_layer",
        ngram_ns=(2,),
        enable_ngrams=True,
        include_np=False,
    )

    remaining_ids = _cluster_ids(session, 1)
    assert bigram_id not in remaining_ids, (
        f"Replace Layer [2] must remove the old bigram cluster. "
        f"Cluster {bigram_id} still present."
    )


def test_replace_layer_preserves_np_clusters(svc, session):
    """Replace Layer [2] must not touch NP clusters (ngram_n_set IS NULL)."""
    np_id = _add_cluster(session, 1, "np_key", None)  # NP cluster
    _add_cluster(session, 1, "bigram_key", canonical_ngram_n_set([2]))

    svc.extract_terms_for_project(
        session,
        project_id=1,
        extraction_mode="replace_layer",
        ngram_ns=(2,),
        enable_ngrams=True,
        include_np=False,
    )

    remaining_ids = _cluster_ids(session, 1)
    assert np_id in remaining_ids, (
        f"Replace Layer [2] must preserve NP clusters. " f"NP cluster {np_id} was deleted."
    )
