from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.infra.nlp_snapshot_codec import build_sentence_text_hash, deserialize_nlp_sentences
from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    DocumentText,
    Library,
    SentenceNLPSnapshot,
    SourceCorpus,
    SourceDocument,
)
from app.services.db_service import DBService
from app.services.process_service import ProcessService
from app.services.term_extraction_service import TermExtractionService


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
    session.add(DocumentText(doc_id=doc.doc_id, raw_text="alpha beta. gamma delta"))
    session.commit()
    return int(project.project_id), int(doc.doc_id)


class _Token:
    def __init__(self, text: str, lemma: str, pos: str, morph: str = ""):
        self.text = text
        self.lemma = lemma
        self.pos = pos
        self.morph = morph


class _Sentence:
    def __init__(self, text: str, tokens):
        self.text = text
        self.tokens = tokens


class _ProcessEngine:
    def process(self, text: str):
        normalized = str(text or "").strip().lower().replace(".", " ")
        words = [word for word in normalized.split() if word]
        if not words:
            return []
        return [_Sentence(str(text or ""), [_Token(word, word, "NOUN") for word in words])]

    def get_name(self):
        return "fake"

    def get_version(self):
        return "1"


class _FailingEngine:
    def process(self, text: str):
        raise AssertionError(
            f"term extraction should have reused snapshots instead of reparsing: {text}"
        )

    def get_name(self):
        return "failing"

    def get_version(self):
        return "1"


def test_process_document_persists_sentence_nlp_snapshots(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        service = ProcessService()
        monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _ProcessEngine())

        with db.get_session() as session:
            _project_id, doc_id = _seed_doc(session)
            assert service.process_document(session, doc_id, use_mock=True) is True
            snapshots = (
                session.execute(
                    select(SentenceNLPSnapshot).order_by(SentenceNLPSnapshot.sentence_id.asc())
                )
                .scalars()
                .all()
            )
            sentences = (
                session.execute(
                    select(DocumentSentence)
                    .where(DocumentSentence.doc_id == doc_id)
                    .order_by(DocumentSentence.sent_index.asc())
                )
                .scalars()
                .all()
            )

        assert len(sentences) == 2
        assert len(snapshots) == 2
        assert snapshots[0].engine == "fake"
        assert snapshots[0].engine_version == "1"
        assert snapshots[0].token_count == 2
        assert snapshots[0].sentence_text_hash == build_sentence_text_hash(sentences[0].text)
        decoded = deserialize_nlp_sentences(snapshots[0].payload_json)
        assert len(decoded) == 1
        assert [token.lemma for token in decoded[0].tokens] == ["alpha", "beta"]
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)


def test_term_extraction_prefers_sentence_nlp_snapshots(monkeypatch) -> None:
    db_path = _init_temp_db()
    _reset_db_service()
    DBService.initialize(db_path)
    db = DBService.get_instance()

    try:
        process_service = ProcessService()
        monkeypatch.setattr(process_service, "get_nlp_engine", lambda **kwargs: _ProcessEngine())

        with db.get_session() as session:
            project_id, doc_id = _seed_doc(session)
            assert process_service.process_document(session, doc_id, use_mock=True) is True

        monkeypatch.setattr(
            "app.services.term_extraction_service.classify_phrase",
            lambda _text: SimpleNamespace(
                entity_class="WORD_HE",
                is_noise=False,
                noise_reason=None,
                norm_text="alpha_beta",
            ),
        )
        term_service = TermExtractionService()
        monkeypatch.setattr(term_service, "get_nlp_engine", lambda **kwargs: _FailingEngine())

        with db.get_session() as session:
            report = term_service.extract_terms_for_project(
                session,
                project_id,
                enable_ngrams=True,
                include_np=False,
                min_freq=1,
                overwrite=True,
            )

        assert report.success is True
        assert report.ngrams_extracted >= 1
    finally:
        _reset_db_service()
        db_path.unlink(missing_ok=True)
