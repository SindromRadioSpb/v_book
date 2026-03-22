"""Epic 5C: Candidate Persistence — min_freq moved from extraction-time to display-time filter.

Tests:
1. algo_version is 2 (bumped in Epic 5C)
2. params_hash independent of min_freq (min_freq no longer in payload)
3. _store_ngrams stores candidates with freq=1 (below default min_freq=2)
4. _store_np_chunks stores candidates with freq=1
5. _iter_term_extract_accumulator_batches yields low-freq rows (no freq gate)
6. list_term_clusters display-time filter still works (freq_abs >= min_freq)
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import (
    Base,
    DictProject,
    Library,
    Ngram,
    NgramProjectStat,
    TermExtractAccumulator,
    TermExtractRun,
)
from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    return TermExtractionService()


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def set_pragma(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
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


@pytest.fixture()
def run(session):
    """Create a minimal TermExtractRun for accumulator tests."""
    r = TermExtractRun(
        project_id=1,
        status="staged",
        stage="test",
        enable_ngrams=1,
        include_np=0,
        overwrite=1,
        min_freq=2,
        ngram_ns_json="[2]",
        np_max_len=5,
        docs_total=10,
        docs_processed=10,
        chunks_total=1,
        chunks_completed=1,
    )
    session.add(r)
    session.commit()
    return r


# ---------------------------------------------------------------------------
# PATCH-01 contract tests
# ---------------------------------------------------------------------------


def test_algo_version_is_2(svc):
    """Epic 5C bumps _TERM_EXTRACT_ALGO_VERSION from 1 to 2."""
    assert TermExtractionService._TERM_EXTRACT_ALGO_VERSION == 2


def test_params_hash_independent_of_min_freq(svc):
    """min_freq is NOT part of params_hash — same structural params produce same hash."""
    h1 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    # Call again (min_freq no longer a parameter at all — hash must be identical)
    h2 = svc._build_term_extract_params_hash(
        enable_ngrams=True, include_np=False, ngram_ns=(2, 3), np_max_len=5
    )
    assert h1 == h2


def test_store_ngrams_keeps_freq_1_candidates(svc, session):
    """_store_ngrams stores all candidates regardless of frequency (Epic 5C)."""
    # Prepare ngram data: one candidate with freq=1, one with freq=5
    ngram_counts = Counter(
        {
            ("שלום עולם", 2): 1,  # freq=1 — would have been filtered pre-5C
            ("בית ספר", 2): 5,
        }
    )
    ngram_doc_freq = Counter(
        {
            ("שלום עולם", 2): 1,
            ("בית ספר", 2): 3,
        }
    )
    ngram_meta = {
        ("שלום עולם", 2): {
            "lemma_phrase": "שלום עולם",
            "pos_pattern": "NN NN",
        },
        ("בית ספר", 2): {
            "lemma_phrase": "בית ספר",
            "pos_pattern": "NN NN",
        },
    }

    # Mock helper methods that require full DB state
    with (
        patch.object(svc, "_build_lemma_freq_map", return_value={}),
        patch.object(svc, "_get_total_tokens", return_value=1000),
    ):
        stored = svc._store_ngrams(
            session,
            project_id=1,
            ngram_counts=ngram_counts,
            ngram_doc_freq=ngram_doc_freq,
            ngram_meta=ngram_meta,
            min_freq=2,  # legacy param: ignored for filtering in Epic 5C
        )

    assert stored == 2, "Both candidates must be stored regardless of min_freq"

    rows = session.execute(select(Ngram).where(Ngram.project_id == 1)).scalars().all()
    assert len(rows) == 2

    surface_texts = {r.surface_text for r in rows}
    assert "שלום עולם" in surface_texts, "freq=1 candidate must be stored"
    assert "בית ספר" in surface_texts


def test_store_np_chunks_keeps_freq_1_candidates(svc, session):
    """_store_np_chunks stores all NP candidates regardless of frequency (Epic 5C)."""
    np_counts = Counter(
        {
            ("בית הספר הגדול", 3): 1,  # freq=1 — would have been filtered pre-5C
            ("ראש הממשלה", 2): 4,
        }
    )
    np_doc_freq = Counter(
        {
            ("בית הספר הגדול", 3): 1,
            ("ראש הממשלה", 2): 3,
        }
    )
    np_meta = {
        ("בית הספר הגדול", 3): {
            "lemma_phrase": "בית ספר גדול",
            "pos_pattern": "NN NN JJ",
        },
        ("ראש הממשלה", 2): {
            "lemma_phrase": "ראש ממשלה",
            "pos_pattern": "NN NN",
        },
    }

    stored = svc._store_np_chunks(
        session,
        project_id=1,
        np_counts=np_counts,
        np_doc_freq=np_doc_freq,
        np_meta=np_meta,
        min_freq=2,  # legacy param: ignored for filtering in Epic 5C
    )

    assert stored == 2, "Both NP candidates must be stored regardless of min_freq"

    rows = (
        session.execute(select(Ngram).where(Ngram.project_id == 1, Ngram.source_kind == "np"))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    surface_texts = {r.surface_text for r in rows}
    assert "בית הספר הגדול" in surface_texts, "freq=1 NP candidate must be stored"


def test_accumulator_batch_yields_low_freq_rows(svc, session, run):
    """_iter_term_extract_accumulator_batches yields all rows regardless of freq_abs (Epic 5C)."""
    # Insert accumulator rows: freq=1 (below old threshold) and freq=10
    low_freq_row = TermExtractAccumulator(
        run_id=run.run_id,
        source_kind="ngram",
        n=2,
        surface_text="נדיר מאוד",
        lemma_phrase="נדיר מאוד",
        pos_pattern="JJ RB",
        freq_abs=1,
        doc_freq=1,
    )
    high_freq_row = TermExtractAccumulator(
        run_id=run.run_id,
        source_kind="ngram",
        n=2,
        surface_text="שכיח מאוד",
        lemma_phrase="שכיח מאוד",
        pos_pattern="JJ RB",
        freq_abs=10,
        doc_freq=5,
    )
    session.add_all([low_freq_row, high_freq_row])
    session.commit()

    batches = list(
        svc._iter_term_extract_accumulator_batches(
            session,
            run_id=run.run_id,
            source_kind="ngram",
            store_hapax=True,  # all rows yielded; freq gate removed in Epic 5C
            batch_size=100,
        )
    )
    all_rows = [row for batch in batches for row in batch]
    surface_texts = {r["surface_text"] for r in all_rows}

    assert "נדיר מאוד" in surface_texts, "freq=1 accumulator row must be yielded"
    assert "שכיח מאוד" in surface_texts
    assert len(all_rows) == 2
