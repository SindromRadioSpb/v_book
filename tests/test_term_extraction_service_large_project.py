from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    DictProject,
    DocumentSentence,
    Lemma,
    LemmaProjectStat,
    Library,
    Ngram,
    NgramProjectStat,
    SourceCorpus,
    SourceDocument,
    TermExtractAccumulator,
    TermExtractRun,
    TermCluster,
    TermClusterMember,
)
from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService


def test_extract_terms_collects_before_overwrite(monkeypatch):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    service = TermExtractionService()
    order: list[str] = []

    class _Session:
        def get(self, model, project_id):
            assert model is DictProject
            assert project_id == 1
            return SimpleNamespace(
                nlp_engine="mock",
                last_extract_np_max_len=None,
                last_extract_min_freq=None,
                last_extract_include_np=None,
                last_extract_at=None,
                updated_at=None,
            )

        def commit(self):
            order.append("commit")

        def rollback(self):
            order.append("rollback")

    ngram_key = ("term one", 2)
    np_key = ("term np", 2)

    monkeypatch.setattr(
        service,
        "_collect_ngrams",
        lambda *args, **kwargs: (
            order.append("collect_ngrams") or Counter({ngram_key: 3}),
            Counter({ngram_key: 2}),
            {ngram_key: {"lemma_phrase": "term one", "pos_pattern": "NOUN|NOUN"}},
        ),
    )
    monkeypatch.setattr(
        service,
        "_collect_np_chunks",
        lambda *args, **kwargs: (
            order.append("collect_np") or Counter({np_key: 2}),
            Counter({np_key: 1}),
            {np_key: {"lemma_phrase": "term np", "pos_pattern": "NOUN|NOUN"}},
        ),
    )
    monkeypatch.setattr(service, "_clear_existing_terms", lambda *args, **kwargs: order.append("clear"))
    monkeypatch.setattr(service, "_store_ngrams", lambda *args, **kwargs: order.append("store_ngrams") or 1)
    monkeypatch.setattr(service, "_store_np_chunks", lambda *args, **kwargs: order.append("store_np") or 1)
    monkeypatch.setattr(service, "_cluster_terms", lambda *args, **kwargs: order.append("cluster") or 2)

    report = service._extract_terms_for_project_legacy(
        _Session(),
        1,
        enable_ngrams=True,
        include_np=True,
        min_freq=2,
        ngram_ns=(2, 3),
        np_max_len=5,
        overwrite=True,
    )

    assert report.success is True
    assert report.ngrams_extracted == 1
    assert report.np_chunks_extracted == 1
    assert report.clusters_created == 2
    assert order == [
        "collect_ngrams",
        "collect_np",
        "clear",
        "store_ngrams",
        "store_np",
        "cluster",
        "commit",
    ]


def test_extract_terms_for_project_small_pipeline(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    engine = create_engine(f"sqlite:///{tmp_path / 'term_extract.db'}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceCorpus.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    DocumentSentence.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    LemmaProjectStat.__table__.create(engine, checkfirst=True)
    Ngram.__table__.create(engine, checkfirst=True)
    NgramProjectStat.__table__.create(engine, checkfirst=True)
    TermExtractRun.__table__.create(engine, checkfirst=True)
    TermExtractAccumulator.__table__.create(engine, checkfirst=True)
    TermCluster.__table__.create(engine, checkfirst=True)
    TermClusterMember.__table__.create(engine, checkfirst=True)

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
            return [
                _Sentence(
                    [
                        _Token("beit", "beit", "NOUN"),
                        _Token("sefer", "sefer", "NOUN"),
                    ]
                )
            ]

        def get_name(self):
            return "fake"

        def get_version(self):
            return "1"

    monkeypatch.setattr(
        "app.services.term_extraction_service.classify_phrase",
        lambda _text: SimpleNamespace(
            entity_class="WORD_HE",
            is_noise=False,
            noise_reason=None,
            norm_text="beit_sefer",
        ),
    )

    service = TermExtractionService()
    monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="project", src_lang="he", tgt_lang="ru", nlp_engine="mock")
        session.add(project)
        session.flush()
        corpus = SourceCorpus(project_id=project.project_id, name="corpus")
        session.add(corpus)
        session.flush()
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path="/tmp/doc.txt",
            file_name="doc.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256="sha",
            status="processed",
        )
        session.add(doc)
        session.flush()
        session.add(DocumentSentence(doc_id=doc.doc_id, sent_index=0, text="beit sefer"))
        lemma1 = Lemma(project_id=project.project_id, lemma_text="beit", pos="NOUN")
        lemma2 = Lemma(project_id=project.project_id, lemma_text="sefer", pos="NOUN")
        session.add_all([lemma1, lemma2])
        session.flush()
        session.add_all(
            [
                LemmaProjectStat(project_id=project.project_id, lemma_id=lemma1.lemma_id, freq_abs=3, doc_freq=1),
                LemmaProjectStat(project_id=project.project_id, lemma_id=lemma2.lemma_id, freq_abs=3, doc_freq=1),
            ]
        )
        session.commit()

        report = service.extract_terms_for_project(
            session,
            int(project.project_id),
            enable_ngrams=True,
            include_np=False,
            min_freq=1,
            overwrite=True,
        )

        ngram_count = session.execute(select(Ngram)).scalars().all()
        cluster_count = session.execute(select(TermCluster)).scalars().all()
        member_count = session.execute(select(TermClusterMember)).scalars().all()

    engine.dispose()

    assert report.success is True
    assert report.ngrams_extracted == 1
    assert report.clusters_created == 1
    assert len(ngram_count) == 1
    assert len(cluster_count) == 1
    assert len(member_count) == 1
    assert cluster_count[0].source_kinds == "ngram"
    assert member_count[0].member_doc_freq == 1


def test_cluster_terms_backfills_canonical_and_preserves_source_kinds(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    engine = create_engine(f"sqlite:///{tmp_path / 'term_cluster.db'}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    Ngram.__table__.create(engine, checkfirst=True)
    NgramProjectStat.__table__.create(engine, checkfirst=True)
    TermCluster.__table__.create(engine, checkfirst=True)
    TermClusterMember.__table__.create(engine, checkfirst=True)

    monkeypatch.setattr(
        "app.services.term_extraction_service.classify_phrase",
        lambda _text: SimpleNamespace(
            entity_class="WORD_HE",
            is_noise=False,
            noise_reason=None,
            norm_text="alpha_beta",
        ),
    )

    service = TermExtractionService()

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="project", src_lang="he", tgt_lang="ru", nlp_engine="mock")
        session.add(project)
        session.flush()

        ng1 = Ngram(
            project_id=project.project_id,
            n=2,
            surface_text="alpha beta",
            he_canonical=None,
            lemma_phrase="alpha beta",
            source_kind="ngram",
            pos_pattern="NOUN|NOUN",
        )
        ng2 = Ngram(
            project_id=project.project_id,
            n=2,
            surface_text="alpha beta",
            he_canonical="alpha_beta",
            lemma_phrase="alpha beta",
            source_kind="np",
            pos_pattern="NOUN|NOUN",
        )
        session.add_all([ng1, ng2])
        session.flush()
        session.add_all(
            [
                NgramProjectStat(project_id=project.project_id, ngram_id=ng1.ngram_id, freq_abs=4, doc_freq=2),
                NgramProjectStat(project_id=project.project_id, ngram_id=ng2.ngram_id, freq_abs=3, doc_freq=1),
            ]
        )
        session.commit()

        clusters_created = service._cluster_terms(session, int(project.project_id))
        session.commit()

        clusters = session.execute(select(TermCluster)).scalars().all()
        members = session.execute(select(TermClusterMember)).scalars().all()
        refreshed_ng1 = session.get(Ngram, ng1.ngram_id)

    engine.dispose()

    assert clusters_created == 1
    assert refreshed_ng1 is not None
    assert refreshed_ng1.he_canonical == "alpha_beta"
    assert len(clusters) == 1
    assert clusters[0].source_kinds == "ngram,np"
    assert clusters[0].freq_abs == 7
    assert clusters[0].doc_freq == 2
    assert len(members) == 2
    assert sorted(member.member_doc_freq for member in members) == [1, 2]


def test_extract_terms_chunked_run_resumes_after_cancel(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    engine = create_engine(f"sqlite:///{tmp_path / 'term_chunked_resume.db'}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceCorpus.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    DocumentSentence.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    LemmaProjectStat.__table__.create(engine, checkfirst=True)
    Ngram.__table__.create(engine, checkfirst=True)
    NgramProjectStat.__table__.create(engine, checkfirst=True)
    TermExtractRun.__table__.create(engine, checkfirst=True)
    TermExtractAccumulator.__table__.create(engine, checkfirst=True)
    TermCluster.__table__.create(engine, checkfirst=True)
    TermClusterMember.__table__.create(engine, checkfirst=True)

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
            return [_Sentence([_Token("alpha", "alpha", "NOUN"), _Token("beta", "beta", "NOUN")])]

        def get_name(self):
            return "fake"

        def get_version(self):
            return "1"

    monkeypatch.setattr(
        "app.services.term_extraction_service.classify_phrase",
        lambda _text: SimpleNamespace(
            entity_class="WORD_HE",
            is_noise=False,
            noise_reason=None,
            norm_text="alpha_beta",
        ),
    )

    service = TermExtractionService()
    monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

    cancel_state = {"should_cancel": False, "calls": 0}
    original_upsert = service._upsert_term_extract_accumulators

    def _upsert_then_cancel(*args, **kwargs):
        result = original_upsert(*args, **kwargs)
        cancel_state["calls"] += 1
        cancel_state["should_cancel"] = True
        return result

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="project", src_lang="he", tgt_lang="ru", nlp_engine="mock")
        session.add(project)
        session.flush()
        corpus = SourceCorpus(project_id=project.project_id, name="corpus")
        session.add(corpus)
        session.flush()
        for idx in range(2):
            doc = SourceDocument(
                corpus_id=corpus.corpus_id,
                file_path=f"/tmp/doc_{idx}.txt",
                file_name=f"doc_{idx}.txt",
                file_ext=".txt",
                file_size_bytes=10,
                sha256=f"sha-{idx}",
                status="processed",
            )
            session.add(doc)
            session.flush()
            session.add(DocumentSentence(doc_id=doc.doc_id, sent_index=0, text="alpha beta"))
        lemma1 = Lemma(project_id=project.project_id, lemma_text="alpha", pos="NOUN")
        lemma2 = Lemma(project_id=project.project_id, lemma_text="beta", pos="NOUN")
        session.add_all([lemma1, lemma2])
        session.flush()
        session.add_all(
            [
                LemmaProjectStat(project_id=project.project_id, lemma_id=lemma1.lemma_id, freq_abs=5, doc_freq=2),
                LemmaProjectStat(project_id=project.project_id, lemma_id=lemma2.lemma_id, freq_abs=5, doc_freq=2),
            ]
        )
        session.commit()

        monkeypatch.setattr(service, "_upsert_term_extract_accumulators", _upsert_then_cancel)
        cancelled = service.extract_terms_for_project(
            session,
            int(project.project_id),
            enable_ngrams=True,
            include_np=False,
            min_freq=1,
            overwrite=True,
            batch_size=1,
            cancel_check=lambda: bool(cancel_state["should_cancel"]),
        )

        assert cancelled.cancelled is True
        assert cancelled.run_id is not None
        assert cancelled.docs_processed == 1
        assert cancel_state["calls"] == 1

        staged_rows = session.execute(select(TermExtractAccumulator)).scalars().all()
        staged_run = session.get(TermExtractRun, cancelled.run_id)
        assert len(staged_rows) == 1
        assert staged_run is not None
        assert staged_run.status == "cancelled"

        monkeypatch.setattr(service, "_upsert_term_extract_accumulators", original_upsert)
        cancel_state["should_cancel"] = False

        resumed = service.extract_terms_for_project(
            session,
            int(project.project_id),
            enable_ngrams=True,
            include_np=False,
            min_freq=1,
            overwrite=True,
            batch_size=1,
            cancel_check=lambda: False,
        )

        clusters = session.execute(select(TermCluster)).scalars().all()
        members = session.execute(select(TermClusterMember)).scalars().all()
        stats = session.execute(select(NgramProjectStat)).scalars().all()
        remaining_stage_rows = session.execute(select(TermExtractAccumulator)).scalars().all()
        resumed_run = session.get(TermExtractRun, cancelled.run_id)

    engine.dispose()

    assert resumed.success is True
    assert resumed.run_id == cancelled.run_id
    assert resumed.docs_processed == 2
    assert len(clusters) == 1
    assert len(members) == 1
    assert len(stats) == 1
    assert stats[0].freq_abs == 2
    assert stats[0].doc_freq == 2
    assert remaining_stage_rows == []
    assert resumed_run is not None
    assert resumed_run.status == "ok"


def test_extract_terms_chunked_state_callback_includes_run_metadata_and_pause_resume(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(DBService, "_instance", SimpleNamespace())
    engine = create_engine(f"sqlite:///{tmp_path / 'term_chunked_state.db'}")
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceCorpus.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    DocumentSentence.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    LemmaProjectStat.__table__.create(engine, checkfirst=True)
    Ngram.__table__.create(engine, checkfirst=True)
    NgramProjectStat.__table__.create(engine, checkfirst=True)
    TermExtractRun.__table__.create(engine, checkfirst=True)
    TermExtractAccumulator.__table__.create(engine, checkfirst=True)
    TermCluster.__table__.create(engine, checkfirst=True)
    TermClusterMember.__table__.create(engine, checkfirst=True)

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
            return [_Sentence([_Token("alpha", "alpha", "NOUN"), _Token("beta", "beta", "NOUN")])]

        def get_name(self):
            return "fake"

        def get_version(self):
            return "1"

    monkeypatch.setattr(
        "app.services.term_extraction_service.classify_phrase",
        lambda _text: SimpleNamespace(
            entity_class="WORD_HE",
            is_noise=False,
            noise_reason=None,
            norm_text="alpha_beta",
        ),
    )

    service = TermExtractionService()
    monkeypatch.setattr(service, "get_nlp_engine", lambda **kwargs: _Engine())

    pause_state = {"remaining_true": 2}
    states: list[dict] = []

    def _pause_check() -> bool:
        if pause_state["remaining_true"] > 0:
            pause_state["remaining_true"] -= 1
            return True
        return False

    with Session(engine) as session:
        lib = Library(name="lib")
        session.add(lib)
        session.flush()
        project = DictProject(
            library_id=lib.library_id,
            name="project",
            src_lang="he",
            tgt_lang="ru",
            nlp_engine="mock",
        )
        session.add(project)
        session.flush()
        corpus = SourceCorpus(project_id=project.project_id, name="corpus")
        session.add(corpus)
        session.flush()
        doc = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path="/tmp/doc_0.txt",
            file_name="doc_0.txt",
            file_ext=".txt",
            file_size_bytes=10,
            sha256="sha-0",
            status="processed",
        )
        session.add(doc)
        session.flush()
        session.add(DocumentSentence(doc_id=doc.doc_id, sent_index=0, text="alpha beta"))
        lemma1 = Lemma(project_id=project.project_id, lemma_text="alpha", pos="NOUN")
        lemma2 = Lemma(project_id=project.project_id, lemma_text="beta", pos="NOUN")
        session.add_all([lemma1, lemma2])
        session.flush()
        session.add_all(
            [
                LemmaProjectStat(project_id=project.project_id, lemma_id=lemma1.lemma_id, freq_abs=2, doc_freq=1),
                LemmaProjectStat(project_id=project.project_id, lemma_id=lemma2.lemma_id, freq_abs=2, doc_freq=1),
            ]
        )
        session.commit()
        project_id = int(project.project_id)

        report = service.extract_terms_for_project(
            session,
            project_id,
            enable_ngrams=True,
            include_np=False,
            min_freq=1,
            overwrite=True,
            batch_size=1,
            pause_check=_pause_check,
            cancel_check=lambda: False,
            state_callback=states.append,
        )

    engine.dispose()

    phases = [str(state.get("phase") or "") for state in states]
    assert report.success is True
    assert states
    assert states[0]["project_id"] == project_id
    assert all("status" in state for state in states)
    assert all("docs_failed" in state for state in states)
    assert all("error_message" in state for state in states)
    assert "" not in phases
    assert "paused" in phases
    assert "resumed" in phases
    assert any(state.get("phase") == "paused" and state.get("stage") == "Paused at batch checkpoint" for state in states)
    assert any(state.get("phase") == "completed" and state.get("status") == "ok" for state in states)
