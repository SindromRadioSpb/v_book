from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from types import MethodType

from sqlalchemy import select

from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    DocumentText,
    Lemma,
    LemmaDocStat,
    LemmaProjectStat,
    Library,
    SentencePronunciation,
    SourceCorpus,
    SourceDocument,
    TermCluster,
)
from app.services.db_service import DBService
from app.services.ingest_service import IngestService
from app.services.process_service import ProcessService
from app.services.sentences_workspace_service import SentencesWorkspaceService


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
            corpus_id = int(corpus.corpus_id)
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


def test_remove_document_stats_cleans_only_document_orphans_and_keeps_shared_lemmas():
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

            doc_a = SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path="/tmp/a.txt",
                file_name="a.txt",
                file_ext=".txt",
                file_size_bytes=10,
                sha256="sha_a",
                status="processed",
            )
            doc_b = SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path="/tmp/b.txt",
                file_name="b.txt",
                file_ext=".txt",
                file_size_bytes=10,
                sha256="sha_b",
                status="processed",
            )
            session.add_all([doc_a, doc_b])
            session.flush()

            lemma_shared = Lemma(project_id=project.project_id, lemma_text="shared", pos="X")
            lemma_only_a = Lemma(project_id=project.project_id, lemma_text="only_a", pos="X")
            lemma_only_b = Lemma(project_id=project.project_id, lemma_text="only_b", pos="X")
            session.add_all([lemma_shared, lemma_only_a, lemma_only_b])
            session.flush()

            session.add_all(
                [
                    LemmaDocStat(
                        project_id=project.project_id,
                        doc_id=doc_a.doc_id,
                        lemma_id=lemma_shared.lemma_id,
                        freq_abs=2,
                        sample_sentence_id=None,
                    ),
                    LemmaDocStat(
                        project_id=project.project_id,
                        doc_id=doc_b.doc_id,
                        lemma_id=lemma_shared.lemma_id,
                        freq_abs=3,
                        sample_sentence_id=None,
                    ),
                    LemmaDocStat(
                        project_id=project.project_id,
                        doc_id=doc_a.doc_id,
                        lemma_id=lemma_only_a.lemma_id,
                        freq_abs=5,
                        sample_sentence_id=None,
                    ),
                    LemmaDocStat(
                        project_id=project.project_id,
                        doc_id=doc_b.doc_id,
                        lemma_id=lemma_only_b.lemma_id,
                        freq_abs=7,
                        sample_sentence_id=None,
                    ),
                    LemmaProjectStat(
                        project_id=project.project_id,
                        lemma_id=lemma_shared.lemma_id,
                        freq_abs=5,
                        doc_freq=2,
                        sample_sentence_id=None,
                    ),
                    LemmaProjectStat(
                        project_id=project.project_id,
                        lemma_id=lemma_only_a.lemma_id,
                        freq_abs=5,
                        doc_freq=1,
                        sample_sentence_id=None,
                    ),
                    LemmaProjectStat(
                        project_id=project.project_id,
                        lemma_id=lemma_only_b.lemma_id,
                        freq_abs=7,
                        doc_freq=1,
                        sample_sentence_id=None,
                    ),
                ]
            )
            session.commit()

            svc = ProcessService()
            assert svc.remove_document_stats(session, int(doc_a.doc_id)) is True
            session.commit()

            remaining_doc_stats = session.execute(
                select(LemmaDocStat).order_by(LemmaDocStat.doc_id, LemmaDocStat.lemma_id)
            ).scalars().all()
            remaining_proj_stats = session.execute(
                select(LemmaProjectStat).order_by(LemmaProjectStat.lemma_id)
            ).scalars().all()
            remaining_lemmas = session.execute(
                select(Lemma).order_by(Lemma.lemma_id)
            ).scalars().all()

            assert {(row.doc_id, row.lemma_id) for row in remaining_doc_stats} == {
                (int(doc_b.doc_id), int(lemma_shared.lemma_id)),
                (int(doc_b.doc_id), int(lemma_only_b.lemma_id)),
            }
            assert {(row.lemma_id, row.freq_abs, row.doc_freq) for row in remaining_proj_stats} == {
                (int(lemma_shared.lemma_id), 3, 1),
                (int(lemma_only_b.lemma_id), 7, 1),
            }
            assert [lemma.lemma_text for lemma in remaining_lemmas] == ["shared", "only_b"]
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
            corpus_id = int(corpus.corpus_id)
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


def test_reprocess_document_clears_old_sentences_before_rebuild():
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
            corpus = SourceCorpus(project_id=project.project_id, name="C")
            session.add(corpus)
            session.flush()
            corpus_id = int(corpus.corpus_id)
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
            sentence = DocumentSentence(
                doc_id=doc.doc_id,
                sent_index=0,
                text="old sentence",
                corpus_id=corpus.corpus_id,
            )
            session.add(sentence)
            session.flush()
            session.add(
                SentencePronunciation(
                    sentence_id=sentence.sentence_id,
                    lang="he",
                    src_hash="h1",
                    niqqud_text="old",
                    source="auto_phonikud",
                    is_override=0,
                    qc_status="pending",
                    review_status="auto",
                    sanitizer_version="1",
                )
            )
            lemma = Lemma(project_id=project.project_id, lemma_text="alpha", pos="X")
            session.add(lemma)
            session.flush()
            session.add(
                LemmaDocStat(
                    project_id=project.project_id,
                    doc_id=doc.doc_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=2,
                    sample_sentence_id=sentence.sentence_id,
                )
            )
            session.add(
                LemmaProjectStat(
                    project_id=project.project_id,
                    lemma_id=lemma.lemma_id,
                    freq_abs=2,
                    doc_freq=1,
                    sample_sentence_id=sentence.sentence_id,
                )
            )
            session.add(
                TermCluster(
                    project_id=project.project_id,
                    canonical_key="c1",
                    representative_he="term",
                    representative_lemma="term",
                    pinned_example_sent_id=sentence.sentence_id,
                )
            )
            session.commit()

            svc = ProcessService()

            def _fake_process(self, session, doc_id, use_gpu=False, use_mock=False):
                remaining = session.execute(
                    select(DocumentSentence).where(DocumentSentence.doc_id == int(doc_id))
                ).scalars().all()
                assert remaining == []
                session.expunge_all()
                rebuilt = DocumentSentence(
                    doc_id=int(doc_id),
                    sent_index=0,
                    text="new sentence",
                    corpus_id=corpus_id,
                )
                session.add(rebuilt)
                doc_row = session.get(SourceDocument, int(doc_id))
                doc_row.status = "processed"
                doc_row.sentence_count = 1
                return True

            svc.process_document = MethodType(_fake_process, svc)
            assert svc.reprocess_document(session, int(doc.doc_id), use_mock=True) is True
            session.commit()

            rows = session.execute(
                select(DocumentSentence).where(DocumentSentence.doc_id == int(doc.doc_id))
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].text == "new sentence"
            assert session.execute(select(SentencePronunciation)).scalars().all() == []
            cluster = session.execute(select(TermCluster)).scalar_one()
            assert cluster.pinned_example_sent_id is None
            proj_stats = session.execute(select(LemmaProjectStat)).scalars().all()
            assert proj_stats == []
    finally:
        DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None
        try:
            db_path.unlink()
        except OSError:
            pass


def test_process_document_populates_sentence_corpus_id_for_sentences_workspace():
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
            corpus = SourceCorpus(project_id=project_id, name="C")
            session.add(corpus)
            session.flush()
            corpus_id = int(corpus.corpus_id)
            doc = SourceDocument(
                corpus_id=corpus_id,
                file_path="/tmp/a.txt",
                file_name="a.txt",
                file_ext=".txt",
                file_size_bytes=10,
                sha256="sha1",
                status="imported",
            )
            session.add(doc)
            session.flush()
            session.add(
                DocumentText(
                    doc_id=doc.doc_id,
                    raw_text="בית ספר גדול. בית הספר החדש. הספר הזה טוב.",
                    cleaned_text=None,
                    ocr_used=0,
                )
            )
            session.commit()

            svc = ProcessService()
            assert svc.process_document(session, int(doc.doc_id), use_mock=True) is True
            session.commit()

            rows = session.execute(
                select(DocumentSentence).where(DocumentSentence.doc_id == int(doc.doc_id))
            ).scalars().all()
            assert len(rows) == 3
            assert {row.corpus_id for row in rows} == {corpus_id}

            ws = SentencesWorkspaceService()
            listed = ws.list_sentences(session, project_id=project_id, page=1, page_size=10)
            assert len(listed) == 3
            assert {dto.doc_id for dto in listed} == {int(doc.doc_id)}
    finally:
        DBService.shutdown()
        DBService._instance = None
        DBService._db_manager = None
        try:
            db_path.unlink()
        except OSError:
            pass
