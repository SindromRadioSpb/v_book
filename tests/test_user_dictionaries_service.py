"""Service-level tests for User Dictionaries."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    AudioAsset,
    DictProject,
    Library,
    SourceDocument,
    TMEntry,
    TMGlobal,
    UserDictionary,
    UserDictionaryItem,
)
from app.services.user_dictionary_service import UserDictionaryService


@pytest.fixture
def user_dict_engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    try:
        Library.__table__.create(engine, checkfirst=True)
        DictProject.__table__.create(engine, checkfirst=True)
        SourceDocument.__table__.create(engine, checkfirst=True)
        TMEntry.__table__.create(engine, checkfirst=True)
        TMGlobal.__table__.create(engine, checkfirst=True)
        UserDictionary.__table__.create(engine, checkfirst=True)
        UserDictionaryItem.__table__.create(engine, checkfirst=True)
        AudioAsset.__table__.create(engine, checkfirst=True)
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def _create_dictionary(session: Session, service: UserDictionaryService, name: str = "Deck A") -> int:
    dto = service.create_dictionary(session, name=name)
    session.commit()
    return dto.dictionary_id


def test_create_dictionary_validations_and_uniqueness(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        created = service.create_dictionary(session, name="  Deck A  ")
        session.commit()
        assert created.name == "Deck A"

        with pytest.raises(ValueError):
            service.create_dictionary(session, name="Deck A")

        with pytest.raises(ValueError):
            service.create_dictionary(session, name="")

        with pytest.raises(ValueError):
            service.create_dictionary(session, name="bad/name")


def test_bulk_add_dedup_by_canonical_hash(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Dedup")
        result = service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "alpha",
                    "src_norm": "alpha",
                },
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "ALPHA",
                    "src_norm": "alpha",
                },
            ],
            include_noise=True,
            skip_duplicates=True,
        )
        session.commit()

        assert result["added"] == 1
        assert result["skipped"] == 1
        count = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
        ).scalars().all()
        assert len(count) == 1


def test_bulk_add_skips_noise_by_default_include_noise_option(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        d1 = _create_dictionary(session, service, "Deck Noise Off")
        res1 = service.bulk_add_items(
            session,
            dictionary_id=d1,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "good",
                    "src_norm": "good",
                    "is_noise": 0,
                },
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "noise",
                    "src_norm": "noise",
                    "is_noise": 1,
                },
            ],
            include_noise=False,
        )
        session.commit()

        d2 = _create_dictionary(session, service, "Deck Noise On")
        res2 = service.bulk_add_items(
            session,
            dictionary_id=d2,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "good2",
                    "src_norm": "good2",
                    "is_noise": 0,
                },
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "noise2",
                    "src_norm": "noise2",
                    "is_noise": 1,
                },
            ],
            include_noise=True,
        )
        session.commit()

        assert res1["added"] == 1 and res1["skipped"] == 1
        assert res2["added"] == 2


def test_query_items_filters_kind_search_hide_noise_study_state(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        library = Library(name="Scope Lib")
        session.add(library)
        session.flush()
        project_a = DictProject(library_id=library.library_id, name="Project A")
        project_b = DictProject(library_id=library.library_id, name="Project B")
        session.add_all([project_a, project_b])
        session.flush()

        dictionary_id = _create_dictionary(session, service, "Deck Filters")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "alpha",
                    "src_norm": "alpha",
                    "study_state": "new",
                    "is_noise": 0,
                    "origin_project_id": project_a.project_id,
                },
                {
                    "kind": "term_cluster",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "beta term",
                    "src_norm": "beta_term",
                    "study_state": "learning",
                    "is_noise": 1,
                    "origin_project_id": project_a.project_id,
                },
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "gamma",
                    "src_norm": "gamma",
                    "study_state": "mastered",
                    "is_noise": 0,
                    "origin_project_id": project_b.project_id,
                },
            ],
            include_noise=True,
        )

        session.add_all(
            [
                TMGlobal(
                    src_lang="he",
                    tgt_lang="ru",
                    kind="term_cluster",
                    src_norm="beta_term",
                    src_text="beta term",
                    translation="RU BETA",
                    status="approved",
                    origin="mt_auto",
                ),
                TMGlobal(
                    src_lang="he",
                    tgt_lang="ru",
                    kind="lemma",
                    src_norm="gamma",
                    src_text="gamma",
                    translation="RU GAMMA",
                    status="approved",
                    origin="mt_auto",
                ),
            ]
        )
        session.commit()

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={"hide_noise": True},
            limit=100,
            offset=0,
        )
        assert total == 2
        assert all(row.is_noise == 0 for row in rows)

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={
                "kind": "lemma",
                "study_state": "mastered",
                "hide_noise": True,
            },
            limit=100,
            offset=0,
        )
        assert total == 1
        assert rows[0].src_text == "gamma"

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={
                "search_text": "RU GAMMA",
                "hide_noise": True,
            },
            limit=100,
            offset=0,
        )
        assert total == 1
        assert rows[0].translation == "RU GAMMA"

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={
                "origin_project_id": project_b.project_id,
                "hide_noise": True,
            },
            limit=100,
            offset=0,
        )
        assert total == 1
        assert rows[0].src_text == "gamma"


def test_resolve_translations_bulk_left_join_tm_global_no_persist(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Join")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "delta",
                    "src_norm": "delta",
                }
            ],
            include_noise=True,
        )
        session.add(
            TMGlobal(
                src_lang="he",
                tgt_lang="ru",
                kind="lemma",
                src_norm="delta",
                src_text="delta",
                translation="RU DELTA",
                status="approved",
                origin="mt_auto",
            )
        )
        session.commit()

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={"hide_noise": True},
            limit=100,
            offset=0,
        )

        assert total == 1
        assert rows[0].translation == "RU DELTA"
        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
        ).scalar_one()
        assert item.src_text == "delta"
