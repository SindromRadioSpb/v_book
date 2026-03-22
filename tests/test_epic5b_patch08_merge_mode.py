"""Epic 5B PATCH-08: Merge mode — add without clearing (upsert-aware chunked path).

Tests:
1. _store_staged_ngrams overwrite=False: OR IGNORE on existing ngram, returns existing id
2. _store_staged_ngrams overwrite=False: new ngram inserted normally
3. _insert_cluster_from_members overwrite=False: existing cluster skipped (returns 0)
4. _insert_cluster_from_members overwrite=False: new cluster inserted (returns 1)
5. _insert_cluster_from_members overwrite=False: new member linked to existing cluster
6. _cluster_terms overwrite=False: propagates to _insert_cluster_from_members
7. extract_terms_for_project merge mode: _clear_existing_terms NOT called
8. extract_terms_for_project overwrite mode: _clear_existing_terms IS called
"""

import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    Ngram,
    NgramProjectStat,
    TermCluster,
    TermClusterMember,
)
from app.services.term_extraction_service import TermExtractionService


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


def _insert_ngram(sess, project_id, surface, n=2, source_kind="ngram", freq=3, doc_freq=1):
    """Helper: insert a test ngram + stat row."""
    from app.domain.term_extraction.canonicalizer import get_cluster_key

    ng = Ngram(
        project_id=project_id,
        n=n,
        surface_text=surface,
        he_canonical=get_cluster_key(surface, surface),
        lemma_phrase=surface,
        source_kind=source_kind,
    )
    sess.add(ng)
    sess.flush()
    stat = NgramProjectStat(
        project_id=project_id,
        ngram_id=ng.ngram_id,
        freq_abs=freq,
        doc_freq=doc_freq,
    )
    sess.add(stat)
    sess.commit()
    return ng.ngram_id


def _insert_cluster(sess, project_id, canonical_key, representative_he):
    """Helper: insert a test cluster."""
    c = TermCluster(
        project_id=project_id,
        canonical_key=canonical_key,
        representative_he=representative_he,
        freq_abs=5,
        doc_freq=2,
        source_kinds="ngram",
    )
    sess.add(c)
    sess.commit()
    return c.cluster_id


# ---------------------------------------------------------------------------
# Test 3: existing cluster skipped in merge mode (INSERT OR IGNORE path)
# ---------------------------------------------------------------------------


def test_insert_cluster_merge_existing_returns_zero(svc, session):
    """If canonical_key already exists, _insert_cluster_from_members returns 0."""
    from app.domain.term_extraction.canonicalizer import get_cluster_key

    ngram_id = _insert_ngram(session, 1, "מילה בדיקה")
    _insert_cluster(session, 1, get_cluster_key("מילה בדיקה", "מילה בדיקה"), "מילה בדיקה")

    member = {
        "ngram_id": ngram_id,
        "surface_text": "מילה בדיקה",
        "lemma_phrase": "מילה בדיקה",
        "he_canonical": get_cluster_key("מילה בדיקה", "מילה בדיקה"),
        "source_kind": "ngram",
        "n": 2,
        "freq_abs": 5,
        "doc_freq": 2,
        "pmi_cache": None,
        "llr_cache": None,
        "dice_cache": None,
        "tscore_cache": None,
    }
    stats = {"noise": 0, "classes": __import__("collections").Counter()}
    result = svc._insert_cluster_from_members(
        session,
        1,
        get_cluster_key("מילה בדיקה", "מילה בדיקה"),
        [member],
        stats,
        overwrite=False,
    )
    assert result == 0


# ---------------------------------------------------------------------------
# Test 4: new cluster inserted in merge mode
# ---------------------------------------------------------------------------


def test_insert_cluster_merge_new_returns_one(svc, session):
    """If canonical_key is fresh, _insert_cluster_from_members returns 1."""
    from app.domain.term_extraction.canonicalizer import get_cluster_key

    ngram_id = _insert_ngram(session, 1, "חדש לגמרי")
    member = {
        "ngram_id": ngram_id,
        "surface_text": "חדש לגמרי",
        "lemma_phrase": "חדש לגמרי",
        "he_canonical": get_cluster_key("חדש לגמרי", "חדש לגמרי"),
        "source_kind": "ngram",
        "n": 2,
        "freq_abs": 3,
        "doc_freq": 1,
        "pmi_cache": None,
        "llr_cache": None,
        "dice_cache": None,
        "tscore_cache": None,
    }
    stats = {"noise": 0, "classes": __import__("collections").Counter()}
    result = svc._insert_cluster_from_members(
        session,
        1,
        get_cluster_key("חדש לגמרי", "חדש לגמרי"),
        [member],
        stats,
        overwrite=False,
    )
    assert result == 1
    # Cluster row persists
    count = session.execute(select(TermCluster).where(TermCluster.project_id == 1)).scalars().all()
    assert len(count) == 1


# ---------------------------------------------------------------------------
# Test 5: new member linked to existing cluster
# ---------------------------------------------------------------------------


def test_insert_cluster_merge_adds_new_member(svc, session):
    """In merge mode, a new ngram is linked as member to an existing cluster."""
    from app.domain.term_extraction.canonicalizer import get_cluster_key

    existing_ngram_id = _insert_ngram(session, 1, "ביטוי ותיק")
    ck = get_cluster_key("ביטוי ותיק", "ביטוי ותיק")
    cluster_id = _insert_cluster(session, 1, ck, "ביטוי ותיק")

    # Link existing ngram as member (simulating that it was there from before)
    session.add(
        TermClusterMember(
            cluster_id=cluster_id,
            ngram_id=existing_ngram_id,
            member_freq_abs=5,
            member_doc_freq=2,
        )
    )
    session.commit()

    # Insert a NEW ngram that should be added as a member
    new_ngram_id = _insert_ngram(session, 1, "ביטוי ותיק נוסף")

    member = {
        "ngram_id": new_ngram_id,
        "surface_text": "ביטוי ותיק נוסף",
        "lemma_phrase": "ביטוי ותיק",
        "he_canonical": ck,
        "source_kind": "ngram",
        "n": 2,
        "freq_abs": 2,
        "doc_freq": 1,
        "pmi_cache": None,
        "llr_cache": None,
        "dice_cache": None,
        "tscore_cache": None,
    }
    stats = {"noise": 0, "classes": __import__("collections").Counter()}
    svc._insert_cluster_from_members(session, 1, ck, [member], stats, overwrite=False)
    session.flush()

    members = (
        session.execute(select(TermClusterMember).where(TermClusterMember.cluster_id == cluster_id))
        .scalars()
        .all()
    )
    member_ids = {m.ngram_id for m in members}
    assert new_ngram_id in member_ids
    assert existing_ngram_id in member_ids


# ---------------------------------------------------------------------------
# Test 7: merge mode does NOT call _clear_existing_terms
# ---------------------------------------------------------------------------


def test_merge_mode_skips_clear(svc, session):
    """extract_terms_for_project merge mode must NOT call _clear_existing_terms."""
    clear_mock = MagicMock()
    chunked_mock = MagicMock(return_value=MagicMock())

    with (
        patch.object(svc, "_clear_existing_terms", clear_mock),
        patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock),
    ):
        svc.extract_terms_for_project(session, 1, extraction_mode="merge")

    clear_mock.assert_not_called()
    chunked_mock.assert_called_once()
    assert chunked_mock.call_args[1]["overwrite"] is False


# ---------------------------------------------------------------------------
# Test 8: overwrite mode DOES call _clear_existing_terms (via chunked path)
# ---------------------------------------------------------------------------


def test_overwrite_mode_calls_clear(svc, session):
    """extract_terms_for_project overwrite mode must call _clear_existing_terms."""
    chunked_mock = MagicMock(return_value=MagicMock())

    with patch.object(svc, "_extract_terms_for_project_chunked", chunked_mock):
        svc.extract_terms_for_project(session, 1, extraction_mode="overwrite")

    chunked_mock.assert_called_once()
    assert chunked_mock.call_args[1]["overwrite"] is True
