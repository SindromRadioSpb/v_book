"""Tests for User Dictionary -> Translation Management projection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    AudioAsset,
    DictProject,
    Lemma,
    Library,
    SourceDocument,
    StudyProgress,
    TMEntry,
    TMGlobal,
    TermCluster,
    UserDictionary,
    UserDictionaryItem,
)
from app.services.translation_admin_service import TranslationAdminService
from app.services.user_dictionary_service import UserDictionaryService


def _build_engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = create_engine(f"sqlite:///{db_path}")
    return engine, db_path


def _create_schema(engine):
    Library.__table__.create(engine, checkfirst=True)
    DictProject.__table__.create(engine, checkfirst=True)
    SourceDocument.__table__.create(engine, checkfirst=True)
    Lemma.__table__.create(engine, checkfirst=True)
    TermCluster.__table__.create(engine, checkfirst=True)
    TMEntry.__table__.create(engine, checkfirst=True)
    TMGlobal.__table__.create(engine, checkfirst=True)
    UserDictionary.__table__.create(engine, checkfirst=True)
    StudyProgress.__table__.create(engine, checkfirst=True)
    UserDictionaryItem.__table__.create(engine, checkfirst=True)
    AudioAsset.__table__.create(engine, checkfirst=True)


def test_bulk_add_materializes_project_tm_entry_and_is_visible_in_tm():
    engine, db_path = _build_engine()
    try:
        _create_schema(engine)
        user_dict_service = UserDictionaryService()
        admin_service = TranslationAdminService()

        with Session(engine) as session:
            lib = Library(name="Projection Lib")
            session.add(lib)
            session.flush()
            project = DictProject(library_id=lib.library_id, name="Projection P")
            session.add(project)
            session.flush()
            lemma = Lemma(
                project_id=project.project_id,
                lemma_text="alpha",
                norm_text="alpha",
                is_noise=0,
            )
            session.add(lemma)
            session.flush()

            dictionary_id = user_dict_service.create_dictionary(session, "Deck Projection").dictionary_id
            result = user_dict_service.bulk_add_items(
                session,
                dictionary_id=dictionary_id,
                items=[
                    {
                        "kind": "lemma",
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "src_text": "alpha",
                        "origin_project_id": project.project_id,
                        "origin_entity_type": "lemma",
                        "origin_entity_id": lemma.lemma_id,
                        "origin_source_ref": "test_projection",
                    }
                ],
                include_noise=True,
            )
            session.commit()

            assert result["added"] == 1
            assert result["tm_linked"] == 1
            assert result["tm_created"] == 1

            item = session.execute(
                select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
            ).scalar_one()
            assert item.origin_tm_entry_id is not None

            entry = session.get(TMEntry, item.origin_tm_entry_id)
            assert entry is not None
            assert entry.project_id == project.project_id
            assert entry.kind == "lemma"
            assert entry.src_text == "alpha"
            assert entry.source_ref == "user_dictionary_add"
            assert entry.lemma_id == lemma.lemma_id

            rows = admin_service.search_tm_entries(
                session,
                filters={
                    "project_ids": [project.project_id],
                    "kind": "lemma",
                    "search_text": "alpha",
                    "hide_noise": False,
                },
                limit=100,
                offset=0,
            )
            assert any(row.tm_id == entry.tm_id for row in rows)
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_bulk_add_reuses_existing_project_tm_anchor():
    engine, db_path = _build_engine()
    try:
        _create_schema(engine)
        user_dict_service = UserDictionaryService()

        with Session(engine) as session:
            lib = Library(name="Reuse Lib")
            session.add(lib)
            session.flush()
            project = DictProject(library_id=lib.library_id, name="Reuse P")
            session.add(project)
            session.flush()

            existing = TMEntry(
                project_id=project.project_id,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="beta",
                src_norm="beta",
                translation="BETA",
                status="approved",
                origin="user_edit",
                source_ref="seed",
                is_noise=0,
            )
            session.add(existing)
            session.flush()

            dictionary_id = user_dict_service.create_dictionary(session, "Deck Reuse").dictionary_id
            result = user_dict_service.bulk_add_items(
                session,
                dictionary_id=dictionary_id,
                items=[
                    {
                        "kind": "lemma",
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "src_text": "beta",
                        "origin_project_id": project.project_id,
                        "origin_source_ref": "test_reuse",
                    }
                ],
                include_noise=True,
            )
            session.commit()

            assert result["tm_reused"] == 1
            assert result["tm_created"] == 0

            item = session.execute(
                select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
            ).scalar_one()
            assert item.origin_tm_entry_id == existing.tm_id

            matches = session.execute(
                select(TMEntry).where(
                    TMEntry.project_id == project.project_id,
                    TMEntry.kind == "lemma",
                    TMEntry.src_lang == "he",
                    TMEntry.tgt_lang == "ru",
                    TMEntry.src_norm == "beta",
                )
            ).scalars().all()
            assert len(matches) == 1
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_bulk_add_materializes_global_tm_anchor_without_project():
    engine, db_path = _build_engine()
    try:
        _create_schema(engine)
        user_dict_service = UserDictionaryService()
        admin_service = TranslationAdminService()

        with Session(engine) as session:
            dictionary_id = user_dict_service.create_dictionary(session, "Deck Global").dictionary_id
            result = user_dict_service.bulk_add_items(
                session,
                dictionary_id=dictionary_id,
                items=[
                    {
                        "kind": "term_cluster",
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "src_text": "gamma term",
                        "origin_source_ref": "test_global_projection",
                    }
                ],
                include_noise=True,
            )
            session.commit()

            assert result["tm_created"] == 1
            item = session.execute(
                select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
            ).scalar_one()
            entry = session.get(TMEntry, item.origin_tm_entry_id)
            assert entry is not None
            assert entry.project_id is None
            assert entry.source_ref == "user_dictionary_add"

            rows = admin_service.search_tm_entries(
                session,
                filters={"project_ids": [-1], "search_text": "gamma", "hide_noise": False},
                limit=100,
                offset=0,
            )
            assert any(row.tm_id == entry.tm_id for row in rows)
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_sync_noise_from_lemmas_updates_user_dictionary_items():
    engine, db_path = _build_engine()
    try:
        _create_schema(engine)
        user_dict_service = UserDictionaryService()

        with Session(engine) as session:
            lib = Library(name="Noise Lemma Lib")
            session.add(lib)
            session.flush()
            project = DictProject(library_id=lib.library_id, name="Noise Lemma Project")
            session.add(project)
            session.flush()

            lemma = Lemma(
                project_id=project.project_id,
                lemma_text="lemma-noise",
                norm_text="lemma-noise",
                is_noise=0,
                noise_reason=None,
            )
            session.add(lemma)
            session.flush()

            dictionary_id = user_dict_service.create_dictionary(session, "Noise Sync Lemmas").dictionary_id
            user_dict_service.bulk_add_items(
                session,
                dictionary_id=dictionary_id,
                items=[
                    {
                        "kind": "lemma",
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "src_text": "lemma-noise",
                        "origin_project_id": project.project_id,
                        "origin_entity_type": "lemma",
                        "origin_entity_id": lemma.lemma_id,
                        "origin_source_ref": "test_noise_lemma",
                    }
                ],
                include_noise=True,
            )
            session.commit()

            lemma.is_noise = 1
            lemma.noise_reason = "NOISE_TEST"
            updated = user_dict_service.sync_noise_from_lemmas(session, [lemma.lemma_id])
            session.commit()

            assert updated >= 1
            item = session.execute(
                select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
            ).scalar_one()
            assert item.is_noise == 1
            assert item.noise_reason == "NOISE_TEST"
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_sync_noise_from_term_clusters_updates_user_dictionary_items():
    engine, db_path = _build_engine()
    try:
        _create_schema(engine)
        user_dict_service = UserDictionaryService()

        with Session(engine) as session:
            lib = Library(name="Noise Cluster Lib")
            session.add(lib)
            session.flush()
            project = DictProject(library_id=lib.library_id, name="Noise Cluster Project")
            session.add(project)
            session.flush()

            cluster = TermCluster(
                project_id=project.project_id,
                canonical_key="term_noise",
                representative_he="term noise",
                representative_lemma="term_noise",
                is_noise=0,
                noise_reason=None,
                norm_text="term_noise",
            )
            session.add(cluster)
            session.flush()

            dictionary_id = user_dict_service.create_dictionary(session, "Noise Sync Terms").dictionary_id
            user_dict_service.bulk_add_items(
                session,
                dictionary_id=dictionary_id,
                items=[
                    {
                        "kind": "term_cluster",
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "src_text": "term noise",
                        "origin_project_id": project.project_id,
                        "origin_entity_type": "term_cluster",
                        "origin_entity_id": cluster.cluster_id,
                        "origin_source_ref": "test_noise_cluster",
                    }
                ],
                include_noise=True,
            )
            session.commit()

            cluster.is_noise = 1
            cluster.noise_reason = "NOISE_TEST_CLUSTER"
            updated = user_dict_service.sync_noise_from_term_clusters(session, [cluster.cluster_id])
            session.commit()

            assert updated >= 1
            item = session.execute(
                select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
            ).scalar_one()
            assert item.is_noise == 1
            assert item.noise_reason == "NOISE_TEST_CLUSTER"
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)
