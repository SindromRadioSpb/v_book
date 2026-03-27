from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.infra.sa_models import (
    DictProject,
    DocumentText,
    Library,
    ProcessorRun,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.nlp_runtime import NlpRuntimeStatus
from app.services.process_service import ProcessService


def _reset_db_service() -> None:
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService._ref_managers = {}


def _init_temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(str(db_path))
    try:
        for migration_file in sorted(Path("app/infra/migrations").glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


def _seed_doc(session) -> tuple[int, int]:
    lib = Library(name="L")
    session.add(lib)
    session.flush()
    project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
    session.add(project)
    session.flush()
    corpus = SourceCorpus(project_id=project.project_id, name="C")
    session.add(corpus)
    session.flush()
    doc = SourceDocument(
        corpus_id=corpus.corpus_id,
        file_path="/tmp/a.txt",
        file_name="a.txt",
        file_ext=".txt",
        file_size_bytes=10,
        sha256="sha1",
        status="imported",
    )
    session.add(doc)
    session.flush()
    session.add(DocumentText(doc_id=doc.doc_id, raw_text="shalom"))
    session.commit()
    return int(project.project_id), int(doc.doc_id)


class _Token:
    def __init__(self, text: str, lemma: str, pos: str):
        self.text = text
        self.lemma = lemma
        self.pos = pos


class _Sentence:
    def __init__(self, tokens):
        self.tokens = tokens


class _Engine:
    def process(self, text: str):
        _ = text
        return [_Sentence([_Token("shalom", "shalom", "INTJ")])]

    def get_name(self):
        return "mock"

    def get_version(self):
        return "1.0.0"


def test_get_nlp_engine_no_longer_silently_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.process_service.DBService.get_instance", lambda: SimpleNamespace()
    )
    service = ProcessService()
    monkeypatch.setattr(
        "app.services.process_service.create_stanza_engine",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("missing model")),
    )

    with pytest.raises(RuntimeError, match="missing model"):
        service.get_nlp_engine(use_gpu=False, use_mock=False)


def test_process_document_records_configured_vs_effective_runtime_note(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    runtime_status = NlpRuntimeStatus(
        configured_engine_id="stanza",
        effective_engine_id="mock",
        package_installed=True,
        model_present=False,
        pipeline_init_ok=False,
        smoke_ok=False,
        cuda_available=False,
        runtime_mode="cpu",
        fallback_used=True,
        error_code="model_missing",
        error_detail="Hebrew resources missing",
        remediation="Install model",
        engine_version="1.0.0",
        model_id="he/tokenize,pos,lemma",
        model_path="C:/fake/he",
    )

    try:
        service = ProcessService()
        monkeypatch.setattr(
            service,
            "_resolve_nlp_runtime",
            lambda **kwargs: (_Engine(), runtime_status),
        )

        with db.get_session() as session:
            project_id, doc_id = _seed_doc(session)
            assert (
                service.process_document(
                    session,
                    doc_id,
                    use_mock=True,
                    configured_engine_id="stanza",
                    allow_mock_fallback=True,
                )
                is True
            )
            run = session.execute(
                select(ProcessorRun).order_by(ProcessorRun.run_id.desc())
            ).scalar_one()
            project = session.get(DictProject, project_id)

        note = json.loads(run.note)
        assert note["configured_engine_id"] == "stanza"
        assert note["effective_engine_id"] == "mock"
        assert note["fallback_used"] is True
        assert note["error_code"] == "model_missing"
        assert note["runtime"]["configured_engine_id"] == "stanza"
        assert note["runtime"]["effective_engine_id"] == "mock"
        assert note["runtime"]["fallback_used"] is True
        assert note["runtime"]["reason_code"] == "model_missing"
        assert note["runtime"]["runtime_mode"] == "cpu"
        assert note["runtime"]["probe_summary"]["model_path"] == "C:/fake/he"
        assert project.nlp_engine == "mock"
        assert run.status == "ok"
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
