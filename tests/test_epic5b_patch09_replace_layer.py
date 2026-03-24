"""Epic 5B PATCH-09: Replace Layer mode — scoped delete by ngram_n_set.

Tests:
1. _clear_terms_for_layer: deletes clusters with matching ngram_n_set
2. _clear_terms_for_layer: preserves clusters with different ngram_n_set
3. _clear_terms_for_layer: preserves NP clusters (ngram_n_set IS NULL)
4. _clear_terms_for_layer: deletes ngrams with matching n-sizes
5. _clear_terms_for_layer: preserves ngrams with different n-sizes
6. _clear_terms_for_layer: empty ngram_ns is a no-op (returns 0)
7. _clear_terms_for_layer: returns correct deleted count
8. replace_layer dispatch: clears layer before re-extraction
9. replace_layer dispatch: resume_latest=False
10. replace_layer dispatch: include_np=False (NP layer preserved)
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    Ngram,
    NgramProjectStat,
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


def _cluster(sess, project_id, key, ngram_n_set):
    """Insert a test cluster with given ngram_n_set."""
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
    return c.cluster_id


def _ngram(sess, project_id, surface, n, source_kind="ngram"):
    """Insert a test ngram."""
    ng = Ngram(
        project_id=project_id,
        n=n,
        surface_text=surface,
        he_canonical=surface,
        lemma_phrase=surface,
        source_kind=source_kind,
    )
    sess.add(ng)
    sess.flush()
    sess.add(NgramProjectStat(project_id=project_id, ngram_id=ng.ngram_id, freq_abs=3, doc_freq=1))
    sess.commit()
    return ng.ngram_id


# ---------------------------------------------------------------------------
# _clear_terms_for_layer tests
# ---------------------------------------------------------------------------


def test_clear_layer_removes_matching_cluster(svc, session):
    """Cluster with ngram_n_set='[2]' is deleted when clearing bigram layer."""
    _cluster(session, 1, "bigram_cluster", canonical_ngram_n_set([2]))
    deleted = svc._clear_terms_for_layer(session, 1, (2,))
    assert deleted == 1
    remaining = (
        session.execute(select(TermCluster).where(TermCluster.project_id == 1)).scalars().all()
    )
    assert len(remaining) == 0


def test_clear_layer_preserves_different_n_set(svc, session):
    """Cluster with ngram_n_set='[3]' is preserved when clearing bigram layer."""
    _cluster(session, 1, "trigram_cluster", canonical_ngram_n_set([3]))
    deleted = svc._clear_terms_for_layer(session, 1, (2,))
    assert deleted == 0
    remaining = (
        session.execute(select(TermCluster).where(TermCluster.project_id == 1)).scalars().all()
    )
    assert len(remaining) == 1


def test_clear_layer_preserves_np_clusters(svc, session):
    """NP clusters (ngram_n_set IS NULL) are never touched by layer clear."""
    _cluster(session, 1, "np_cluster", None)
    deleted = svc._clear_terms_for_layer(session, 1, (2,))
    assert deleted == 0
    remaining = (
        session.execute(select(TermCluster).where(TermCluster.project_id == 1)).scalars().all()
    )
    assert len(remaining) == 1


def test_clear_layer_deletes_matching_ngrams(svc, session):
    """Ngrams with matching n-sizes are deleted."""
    _ngram(session, 1, "bigram_one", n=2)
    svc._clear_terms_for_layer(session, 1, (2,))
    remaining = session.execute(select(Ngram).where(Ngram.project_id == 1)).scalars().all()
    assert len(remaining) == 0


def test_clear_layer_preserves_other_n_ngrams(svc, session):
    """Ngrams with different n-sizes are preserved."""
    _ngram(session, 1, "bigram_one", n=2)
    _ngram(session, 1, "trigram_two", n=3)
    svc._clear_terms_for_layer(session, 1, (2,))
    remaining = session.execute(select(Ngram).where(Ngram.project_id == 1)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].n == 3


def test_clear_layer_empty_ngram_ns_noop(svc, session):
    """Empty ngram_ns tuple returns 0 without touching the DB."""
    _cluster(session, 1, "bigram_cluster", canonical_ngram_n_set([2]))
    deleted = svc._clear_terms_for_layer(session, 1, ())
    assert deleted == 0
    # Cluster still exists
    remaining = (
        session.execute(select(TermCluster).where(TermCluster.project_id == 1)).scalars().all()
    )
    assert len(remaining) == 1


def test_clear_layer_returns_correct_count(svc, session):
    """Returns the number of clusters actually deleted."""
    _cluster(session, 1, "bigram_a", canonical_ngram_n_set([2]))
    _cluster(session, 1, "bigram_b", canonical_ngram_n_set([2]))
    _cluster(session, 1, "trigram_c", canonical_ngram_n_set([3]))
    deleted = svc._clear_terms_for_layer(session, 1, (2,))
    assert deleted == 2


# ---------------------------------------------------------------------------
# replace_layer dispatch tests
# ---------------------------------------------------------------------------


def test_replace_layer_calls_clear_before_extract(svc, session):
    """Replace Layer mode calls _clear_terms_for_layer before extraction."""
    chunked_mock = MagicMock(return_value=MagicMock())
    clear_mock = MagicMock(return_value=0)

    with (
        patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock),
        patch.object(svc, "_clear_terms_for_layer", clear_mock),
    ):
        svc.extract_terms_for_project(session, 1, extraction_mode="replace_layer", ngram_ns=(2,))

    clear_mock.assert_called_once_with(session, 1, (2,))
    chunked_mock.assert_called_once()


def test_replace_layer_passes_overwrite_false_to_chunked(svc, session):
    """replace_layer must pass overwrite=False to _extract_terms_for_project_chunked.

    overwrite=True would cause _clear_existing_terms() to run in finalization,
    wiping clusters from other layers (trigrams, NP) that replace_layer must preserve.
    """
    chunked_mock = MagicMock(return_value=MagicMock())

    with (
        patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock),
        patch.object(svc, "_clear_terms_for_layer", MagicMock(return_value=0)),
    ):
        svc.extract_terms_for_project(session, 1, extraction_mode="replace_layer", ngram_ns=(2,))

    assert (
        chunked_mock.call_args[1].get("overwrite") is False
    ), "replace_layer must pass overwrite=False; overwrite=True would wipe all clusters"


def test_replace_layer_resume_latest_false(svc, session):
    """replace_layer sets resume_latest=False to avoid stale checkpoints."""
    chunked_mock = MagicMock(return_value=MagicMock())

    with (
        patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock),
        patch.object(svc, "_clear_terms_for_layer", MagicMock(return_value=0)),
    ):
        svc.extract_terms_for_project(session, 1, extraction_mode="replace_layer", ngram_ns=(2,))

    assert chunked_mock.call_args[1].get("resume_latest") is False


def test_replace_layer_include_np_false(svc, session):
    """replace_layer passes include_np=False to preserve NP layer."""
    chunked_mock = MagicMock(return_value=MagicMock())

    with (
        patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock),
        patch.object(svc, "_clear_terms_for_layer", MagicMock(return_value=0)),
    ):
        svc.extract_terms_for_project(
            session, 1, extraction_mode="replace_layer", ngram_ns=(2,), include_np=True
        )

    # include_np is forced to False in replace_layer regardless of caller
    assert chunked_mock.call_args[1].get("include_np") is False
