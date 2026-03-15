from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra.fts_manager import ensure_lemma_fts_health, inspect_lemma_fts_parity
from app.infra.sa_models import DictProject, Lemma, LemmaProjectStat, Library
from app.services.dictionary_service import DictionaryService
from scripts import repair_lemma_fts as repair_mod


def _make_engine(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    LemmaProjectStat.__table__.create(engine, checkfirst=True)
    return engine


def _seed(engine) -> tuple[int, int, str]:
    with Session(engine) as session:
        lib = Library(name="L")
        session.add(lib)
        session.flush()
        proj = DictProject(
            library_id=lib.library_id,
            name="P",
            src_lang="he",
            tgt_lang="ru",
        )
        session.add(proj)
        session.flush()
        lemma = Lemma(
            project_id=proj.project_id,
            lemma_text="unique_term",
            pos="NN",
        )
        session.add(lemma)
        session.flush()
        stat = LemmaProjectStat(
            project_id=proj.project_id,
            lemma_id=lemma.lemma_id,
            freq_abs=5,
            doc_freq=1,
        )
        session.add(stat)
        session.commit()
        return int(proj.project_id), int(lemma.lemma_id), str(lemma.lemma_text)


def _install_broken_lemma_fts(db_path: Path, lemma_id: int, lemma_text: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TRIGGER IF EXISTS trg_lemma_fts_ai")
        conn.execute("DROP TRIGGER IF EXISTS trg_lemma_fts_au")
        conn.execute("DROP TRIGGER IF EXISTS trg_lemma_fts_ad")
        conn.execute("DROP TABLE IF EXISTS lemma_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE lemma_fts USING fts5(
                lemma_text,
                tokenize='unicode61 remove_diacritics 1'
            )
            """
        )
        conn.execute(
            "INSERT INTO lemma_fts(rowid, lemma_text) VALUES(?, ?)",
            (lemma_id + 10000, lemma_text),
        )
        conn.commit()
    finally:
        conn.close()


def test_repair_lemma_fts_repairs_rowid_parity_drift(tmp_path: Path) -> None:
    db_path = tmp_path / "lemma_fts_drift.db"
    engine = _make_engine(str(db_path))
    project_id, lemma_id, lemma_text = _seed(engine)
    _install_broken_lemma_fts(db_path, lemma_id, lemma_text)

    with sqlite3.connect(str(db_path)) as conn:
        before = inspect_lemma_fts_parity(conn)
    assert before["healthy"] is False
    assert before["missing_in_fts_count"] == 1
    assert before["extra_in_fts_count"] == 1

    svc = DictionaryService()
    with Session(engine) as session:
        before_results = svc.search_lemmas(
            session,
            project_id,
            filters={"search": "unique_term", "hide_noise": False},
            limit=50,
            offset=0,
        )
        like_count = session.execute(
            text("SELECT COUNT(*) FROM lemma WHERE lemma_text LIKE :term"),
            {"term": "%unique_term%"},
        ).scalar_one()
        fts_raw_count = session.execute(
            text("SELECT COUNT(*) FROM lemma_fts WHERE lemma_fts MATCH :term"),
            {"term": '"unique_term"*'},
        ).scalar_one()
    assert len(before_results) == 1
    assert before_results[0][0].lemma_text == "unique_term"
    assert like_count == 1
    assert fts_raw_count == 1

    summary = repair_mod.repair_lemma_fts(db_path, dry_run=False, backup=False)
    assert summary["status"] == "REPAIRED"
    assert summary["after"]["healthy"] is True
    assert summary["after"]["missing_in_fts_count"] == 0
    assert summary["after"]["extra_in_fts_count"] == 0

    with Session(engine) as session:
        after_results = svc.search_lemmas(
            session,
            project_id,
            filters={"search": "unique_term", "hide_noise": False},
            limit=50,
            offset=0,
        )
    assert len(after_results) == 1
    assert after_results[0][0].lemma_text == "unique_term"

    engine.dispose()


def test_repair_lemma_fts_dry_run_reports_required_action(tmp_path: Path) -> None:
    db_path = tmp_path / "lemma_fts_dry_run.db"
    engine = _make_engine(str(db_path))
    _, lemma_id, lemma_text = _seed(engine)
    _install_broken_lemma_fts(db_path, lemma_id, lemma_text)

    summary = repair_mod.repair_lemma_fts(db_path, dry_run=True, backup=False)
    assert summary["status"] == "FAILED"
    assert "dry-run" in str(summary["error"]).lower()
    assert summary["issues_detected"]

    engine.dispose()


def test_repair_lemma_fts_repairs_semantic_drift(tmp_path: Path) -> None:
    db_path = tmp_path / "lemma_fts_semantic_drift.db"
    engine = _make_engine(str(db_path))
    project_id, lemma_id, _lemma_text = _seed(engine)
    raw = engine.raw_connection()
    try:
        ensure_lemma_fts_health(raw, schema="main", rebuild=True)
    finally:
        raw.close()

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DROP TRIGGER IF EXISTS trg_lemma_fts_ai")
        conn.execute("DROP TRIGGER IF EXISTS trg_lemma_fts_au")
        conn.execute("DROP TRIGGER IF EXISTS trg_lemma_fts_ad")
        conn.execute(
            "UPDATE lemma SET lemma_text = ? WHERE lemma_id = ?",
            ("semantic_shift", lemma_id),
        )
        conn.commit()
        before = inspect_lemma_fts_parity(conn)

    assert before["healthy"] is False
    assert lemma_id in before["unsearchable_sample_ids"]

    svc = DictionaryService()
    with Session(engine) as session:
        before_results = svc.search_lemmas(
            session,
            project_id,
            filters={"search": "semantic_shift", "hide_noise": False},
            limit=50,
            offset=0,
        )
        like_count = session.execute(
            text("SELECT COUNT(*) FROM lemma WHERE lemma_text LIKE :term"),
            {"term": "%semantic_shift%"},
        ).scalar_one()
        fts_raw_count = session.execute(
            text("SELECT COUNT(*) FROM lemma_fts WHERE lemma_fts MATCH :term"),
            {"term": '"semantic_shift"*'},
        ).scalar_one()
    assert len(before_results) == 1
    assert before_results[0][0].lemma_text == "semantic_shift"
    assert like_count == 1
    assert fts_raw_count == 0

    summary = repair_mod.repair_lemma_fts(db_path, dry_run=False, backup=False)
    assert summary["status"] == "REPAIRED"
    assert summary["after"]["healthy"] is True
    assert summary["after"]["unsearchable_sample_ids"] == []

    with Session(engine) as session:
        after_results = svc.search_lemmas(
            session,
            project_id,
            filters={"search": "semantic_shift", "hide_noise": False},
            limit=50,
            offset=0,
        )
        fts_raw_count_after = session.execute(
            text("SELECT COUNT(*) FROM lemma_fts WHERE lemma_fts MATCH :term"),
            {"term": '"semantic_shift"*'},
        ).scalar_one()
    assert len(after_results) == 1
    assert after_results[0][0].lemma_text == "semantic_shift"
    assert fts_raw_count_after == 1

    engine.dispose()
