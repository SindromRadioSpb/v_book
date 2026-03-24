"""Diagnostic tests for Issues 3.1 and 3.2 — extraction mode cross-layer safety.

Issue 3.1 — Replace Layer wipes preserved layers:
  replace_layer dispatch called _extract_terms_for_project_chunked(overwrite=True).
  At finalization this triggered _clear_existing_terms() which deleted ALL clusters —
  including those that _clear_terms_for_layer intentionally preserved.
  FIXED: overwrite=False is now passed.

Issue 3.2 — Full Overwrite bigrams-only must delete trigram clusters:
  extract_terms_for_project(extraction_mode="overwrite", ngram_ns=(2,)) must delete
  ALL existing clusters (including trigrams from a previous extraction) before
  re-inserting only the newly staged bigrams.

Issue 3.2 (part 2) — Full Overwrite re-extracts ONLY the selected ngram_ns:
  After clearing all terms, Full Overwrite with ngram_ns=(2,) must re-insert
  only bigrams; with ngram_ns=(3,) only trigrams; with ngram_ns=(2,3) both.
  The ngram_ns checkbox selection is honoured end-to-end.
"""

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    Ngram,
    TermCluster,
    TermExtractAccumulator,
    TermExtractRun,
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


# ---------------------------------------------------------------------------
# Issue 3.2 (part 2) — Full Overwrite re-extracts ONLY the selected ngram_ns
#
# Strategy: bypass corpus NLP by pre-seeding TermExtractAccumulator with the
# desired n-gram rows, then call the finalization phase directly:
#   _clear_existing_terms → _store_staged_ngrams → _cluster_terms
# This is the exact code path executed after staging completes.
# ---------------------------------------------------------------------------


def _make_run(sess, project_id: int, ngram_ns_json: str) -> TermExtractRun:
    """Create a TermExtractRun in 'staged' status (staging already done)."""
    r = TermExtractRun(
        project_id=project_id,
        status="staged",
        stage="test",
        enable_ngrams=1,
        include_np=0,
        overwrite=1,
        min_freq=2,
        ngram_ns_json=ngram_ns_json,
        np_max_len=5,
        docs_total=1,
        docs_processed=1,
        chunks_total=1,
        chunks_completed=1,
    )
    sess.add(r)
    sess.commit()
    return r


def _acc(sess, run_id: int, surface: str, n: int, freq: int = 3, doc_freq: int = 2) -> None:
    """Insert a TermExtractAccumulator row simulating a staged n-gram."""
    sess.add(
        TermExtractAccumulator(
            run_id=run_id,
            source_kind="ngram",
            n=n,
            surface_text=surface,
            lemma_phrase=surface,
            pos_pattern="NN " * n,
            freq_abs=freq,
            doc_freq=doc_freq,
        )
    )
    sess.commit()


def _finalize_overwrite(svc: TermExtractionService, session, project_id: int, run_id: int) -> None:
    """Run the Full Overwrite finalization phase: clear all → store staged → cluster."""
    svc._clear_existing_terms(session, project_id)
    svc._store_staged_ngrams(session, project_id, run_id=run_id, total_tokens=1000, overwrite=True)
    svc._cluster_terms(session, project_id, overwrite=True)


def _ngram_n_values(sess, project_id: int) -> set[int]:
    rows = sess.execute(select(Ngram.n).where(Ngram.project_id == project_id)).scalars().all()
    return set(rows)


def _cluster_n_values(sess, project_id: int) -> set[str | None]:
    return _cluster_n_sets(sess, project_id)


def test_full_overwrite_bigrams_only_reextracts_only_bigrams(svc, session):
    """Full Overwrite with only bigrams staged produces only bigrams in Ngram + Cluster tables.

    Scenario: project previously had bigram + trigram clusters (pre-seeded).
    Staged accumulators contain ONLY bigrams (user selected only bigrams checkbox).
    After Full Overwrite finalization: only bigrams must remain.
    """
    _add_cluster(session, 1, "old_bigram", canonical_ngram_n_set([2]))
    _add_cluster(session, 1, "old_trigram", canonical_ngram_n_set([3]))

    run = _make_run(session, 1, "[2]")
    _acc(session, run.run_id, "שני מילים", n=2)  # only bigrams staged

    _finalize_overwrite(svc, session, 1, run.run_id)

    ngram_ns = _ngram_n_values(session, 1)
    cluster_ns = _cluster_n_values(session, 1)
    assert ngram_ns == {
        2
    }, f"Only bigram Ngrams must exist after Full Overwrite [2]; found: {ngram_ns}"
    assert cluster_ns == {
        canonical_ngram_n_set([2])
    }, f"Only bigram clusters must exist; found ngram_n_sets: {cluster_ns}"


def test_full_overwrite_trigrams_only_reextracts_only_trigrams(svc, session):
    """Full Overwrite with only trigrams staged produces only trigrams.

    Scenario: project previously had bigram + trigram clusters.
    Staged accumulators contain ONLY trigrams (user selected only trigrams checkbox).
    After Full Overwrite finalization: only trigrams must remain.
    """
    _add_cluster(session, 1, "old_bigram", canonical_ngram_n_set([2]))
    _add_cluster(session, 1, "old_trigram", canonical_ngram_n_set([3]))

    run = _make_run(session, 1, "[3]")
    _acc(session, run.run_id, "שלש מילים הנה", n=3)  # only trigrams staged

    _finalize_overwrite(svc, session, 1, run.run_id)

    ngram_ns = _ngram_n_values(session, 1)
    cluster_ns = _cluster_n_values(session, 1)
    assert ngram_ns == {
        3
    }, f"Only trigram Ngrams must exist after Full Overwrite [3]; found: {ngram_ns}"
    assert cluster_ns == {
        canonical_ngram_n_set([3])
    }, f"Only trigram clusters must exist; found ngram_n_sets: {cluster_ns}"


def test_full_overwrite_both_layers_reextracts_both(svc, session):
    """Full Overwrite with bigrams+trigrams staged produces both.

    Scenario: project previously had bigram + trigram clusters.
    Staged accumulators contain BOTH bigrams and trigrams (both checkboxes selected).
    After Full Overwrite finalization: both must be present.
    """
    _add_cluster(session, 1, "old_bigram", canonical_ngram_n_set([2]))
    _add_cluster(session, 1, "old_trigram", canonical_ngram_n_set([3]))

    run = _make_run(session, 1, "[2,3]")
    _acc(session, run.run_id, "שני מילים", n=2)
    _acc(session, run.run_id, "שלש מילים הנה", n=3)

    _finalize_overwrite(svc, session, 1, run.run_id)

    ngram_ns = _ngram_n_values(session, 1)
    assert ngram_ns == {
        2,
        3,
    }, f"Both bigram and trigram Ngrams must exist after Full Overwrite [2,3]; found: {ngram_ns}"
