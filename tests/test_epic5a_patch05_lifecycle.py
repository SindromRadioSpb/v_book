"""Epic 5A PATCH-05: End-to-end lifecycle tests.

Tests:
1. After re-extraction (cluster deleted): source_status → 'source_cluster_missing'
2. promoted_from_cluster_id preserved after source cluster deleted
3. source_status == 'manual' for lemma-kind entries (cluster_id always None)
4. source_status of TMEntryDTO matches TMEntry.source_status property
5. get_overwrite_impact correctly forecasts linked_tm_entries count
   that will become 'source_cluster_missing' after the overwrite
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.domain.dto import TMEntryDTO
from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    TermCluster,
    TermExtractRun,
    TMEntry,
)
from app.services.term_extraction_service import TermExtractionService


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


def _cluster(session, key="term1") -> TermCluster:
    c = TermCluster(
        project_id=1,
        canonical_key=key,
        representative_he=key,
        freq_abs=5,
        doc_freq=2,
        source_kinds="ngram",
    )
    session.add(c)
    session.flush()
    return c


def _run(session, params_hash="hash1234") -> TermExtractRun:
    r = TermExtractRun(
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
        params_hash=params_hash,
    )
    session.add(r)
    session.flush()
    return r


_ctr = 0


def _entry(session, cluster_id=None, promoted_from=None, params_hash=None) -> TMEntry:
    global _ctr
    _ctr += 1
    e = TMEntry(
        project_id=1,
        kind="term_cluster",
        src_lang="he",
        tgt_lang="ru",
        src_text=f"term_{_ctr}",
        src_norm=f"term_{_ctr}",
        translation="word",
        status="draft",
        origin="import",
        cluster_id=cluster_id,
        promoted_from_cluster_id=promoted_from,
        promoted_at_params_hash=params_hash,
    )
    session.add(e)
    session.flush()
    return e


def test_source_status_after_cluster_delete(session):
    """After cluster deletion, entry becomes 'source_cluster_missing'."""
    cluster = _cluster(session)
    cid = cluster.cluster_id
    entry = _entry(session, cluster_id=cid, promoted_from=cid, params_hash="abc")
    session.commit()

    assert entry.source_status == "linked"

    session.delete(cluster)
    session.commit()
    session.refresh(entry)

    assert entry.cluster_id is None
    assert entry.promoted_from_cluster_id == cid
    assert entry.source_status == "source_cluster_missing"


def test_promoted_from_preserved_after_cluster_delete(session):
    """promoted_from_cluster_id retains original cid even after cluster gone."""
    cluster = _cluster(session)
    cid = cluster.cluster_id
    entry = _entry(session, cluster_id=cid, promoted_from=cid, params_hash="abc")
    session.commit()

    session.delete(cluster)
    session.commit()
    session.refresh(entry)

    assert entry.promoted_from_cluster_id == cid


def test_source_status_manual_for_no_source(session):
    """Entry with no cluster link and no promoted_from is 'manual'."""
    entry = _entry(session, cluster_id=None, promoted_from=None)
    assert entry.source_status == "manual"


def test_dto_source_status_matches_sa_model(session):
    """TMEntryDTO.source_status mirrors TMEntry.source_status for all three states."""
    cluster = _cluster(session)
    cid = cluster.cluster_id

    # Linked
    e_linked = _entry(session, cluster_id=cid, promoted_from=cid, params_hash="h1")
    session.commit()
    dto_linked = TMEntryDTO(
        tm_id=e_linked.tm_id,
        project_id=1,
        kind="term_cluster",
        src_lang="he",
        tgt_lang="ru",
        src_text=e_linked.src_text,
        src_norm=e_linked.src_norm,
        translation="word",
        translation_norm=None,
        pos=None,
        domain=None,
        notes=None,
        status="draft",
        confidence=None,
        origin="import",
        source_ref=None,
        created_at="",
        updated_at="",
        approved_at=None,
        approved_by=None,
        is_noise=0,
        noise_reason=None,
        norm_text=None,
        lemma_id=None,
        cluster_id=cid,
        ngram_id=None,
        promoted_from_cluster_id=cid,
        promoted_at_params_hash="h1",
    )
    assert dto_linked.source_status == e_linked.source_status == "linked"

    # Source cluster missing
    session.delete(cluster)
    session.commit()
    session.refresh(e_linked)
    dto_linked.cluster_id = None  # simulate what happens after delete
    assert dto_linked.source_status == "source_cluster_missing"
    assert e_linked.source_status == "source_cluster_missing"

    # Manual
    dto_manual = TMEntryDTO(
        tm_id=0,
        project_id=1,
        kind="term_cluster",
        src_lang="he",
        tgt_lang="ru",
        src_text="x",
        src_norm="x",
        translation="y",
        translation_norm=None,
        pos=None,
        domain=None,
        notes=None,
        status="draft",
        confidence=None,
        origin="import",
        source_ref=None,
        created_at="",
        updated_at="",
        approved_at=None,
        approved_by=None,
        is_noise=0,
        noise_reason=None,
        norm_text=None,
        lemma_id=None,
        cluster_id=None,
        ngram_id=None,
    )
    assert dto_manual.source_status == "manual"


def test_overwrite_impact_predicts_source_cluster_missing(session):
    """get_overwrite_impact.linked_tm_entries == entries that WILL become source_cluster_missing."""
    cluster = _cluster(session)
    cid = cluster.cluster_id
    _entry(session, cluster_id=cid, promoted_from=cid, params_hash="h")
    _entry(session, cluster_id=cid, promoted_from=cid, params_hash="h")
    _entry(session, cluster_id=None, promoted_from=cid, params_hash="h")  # already missing
    session.commit()

    impact = TermExtractionService.get_overwrite_impact(session, 1)
    # 2 linked entries will lose their link (become source_cluster_missing)
    assert impact["linked_tm_entries"] == 2
    assert impact["clusters"] == 1
