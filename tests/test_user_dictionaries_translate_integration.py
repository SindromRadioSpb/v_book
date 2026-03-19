"""Integration tests for user dictionary translation write path."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    DictProject,
    Lemma,
    Library,
    Ngram,
    SourceCorpus,
    SourceDocument,
    StudyProgress,
    TermCluster,
    TMEntry,
    TMGlobal,
    UserDictionary,
    UserDictionaryItem,
)
from app.services.translation_service import TranslationResult
from app.services.user_dictionary_service import UserDictionaryService
from app.ui.workers import UserDictTranslateWorker


@pytest.fixture
def translate_engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        SourceCorpus.__table__.create(engine, checkfirst=True)
        SourceDocument.__table__.create(engine, checkfirst=True)
        TMGlobal.__table__.create(engine, checkfirst=True)
        Lemma.__table__.create(engine, checkfirst=True)
        TermCluster.__table__.create(engine, checkfirst=True)
        Ngram.__table__.create(engine, checkfirst=True)
        TMEntry.__table__.create(engine, checkfirst=True)
        UserDictionary.__table__.create(engine, checkfirst=True)
        StudyProgress.__table__.create(engine, checkfirst=True)
        UserDictionaryItem.__table__.create(engine, checkfirst=True)
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_translate_selected_updates_tm_global_and_refreshes_resolution(
    monkeypatch, translate_engine
):
    service = UserDictionaryService()

    with Session(translate_engine) as session:
        lib = Library(name="Lib")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="P1")
        session.add(project)
        session.flush()

        global_row = TMGlobal(
            src_lang="he",
            tgt_lang="ru",
            kind="lemma",
            src_norm="alpha",
            src_text="alpha",
            translation="",
            status="draft",
            origin="mt_auto",
        )
        session.add(global_row)
        session.flush()

        entry = TMEntry(
            project_id=project.project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="alpha",
            src_norm="alpha",
            translation="",
            status="draft",
            origin="mt_auto",
            tm_global_id=global_row.tm_global_id,
            is_noise=0,
        )
        session.add(entry)

        dictionary_id = service.create_dictionary(session, name="Deck T").dictionary_id
        add_result = service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "alpha",
                    "src_norm": "alpha",
                    "origin_project_id": project.project_id,
                    "origin_tm_entry_id": entry.tm_id,
                }
            ],
            include_noise=True,
        )
        assert add_result["added"] == 1
        session.commit()

        item_id = session.execute(
            select(UserDictionaryItem.item_id).where(
                UserDictionaryItem.dictionary_id == dictionary_id
            )
        ).scalar_one()

    class DummyDB:
        def __init__(self, engine):
            self.engine = engine

        def get_session(self):
            return Session(self.engine)

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance", lambda: DummyDB(translate_engine)
    )

    def fake_resolve(
        self,
        session,
        src_text,
        kind,
        src_lang,
        tgt_lang,
        project_id,
        allow_draft,
        use_mt,
    ):
        return TranslationResult(translation=f"MT::{src_text}", source="local_nllb", confidence=1.0)

    monkeypatch.setattr(
        "app.services.translation_service.TranslationService.resolve_translation", fake_resolve
    )

    worker = UserDictTranslateWorker(
        dictionary_id=dictionary_id,
        scope="current_page",
        selected_item_ids=[item_id],
        filters={},
        provider_mode="chain",
        write_mode="OVERWRITE",
        id_fetch_chunk=100,
        translation_chunk=10,
    )

    results = []
    errors = []
    worker.finished.connect(lambda result: results.append(result))
    worker.error.connect(lambda err: errors.append(err))
    worker.run()

    assert not errors
    assert results
    assert results[0].succeeded == 1

    with Session(translate_engine) as session:
        updated_global = session.execute(
            select(TMGlobal).where(
                TMGlobal.src_lang == "he",
                TMGlobal.tgt_lang == "ru",
                TMGlobal.kind == "lemma",
                TMGlobal.src_norm == "alpha",
            )
        ).scalar_one()
        assert updated_global.translation == "MT::alpha"

        updated_entry = session.execute(
            select(TMEntry).where(TMEntry.src_norm == "alpha", TMEntry.kind == "lemma")
        ).scalar_one()
        assert updated_entry.translation == "MT::alpha"

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={"hide_noise": True},
            limit=50,
            offset=0,
        )
        assert total == 1
        assert rows[0].translation == "MT::alpha"


def test_translate_selected_fill_empty_skips_non_empty_global(monkeypatch, translate_engine):
    service = UserDictionaryService()

    with Session(translate_engine) as session:
        lib = Library(name="Lib2")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="P2")
        session.add(project)
        session.flush()

        global_row = TMGlobal(
            src_lang="he",
            tgt_lang="ru",
            kind="lemma",
            src_norm="beta",
            src_text="beta",
            translation="EXISTING",
            status="approved",
            origin="user_edit",
        )
        session.add(global_row)
        session.flush()

        entry = TMEntry(
            project_id=project.project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="beta",
            src_norm="beta",
            translation="EXISTING",
            status="approved",
            origin="user_edit",
            tm_global_id=global_row.tm_global_id,
            is_noise=0,
        )
        session.add(entry)

        dictionary_id = service.create_dictionary(session, name="Deck Skip").dictionary_id
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "beta",
                    "src_norm": "beta",
                    "origin_project_id": project.project_id,
                    "origin_tm_entry_id": entry.tm_id,
                }
            ],
            include_noise=True,
        )
        session.commit()

        item_id = session.execute(
            select(UserDictionaryItem.item_id).where(
                UserDictionaryItem.dictionary_id == dictionary_id
            )
        ).scalar_one()

    class DummyDB:
        def __init__(self, engine):
            self.engine = engine

        def get_session(self):
            return Session(self.engine)

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance", lambda: DummyDB(translate_engine)
    )

    def fake_resolve(
        self,
        session,
        src_text,
        kind,
        src_lang,
        tgt_lang,
        project_id,
        allow_draft,
        use_mt,
    ):
        return TranslationResult(translation=f"MT::{src_text}", source="local_nllb", confidence=1.0)

    monkeypatch.setattr(
        "app.services.translation_service.TranslationService.resolve_translation", fake_resolve
    )

    worker = UserDictTranslateWorker(
        dictionary_id=dictionary_id,
        scope="current_page",
        selected_item_ids=[item_id],
        filters={},
        provider_mode="chain",
        write_mode="FILL_EMPTY",
    )

    results = []
    worker.finished.connect(lambda result: results.append(result))
    worker.run()
    assert results
    assert results[0].skipped == 1

    with Session(translate_engine) as session:
        updated_global = session.execute(
            select(TMGlobal).where(TMGlobal.src_norm == "beta", TMGlobal.kind == "lemma")
        ).scalar_one()
        assert updated_global.translation == "EXISTING"


def test_translate_selected_overwrite_replaces_higher_ranked_global(monkeypatch, translate_engine):
    service = UserDictionaryService()

    with Session(translate_engine) as session:
        lib = Library(name="Lib3")
        session.add(lib)
        session.flush()
        project = DictProject(library_id=lib.library_id, name="P3")
        session.add(project)
        session.flush()

        global_row = TMGlobal(
            src_lang="he",
            tgt_lang="ru",
            kind="lemma",
            src_norm="gamma",
            src_text="gamma",
            translation="USER_OLD",
            status="approved",
            origin="user_edit",
        )
        session.add(global_row)
        session.flush()

        entry = TMEntry(
            project_id=project.project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="gamma",
            src_norm="gamma",
            translation="USER_OLD",
            status="approved",
            origin="user_edit",
            tm_global_id=global_row.tm_global_id,
            is_noise=0,
        )
        session.add(entry)
        session.flush()

        dictionary_id = service.create_dictionary(session, name="Deck Overwrite").dictionary_id
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "gamma",
                    "src_norm": "gamma",
                    "origin_project_id": project.project_id,
                    "origin_tm_entry_id": entry.tm_id,
                }
            ],
            include_noise=True,
        )
        session.commit()

        item_id = session.execute(
            select(UserDictionaryItem.item_id).where(
                UserDictionaryItem.dictionary_id == dictionary_id
            )
        ).scalar_one()

    class DummyDB:
        def __init__(self, engine):
            self.engine = engine

        def get_session(self):
            return Session(self.engine)

    monkeypatch.setattr(
        "app.services.db_service.DBService.get_instance", lambda: DummyDB(translate_engine)
    )

    def fake_resolve(
        self,
        session,
        src_text,
        kind,
        src_lang,
        tgt_lang,
        project_id,
        allow_draft,
        use_mt,
    ):
        return TranslationResult(translation=f"MT::{src_text}", source="local_nllb", confidence=1.0)

    monkeypatch.setattr(
        "app.services.translation_service.TranslationService.resolve_translation", fake_resolve
    )

    worker = UserDictTranslateWorker(
        dictionary_id=dictionary_id,
        scope="current_page",
        selected_item_ids=[item_id],
        filters={},
        provider_mode="chain",
        write_mode="OVERWRITE",
    )

    results = []
    errors = []
    worker.finished.connect(lambda result: results.append(result))
    worker.error.connect(lambda err: errors.append(err))
    worker.run()

    assert not errors
    assert results
    assert results[0].succeeded == 1

    with Session(translate_engine) as session:
        updated_global = session.execute(
            select(TMGlobal).where(TMGlobal.src_norm == "gamma", TMGlobal.kind == "lemma")
        ).scalar_one()
        updated_entry = session.execute(
            select(TMEntry).where(TMEntry.src_norm == "gamma", TMEntry.kind == "lemma")
        ).scalar_one()
        assert updated_global.translation == "MT::gamma"
        assert updated_entry.translation == "MT::gamma"
