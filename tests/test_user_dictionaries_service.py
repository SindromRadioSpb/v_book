"""Service-level tests for User Dictionaries."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.sa_models import (
    AudioAsset,
    DocumentSentence,
    DictProject,
    Lemma,
    Library,
    PronunciationEntry,
    SentencePronunciation,
    SourceCorpus,
    SourceDocument,
    StudyProgress,
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
        SourceCorpus.__table__.create(engine, checkfirst=True)
        SourceDocument.__table__.create(engine, checkfirst=True)
        DocumentSentence.__table__.create(engine, checkfirst=True)
        SentencePronunciation.__table__.create(engine, checkfirst=True)
        Lemma.__table__.create(engine, checkfirst=True)
        TMEntry.__table__.create(engine, checkfirst=True)
        TMGlobal.__table__.create(engine, checkfirst=True)
        UserDictionary.__table__.create(engine, checkfirst=True)
        StudyProgress.__table__.create(engine, checkfirst=True)
        UserDictionaryItem.__table__.create(engine, checkfirst=True)
        AudioAsset.__table__.create(engine, checkfirst=True)
        PronunciationEntry.__table__.create(engine, checkfirst=True)
        yield engine
    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def _create_dictionary(
    session: Session, service: UserDictionaryService, name: str = "Deck A"
) -> int:
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
        count = (
            session.execute(
                select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
            )
            .scalars()
            .all()
        )
        assert len(count) == 1
        assert count[0].study_progress_id is not None
        progress_rows = (
            session.execute(
                select(StudyProgress).where(StudyProgress.canonical_hash == count[0].canonical_hash)
            )
            .scalars()
            .all()
        )
        assert len(progress_rows) == 1


def test_bulk_add_canonicalizes_src_norm_from_text(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Canonical")
        expected_norm = normalize_for_tm("he", "alpha term", "term_cluster").norm

        result = service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "term_cluster",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "alpha term",
                    "src_norm": "legacy_wrong_norm",
                }
            ],
            include_noise=True,
        )
        session.commit()

        assert result["added"] == 1
        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
        ).scalar_one()
        assert item.src_norm == expected_norm


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


def test_query_items_fallback_resolves_legacy_src_norm_mismatch(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Legacy")
        canonical_norm = normalize_for_tm("he", "legacy source", "term_cluster").norm

        legacy_item = UserDictionaryItem(
            dictionary_id=dictionary_id,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text="legacy source",
            src_norm="legacy_bad_norm",
            canonical_hash=service.build_canonical_hash(
                "he", "ru", "term_cluster", "legacy_bad_norm"
            ),
            tags_json="[]",
            is_noise=0,
            study_state="new",
            seen_count=0,
        )
        session.add(legacy_item)
        session.add(
            TMGlobal(
                src_lang="he",
                tgt_lang="ru",
                kind="term_cluster",
                src_norm=canonical_norm,
                src_text="legacy source",
                translation="RU LEGACY",
                status="approved",
                origin="user_edit",
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
        assert rows[0].translation == "RU LEGACY"


def test_query_items_pronunciation_overlay_handles_whitespace_norm_key(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Pron Overlay")

        legacy_norm = "term_with_space   "
        session.add(
            UserDictionaryItem(
                dictionary_id=dictionary_id,
                kind="term_cluster",
                src_lang="he",
                tgt_lang="ru",
                src_text="term with space",
                src_norm=legacy_norm,
                canonical_hash=service.build_canonical_hash(
                    "he", "ru", "term_cluster", legacy_norm
                ),
                tags_json="[]",
                is_noise=0,
                study_state="new",
                seen_count=0,
            )
        )
        session.add(
            PronunciationEntry(
                lang="he",
                src_norm="term_with_space",
                niqqud_text="תֶּרְם",
                source="manual",
                is_override=1,
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
        assert rows[0].pronunciation_text == "תֶּרְם"


def test_query_items_sentence_origin_uses_sentence_pronunciation_overlay(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        library = Library(name="Sentence Overlay Lib")
        session.add(library)
        session.flush()
        project = DictProject(library_id=library.library_id, name="Sentence Overlay Project")
        session.add(project)
        session.flush()
        corpus = SourceCorpus(project_id=project.project_id, name="Sentence Overlay Corpus")
        session.add(corpus)
        session.flush()
        document = SourceDocument(
            corpus_id=corpus.corpus_id,
            file_path="C:/tmp/sentence_overlay.txt",
            file_name="sentence_overlay.txt",
            file_ext=".txt",
            file_size_bytes=123,
            sha256="sentence-overlay-doc-sha",
            status="processed",
        )
        session.add(document)
        session.flush()
        sentence = DocumentSentence(doc_id=document.doc_id, sent_index=0, text="שלום עולם")
        session.add(sentence)
        session.flush()

        src_norm = normalize_for_tm("he", "שלום עולם", "surface").norm
        dictionary_id = _create_dictionary(session, service, "Deck Sentence Pron Overlay")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "surface",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "שלום עולם",
                    "src_norm": src_norm,
                    "origin_project_id": project.project_id,
                    "origin_entity_type": "sentence",
                    "origin_entity_id": str(sentence.sentence_id),
                    "origin_doc_id": document.doc_id,
                }
            ],
            include_noise=True,
        )

        # Lexical pronunciation exists; sentence overlay must win for sentence-origin rows.
        session.add(
            PronunciationEntry(
                lang="he",
                src_norm=src_norm,
                niqqud_text="שָלוֹם",
                source="manual",
                is_override=1,
            )
        )
        session.add(
            SentencePronunciation(
                sentence_id=sentence.sentence_id,
                lang="he",
                src_hash="sentence-overlay-hash",
                niqqud_text="שָׁלוֹם עוֹלָם",
                source="manual",
                confidence=0.91,
                qc_status="ok",
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
        assert rows[0].pronunciation_text == "שָׁלוֹם עוֹלָם"
        assert rows[0].pronunciation_source == "sentence:manual"
        assert rows[0].pronunciation_qc == "ok"
        assert rows[0].pronunciation_confidence == pytest.approx(0.91)


def test_update_item_translation_updates_tm_global_and_tm_entry(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        library = Library(name="Link Lib")
        session.add(library)
        session.flush()
        project = DictProject(library_id=library.library_id, name="Link Project")
        session.add(project)
        session.flush()

        lemma = Lemma(
            project_id=project.project_id, lemma_text="alpha", norm_text="alpha", is_noise=0
        )
        session.add(lemma)
        session.flush()

        src_norm = normalize_for_tm("he", "alpha", "lemma").norm
        global_row = TMGlobal(
            src_lang="he",
            tgt_lang="ru",
            kind="lemma",
            src_norm=src_norm,
            src_text="alpha",
            translation="OLD",
            status="draft",
            origin="mt_auto",
            is_noise=0,
        )
        session.add(global_row)
        session.flush()

        entry = TMEntry(
            project_id=project.project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="alpha",
            src_norm=src_norm,
            translation="OLD",
            status="draft",
            origin="mt_auto",
            lemma_id=lemma.lemma_id,
            is_noise=0,
            tm_global_id=global_row.tm_global_id,
        )
        session.add(entry)
        session.flush()

        dictionary_id = _create_dictionary(session, service, "Deck Edit")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "alpha",
                    "src_norm": src_norm,
                    "origin_project_id": project.project_id,
                    "origin_entity_type": "lemma",
                    "origin_entity_id": lemma.lemma_id,
                    "origin_tm_entry_id": entry.tm_id,
                }
            ],
            include_noise=True,
        )
        session.flush()
        item_id = session.execute(
            select(UserDictionaryItem.item_id).where(
                UserDictionaryItem.dictionary_id == dictionary_id
            )
        ).scalar_one()

        service.update_item_translation(session, item_id=item_id, translation="NEW VALUE")
        session.commit()

        updated_global = session.execute(
            select(TMGlobal).where(
                TMGlobal.src_lang == "he",
                TMGlobal.tgt_lang == "ru",
                TMGlobal.kind == "lemma",
                TMGlobal.src_norm == src_norm,
            )
        ).scalar_one()
        updated_entry = session.execute(
            select(TMEntry).where(TMEntry.tm_id == entry.tm_id)
        ).scalar_one()

        assert updated_global.translation == "NEW VALUE"
        assert updated_global.status == "approved"
        assert updated_global.origin == "user_edit"
        assert updated_entry.translation == "NEW VALUE"
        assert updated_entry.status == "approved"
        assert updated_entry.origin == "user_edit"


def test_set_items_noise_status_bulk_syncs_tm_and_lemma(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        library = Library(name="Noise Lib")
        session.add(library)
        session.flush()
        project = DictProject(library_id=library.library_id, name="Noise Project")
        session.add(project)
        session.flush()

        lemma = Lemma(
            project_id=project.project_id, lemma_text="beta", norm_text="beta", is_noise=0
        )
        session.add(lemma)
        session.flush()

        src_norm = normalize_for_tm("he", "beta", "lemma").norm
        global_row = TMGlobal(
            src_lang="he",
            tgt_lang="ru",
            kind="lemma",
            src_norm=src_norm,
            src_text="beta",
            translation="BETA",
            status="approved",
            origin="user_edit",
            is_noise=0,
        )
        session.add(global_row)
        session.flush()

        entry = TMEntry(
            project_id=project.project_id,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="beta",
            src_norm=src_norm,
            translation="BETA",
            status="approved",
            origin="user_edit",
            lemma_id=lemma.lemma_id,
            is_noise=0,
            tm_global_id=global_row.tm_global_id,
        )
        session.add(entry)
        session.flush()

        dictionary_id = _create_dictionary(session, service, "Deck Noise")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "beta",
                    "src_norm": src_norm,
                    "origin_project_id": project.project_id,
                    "origin_entity_type": "lemma",
                    "origin_entity_id": lemma.lemma_id,
                    "origin_tm_entry_id": entry.tm_id,
                }
            ],
            include_noise=True,
        )
        session.flush()
        item_id = session.execute(
            select(UserDictionaryItem.item_id).where(
                UserDictionaryItem.dictionary_id == dictionary_id
            )
        ).scalar_one()

        changed = service.set_items_noise_status_bulk(
            session,
            item_ids=[item_id],
            is_noise=True,
            noise_reason="NOISE_USER_MARKED",
        )
        session.commit()

        assert changed == 1
        updated_item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.item_id == item_id)
        ).scalar_one()
        updated_global = session.execute(
            select(TMGlobal).where(TMGlobal.tm_global_id == global_row.tm_global_id)
        ).scalar_one()
        updated_entry = session.execute(
            select(TMEntry).where(TMEntry.tm_id == entry.tm_id)
        ).scalar_one()
        updated_lemma = session.execute(
            select(Lemma).where(Lemma.lemma_id == lemma.lemma_id)
        ).scalar_one()

        assert updated_item.is_noise == 1
        assert updated_item.noise_reason == "NOISE_USER_MARKED"
        assert updated_global.is_noise == 1
        assert updated_global.noise_reason == "NOISE_USER_MARKED"
        assert updated_entry.is_noise == 1
        assert updated_entry.noise_reason == "NOISE_USER_MARKED"
        assert updated_lemma.is_noise == 1
        assert updated_lemma.noise_reason == "NOISE_USER_MARKED"


def test_resolve_cross_view_status_tooltip_only_for_user_dictionary_members(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Tooltip Scope")

        in_ud_text = "in-ud-term"
        out_ud_text = "out-ud-term"
        in_ud_norm = normalize_for_tm("he", in_ud_text, "term_cluster").norm
        out_ud_norm = normalize_for_tm("he", out_ud_text, "term_cluster").norm

        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "term_cluster",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": in_ud_text,
                    "src_norm": in_ud_norm,
                }
            ],
            include_noise=True,
        )
        session.commit()

        overlay = service.resolve_cross_view_status(
            session,
            rows=[
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": in_ud_text,
                    "src_norm": in_ud_norm,
                },
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": out_ud_text,
                    "src_norm": out_ud_norm,
                },
            ],
        )

        in_hash = service.build_canonical_hash("he", "ru", "term_cluster", in_ud_norm)
        out_hash = service.build_canonical_hash("he", "ru", "term_cluster", out_ud_norm)

        assert overlay[in_hash]["in_user_dictionary_count"] == 1
        assert overlay[in_hash]["study_tooltip"]
        assert overlay[out_hash]["in_user_dictionary_count"] == 0
        assert overlay[out_hash]["study_tooltip"] is None


def test_resolve_cross_view_status_includes_failed_audio_for_non_ud_rows(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        src_text = "audio-failed-term"
        src_norm = normalize_for_tm("he", src_text, "term_cluster").norm
        canonical_hash = service.build_canonical_hash("he", "ru", "term_cluster", src_norm)

        session.add(
            AudioAsset(
                lang="he",
                norm_text=src_norm,
                voice_id="default",
                speed=1.0,
                provider="google_cloud_tts",
                asset_status="failed",
                error_text="auth failed",
            )
        )
        session.commit()

        overlay = service.resolve_cross_view_status(
            session,
            rows=[
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": src_text,
                    "src_norm": src_norm,
                }
            ],
        )

        assert overlay[canonical_hash]["in_user_dictionary_count"] == 0
        assert overlay[canonical_hash]["audio_status"] == "failed"
        assert overlay[canonical_hash]["study_tooltip"] is None


def test_resolve_cross_view_status_ignores_stale_norm_only_audio(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        src_text = "שלום בית"
        src_norm = normalize_for_tm("he", src_text, "term_cluster").norm
        canonical_hash = service.build_canonical_hash("he", "ru", "term_cluster", src_norm)

        session.add(
            AudioAsset(
                lang="he",
                norm_text=src_norm,
                voice_id="default",
                speed=1.0,
                provider="google_cloud_tts",
                speech_hash="stale-speech-hash",
                input_hash="stale-input-hash",
                asset_status="ready",
                audio_rel_path="audio/stale.wav",
            )
        )
        session.commit()

        overlay = service.resolve_cross_view_status(
            session,
            rows=[
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": "שלום בַיִת",
                    "src_norm": src_norm,
                }
            ],
        )

        assert overlay[canonical_hash]["audio_status"] == "missing"


def test_resolve_cross_view_status_pronunciation_falls_back_to_raw_norm(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        src_text = "legacy pronunciation term"
        canonical_norm = normalize_for_tm("he", src_text, "term_cluster").norm
        legacy_norm = "legacy_pron_norm"
        canonical_hash = service.build_canonical_hash("he", "ru", "term_cluster", canonical_norm)

        session.add(
            PronunciationEntry(
                lang="he",
                src_norm=legacy_norm,
                niqqud_text="term nikud",
                source="auto_phonikud",
                is_override=0,
                notes="auto:phonikud:real_inference",
            )
        )
        session.commit()

        overlay = service.resolve_cross_view_status(
            session,
            rows=[
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": src_text,
                    "src_norm": canonical_norm,
                    "raw_src_norm": legacy_norm,
                }
            ],
        )

        assert overlay[canonical_hash]["pronunciation_text"] == "term nikud"
        assert overlay[canonical_hash]["pronunciation_source"] == "auto_phonikud"


def test_resolve_cross_view_status_derives_raw_norm_from_source_text(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        src_text = "\u05d4\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df"
        canonical_norm = normalize_for_tm("he", src_text, "term_cluster").norm
        surface_norm = normalize_for_tm("he", src_text, "surface").norm
        assert canonical_norm != surface_norm

        canonical_hash = service.build_canonical_hash("he", "ru", "term_cluster", canonical_norm)
        session.add(
            PronunciationEntry(
                lang="he",
                src_norm=surface_norm,
                niqqud_text="surface nikud",
                source="manual",
                is_override=1,
                notes="manual",
            )
        )
        session.commit()

        overlay = service.resolve_cross_view_status(
            session,
            rows=[
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": src_text,
                    "src_norm": canonical_norm,
                }
            ],
        )

        assert overlay[canonical_hash]["pronunciation_text"] == "surface nikud"
        assert overlay[canonical_hash]["pronunciation_source"] == "manual"


def test_query_items_pronunciation_prefers_surface_norm(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Pron Surface")
        src_text = "\u05d4\u05e4\u05e8\u05e7 \u05d4\u05d6\u05de\u05df"
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "term_cluster",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": src_text,
                    "src_norm": "legacy_term_norm",
                }
            ],
            include_noise=True,
        )
        session.flush()
        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
        ).scalar_one()
        canonical_norm = (item.src_norm or "").strip()
        surface_norm = normalize_for_tm("he", src_text, "surface").norm
        assert canonical_norm != surface_norm

        session.add_all(
            [
                PronunciationEntry(
                    lang="he",
                    src_norm=canonical_norm,
                    niqqud_text="canonical nikud",
                    source="auto_phonikud",
                    is_override=0,
                    notes="auto:phonikud",
                ),
                PronunciationEntry(
                    lang="he",
                    src_norm=surface_norm,
                    niqqud_text="surface nikud",
                    source="manual",
                    is_override=1,
                    notes="manual",
                ),
            ]
        )
        session.commit()

        rows, total = service.query_items(
            session,
            dictionary_id=dictionary_id,
            filters={},
            limit=20,
            offset=0,
            sort_column="updated_at",
            sort_direction="desc",
        )

        assert total == 1
        assert len(rows) == 1
        assert rows[0].pronunciation_text == "surface nikud"
        assert rows[0].pronunciation_source == "manual"


def test_set_items_suspension_bulk_updates_flags(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Suspend")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "suspend-me",
                    "src_norm": "suspend-me",
                }
            ],
            include_noise=True,
        )
        session.flush()
        item_id = session.execute(
            select(UserDictionaryItem.item_id).where(
                UserDictionaryItem.dictionary_id == dictionary_id
            )
        ).scalar_one()

        changed = service.set_items_suspension_bulk(
            session,
            item_ids=[item_id],
            is_suspended=True,
            suspended_reason="USER_SUSPENDED",
        )
        session.commit()
        assert changed == 1

        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.item_id == item_id)
        ).scalar_one()
        assert item.is_suspended == 1
        assert item.suspended_reason == "USER_SUSPENDED"
        assert item.study_state == "suspended"

        changed = service.set_items_suspension_bulk(
            session,
            item_ids=[item_id],
            is_suspended=False,
        )
        session.commit()
        assert changed == 1

        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.item_id == item_id)
        ).scalar_one()
        assert item.is_suspended == 0
        assert item.suspended_reason is None


def test_set_items_due_now_bulk_updates_linked_progress(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Due Now")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "due-me",
                    "src_norm": "due-me",
                }
            ],
            include_noise=True,
        )
        session.flush()
        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
        ).scalar_one()
        progress_before = session.execute(
            select(StudyProgress).where(StudyProgress.id == item.study_progress_id)
        ).scalar_one()
        due_before = progress_before.due_at

        changed = service.set_items_due_now_bulk(session, [item.item_id])
        session.commit()
        assert changed == 1

        progress_after = session.execute(
            select(StudyProgress).where(StudyProgress.id == item.study_progress_id)
        ).scalar_one()
        assert progress_after.due_at >= due_before


def test_get_study_summary_counts_by_computed_states(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Summary")
        payloads = []
        for idx in range(5):
            payloads.append(
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": f"summary-{idx}",
                    "src_norm": f"summary-{idx}",
                    "origin_project_id": 100,
                }
            )
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=payloads,
            include_noise=True,
        )
        session.flush()

        items = (
            session.execute(
                select(UserDictionaryItem)
                .where(UserDictionaryItem.dictionary_id == dictionary_id)
                .order_by(UserDictionaryItem.item_id)
            )
            .scalars()
            .all()
        )
        assert len(items) == 5

        now_dt = datetime.now(timezone.utc)
        # new
        p0 = session.get(StudyProgress, items[0].study_progress_id)
        p0.review_count = 0
        p0.interval_days = 0
        p0.due_at = (now_dt + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # learning
        p1 = session.get(StudyProgress, items[1].study_progress_id)
        p1.review_count = 1
        p1.interval_days = 4
        p1.due_at = (now_dt + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # due
        p2 = session.get(StudyProgress, items[2].study_progress_id)
        p2.review_count = 2
        p2.interval_days = 6
        p2.due_at = (now_dt - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # mastered
        p3 = session.get(StudyProgress, items[3].study_progress_id)
        p3.review_count = 3
        p3.interval_days = 30
        p3.due_at = (now_dt + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # suspended
        items[4].is_suspended = 1
        items[4].suspended_reason = "USER_SUSPENDED"
        p4 = session.get(StudyProgress, items[4].study_progress_id)
        p4.review_count = 1
        p4.interval_days = 1
        p4.due_at = (now_dt - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        session.commit()

        counters = service.get_study_summary_counts(
            session=session,
            dictionary_id=dictionary_id,
            scope_origin_project_id=100,
            hide_noise=True,
        )

        assert counters["total"] == 5
        assert counters["new"] == 1
        assert counters["learning"] == 1
        assert counters["due"] == 1
        assert counters["mastered"] == 1
        assert counters["suspended"] == 1


def test_get_study_summary_counts_treats_again_with_zero_review_as_learning(user_dict_engine):
    service = UserDictionaryService()
    with Session(user_dict_engine) as session:
        dictionary_id = _create_dictionary(session, service, "Deck Summary Again")
        service.bulk_add_items(
            session,
            dictionary_id=dictionary_id,
            items=[
                {
                    "kind": "lemma",
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "src_text": "again-zero",
                    "src_norm": "again-zero",
                    "origin_project_id": 200,
                }
            ],
            include_noise=True,
        )
        session.flush()
        item = session.execute(
            select(UserDictionaryItem).where(UserDictionaryItem.dictionary_id == dictionary_id)
        ).scalar_one()
        progress = session.get(StudyProgress, item.study_progress_id)
        now_dt = datetime.now(timezone.utc)
        progress.review_count = 0
        progress.last_grade = "again"
        progress.last_graded_at = (now_dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        progress.due_at = (now_dt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        session.commit()

        counters = service.get_study_summary_counts(
            session=session,
            dictionary_id=dictionary_id,
            scope_origin_project_id=200,
            hide_noise=True,
        )

        assert counters["total"] == 1
        assert counters["new"] == 0
        assert counters["learning"] == 1
