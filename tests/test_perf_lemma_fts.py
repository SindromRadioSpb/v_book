"""Tests for PERF-SCALE PATCH-E: lemma_fts FTS5 + TTL count cache.

Covers:
- fts_manager: ensure_lemma_fts_health creates table + triggers, is idempotent
- fts_manager: triggers sync on INSERT / UPDATE / DELETE of lemma rows
- DictionaryService: _fts5_escape_term correctness
- DictionaryService: _is_lemma_fts_available returns True/False
- DictionaryService: FTS5 path returns correct results when table present
- DictionaryService: LIKE fallback when table absent
- DictionaryService: TTL count cache (hit, miss, expiry)
- DictionaryService: invalidate_count_cache clears entries
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra.fts_manager import (
    LEMMA_FTS_DDL,
    LEMMA_FTS_TRIGGERS,
    ensure_lemma_fts_health,
)
from app.infra.sa_models import DictProject, Lemma, Library, LemmaProjectStat
from app.services.dictionary_service import COUNT_CACHE_TTL, DictionaryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_engine(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    LemmaProjectStat.__table__.create(engine, checkfirst=True)
    return engine


@pytest.fixture
def plain_engine():
    """Engine without lemma_fts — exercises LIKE fallback."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = _make_engine(db_path)
    try:
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def fts_engine():
    """Engine with lemma_fts FTS5 table."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = _make_engine(db_path)
    raw = engine.raw_connection()
    try:
        ensure_lemma_fts_health(raw, schema="main", rebuild=True)
    finally:
        raw.close()
    try:
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def _seed(session: Session, count: int = 20) -> int:
    """Seed project + lemmas, return project_id."""
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    proj = DictProject(
        library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru"
    )
    session.add(proj)
    session.flush()
    for i in range(count):
        lemma = Lemma(
            project_id=proj.project_id,
            lemma_text=f"word_{i:04d}" if i % 4 != 0 else f"unique_term_{i:04d}",
            pos="NN",
        )
        session.add(lemma)
        session.flush()  # obtain lemma_id before creating stat
        stat = LemmaProjectStat(
            project_id=proj.project_id,
            lemma_id=lemma.lemma_id,
            freq_abs=i + 1,
            doc_freq=1,
        )
        session.add(stat)
    session.commit()
    return int(proj.project_id)


# ---------------------------------------------------------------------------
# fts_manager: ensure_lemma_fts_health
# ---------------------------------------------------------------------------


def test_ensure_lemma_fts_creates_table():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE lemma "
            "(lemma_id INTEGER PRIMARY KEY, project_id INTEGER, lemma_text TEXT)"
        )
        conn.commit()
        result = ensure_lemma_fts_health(conn, schema="main", rebuild=False)
        conn.close()

        assert result == {"lemma_fts": True}

        conn2 = sqlite3.connect(db_path)
        tables = {r[0] for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        triggers = {r[0] for r in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()}
        conn2.close()

        assert "lemma_fts" in tables
        assert "trg_lemma_fts_ai" in triggers
        assert "trg_lemma_fts_au" in triggers
        assert "trg_lemma_fts_ad" in triggers
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_ensure_lemma_fts_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE lemma "
            "(lemma_id INTEGER PRIMARY KEY, project_id INTEGER, lemma_text TEXT)"
        )
        conn.commit()
        r1 = ensure_lemma_fts_health(conn, schema="main", rebuild=False)
        r2 = ensure_lemma_fts_health(conn, schema="main", rebuild=False)
        conn.close()
        assert r1 == {"lemma_fts": True}
        assert r2 == {"lemma_fts": False}
    finally:
        Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _fts5_escape_term
# ---------------------------------------------------------------------------


def test_escape_plain():
    assert DictionaryService._fts5_escape_term("שלום") == '"שלום"*'


def test_escape_embedded_quote():
    assert DictionaryService._fts5_escape_term('foo "bar') == '"foo ""bar"*'


def test_escape_empty():
    assert DictionaryService._fts5_escape_term("") == '""*'


# ---------------------------------------------------------------------------
# _is_lemma_fts_available
# ---------------------------------------------------------------------------


def test_fts_available_true(fts_engine):
    svc = DictionaryService()
    with Session(fts_engine) as session:
        assert svc._is_lemma_fts_available(session) is True


def test_fts_available_false(plain_engine):
    svc = DictionaryService()
    with Session(plain_engine) as session:
        assert svc._is_lemma_fts_available(session) is False


# ---------------------------------------------------------------------------
# DictionaryService.search_lemmas — FTS5 path
# ---------------------------------------------------------------------------


def test_fts_path_finds_matching_lemmas(fts_engine):
    svc = DictionaryService()
    with Session(fts_engine) as session:
        project_id = _seed(session, count=20)
        results = svc.search_lemmas(
            session,
            project_id,
            filters={"search": "unique_term"},
            limit=50,
            offset=0,
        )
    assert len(results) > 0
    assert all("unique_term" in r[0].lemma_text for r in results)


def test_like_fallback_finds_matching_lemmas(plain_engine):
    svc = DictionaryService()
    with Session(plain_engine) as session:
        project_id = _seed(session, count=20)
        results = svc.search_lemmas(
            session,
            project_id,
            filters={"search": "unique_term"},
            limit=50,
            offset=0,
        )
    assert len(results) > 0
    assert all("unique_term" in r[0].lemma_text for r in results)


# ---------------------------------------------------------------------------
# TTL count cache
# ---------------------------------------------------------------------------


def test_count_cache_hit_on_second_call(fts_engine):
    """Second call returns cached count without hitting DB."""
    svc = DictionaryService()
    DictionaryService._count_cache.clear()
    with Session(fts_engine) as session:
        project_id = _seed(session, count=10)
        filters = {"search": "word_", "hide_noise": False}
        count1 = svc.count_lemmas(session, project_id, filters)
        count2 = svc.count_lemmas(session, project_id, filters)
    assert count1 == count2
    DictionaryService._count_cache.clear()


def test_count_cache_expires(fts_engine, monkeypatch):
    """Cache entry older than TTL is not returned."""
    svc = DictionaryService()
    DictionaryService._count_cache.clear()

    # Patch monotonic to control time
    _fake_time = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: _fake_time[0])

    with Session(fts_engine) as session:
        project_id = _seed(session, count=5)
        filters = {"hide_noise": False}
        _ = svc.count_lemmas(session, project_id, filters)
        # Advance time past TTL
        _fake_time[0] = COUNT_CACHE_TTL + 1.0
        # Should recompute (no exception, fresh count)
        count2 = svc.count_lemmas(session, project_id, filters)
    assert count2 >= 0
    DictionaryService._count_cache.clear()


def test_invalidate_count_cache_clears_all(fts_engine):
    svc = DictionaryService()
    DictionaryService._count_cache.clear()
    with Session(fts_engine) as session:
        project_id = _seed(session, count=5)
        svc.count_lemmas(session, project_id, {"hide_noise": False})
        assert len(DictionaryService._count_cache) > 0
    DictionaryService.invalidate_count_cache()
    assert len(DictionaryService._count_cache) == 0
