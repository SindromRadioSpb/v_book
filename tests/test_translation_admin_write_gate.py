"""Write-gate integration tests for TranslationAdminService."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.infra.sa_models import Base, DictProject, Library, TMEntry, TMEntryHistory
from app.services import translation_admin_service as translation_admin_module
from app.services.translation_admin_service import TranslationAdminService


def test_update_translation_enters_serialized_write_gate(monkeypatch) -> None:
    operations: list[str] = []

    @contextmanager
    def fake_serialized_db_write(operation: str, **_kwargs):
        operations.append(operation)
        yield

    monkeypatch.setattr(
        translation_admin_module,
        "serialized_db_write",
        fake_serialized_db_write,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        session.add(Library(library_id=1, name="Test Library"))
        session.add(
            DictProject(
                project_id=1,
                library_id=1,
                name="Project 1",
                src_lang="he",
                tgt_lang="ru",
            )
        )
        session.add(
            TMEntry(
                tm_id=1,
                project_id=1,
                kind="lemma",
                src_lang="he",
                tgt_lang="ru",
                src_text="שלום",
                src_norm="שלום",
                translation="old",
                status="approved",
                origin="user_edit",
            )
        )
        session.commit()

        service = TranslationAdminService()
        service.update_translation(session, tm_id=1, translation="new", notes="edited")

        updated = session.execute(select(TMEntry).where(TMEntry.tm_id == 1)).scalar_one()
        history_rows = (
            session.execute(select(TMEntryHistory).where(TMEntryHistory.tm_id == 1)).scalars().all()
        )

        assert updated.translation == "new"
        assert updated.notes == "edited"
        assert len(history_rows) == 1
        assert operations == ["tm.update_translation"]
    finally:
        session.close()
        engine.dispose()
