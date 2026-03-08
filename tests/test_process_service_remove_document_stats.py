from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    DocumentText,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    Library,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.ingest_service import IngestService
from app.services.process_service import ProcessService


def _init_temp_db() -> Path:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(str(db_path))
    try:
        migrations_dir = Path("app/infra/migrations")
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            conn.executescript(migration_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_remove_document_stats_cleans_doc_and_project_stats():
    db_path = _init_temp_db()
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            lib = Library(name="L")
            session.add(lib)
            session.flush()
            project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
            session.add(project)
            session.flush()
            project_id = int(project.project_id)
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
                status="processed",
            )
            session.add(doc)
            session.flush()

            lemma = Lemma(project_id=project.project_id, lemma_text="alpha", pos="X")
            session.add(lemma)
            session.flush()

            session.add(
                LemmaDocStat(
                    project_id=project.project_id,
                    doc_id=doc.doc_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=5,
                    sample_sentence_id=None,
                )
            )
            session.add(
                LemmaProjectStat(
                    project_id=project.project_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=5,
                    doc_freq=1,
                    sample_sentence_id=None,
                )
            )
            session.commit()

            svc = ProcessService()
            assert svc.remove_document_stats(session, int(doc.doc_id)) is True
            session.commit()

            assert session.execute(
                select(LemmaDocStat).where(LemmaDocStat.doc_id == int(doc.doc_id))
            ).scalars().all() == []
            assert session.execute(
                select(LemmaProjectStat).where(LemmaProjectStat.project_id == project_id)
            ).scalars().all() == []
            assert session.execute(
                select(Lemma).where(Lemma.project_id == project_id)
            ).scalars().all() == []
    finally:
        DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None
        try:
            db_path.unlink()
        except OSError:
            pass


def test_delete_document_cleans_processed_sentence_references():
    db_path = _init_temp_db()
    DBService.shutdown()
    DBService._instance = None
    DBService._db_manager = None
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        with db.get_session() as session:
            lib = Library(name="L")
            session.add(lib)
            session.flush()
            project = DictProject(library_id=lib.library_id, name="P", src_lang="he", tgt_lang="ru")
            session.add(project)
            session.flush()
            project_id = int(project.project_id)
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
                status="processed",
                sentence_count=1,
            )
            session.add(doc)
            session.flush()
            session.add(
                DocumentText(
                    doc_id=doc.doc_id,
                    raw_text="alpha",
                    cleaned_text="alpha",
                    ocr_used=0,
                )
            )
            sentence = DocumentSentence(
                doc_id=doc.doc_id,
                sent_index=0,
                text="alpha",
                corpus_id=corpus.corpus_id,
            )
            session.add(sentence)
            session.flush()

            lemma = Lemma(project_id=project.project_id, lemma_text="alpha", pos="X")
            session.add(lemma)
            session.flush()

            session.add(
                LemmaDocStat(
                    project_id=project.project_id,
                    doc_id=doc.doc_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=5,
                    sample_sentence_id=sentence.sentence_id,
                )
            )
            session.add(
                LemmaProjectStat(
                    project_id=project.project_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=5,
                    doc_freq=1,
                    sample_sentence_id=sentence.sentence_id,
                )
            )
            session.commit()

            ingest = IngestService()
            assert ingest.delete_document(session, int(doc.doc_id)) is True

            assert session.get(SourceDocument, int(doc.doc_id)) is None
            assert session.get(DocumentText, int(doc.doc_id)) is None
            assert session.execute(
                select(DocumentSentence).where(DocumentSentence.doc_id == int(doc.doc_id))
            ).scalars().all() == []
            assert session.execute(
                select(LemmaDocStat).where(LemmaDocStat.doc_id == int(doc.doc_id))
            ).scalars().all() == []
            assert session.execute(
                select(LemmaProjectStat).where(LemmaProjectStat.project_id == project_id)
            ).scalars().all() == []
            assert session.execute(
                select(Lemma).where(Lemma.project_id == project_id)
            ).scalars().all() == []
    finally:
        DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None
        try:
            db_path.unlink()
        except OSError:
            pass
