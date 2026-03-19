"""Regression tests for bulk TM admin performance-safe propagation."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, Library, TMEntry
from app.services.translation_admin_service import TranslationAdminService
from app.services.tm_global_service import TMGlobalService


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    session.add(Library(library_id=1, name="Test Library"))
    session.add_all(
        [
            DictProject(
                project_id=1,
                library_id=1,
                name="Project 1",
                src_lang="he",
                tgt_lang="ru",
            ),
            DictProject(
                project_id=2,
                library_id=1,
                name="Project 2",
                src_lang="he",
                tgt_lang="ru",
            ),
        ]
    )
    session.commit()
    return engine, session


def test_bulk_set_status_defers_tm_global_propagation(monkeypatch) -> None:
    """Bulk status update should propagate once per touched tm_global_id."""
    engine, session = _make_session()
    try:
        service = TranslationAdminService()
        global_service = TMGlobalService()

        entry_a = TMEntry(
            tm_id=1,
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="alpha",
            src_norm="shared_norm",
            translation="old",
            status="draft",
            origin="mt_auto",
        )
        entry_b = TMEntry(
            tm_id=2,
            project_id=2,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="alpha",
            src_norm="shared_norm",
            translation="old",
            status="draft",
            origin="mt_auto",
        )
        session.add_all([entry_a, entry_b])
        session.flush()
        global_service.upsert_and_link(session, entry_a)
        global_service.upsert_and_link(session, entry_b)
        session.commit()

        propagate_calls: list[int] = []
        original_propagate = TMGlobalService.propagate_to_entries

        def tracked_propagate(self, session, tm_global_id, fields=None):
            propagate_calls.append(tm_global_id)
            return original_propagate(self, session, tm_global_id, fields)

        monkeypatch.setattr(TMGlobalService, "propagate_to_entries", tracked_propagate)

        updated = service.bulk_set_status(session, [1, 2], "approved", approved_by="ui")

        assert updated == 2
        assert len(propagate_calls) == 1
        assert propagate_calls[0] == entry_a.tm_global_id

        rows = session.execute(
            select(TMEntry.tm_id, TMEntry.status)
            .where(TMEntry.tm_id.in_([1, 2]))
            .order_by(TMEntry.tm_id)
        ).all()
        assert rows == [(1, "approved"), (2, "approved")]
    finally:
        session.close()
        engine.dispose()


def test_set_noise_status_bulk_defers_tm_global_propagation(monkeypatch) -> None:
    """Bulk noise update should not trigger propagation per entry."""
    engine, session = _make_session()
    try:
        service = TranslationAdminService()
        global_service = TMGlobalService()

        entry_a = TMEntry(
            tm_id=11,
            project_id=1,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="beta",
            src_norm="noise_norm",
            translation="x",
            status="approved",
            origin="user_edit",
        )
        entry_b = TMEntry(
            tm_id=12,
            project_id=2,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text="beta",
            src_norm="noise_norm",
            translation="x",
            status="approved",
            origin="user_edit",
        )
        session.add_all([entry_a, entry_b])
        session.flush()
        global_service.upsert_and_link(session, entry_a)
        global_service.upsert_and_link(session, entry_b)
        session.commit()

        upsert_immediate_flags: list[bool] = []
        original_upsert = TMGlobalService.upsert_and_link
        original_propagate = TMGlobalService.propagate_to_entries
        propagate_calls: list[int] = []

        def tracked_upsert(
            self, session, entry, immediate_propagate=True, force_global_update=False
        ):
            upsert_immediate_flags.append(immediate_propagate)
            return original_upsert(
                self,
                session,
                entry,
                immediate_propagate=immediate_propagate,
                force_global_update=force_global_update,
            )

        def tracked_propagate(self, session, tm_global_id, fields=None):
            propagate_calls.append(tm_global_id)
            return original_propagate(self, session, tm_global_id, fields)

        monkeypatch.setattr(TMGlobalService, "upsert_and_link", tracked_upsert)
        monkeypatch.setattr(TMGlobalService, "propagate_to_entries", tracked_propagate)

        updated = service.set_noise_status_bulk(
            session,
            [11, 12],
            True,
            noise_reason="NOISE_TEST",
        )

        assert updated == 2
        assert upsert_immediate_flags == [False, False]
        assert len(propagate_calls) == 1
        assert propagate_calls[0] == entry_a.tm_global_id

        rows = session.execute(
            select(TMEntry.tm_id, TMEntry.is_noise, TMEntry.noise_reason)
            .where(TMEntry.tm_id.in_([11, 12]))
            .order_by(TMEntry.tm_id)
        ).all()
        assert rows == [(11, 1, "NOISE_TEST"), (12, 1, "NOISE_TEST")]
    finally:
        session.close()
        engine.dispose()
