"""Unit tests for scripts/collect_queryplan_evidence.py."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "collect_queryplan_evidence.py"
    spec = importlib.util.spec_from_file_location("collect_queryplan_evidence", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_minimal_db(path: Path) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
CREATE TABLE dict_project (
  project_id INTEGER PRIMARY KEY,
  src_lang TEXT,
  tgt_lang TEXT
);
CREATE TABLE schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE source_corpus (
  corpus_id INTEGER PRIMARY KEY,
  project_id INTEGER
);
CREATE TABLE source_document (
  doc_id INTEGER PRIMARY KEY,
  corpus_id INTEGER,
  file_name TEXT,
  tag TEXT
);
CREATE TABLE lemma_doc_stat (
  project_id INTEGER,
  lemma_id INTEGER,
  doc_id INTEGER,
  freq_abs INTEGER
);
CREATE TABLE lemma (
  lemma_id INTEGER PRIMARY KEY,
  project_id INTEGER,
  lemma_text TEXT,
  pos TEXT,
  is_noise INTEGER
);
CREATE TABLE lemma_project_stat (
  project_id INTEGER,
  lemma_id INTEGER,
  freq_abs INTEGER,
  doc_freq INTEGER
);
CREATE TABLE term_cluster (
  cluster_id INTEGER PRIMARY KEY,
  project_id INTEGER,
  representative_he TEXT,
  freq_abs INTEGER,
  doc_freq INTEGER
);
CREATE TABLE term_search (
  term_rowid INTEGER PRIMARY KEY,
  project_id INTEGER,
  kind TEXT,
  he_term TEXT
);
CREATE TABLE tm_entry (
  tm_id INTEGER PRIMARY KEY,
  project_id INTEGER,
  src_text TEXT,
  translation TEXT,
  status TEXT,
  updated_at TEXT
);
CREATE TABLE tm_global (
  tm_global_id INTEGER PRIMARY KEY,
  src_lang TEXT,
  tgt_lang TEXT,
  src_norm TEXT,
  src_text TEXT,
  translation TEXT,
  status TEXT
);
CREATE TABLE document_sentence (
  sentence_id INTEGER PRIMARY KEY,
  doc_id INTEGER,
  text TEXT
);
INSERT INTO dict_project(project_id, src_lang, tgt_lang) VALUES (1, 'he', 'ru');
INSERT INTO schema_meta(key, value) VALUES ('schema_version', '35');
INSERT INTO source_corpus(corpus_id, project_id) VALUES (11, 1);
INSERT INTO source_document(doc_id, corpus_id, file_name, tag) VALUES (101, 11, 'wiki_doc.txt', 'wiki');
INSERT INTO lemma(lemma_id, project_id, lemma_text, pos, is_noise) VALUES (201, 1, 'שלום', 'NOUN', 0);
INSERT INTO lemma_project_stat(project_id, lemma_id, freq_abs, doc_freq) VALUES (1, 201, 5, 1);
INSERT INTO lemma_doc_stat(project_id, lemma_id, doc_id, freq_abs) VALUES (1, 201, 101, 5);
INSERT INTO term_cluster(cluster_id, project_id, representative_he, freq_abs, doc_freq) VALUES (301, 1, 'שלום עולם', 3, 1);
INSERT INTO term_search(term_rowid, project_id, kind, he_term) VALUES (401, 1, 'term', 'שלום');
INSERT INTO tm_entry(tm_id, project_id, src_text, translation, status, updated_at) VALUES (501, 1, 'שלום', 'привет', 'approved', '2026-03-06T00:00:00Z');
INSERT INTO tm_global(tm_global_id, src_lang, tgt_lang, src_norm, src_text, translation, status) VALUES (601, 'he', 'ru', 'שלום', 'שלום', 'привет', 'approved');
INSERT INTO document_sentence(sentence_id, doc_id, text) VALUES (701, 101, 'שלום עולם');
"""
    )
    con.commit()
    con.close()


def test_collect_queryplan_evidence_generates_json_and_md(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "_is_expected_j_path", lambda p: True)
    db = tmp_path / "queryplan_fixture.db"
    out_dir = tmp_path / "out"
    _create_minimal_db(db)

    rc = mod.run(
        [
            "--db-path",
            str(db),
            "--project-id",
            "1",
            "--search-term",
            "wiki",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    json_files = list(out_dir.glob("queryplan_evidence_*.json"))
    md_files = list(out_dir.glob("queryplan_evidence_*.md"))
    assert json_files
    assert md_files
    payload = json_files[0].read_text(encoding="utf-8")
    assert '"schema_version": 35' in payload


def test_collect_queryplan_evidence_rejects_m_drive() -> None:
    mod = _load_module()
    try:
        mod.run(["--db-path", r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db"])
    except RuntimeError as exc:
        assert "Forbidden db-path on M:" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for forbidden M: path")
