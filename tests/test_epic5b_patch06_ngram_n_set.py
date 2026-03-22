"""Epic 5B PATCH-06: ngram_n_set column on term_cluster.

Tests:
1. canonical_ngram_n_set: bigrams only → "[2]"
2. canonical_ngram_n_set: trigrams only → "[3]"
3. canonical_ngram_n_set: bigrams + trigrams → "[2,3]"
4. canonical_ngram_n_set: empty set → None (NP-only cluster)
5. canonical_ngram_n_set: deduplication + sort  (e.g. {3, 2, 2} → "[2,3]")
6. ngram_n_set column exists on term_cluster
7. term_cluster row accepts NULL (NP-only cluster)
8. ngram_n_set stored when cluster created with ngram members
"""

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, Library, TermCluster
from app.services.term_extraction_service import canonical_ngram_n_set


# --- Unit tests for canonical_ngram_n_set ---


def test_canonical_bigrams_only():
    assert canonical_ngram_n_set([2]) == "[2]"


def test_canonical_trigrams_only():
    assert canonical_ngram_n_set([3]) == "[3]"


def test_canonical_bigrams_and_trigrams():
    assert canonical_ngram_n_set([2, 3]) == "[2,3]"


def test_canonical_empty_returns_none():
    assert canonical_ngram_n_set([]) is None


def test_canonical_dedup_and_sort():
    """Deduplication and ascending sort enforced."""
    assert canonical_ngram_n_set([3, 2, 2, 3]) == "[2,3]"
    assert canonical_ngram_n_set({3, 2}) == "[2,3]"
    assert canonical_ngram_n_set([4, 2]) == "[2,4]"


def test_canonical_compact_serialization():
    """No spaces in JSON output."""
    result = canonical_ngram_n_set([2, 3])
    assert " " not in result


# --- Schema tests ---


@pytest.fixture
def session():
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
    sess.commit()

    yield sess
    sess.close()
    engine.dispose()


def test_ngram_n_set_column_exists(session):
    """Column ngram_n_set present on term_cluster."""
    cols = {c["name"] for c in inspect(session.bind).get_columns("term_cluster")}
    assert "ngram_n_set" in cols


def test_ngram_n_set_accepts_null(session):
    """NP-only cluster: ngram_n_set = NULL."""
    cluster = TermCluster(
        project_id=1,
        canonical_key="np_term",
        representative_he="np_term",
        freq_abs=3,
        doc_freq=1,
        source_kinds="np",
        ngram_n_set=None,
    )
    session.add(cluster)
    session.flush()
    session.refresh(cluster)
    assert cluster.ngram_n_set is None


def test_ngram_n_set_stored_for_bigram_cluster(session):
    """Bigram cluster stores ngram_n_set = '[2]'."""
    cluster = TermCluster(
        project_id=1,
        canonical_key="bigram_term",
        representative_he="bigram_term",
        freq_abs=5,
        doc_freq=2,
        source_kinds="ngram",
        ngram_n_set=canonical_ngram_n_set([2]),
    )
    session.add(cluster)
    session.flush()
    session.refresh(cluster)
    assert cluster.ngram_n_set == "[2]"


def test_ngram_n_set_stored_for_mixed_cluster(session):
    """Bigrams+Trigrams cluster stores ngram_n_set = '[2,3]'."""
    cluster = TermCluster(
        project_id=1,
        canonical_key="mixed_term",
        representative_he="mixed_term",
        freq_abs=8,
        doc_freq=3,
        source_kinds="ngram",
        ngram_n_set=canonical_ngram_n_set([2, 3]),
    )
    session.add(cluster)
    session.flush()
    session.refresh(cluster)
    assert cluster.ngram_n_set == "[2,3]"
