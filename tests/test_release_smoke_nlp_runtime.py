from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from app.infra.sa_models import DictProject, DocumentText, Library, ProcessorRun, SourceCorpus, SourceDocument
from app.services.db_service import DBService


def _reset_db_service() -> None:
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService._ref_managers = {}


def _load_smoke_module():
    module_path = Path("scripts/release_smoke_nlp_runtime.py").resolve()
    spec = importlib.util.spec_from_file_location("test_release_smoke_nlp_runtime_module", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _seed_source_project(db_path: Path) -> tuple[int, int]:
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()
    try:
        with db.get_session() as session:
            library = Library(name="Smoke Library")
            session.add(library)
            session.flush()

            project = DictProject(
                library_id=library.library_id,
                name="Smoke Project",
                src_lang="he",
                tgt_lang="ru",
            )
            session.add(project)
            session.flush()

            corpus = SourceCorpus(project_id=project.project_id, name="Smoke Corpus")
            session.add(corpus)
            session.flush()

            document = SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path="/tmp/smoke.txt",
                file_name="smoke.txt",
                file_ext=".txt",
                file_size_bytes=42,
                sha256="smoke-sha",
                status="processed",
            )
            session.add(document)
            session.flush()

            session.add(
                DocumentText(
                    doc_id=document.doc_id,
                    raw_text="הילד הגדול קורא ספר חדש.",
                    cleaned_text="הילד הגדול קורא ספר חדש.",
                )
            )
            session.commit()
            return int(project.project_id), int(document.doc_id)
    finally:
        _reset_db_service()


def test_run_db_smoke_builds_project_scoped_db_and_reprocesses(monkeypatch, tmp_path):
    smoke = _load_smoke_module()
    source_db = _init_temp_db()
    _project_id, source_doc_id = _seed_source_project(source_db)
    target_db = tmp_path / "smoke_target.db"

    def _fake_reprocess(self, session, doc_id, **kwargs):
        doc = session.get(SourceDocument, int(doc_id))
        assert doc is not None
        doc.status = "processed"
        session.flush()
        run = ProcessorRun(
            project_id=int(doc.corpus.project_id),
            engine="stanza",
            engine_version="1.11.1",
            status="ok",
            note=json.dumps({"runtime": {"effective_engine_id": "stanza"}}),
        )
        session.add(run)
        session.flush()
        return True

    monkeypatch.setattr(smoke.ProcessService, "reprocess_document", _fake_reprocess)

    try:
        report = smoke._run_db_smoke(
            source_db=source_db,
            copy_db_to=target_db,
            doc_id=source_doc_id,
        )
    finally:
        _reset_db_service()
        source_db.unlink(missing_ok=True)

    assert report["db_copy_strategy"] == "document_scoped_clone"
    assert report["source_doc_id"] == source_doc_id
    assert report["ok"] is True
    assert report["document_status"] == "processed"
    assert report["run_engine"] == "stanza"
    assert report["run_status"] == "ok"
    assert report["runtime_effective"] == "stanza"
    assert Path(report["db_copy"]).exists()
    assert report["doc_id"] > 0
    assert report["project_id"] > 0
